"""
DialogEnvironment — 多轮对话 / 槽位填充任务环境。

复用了 22iterate_evalv3.py 的评测逻辑：
  - 逐字段对比 ground truth
  - 特殊字段归一化（如 "空气能" → "中央空调"）
  - JSON 格式合规性检查
  - 字段级 + 全局评分
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import BaseEnvironment, EnvConfig, EnvStepResult, TaskInstance


# ── 特殊归一化规则 ──
_NORMALIZATIONS: Dict[str, Dict[str, str]] = {
    "product_name": {"空气能": "中央空调"},
}


class DialogEnvironment(BaseEnvironment):
    """多轮对话槽位填充环境。

    数据集中的每个 TaskInstance 包含:
      - conversation_history: 多轮对话消息列表
      - expected_slots: 期望输出的槽位字典
      - slot_keys: 需要评测的槽位键名

    Agent 通过一次 step 提交结构化 JSON 输出，
    环境对其逐字段与 ground truth 比较并评分。
    """

    def __init__(self, config: EnvConfig):
        super().__init__(config)
        self._extracted_slots: Optional[Dict[str, Any]] = None
        self._raw_output: str = ""
        self._format_ok: bool = False
        self._field_results: Dict[str, bool] = {}

    async def reset(self, task: TaskInstance) -> str:
        """加载一个槽位填充任务。

        Returns:
            包含对话历史和提取要求的 prompt。
        """
        self.current_task = task
        self.step_count = 0
        self._done = False
        self._extracted_slots = None
        self._raw_output = ""
        self._format_ok = False
        self._field_results = {}

        # 构造返回给 agent 的初始观察
        return task.prompt

    async def step(self, action: Any) -> EnvStepResult:
        """处理 agent 的槽位提取结果。

        action 应为包含 agent 输出的对象（由 harness 构造）。
        我们从 action.content 或 action 本身提取文本输出。
        """
        self.step_count += 1

        # 从 action 中提取文本内容
        if hasattr(action, "content"):
            raw_output = action.content
        elif isinstance(action, str):
            raw_output = action
        elif isinstance(action, dict):
            raw_output = action.get("content", str(action))
        else:
            raw_output = str(action)

        self._raw_output = raw_output

        # 尝试解析 JSON
        try:
            parsed = json.loads(raw_output)
            self._extracted_slots = self._flatten_slots(parsed)
            self._format_ok = True
        except (json.JSONDecodeError, TypeError):
            self._extracted_slots = None
            self._format_ok = False

        # 逐字段评分
        self._field_results = self._compare_fields()

        # 计算总 reward
        reward = self.get_reward()

        self._mark_done(terminated=True)

        return EnvStepResult(
            observation=f"评测完成。格式合规: {self._format_ok}，得分: {reward:.2%}",
            reward=reward,
            terminated=True,
            truncated=False,
            info={
                "format_ok": self._format_ok,
                "field_results": self._field_results,
                "raw_output": raw_output,
                "extracted_slots": self._extracted_slots,
            },
        )

    def get_reward(self) -> float:
        """计算最终得分。

        采用字段级准确率：正确字段数 / 总字段数。
        如果 JSON 解析失败（格式不合规），直接返回 0 分，
        因为无法提取出任何有效结构化信息。
        """
        if not self.current_task or not self.current_task.slot_keys:
            return 0.0
        if not self._format_ok:
            return 0.0
        total = len(self.current_task.slot_keys)
        if total == 0:
            return 0.0
        correct = sum(1 for v in self._field_results.values() if v)
        return correct / total

    def get_all_correct(self) -> bool:
        """是否全部字段都正确。"""
        return all(self._field_results.values()) if self._field_results else False

    def get_format_ok(self) -> bool:
        """输出是否为合法 JSON。"""
        return self._format_ok

    def get_field_results(self) -> Dict[str, bool]:
        """获取每个字段的正确/错误结果。"""
        return dict(self._field_results)

    # ── 内部方法 ──

    def _flatten_slots(self, parsed: Dict[str, Any]) -> Dict[str, str]:
        """将嵌套的 JSON 结构展平为 slot_key → value 映射。

        输入示例:
            {
                "product_info": {"product_name": "XX", ...},
                "address_info": {"province": "XX", ...},
                "date_info": {"book_desc": "XX"},
                "number_info": {"phone_number": "XX"}
            }
        输出:
            {"product_name": "XX", "province": "XX", ...}
        """
        flat: Dict[str, str] = {}
        for section in parsed.values():
            if isinstance(section, dict):
                flat.update({k: str(v) for k, v in section.items()})
        return flat

    def _compare_fields(self) -> Dict[str, bool]:
        """逐字段与 ground truth 对比。

        遵循 22iterate_evalv3.py 中的比较逻辑：
          - fault_info_desc 特殊处理：只要非空就算对
          - 其他字段精确匹配
          - 应用归一化规则
        """
        if not self.current_task or not self.current_task.expected_slots:
            return {}

        expected = self.current_task.expected_slots
        slot_keys = self.current_task.slot_keys or list(expected.keys())
        actual = self._extracted_slots or {}

        results: Dict[str, bool] = {}
        for key in slot_keys:
            ans = str(expected.get(key, "")).strip()
            out = str(actual.get(key, "")).strip()

            # 应用归一化
            if key in _NORMALIZATIONS:
                for src, dst in _NORMALIZATIONS[key].items():
                    if out == src:
                        out = dst
                    if ans == src:
                        ans = dst

            # fault_info_desc 特殊处理：空对空、非空对非空都算对
            if key == "fault_info_desc":
                results[key] = (ans == "" and out == "") or (ans != "" and out != "")
            else:
                results[key] = ans == out

        return results
