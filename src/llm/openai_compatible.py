"""
OpenAI 兼容 LLM 后端 — 适配 vLLM / DeepSeek / Qwen 等本地推理服务。

基于 httpx 异步客户端，无重 SDK 依赖。
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from .base import BaseLLM, LLMConfig, LLMResponse


class OpenAICompatibleLLM(BaseLLM):
    """基于 httpx 的 OpenAI 兼容 LLM 客户端。

    适配 vLLM / SGLang / LMStudio 等所有 OpenAI API 兼容的推理服务。
    支持流式输出、工具调用、reasoning_content 提取。
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self._client = httpx.AsyncClient(
            base_url=config.endpoint_url.rsplit("/v1", 1)[0] if "/v1" in config.endpoint_url else config.endpoint_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            },
            timeout=httpx.Timeout(config.timeout_seconds, connect=10.0),
        )
        # 提取 endpoint_path（如 /v1/chat/completions）
        base = config.endpoint_url
        if "/v1" in base:
            self._chat_path = "/v1/chat/completions"
        else:
            self._chat_path = base.split("://", 1)[-1].split("/", 1)[-1] if "/" in base.split("://", 1)[-1] else "/chat/completions"

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        t, m = self._override_params(temperature, max_tokens)
        payload = self._build_payload(messages, t, m)

        start = time.perf_counter()
        resp = await self._client.post(self._chat_path, json=payload)
        latency = (time.perf_counter() - start) * 1000

        resp.raise_for_status()
        data = resp.json()
        return self._parse_response(data, latency)

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        t, m = self._override_params(temperature, max_tokens)
        payload = self._build_payload(messages, t, m, stream=True)

        async with self._client.stream("POST", self._chat_path, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue

    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        t, m = self._override_params(temperature, max_tokens)
        payload = self._build_payload(messages, t, m, tools=tools, tool_choice=tool_choice)

        start = time.perf_counter()
        resp = await self._client.post(self._chat_path, json=payload)
        latency = (time.perf_counter() - start) * 1000

        resp.raise_for_status()
        data = resp.json()
        return self._parse_response(data, latency)

    async def close(self) -> None:
        await self._client.aclose()

    # ── 内部方法 ──

    def _build_payload(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": self.config.top_p,
            "stream": stream,
        }
        # 额外参数（如 chat_template_kwargs）
        if self.config.extra_params:
            payload.update(self.config.extra_params)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        return payload

    def _parse_response(self, data: Dict[str, Any], latency_ms: float) -> LLMResponse:
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = data.get("usage", {})

        content = message.get("content", "") or ""
        reasoning = message.get("reasoning_content") or message.get("reasoning_content")

        tool_calls = None
        if message.get("tool_calls"):
            tool_calls = []
            for tc in message["tool_calls"]:
                tool_calls.append({
                    "id": tc.get("id", ""),
                    "type": tc.get("type", "function"),
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                })

        return LLMResponse(
            content=content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
            raw_response=data,
            finish_reason=choice.get("finish_reason"),
        )
