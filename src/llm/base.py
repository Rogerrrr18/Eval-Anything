"""
LLM 抽象层 — BaseLLM 及相关数据模型

所有 LLM 后端都必须继承 BaseLLM，实现 chat / chat_stream / chat_with_tools。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional


# ────────────────────────── 数据模型 ──────────────────────────

@dataclass
class LLMConfig:
    """LLM 端点配置，从 YAML llm_profiles 加载。"""
    model_name: str
    endpoint_url: str
    api_key: str = "EMPTY"
    temperature: float = 0.0
    max_tokens: int = 600
    top_p: float = 1.0
    system_prompt: Optional[str] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 30
    enable_thinking: bool = False


@dataclass
class LLMResponse:
    """LLM 调用的统一返回结果。"""
    content: str
    reasoning_content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    raw_response: Optional[Dict[str, Any]] = None
    finish_reason: Optional[str] = None


# ────────────────────────── 抽象基类 ──────────────────────────

class BaseLLM(ABC):
    """LLM 后端抽象基类。

    子类需要实现 chat / chat_stream / chat_with_tools 三个核心方法。
    """

    def __init__(self, config: LLMConfig):
        self.config = config

    # ── 核心接口 ──

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """单轮 / 多轮对话补全（非流式）。"""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """流式对话补全，yield 内容增量字符串。"""
        ...
        # 为了让 mypy / IDE 满意，这里 yield 一个假值
        yield ""  # type: ignore[misc]

    @abstractmethod
    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """带函数 / 工具调用的对话补全。

        返回的 LLMResponse.tool_calls 应为非空列表。
        """
        ...

    # ── 通用工具方法 ──

    async def close(self) -> None:
        """清理资源（子类可选覆写）。"""
        pass

    def format_messages(
        self,
        history: List[Dict[str, str]],
        user_input: str,
        system_prompt: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """从历史记录 + 当前输入构造 messages 列表。

        与 22iterate_evalv3.py 中构造多轮消息的模式一致。
        """
        messages: List[Dict[str, str]] = []
        sp = system_prompt or self.config.system_prompt
        if sp:
            messages.append({"role": "system", "content": sp})
        messages.extend(history)
        messages.append({"role": "user", "content": user_input})
        return messages

    def _override_params(
        self,
        temperature: Optional[float],
        max_tokens: Optional[int],
    ) -> tuple[float, int]:
        """合并实例默认值和调用时覆写值。"""
        t = temperature if temperature is not None else self.config.temperature
        m = max_tokens if max_tokens is not None else self.config.max_tokens
        return t, m

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} model={self.config.model_name!r}>"
