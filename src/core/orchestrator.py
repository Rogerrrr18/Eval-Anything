"""
Orchestrator — 核心调度器。

驱动整个评测流程：
  1. 加载配置 → 创建组件
  2. 对每个 (LLM × Harness × Environment) 组合运行评测
  3. 收集轨迹 → 计算指标 → 生成报告
"""
from __future__ import annotations

import asyncio
import itertools
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..llm.base import BaseLLM, LLMConfig
from ..llm import create_llm
from ..harness.base import BaseHarness, Action
from ..harness.raw import RawHarness
from ..harness.react import ReActHarness
from ..harness.function_call import FunctionCallHarness
from ..environment.base import BaseEnvironment, TaskInstance
from ..environment.dialog import DialogEnvironment
from ..environment import create_environment
from .config import (
    ConfigLoader, EnvironmentProfile, ExperimentConfig,
    HarnessProfile, LLMProfile,
)
from ..environment.base import EnvConfig
from ..harness.base import HarnessConfig
from .trajectory import Trajectory, ComboResult, ExperimentResult

# ── Harness 注册表 ──
_HARNESS_REGISTRY = {
    "RawHarness": RawHarness,
    "ReActHarness": ReActHarness,
    "FunctionCallHarness": FunctionCallHarness,
}


def _create_llm_from_profile(profile: LLMProfile) -> BaseLLM:
    """从 profile 创建 LLM 实例。"""
    config = LLMConfig(
        model_name=profile.model_name,
        endpoint_url=profile.endpoint_url,
        api_key=profile.api_key,
        temperature=profile.temperature,
        max_tokens=profile.max_tokens,
        top_p=profile.top_p,
        timeout_seconds=profile.timeout_seconds,
        enable_thinking=profile.enable_thinking,
        extra_params=profile.extra_params,
    )
    return create_llm(config, class_name=profile.class_name)


def _create_harness_from_profile(
    profile: HarnessProfile, llm: BaseLLM
) -> BaseHarness:
    """从 profile 创建 Harness 实例。"""
    cls = _HARNESS_REGISTRY.get(profile.class_name)
    if cls is None:
        raise ValueError(f"未注册的 Harness 类: {profile.class_name!r}")
    config = HarnessConfig(
        name=profile.name,
        max_steps=profile.max_steps,
        max_retries=profile.max_retries,
        timeout_per_step=profile.timeout_per_step,
        description=profile.description,
        extra_params=profile.extra_params,
    )
    return cls(llm, config)


def _create_env_from_profile(profile: EnvironmentProfile) -> BaseEnvironment:
    """从 profile 创建 Environment 实例。"""
    from ..environment.base import EnvConfig
    config = EnvConfig(
        name=profile.name,
        dataset=profile.dataset,
        description=profile.description,
        max_steps=profile.max_steps,
        extra_params=profile.extra_params,
    )
    return create_environment(config, class_name=profile.class_name)


