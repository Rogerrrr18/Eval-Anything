"""
Harness 抽象层 — Agent 架构脚手架。

不同的 Harness 代表不同的 Agent 策略（ReAct、FunctionCall 等）。
每个 Harness 管理 prompt 构造、动作选择、观察解析、记忆状态。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..llm.base import BaseLLM


@dataclass
class HarnessConfig:
    """Harness 配置，从 YAML harness_profiles 加载。"""
    name: str
    max_steps: int = 10
    max_retries: int = 3
    timeout_per_step: int = 60
    description: str = ""
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Action:
    """Harness 产出的动作，发送给 Environment。"""
    action_type: str           # "text_response" | "tool_call" | "command" | "plan_step"
    content: str = ""
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepRecord:
    """轨迹中的单步记录。"""
    step_number: int
    observation: str           # Agent 看到的内容
    thought: Optional[str]     # Agent 的推理（如果有）
    action: Action             # Agent 做了什么
    action_result: str         # 动作执行后的结果
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    error: Optional[str] = None


class BaseHarness(ABC):
    """Agent 架构抽象基类。

    Harness 将 LLM 包装成 Agent，管理：
      - prompt 构造（系统提示、few-shot、指令）
      - 动作选择（解析 LLM 输出为结构化 Action）
      - 观察解析（将环境输出转为 LLM 可读形式）
      - 记忆 / 状态管理
      - 重试逻辑

    灵感来自 openmanus/app/agent/base.py 的 BaseAgent 模式。
    """

    def __init__(self, llm: BaseLLM, config: HarnessConfig):
        self.llm = llm
        self.config = config
        self.history: List[Dict[str, str]] = []
        self.step_records: List[StepRecord] = []
        self._finished: bool = False
        self._final_answer: str = ""
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._total_latency_ms: float = 0.0

    @abstractmethod
    async def initial_action(self, task_prompt: str) -> Action:
        """根据任务描述产生第一个动作。

        不同架构的区别在此体现：
          - RawHarness: 直接透传 prompt
          - ReActHarness: 产生 Thought + Action
          - FunctionCallHarness: 产生工具调用
          - PlanAndExecuteHarness: 产生初始计划
        """
        ...

    @abstractmethod
    async def next_action(self, observation: str) -> Action:
        """根据环境观察产生下一个动作。"""
        ...

    @abstractmethod
    def is_finished(self) -> bool:
        """检查 Harness 是否认为任务完成。"""
        ...

    def reset(self) -> None:
        """重置状态以处理新任务。"""
        self.history.clear()
        self.step_records.clear()
        self._finished = False
        self._final_answer = ""
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_latency_ms = 0.0

    def get_trajectory(self) -> List[StepRecord]:
        """返回完整的步骤轨迹。"""
        return self.step_records.copy()

    def get_final_answer(self) -> str:
        """返回 Agent 的最终输出。"""
        return self._final_answer

    def get_total_tokens(self) -> int:
        return self._total_input_tokens + self._total_output_tokens

    def get_total_latency(self) -> float:
        return self._total_latency_ms

    def _record_step(
        self,
        step_num: int,
        observation: str,
        thought: Optional[str],
        action: Action,
        result: str,
        latency_ms: float,
        input_tokens: int,
        output_tokens: int,
        error: Optional[str] = None,
    ) -> None:
        """记录一个步骤。"""
        self.step_records.append(StepRecord(
            step_number=step_num,
            observation=observation,
            thought=thought,
            action=action,
            action_result=result,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=error,
        ))
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._total_latency_ms += latency_ms
