"""
Target abstraction — adapters for systems under evaluation.

A target can be a plain LLM endpoint, an HTTP application, a CLI tool, or a
mock used by tests. Environments decide how to call a target for a task.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class TargetConfig:
    """Configuration for a system under evaluation."""
    name: str
    class_name: str = "HTTPAppTarget"
    base_url: str = ""
    endpoints: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    api_key: str = "EMPTY"
    api_key_env: Optional[str] = None
    timeout_seconds: int = 60
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetResponse:
    """Standard response returned by a target adapter."""
    content: Any
    status_code: int = 200
    latency_ms: float = 0.0
    raw_response: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and 200 <= self.status_code < 300


class BaseTarget(ABC):
    """Base class for all target adapters."""

    def __init__(self, config: TargetConfig):
        self.config = config

    async def setup(self, task: Any = None) -> None:
        """Prepare target state for a task. Subclasses may override."""
        return None

    @abstractmethod
    async def invoke(
        self,
        operation: str,
        payload: Dict[str, Any],
        *,
        task: Any = None,
    ) -> TargetResponse:
        """Invoke one operation on the target."""
        ...

    async def teardown(self, task: Any = None) -> None:
        """Clean up target state for a task. Subclasses may override."""
        return None

    async def close(self) -> None:
        """Release any long-lived resources."""
        return None
