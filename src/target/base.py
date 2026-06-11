"""
Target — 被测系统适配器抽象层。

"被测系统"是指评测的对象本身。和 LLM/Harness/Environment 三层并列：
  - LLM 层：评测某个模型本身的能力
  - Target 层：评测某个**完整应用 / 工具 / 服务**的能力（应用内部可能就在用 LLM）

Environment 通过统一的 `target.invoke(operation, payload)` 接口与被测系统通信，
不关心后面是 HTTP API、CLI 工具、Python 库、还是子进程。

内置 2 个适配器（registry 在 src/target/__init__.py）：
  HTTPAppTarget   REST / HTTP API（RAG 服务、Dify、自建 LangChain 服务…）
  MockTarget     离线测试

需要其他形态（CLI 工具 / Python 库 / stdio agent / MCP server …）时，子类化
BaseTarget 然后 `register_target(name, cls)` 即可，整个流程见类下方的注释 +
README §5 "Bring Your Own Target"。
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional


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
    """Standard response returned by a target adapter.

    内容统一形态：
      - content: 被测系统返回的"答案"主体（字符串、dict、list 等）
      - error:   非 None 表示这次调用失败；上层据此跳过评分或重试
      - latency_ms / status_code / metadata / raw_response: 观测字段
    """
    content: Any
    status_code: int = 200
    latency_ms: float = 0.0
    raw_response: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        # error 是统一的真理来源——HTTP 非 2xx 会被 invoke 设到 error 里，
        # CLI / 子进程的 returncode 也走同样的归一化逻辑。
        return self.error is None


class BaseTarget(ABC):
    """Base class for all target adapters.

    子类约定：
      - 实现 `invoke(operation, payload)`，**不要从中抛异常**——所有错误都包成
        `TargetResponse(error=...)` 返回，让上层评测流程能正常归档失败。
      - 声明 `capabilities` 列表（操作名集合）；空列表 = "任意操作我都试，
        不支持的回 error"。Agent 用这个字段做能力发现。
      - 长驻资源（client、subprocess、文件句柄）在 `close()` 里释放。
    """

    # 子类可在 __init__ 里赋实例属性，或直接写在类上。
    capabilities: ClassVar[List[str]] = []

    def __init__(self, config: TargetConfig):
        self.config = config

    # ── 公共 helper ────────────────────────────────────────────────────

    def _resolve_api_key(self) -> str:
        """统一从 api_key_env 或 api_key 解析最终 key。

        ConfigLoader 已经做过 ${VAR} 替换，但 api_key_env 是一层间接引用
        （YAML 写 `api_key_env: OPENAI_API_KEY` → 现在去读环境变量），
        所以这里再兜一次。
        """
        if self.config.api_key_env:
            val = os.getenv(self.config.api_key_env, "")
            if val:
                return val
        return self.config.api_key

    def supports(self, operation: str) -> bool:
        """子类声明的 capabilities 非空时，按白名单判断；否则放过去试。"""
        return not self.capabilities or operation in self.capabilities

    # ── 生命周期钩子 ──────────────────────────────────────────────────

    async def setup(self, task: Any = None) -> None:
        """每个任务开始前调用。需要 per-task 重置状态时覆盖。"""
        return None

    @abstractmethod
    async def invoke(
        self,
        operation: str,
        payload: Dict[str, Any],
        *,
        task: Any = None,
    ) -> TargetResponse:
        """执行一次被测系统调用。错误**必须**包成 TargetResponse 返回。"""
        ...

    async def teardown(self, task: Any = None) -> None:
        """每个任务结束后调用。需要 per-task 清理时覆盖。"""
        return None

    async def close(self) -> None:
        """释放长驻资源（HTTP client、subprocess 等）。"""
        return None
