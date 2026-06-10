"""
Target registry.
"""
from __future__ import annotations

from typing import Dict, Optional, Type

from .base import BaseTarget, TargetConfig
from .http_app import HTTPAppTarget
from .mock import MockTarget


_TARGET_REGISTRY: Dict[str, Type[BaseTarget]] = {
    "HTTPAppTarget": HTTPAppTarget,
    "MockTarget": MockTarget,
}


def register_target(name: str, cls: Type[BaseTarget]) -> None:
    _TARGET_REGISTRY[name] = cls


def create_target(config: TargetConfig, class_name: Optional[str] = None) -> BaseTarget:
    cls_name = class_name or config.class_name
    if cls_name not in _TARGET_REGISTRY:
        raise ValueError(f"未注册的 Target 类: {cls_name!r}。可用: {list(_TARGET_REGISTRY.keys())}")
    return _TARGET_REGISTRY[cls_name](config)
