"""
FunctionCallHarness — 基于原生工具调用的 Agent 架构。

使用 LLM 的原生 tool/function calling 能力，
让模型自主选择调用哪个工具、传什么参数。

需要 LLM 后端支持 chat_with_tools()。
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from ..llm.base import BaseLLM, LLMResponse
from .base import Action, BaseHarness, HarnessConfig


# ── 通用工具 schema（根据任务类型动态配置） ──
DEFAULT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "submit_answer",
            "description": "提交最终答案。当任务完成时调用此工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "最终答案的 JSON 字符串",
                    }
                },
                "required": ["answer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_info",
            "description": "请求更多信息或说明。当需要额外输入时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "请求的内容描述",
                    }
                },
                "required": ["query"],
            },
        },
    },
]


class FunctionCallHarness(BaseHarness):
    """基于原生工具调用的 Harness。

    让 LLM 通过 function calling 自主选择工具和参数。
    当 LLM 调用 submit_answer 时视为任务完成。
    """

    def __init__(self, llm: BaseLLM, config: HarnessConfig):
        super().__init__(llm, config)
        self._step_num: int = 0
        self._tools: List[Dict] = config.extra_params.get("tools", DEFAULT_TOOLS)
        self._messages: List[Dict[str, Any]] = []

    async def initial_action(self, task_prompt: str) -> Action:
        """首次调用 LLM with tools。"""
        self._messages = [{"role": "user", "content": task_prompt}]
        return await self._call_llm(task_prompt)

    async def next_action(self, observation: str) -> Action:
        """将环境观察追加到消息历史，继续调用。"""
        self._step_num += 1
        if self._step_num >= self.config.max_steps:
            self._finished = True
            return Action(action_type="text_response", content=self._final_answer)

        self._messages.append({"role": "user", "content": observation})
        return await self._call_llm(observation)

    def is_finished(self) -> bool:
        return self._finished

    # ── 内部方法 ──

    async def _call_llm(self, observation: str) -> Action:
        start = time.perf_counter()
        try:
            response: LLMResponse = await self._call_with_retries(
                lambda: self.llm.chat_with_tools(
                    messages=self._messages,
                    tools=self._tools,
                    tool_choice=self.config.extra_params.get("tool_choice", "auto"),
                ),
                label="function call chat",
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            self._final_answer = f"[工具调用失败] {e}"
            self._finished = True
            action = Action(action_type="text_response", content=self._final_answer)
            self._record_step(
                self._step_num + 1, observation, None, action, f"错误: {e}",
                latency, 0, 0, str(e),
            )
            return action

        latency = (time.perf_counter() - start) * 1000

        # 记录 assistant 响应到消息历史
        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": response.content or ""}
        if response.tool_calls:
            assistant_msg["tool_calls"] = response.tool_calls
        self._messages.append(assistant_msg)

        # 解析工具调用
        thought = response.content  # 可能有 reasoning_content
        if response.tool_calls:
            tc = response.tool_calls[0]
            func_name = tc["function"]["name"]
            func_args = tc["function"]["arguments"]

            if func_name == "submit_answer":
                # 提交最终答案
                try:
                    args = json.loads(func_args) if isinstance(func_args, str) else func_args
                    answer = args.get("answer", func_args)
                except json.JSONDecodeError:
                    answer = func_args
                self._final_answer = answer
                self._finished = True
                action = Action(action_type="text_response", content=answer, tool_name=func_name)
            else:
                # 其他工具调用
                try:
                    tool_args = json.loads(func_args) if isinstance(func_args, str) else func_args
                except json.JSONDecodeError:
                    tool_args = {"raw": func_args}
                action = Action(
                    action_type="tool_call",
                    content=func_args,
                    tool_name=func_name,
                    tool_args=tool_args,
                )
        else:
            # 没有工具调用，直接作为文本响应
            self._final_answer = response.content
            self._finished = True
            action = Action(action_type="text_response", content=response.content)

        self._record_step(
            self._step_num + 1, observation, thought, action,
            response.content or "",
            latency, response.input_tokens, response.output_tokens,
        )
        return action
