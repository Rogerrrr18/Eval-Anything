"""
RawHarness — 直接 prompt-in / response-out 基线。

不做任何 Agent 循环，直接将任务 prompt 发给 LLM，返回原始文本。
这是最简单的 Harness，用于与更复杂的 Agent 架构做对比基线。

行为与 22iterate_evalv3.py 中的 call_model + 直接对比一致。
"""
from __future__ import annotations

import time
from typing import Optional

from ..llm.base import BaseLLM, LLMResponse
from .base import Action, BaseHarness, HarnessConfig, StepRecord


class RawHarness(BaseHarness):
    """直接 prompt-in / response-out 的基线 Harness。

    不做任何 Agent 循环、工具调用或多步推理。
    单次 LLM 调用即完成任务。
    """

    def __init__(self, llm: BaseLLM, config: HarnessConfig):
        super().__init__(llm, config)
        self._task_prompt: str = ""

    async def initial_action(self, task_prompt: str) -> Action:
        """直接将 prompt 发给 LLM，一步完成。"""
        self._task_prompt = task_prompt

        # 构造 messages
        messages = self.llm.format_messages(
            history=[],
            user_input=task_prompt,
        )

        # 调用 LLM
        start = time.perf_counter()
        try:
            response: LLMResponse = await self.llm.chat(messages)
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            self._final_answer = f"[LLM调用失败] {e}"
            self._finished = True
            action = Action(action_type="text_response", content=self._final_answer)
            self._record_step(1, task_prompt, None, action, f"错误: {e}", latency, 0, 0, str(e))
            return action

        latency = (time.perf_counter() - start) * 1000
        self._final_answer = response.content
        self._finished = True

        action = Action(action_type="text_response", content=response.content)
        self._record_step(
            step_num=1,
            observation=task_prompt,
            thought=None,
            action=action,
            result=response.content,
            latency_ms=latency,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
        return action

    async def next_action(self, observation: str) -> Action:
        """RawHarness 只做一步，此方法不应被调用。"""
        return Action(action_type="text_response", content=self._final_answer)

    def is_finished(self) -> bool:
        return self._finished
