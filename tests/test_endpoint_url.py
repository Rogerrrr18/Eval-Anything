"""
split_endpoint_url 测试 — 覆盖各家厂商的真实 endpoint 形态。

回归背景：旧实现用 "/v1" 子串切分 base_url，
GLM (/api/paas/v4/...) 和 Gemini (/v1beta/openai/...) 都会被切坏。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.openai_compatible import split_endpoint_url


def test_openai_standard():
    base, path = split_endpoint_url("https://api.openai.com/v1/chat/completions")
    assert base == "https://api.openai.com"
    assert path == "/v1/chat/completions"


def test_glm_v4_path_not_mangled():
    """GLM 没有 /v1 — 旧实现会把整个 URL 当 base_url，路径重复 404。"""
    base, path = split_endpoint_url("https://open.bigmodel.cn/api/paas/v4/chat/completions")
    assert base == "https://open.bigmodel.cn"
    assert path == "/api/paas/v4/chat/completions"


def test_gemini_v1beta_not_truncated():
    """Gemini 的 /v1beta 含 /v1 子串 — 旧实现会误切丢掉 /v1beta/openai 前缀。"""
    base, path = split_endpoint_url(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert base == "https://generativelanguage.googleapis.com"
    assert path == "/v1beta/openai/chat/completions"


def test_local_vllm_with_port():
    base, path = split_endpoint_url("http://localhost:8000/v1/chat/completions")
    assert base == "http://localhost:8000"
    assert path == "/v1/chat/completions"


def test_dashscope_compatible_mode():
    base, path = split_endpoint_url(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    assert base == "https://dashscope.aliyuncs.com"
    assert path == "/compatible-mode/v1/chat/completions"


def test_bare_host_defaults_to_v1_chat_completions():
    base, path = split_endpoint_url("https://my-proxy.example.com")
    assert base == "https://my-proxy.example.com"
    assert path == "/v1/chat/completions"


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