class Orchestrator:
    """核心评测调度器。"""

    def __init__(self, config_loader: ConfigLoader):
        self.config_loader = config_loader

    async def run_experiment(self, experiment_config: ExperimentConfig) -> ExperimentResult:
        """运行完整实验。

        对每个 (LLM × Harness × Environment) 组合：
          1. 初始化组件
          2. 加载测试集
          3. 逐任务运行 agent loop
          4. 收集轨迹和分数
          5. 汇总结果
        """
        print(f"\n{'='*60}")
        print(f"实验: {experiment_config.name}")
        print(f"描述: {experiment_config.description}")
        print(f"{'='*60}\n")

        # 生成所有组合
        combos = list(itertools.product(
            experiment_config.llm_profiles,
            experiment_config.harness_profiles,
            experiment_config.environments,
        ))
        print(f"共 {len(combos)} 个评测组合\n")

        # 依次运行每个组合（可并行）
        semaphore = asyncio.Semaphore(experiment_config.execution.max_concurrent_combos)
        combo_results: List[ComboResult] = []

        for idx, (llm_name, harness_name, env_name) in enumerate(combos, 1):
            print(f"\n[{idx}/{len(combos)}] 运行: LLM={llm_name}, Harness={harness_name}, Env={env_name}")
            result = await self._run_combo(
                llm_name, harness_name, env_name, experiment_config
            )
            combo_results.append(result)
            self._print_combo_summary(result)

        # 汇总
        exp_result = ExperimentResult(
            experiment_name=experiment_config.name,
            combo_results=combo_results,
            config_snapshot={
                "llm_profiles": experiment_config.llm_profiles,
                "harness_profiles": experiment_config.harness_profiles,
                "environments": experiment_config.environments,
                "seed": experiment_config.seed,
            },
        )

        print(f"\n{'='*60}")
        print(f"实验完成！共 {len(combo_results)} 个组合，"
              f"{sum(len(cr.task_results) for cr in combo_results)} 条轨迹")
        print(f"{'='*60}\n")

        return exp_result

    async def _run_combo(
        self,
        llm_name: str,
        harness_name: str,
        env_name: str,
        exp_config: ExperimentConfig,
    ) -> ComboResult:
        """运行单个 (LLM × Harness × Env) 组合。"""
        # 创建组件
        llm_profile = self.config_loader.get_llm_profile(llm_name)
        harness_profile = self.config_loader.get_harness_profile(harness_name)
        env_profile = self.config_loader.get_env_profile(env_name)

        llm = _create_llm_from_profile(llm_profile)
        harness = _create_harness_from_profile(harness_profile, llm)
        env = _create_env_from_profile(env_profile)

        # 加载测试集
        tasks = self._load_tasks(env_profile)
        print(f"  加载 {len(tasks)} 条测试用例")

        # 逐任务运行
        trajectories: List[Trajectory] = []
        for task_idx, task in enumerate(tasks):
            traj = await self._run_single_task(
                harness, env, task, exp_config, task_idx, len(tasks),
                llm_name, harness_name, env_name,
            )
            trajectories.append(traj)

        # 清理
        await llm.close()

        # 汇总
        combo = ComboResult(
            llm_name=llm_name,
            harness_name=harness_name,
            env_name=env_name,
            task_results=trajectories,
        )
        combo.compute_summary()
        return combo

    async def _run_single_task(
        self,
        harness: BaseHarness,
        env: BaseEnvironment,
        task: TaskInstance,
        exp_config: ExperimentConfig,
        task_idx: int,
        total_tasks: int,
        llm_name: str,
        harness_name: str,
        env_name: str,
    ) -> Trajectory:
        """运行单个任务。"""
        harness.reset()

        try:
            # 重置环境
            observation = await asyncio.wait_for(
                env.reset(task),
                timeout=exp_config.execution.task_timeout_seconds,
            )

            # Agent 产生第一个动作
            action = await asyncio.wait_for(
                harness.initial_action(task.prompt),
                timeout=exp_config.execution.step_timeout_seconds,
            )

            # Agent loop
            step_count = 0
            while not harness.is_finished() and not env.is_done():
                if step_count >= exp_config.execution.step_timeout_seconds:
                    break
                step_count += 1

                result = await asyncio.wait_for(
                    env.step(action),
                    timeout=exp_config.execution.step_timeout_seconds,
                )

                if result.terminated or result.truncated:
                    break

                action = await asyncio.wait_for(
                    harness.next_action(result.observation),
                    timeout=exp_config.execution.step_timeout_seconds,
                )

            # 最后一步如果环境还没 done，提交最终动作
            if not env.is_done() and action:
                await env.step(action)

        except asyncio.TimeoutError:
            print(f"  [{task_idx+1}/{total_tasks}] 超时: {task.task_id}")
            return Trajectory(
                experiment_name=exp_config.name,
                task_id=task.task_id,
                llm_name=llm_name,
                harness_name=harness_name,
                env_name=env_name,
                steps=harness.get_trajectory(),
                final_answer=harness.get_final_answer(),
                ground_truth=task.ground_truth,
                scores={},
                total_input_tokens=harness.get_total_tokens(),
                total_output_tokens=0,
                total_latency_ms=harness.get_total_latency(),
                status="timeout",
                error_message="任务执行超时",
            )
        except Exception as e:
            print(f"  [{task_idx+1}/{total_tasks}] 错误: {task.task_id}: {e}")
            return Trajectory(
                experiment_name=exp_config.name,
                task_id=task.task_id,
                llm_name=llm_name,
                harness_name=harness_name,
                env_name=env_name,
                steps=harness.get_trajectory(),
                final_answer=harness.get_final_answer(),
                ground_truth=task.ground_truth,
                scores={},
                total_input_tokens=harness.get_total_tokens(),
                total_output_tokens=0,
                total_latency_ms=harness.get_total_latency(),
                status="error",
                error_message=str(e),
            )

        # 计算分数
        reward = env.get_reward()
        final_answer = harness.get_final_answer()

        # 从环境获取详细信息
        env_info = env.get_info()
        field_results = env_info.get("field_results", {})
        format_ok = env_info.get("format_ok", False)

        # 确定状态
        if reward >= 1.0:
            status = "success"
        elif reward > 0.0:
            status = "partial"
        else:
            status = "failure"

        scores = {
            "partial_completion": reward,
            "format_compliance": 1.0 if format_ok else 0.0,
            "task_completion": 1.0 if status == "success" else 0.0,
        }

        # 加入字段级分数
        if field_results:
            for key, passed in field_results.items():
                scores[f"field_{key}"] = 1.0 if passed else 0.0

        print(f"  [{task_idx+1}/{total_tasks}] {task.task_id}: {status} ({reward:.1%})")

        return Trajectory(
            experiment_name=exp_config.name,
            task_id=task.task_id,
            llm_name=llm_name,
            harness_name=harness_name,
            env_name=env_name,
            steps=harness.get_trajectory(),
            final_answer=final_answer,
            ground_truth=task.ground_truth,
            scores=scores,
            total_input_tokens=harness._total_input_tokens,
            total_output_tokens=harness._total_output_tokens,
            total_latency_ms=harness.get_total_latency(),
            status=status,
            metadata={"field_results": field_results, "format_ok": format_ok},
        )

    def _load_tasks(self, env_profile: EnvironmentProfile) -> List[TaskInstance]:
        """根据环境 profile 加载测试集。

        支持两种数据源：
          1. JSONL 文件（推荐）
          2. Excel 文件（兼容现有 evalv3 数据）
        """
        dataset_path = env_profile.dataset
        if not dataset_path:
            print(f"  警告: 环境 {env_profile.name} 未配置 dataset，使用空测试集")
            return []

        path = Path(dataset_path)
        if not path.exists():
            # 尝试从项目根目录查找
            alt_path = Path("/home/ai/agent-eval-pipeline") / dataset_path
            if alt_path.exists():
                path = alt_path
            else:
                print(f"  警告: 数据集文件不存在: {dataset_path}")
                return []

        if path.suffix == ".jsonl":
            return self._load_jsonl(path, env_profile)
        elif path.suffix in (".xlsx", ".xls"):
            return self._load_excel(path, env_profile)
        elif path.suffix == ".json":
            return self._load_json(path, env_profile)
        else:
            print(f"  警告: 不支持的数据集格式: {path.suffix}")
            return []

    def _load_jsonl(self, path: Path, env_profile: EnvironmentProfile) -> List[TaskInstance]:
        """从 JSONL 文件加载测试集。"""
        tasks = []
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    tasks.append(TaskInstance(
                        task_id=obj.get("task_id", f"task_{line_no}"),
                        task_type=obj.get("task_type", "slot_filling"),
                        prompt=obj.get("prompt", ""),
                        ground_truth=obj.get("ground_truth"),
                        metadata=obj.get("metadata", {}),
                        conversation_history=obj.get("conversation_history"),
                        expected_slots=obj.get("expected_slots"),
                        slot_keys=obj.get("slot_keys"),
                    ))
                except json.JSONDecodeError as e:
                    print(f"  警告: JSONL 第 {line_no} 行解析失败: {e}")
        return tasks

    def _load_json(self, path: Path, env_profile: EnvironmentProfile) -> List[TaskInstance]:
        """从 JSON 文件加载测试集。"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("tasks", [])
        tasks = []
        for i, obj in enumerate(items):
            tasks.append(TaskInstance(
                task_id=obj.get("task_id", f"task_{i}"),
                task_type=obj.get("task_type", "slot_filling"),
                prompt=obj.get("prompt", ""),
                ground_truth=obj.get("ground_truth"),
                metadata=obj.get("metadata", {}),
                conversation_history=obj.get("conversation_history"),
                expected_slots=obj.get("expected_slots"),
                slot_keys=obj.get("slot_keys"),
            ))
        return tasks

    def _load_excel(self, path: Path, env_profile: EnvironmentProfile) -> List[TaskInstance]:
        """从 Excel 文件加载测试集（兼容 evalv3 数据格式）。"""
        import pandas as pd

        df = pd.read_excel(path, dtype={"phone_number": str})
        df = df.fillna("")

        slot_keys = env_profile.extra_params.get("slot_keys", [])
        system_prompt_file = env_profile.extra_params.get("system_prompt_file", "")

        tasks = []
        grouped = df.groupby("conversation_id") if "conversation_id" in df.columns else [(None, df)]

        for conv_id, group in grouped:
            if isinstance(group, pd.DataFrame):
                group = group.sort_values("dialogue_count") if "dialogue_count" in group.columns else group

            for idx, row in group.iterrows():
                # 构造期望槽位
                expected = {}
                for key in slot_keys:
                    val = row.get(key, "")
                    # 特殊处理数值字段
                    if key == "phone_number" and isinstance(val, str) and val.endswith(".0"):
                        val = val[:-2]
                    elif key in ("product_num",) and val != "":
                        try:
                            val = str(int(float(val)))
                        except (ValueError, TypeError):
                            pass
                    expected[key] = val

                # 构造多轮对话历史
                history = []
                if "dialogue_count" in df.columns:
                    hist_rows = group[group["dialogue_count"] < row.get("dialogue_count", 0)]
                    for _, hr in hist_rows.iterrows():
                        history.append({"role": "user", "content": str(hr.get("query", ""))})
                        ans = hr.get("answer", "")
                        if ans and str(ans) != "nan":
                            history.append({"role": "assistant", "content": str(ans)})

                # 构造 prompt
                query = str(row.get("query", ""))
                intent = row.get("INTENTION", "")
                if intent and str(intent) == "预约维修" and env_profile.extra_params.get("intent_filter") == "预约维修":
                    pass  # 保留
                elif intent and env_profile.extra_params.get("intent_filter") and str(intent) != str(env_profile.extra_params.get("intent_filter")):
                    continue  # 跳过非目标意图

                prompt = query  # 简单 prompt = 用户输入

                task_id = f"{conv_id}_{row.get('dialogue_count', idx)}" if conv_id else f"task_{idx}"

                tasks.append(TaskInstance(
                    task_id=task_id,
                    task_type="slot_filling",
                    prompt=prompt,
                    ground_truth=expected,
                    metadata={"conversation_id": str(conv_id), "query": query},
                    conversation_history=history,
                    expected_slots=expected,
                    slot_keys=slot_keys,
                ))

        return tasks

    def _print_combo_summary(self, combo: ComboResult) -> None:
        """打印组合结果摘要。"""
        s = combo.summary
        if not s:
            return
        print(f"  结果: 成功率={s.get('success_rate', 0):.1%}, "
              f"平均得分={s.get('avg_score', 0):.1%}, "
              f"平均延迟={s.get('avg_latency_ms', 0):.0f}ms, "
              f"平均token={s.get('avg_tokens', 0):.0f}")
