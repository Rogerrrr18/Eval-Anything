"""
Target registry + 内置 target 的封装测试。

覆盖：
  - registry 内置成员 + register_target + 错误类名提示
  - HTTPAppTarget.capabilities 从 endpoints 推导
  - MockTarget 队列弹出 + 空队列降级
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.target import (
    BaseTarget,
    HTTPAppTarget,
    MockTarget,
    TargetConfig,
    create_target,
    list_available_targets,
    register_target,
)


# ── Registry ────────────────────────────────────────────────────────────────

def test_registry_has_builtin_targets():
    targets = list_available_targets()
    assert "HTTPAppTarget" in targets
    assert "MockTarget" in targets


def test_registry_unknown_target_raises_with_listing():
    config = TargetConfig(name="x", class_name="NotARealTarget")
    try:
        create_target(config)
    except ValueError as e:
        msg = str(e)
        assert "NotARealTarget" in msg
        assert "HTTPAppTarget" in msg  # 错误信息要列出可用项，方便排错
    else:
        raise AssertionError("应该抛 ValueError")


def test_register_custom_target():
    """register_target 接受第三方子类——这是 Target 扩展点的核心契约。"""
    class DummyTarget(BaseTarget):
        async def invoke(self, operation, payload, *, task=None):
            from src.target.base import TargetResponse
            return TargetResponse(content="dummy")

    register_target("DummyTarget", DummyTarget)
    try:
        assert "DummyTarget" in list_available_targets()
        target = create_target(TargetConfig(name="d", class_name="DummyTarget"))
        result = asyncio.run(target.invoke("anything", {}))
        assert result.content == "dummy"
        assert result.ok  # error is None → ok
    finally:
        # 不污染全局 registry
        from src.target import _TARGET_REGISTRY
        _TARGET_REGISTRY.pop("DummyTarget", None)


# ── HTTPAppTarget ───────────────────────────────────────────────────────────

def test_http_target_capabilities_from_endpoints():
    cfg = TargetConfig(
        name="rag", class_name="HTTPAppTarget",
        base_url="http://example.com",
        endpoints={"chat": "/chat", "search": "/search"},
    )
    target = HTTPAppTarget(cfg)
    assert set(target.capabilities) == {"chat", "search"}
    assert target.supports("chat")
    assert not target.supports("missing")
    asyncio.run(target.close())


# ── MockTarget ──────────────────────────────────────────────────────────────

def test_mock_target_queue_pops_and_falls_back():
    cfg = TargetConfig(
        name="m", class_name="MockTarget",
        extra_params={"responses": [{"a": 1}, "second"]},
    )
    target = MockTarget(cfg)
    r1 = asyncio.run(target.invoke("op", {}))
    r2 = asyncio.run(target.invoke("op", {}))
    r3 = asyncio.run(target.invoke("op", {}))
    assert r1.content == {"a": 1}
    assert r2.content == "second"
    assert r3.content == {}  # 队列空时降级
    assert len(target.call_log) == 3


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
