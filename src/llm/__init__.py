"""
LLM 注册表 — 根据配置中的 class 名称动态创建 LLM 实例。
"""
from __future__ import annotations

from typing import Dict, Optional, Type

from .base import BaseLLM, LLMConfig
from .openai_compatible import OpenAICompatibleLLM
from .mock import MockLLM

# 注册表：class name → 实现类
_LLM_REGISTRY: Dict[str, Type[BaseLLM]] = {
    "OpenAICompatibleLLM": OpenAICompatibleLLM,
    "HttpxLLM": OpenAICompatibleLLM,  # 暂时复用
    "MockLLM": MockLLM,
}


def register_llm(name: str, cls: Type[BaseLLM]) -> None:
    """注册自定义 LLM 实现。"""
    _LLM_REGISTRY[name] = cls


def create_llm(config: LLMConfig, class_name: Optional[str] = None) -> BaseLLM:
    """根据配置创建 LLM 实例。"""
    cls_name = class_name or config.extra_params.get("class", "OpenAICompatibleLLM")
    if cls_name not in _LLM_REGISTRY:
        raise ValueError(
            f"未注册的 LLM 类: {cls_name!r}。可用: {list(_LLM_REGISTRY.keys())}"
        )
    return _LLM_REGISTRY[cls_name](config)
