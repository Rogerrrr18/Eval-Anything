"""
Mock target for tests and offline demos.
"""
from __future__ import annotations

from typing import Any, Dict, List

from .base import BaseTarget, TargetConfig, TargetResponse


class MockTarget(BaseTarget):
    """Queue-based target adapter that returns configured responses."""

    def __init__(self, config: TargetConfig):
        super().__init__(config)
        self._responses: List[Any] = list(config.extra_params.get("responses", []))
        self.call_log: List[Dict[str, Any]] = []

    async def invoke(
        self,
        operation: str,
        payload: Dict[str, Any],
        *,
        task: Any = None,
    ) -> TargetResponse:
        self.call_log.append({"operation": operation, "payload": payload, "task": task})
        content = self._responses.pop(0) if self._responses else {}
        return TargetResponse(
            content=content,
            status_code=200,
            raw_response=content,
            metadata={"operation": operation},
        )
