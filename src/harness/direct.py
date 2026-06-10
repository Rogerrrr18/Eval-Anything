"""
DirectHarness — pass environment observations straight through.

Useful when the environment itself calls an application target, e.g. an RAG app
HTTP API. A placeholder LLM can still be present for compatibility with the
current LLM x Harness x Environment orchestrator.
"""
from __future__ import annotations

from .base import Action, BaseHarness, HarnessConfig
from ..llm.base import BaseLLM


class DirectHarness(BaseHarness):
    """No-op harness for target-backed environments."""

    def __init__(self, llm: BaseLLM, config: HarnessConfig):
        super().__init__(llm, config)
        self._step_num = 0

    async def initial_action(self, task_prompt: str) -> Action:
        self._step_num = 1
        action = Action(action_type="direct_input", content=task_prompt)
        self._final_answer = task_prompt
        self._finished = True
        self._record_step(
            step_num=1,
            observation=task_prompt,
            thought=None,
            action=action,
            result=task_prompt,
            latency_ms=0.0,
            input_tokens=0,
            output_tokens=0,
        )
        return action

    async def next_action(self, observation: str) -> Action:
        return Action(action_type="direct_input", content=observation)

    def is_finished(self) -> bool:
        return self._finished
