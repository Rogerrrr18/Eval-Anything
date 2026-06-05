"""
Mock LLM — 用于管线自身测试，不发送真实请求。
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict, List, Optional

from .base import BaseLLM, LLMConfig, LLMResponse


class MockLLM(BaseLLM):
    """Mock LLM，返回预设的固定响应或基于模板生成的响应。

    用法:
        mock = MockLLM(LLMConfig(model_name="mock", endpoint_url=""))
        mock.set_response("你好")  # 设置下次调用的返回值
        resp = await mock.chat([{"role": "user", "content": "hi"}])
        assert resp.content == "你好"
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._responses: List[str] = []
        self._call_log: List[List[Dict[str, str]]] = []

    def set_response(self, content: str) -> None:
        """设置下一次调用的返回内容。可多次调用以队列式返回不同内容。"""
        self._responses.append(content)

    def set_json_response(self, obj: Dict[str, Any]) -> None:
        """设置下一次调用返回 JSON 序列化后的内容。"""
        self._responses.append(json.dumps(obj, ensure_ascii=False))

    @property
    def call_log(self) -> List[List[Dict[str, str]]]:
        """获取所有调用的 messages 记录。"""
        return self._call_log

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        self._call_log.append(messages)
        content = self._responses.pop(0) if self._responses else ""
        return LLMResponse(
            content=content,
            input_tokens=sum(len(m.get("content", "")) for m in messages),
            output_tokens=len(content),
        )

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        self._call_log.append(messages)
        content = self._responses.pop(0) if self._responses else ""
        yield content

    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        self._call_log.append(messages)
        content = self._responses.pop(0) if self._responses else ""
        return LLMResponse(
            content=content,
            tool_calls=None,
            input_tokens=sum(len(m.get("content", "")) for m in messages),
            output_tokens=len(content),
        )
