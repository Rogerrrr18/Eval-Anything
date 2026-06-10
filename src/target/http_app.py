"""
HTTP application target.

This adapter lets an Environment evaluate a whole application through its API,
instead of treating every benchmark subject as a bare LLM model.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict

import httpx

from .base import BaseTarget, TargetConfig, TargetResponse


class HTTPAppTarget(BaseTarget):
    """Generic HTTP target using operation -> endpoint mapping."""

    def __init__(self, config: TargetConfig):
        super().__init__(config)
        headers = dict(config.headers)
        api_key = os.getenv(config.api_key_env or "", "") or config.api_key
        auth_header = config.extra_params.get("auth_header", "Authorization")
        auth_prefix = config.extra_params.get("auth_prefix", "Bearer")
        if api_key and api_key != "EMPTY" and auth_header not in headers:
            headers[auth_header] = f"{auth_prefix} {api_key}".strip()

        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(config.timeout_seconds, connect=10.0),
        )

    async def invoke(
        self,
        operation: str,
        payload: Dict[str, Any],
        *,
        task: Any = None,
    ) -> TargetResponse:
        endpoint = self.config.endpoints.get(operation)
        if not endpoint:
            return TargetResponse(
                content=None,
                status_code=0,
                error=f"Target {self.config.name!r} has no endpoint for operation {operation!r}",
            )

        method = self.config.extra_params.get("methods", {}).get(operation, "POST").upper()
        start = time.perf_counter()
        try:
            if method == "GET":
                response = await self._client.get(endpoint, params=payload)
            else:
                response = await self._client.request(method, endpoint, json=payload)
            latency = (time.perf_counter() - start) * 1000
            content_type = response.headers.get("content-type", "")
            raw: Any
            if "application/json" in content_type:
                raw = response.json()
            else:
                raw = response.text
            return TargetResponse(
                content=raw,
                status_code=response.status_code,
                latency_ms=latency,
                raw_response=raw,
                metadata={"operation": operation, "endpoint": endpoint, "method": method},
                error=None if response.is_success else response.text,
            )
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            return TargetResponse(
                content=None,
                status_code=0,
                latency_ms=latency,
                metadata={"operation": operation, "endpoint": endpoint, "method": method},
                error=str(exc),
            )

    async def close(self) -> None:
        await self._client.aclose()
