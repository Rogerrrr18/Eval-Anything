"""
ReActHarness — 思考 + 行动循环。

经典的 ReAct (Reasoning + Acting) 模式：
  Thought: 推理当前状态
  Action: 选择并执行动作
  Observation: 获取环境反馈

循环直到任务完成或达到最大步数。
"""
from __future__ import annotations

import re
import time
from typing import Optional

from ..llm.base import BaseLLM, LLMResponse
from .base import Action, BaseHarness, HarnessConfig


# ── 解析 ReAct 输出的正则 ──
_THOUGHT_RE = re.compile(r"Thought:\s*(.+?)(?=\n(?:Action:|$))", re.DOTALL)
_ACTION_RE = re.compile(r"Action:\s*(\w+)\[(.+?)\]", re.DOTALL)
_FINISH_RE = re.compile(r"Action:\s*Finish\[(.+?)\]", re.DOTALL)


class ReActHarness(BaseHarness):
    """ReAct 思考-行动循环 Harness。"""

    def __init__(self, llm: BaseLLM, config: HarnessConfig):
        super().__init__(llm, config)
        self._scratchpad: str = ""
        self._step_num: int = 0

    async def initial_action(self, task_prompt: str) -> Action:
        """产生第一个 Thought + Action。"""
        self._scratchpad = f"Task: {task_prompt}\n"

        system_prompt = self.config.extra_params.get(
            "system_prompt",
            "你是一个智能助手。请按照 Thought/Action 格式逐步解决问题。\n"
            "格式要求:\n"
            "Thought: 你的推理过程\n"
            "Action: <动作类型>[<动作内容>]\n\n"
            "可用动作:\n"
            "- respond[<你的回答>] — 给出最终答案\n"
            "- think[<继续思考>] — 继续推理\n\n"
            "请先输出 Thought，再输出 Action。",
        )

        messages = [{"role": "system", "content": system_prompt}]
        messages.append({"role": "user", "content": task_prompt})

        return await self._call_llm(messages, task_prompt)

    async def next_action(self, observation: str) -> Action:
        """根据观察继续推理。"""
        self._step_num += 1
        if self._step_num >= self.config.max_steps:
            self._finished = True
            return Action(action_type="text_response", content=self._final_answer)

        self._scratchpad += f"Observation: {observation}\n"

        messages = [{"role": "user", "content": self._scratchpad + "\n请继续你的推理。"}]
        return await self._call_llm(messages, observation)

    def is_finished(self) -> bool:
        return self._finished

    # ── 内部方法 ──

    async def _call_llm(self, messages: list, observation: str) -> Action:
        start = time.perf_counter()
        try:
            response: LLMResponse = await self.llm.chat(messages)
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            self._final_answer = f"[LLM调用失败] {e}"
            self._finished = True
            action = Action(action_type="text_response", content=self._final_answer)
            self._record_step(
                self._step_num + 1, observation, None, action, f"错误: {e}",
                latency, 0, 0, str(e),
            )
            return action

        latency = (time.perf_counter() - start) * 1000
        content = response.content

        # 解析 Thought
        thought_match = _THOUGHT_RE.search(content)
        thought = thought_match.group(1).strip() if thought_match else None

        # 解析 Action
        finish_match = _FINISH_RE.search(content)
        if finish_match:
            answer = finish_match.group(1).strip()
            self._final_answer = answer
            self._finished = True
            action = Action(action_type="text_response", content=answer)
        else:
            action_match = _ACTION_RE.search(content)
            if action_match:
                action_type = action_match.group(1)
                action_content = action_match.group(2).strip()
                action = Action(action_type=action_type.lower(), content=action_content)
                if action_type.lower() == "respond":
                    self._final_answer = action_content
                    self._finished = True
            else:
                # 无法解析 action，直接作为文本响应
                self._final_answer = content
                self._finished = True
                action = Action(action_type="text_response", content=content)

        self._scratchpad += f"Thought: {thought or '(无)'}\nAction: {content}\n"

        self._record_step(
            self._step_num + 1, observation, thought, action, content,
            latency, response.input_tokens, response.output_tokens,
        )
        return action
