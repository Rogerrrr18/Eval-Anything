"""
Target registry — 被测系统适配器注册表。

内置 2 个 target：

| 类名            | 适配 |
|---------------|------|
| HTTPAppTarget | REST / HTTP API（RAG、Dify、自建 web 服务等） |
| MockTarget    | 离线测试 |

需要评测其他形态的项目（CLI 工具、Python 库、stdio agent 等）时，
子类化 `BaseTarget` 然后调用 `register_target` 即可——见 BaseTarget docstring 与
README §5 "Bring Your Own Target"。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Type

from .base import BaseTarget, TargetConfig, TargetResponse
from .http_app import HTTPAppTarget
from .mock import MockTarget


_TARGET_REGISTRY: Dict[str, Type[BaseTarget]] = {
    "HTTPAppTarget": HTTPAppTarget,
    "MockTarget": MockTarget,
}


def register_target(name: str, cls: Type[BaseTarget]) -> None:
    """注册第三方 target 类。重复注册会覆盖。

    使用方式：
        from src.target import BaseTarget, TargetResponse, register_target

        class MyTarget(BaseTarget):
            capabilities = ["chat"]
            async def invoke(self, operation, payload, *, task=None):
                ...
                return TargetResponse(content=..., ...)

        register_target("MyTarget", MyTarget)
        # 之后 YAML 里 `class: MyTarget` 就能用了
    """
    _TARGET_REGISTRY[name] = cls


def list_available_targets() -> List[str]:
    """返回当前已注册的所有 target 类名。CLI / agent 用于能力发现。"""
    return sorted(_TARGET_REGISTRY.keys())


def create_target(config: TargetConfig, class_name: Optional[str] = None) -> BaseTarget:
    cls_name = class_name or config.class_name
    if cls_name not in _TARGET_REGISTRY:
        raise ValueError(
            f"未注册的 Target 类: {cls_name!r}。"
            f" 已注册: {list_available_targets()}"
        )
    return _TARGET_REGISTRY[cls_name](config)


__all__ = [
    "BaseTarget",
    "HTTPAppTarget",
    "MockTarget",
    "TargetConfig",
    "TargetResponse",
    "create_target",
    "list_available_targets",
    "register_target",
]
