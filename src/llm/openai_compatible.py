"""
OpenAI 兼容 LLM 后端 — 适配 vLLM / DeepSeek / Qwen 等本地推理服务。

基于 httpx 异步客户端，无重 SDK 依赖。
"""
from __future__ import annotations

import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from .base import BaseLLM, LLMConfig, LLMResponse


def split_endpoint_url(endpoint_url: str) -> Tuple[str, str]:
    """把完整 endpoint URL 拆成 (base_url, path)。

    不做任何 "/v1" 字符串猜测——GLM 是 /api/paas/v4/...，
    Gemini 是 /v1beta/openai/...，按子串切会把它们切坏。
    path 为空时默认 /v1/chat/completions。
    """
    parts = urlsplit(endpoint_url)
    base = f"{parts.scheme}://{parts.netloc}"
    path = parts.path or "/v1/chat/completions"
    return base, path


class OpenAICompatibleLLM(BaseLLM):
    """基于 httpx 的 OpenAI 兼容 LLM 客户端。

    适配 vLLM / SGLang / LMStudio 等所有 OpenAI API 兼容的推理服务。
    支持流式输出、工具调用、reasoning_content 提取。
    """

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        base_url, self._chat_path = split_endpoint_url(config.endpoint_url)
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.api_key}",
            },
            timeout=httpx.Timeout(config.timeout_seconds, connect=10.0),
        )

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
        reasoning = message.get("reasoning_content") or message.get("reasoning")

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
