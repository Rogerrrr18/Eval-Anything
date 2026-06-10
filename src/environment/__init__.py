"""
Environment 注册表。
"""
from __future__ import annotations

from typing import Dict, Optional, Type

from .base import BaseEnvironment, EnvConfig
from .dialog import DialogEnvironment
from .rag_qa import RAGQAEnvironment
from .workspace import WorkspaceEnvironment

_ENV_REGISTRY: Dict[str, Type[BaseEnvironment]] = {
    "DialogEnvironment": DialogEnvironment,
    "SlotFillingEnvironment": DialogEnvironment,
    "RAGQAEnvironment": RAGQAEnvironment,
    "WorkspaceEnvironment": WorkspaceEnvironment,
    "AlphaTaskEnvironment": WorkspaceEnvironment,
}


def register_environment(name: str, cls: Type[BaseEnvironment]) -> None:
    _ENV_REGISTRY[name] = cls


def create_environment(config: EnvConfig, class_name: Optional[str] = None) -> BaseEnvironment:
    cls_name = class_name or config.extra_params.get("class", "DialogEnvironment")
    if cls_name not in _ENV_REGISTRY:
        raise ValueError(f"未注册的 Environment 类: {cls_name!r}。可用: {list(_ENV_REGISTRY.keys())}")
    return _ENV_REGISTRY[cls_name](config)
