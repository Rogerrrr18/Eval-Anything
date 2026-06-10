"""
${VAR} / ${VAR:-default} 环境变量插值测试。

判 ConfigLoader._resolve_env_value 直接 + 在 JudgeProfile / LLMProfile 上的端到端表现。
"""
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import ConfigLoader


def test_resolve_plain_string_unchanged():
    assert ConfigLoader._resolve_env_value("gpt-4o") == "gpt-4o"
    assert ConfigLoader._resolve_env_value("") == ""
    # 非 str 原样返回（数值、bool 等）
    assert ConfigLoader._resolve_env_value(42) == 42
    assert ConfigLoader._resolve_env_value(None) is None


def test_resolve_unset_no_default_keeps_placeholder():
    # 没设变量且没 default → 保留原 placeholder，让下游报错
    os.environ.pop("NEVER_SET_HOPEFULLY_XYZ", None)
    out = ConfigLoader._resolve_env_value("${NEVER_SET_HOPEFULLY_XYZ}")
    assert out == "${NEVER_SET_HOPEFULLY_XYZ}"


def test_resolve_unset_with_default_falls_back():
    os.environ.pop("NEVER_SET_HOPEFULLY_XYZ", None)
    out = ConfigLoader._resolve_env_value("${NEVER_SET_HOPEFULLY_XYZ:-gpt-4o-mini}")
    assert out == "gpt-4o-mini"


def test_resolve_set_var_wins_over_default():
    os.environ["MY_TEST_VAR"] = "actual_value"
    try:
        out = ConfigLoader._resolve_env_value("${MY_TEST_VAR:-fallback}")
        assert out == "actual_value"
    finally:
        del os.environ["MY_TEST_VAR"]


def test_resolve_empty_string_var_falls_back_to_default():
    """空字符串视为未设，落到 default。"""
    os.environ["EMPTY_TEST_VAR"] = ""
    try:
        out = ConfigLoader._resolve_env_value("${EMPTY_TEST_VAR:-default_val}")
        assert out == "default_val"
    finally:
        del os.environ["EMPTY_TEST_VAR"]


def test_resolve_multiple_vars_in_one_string():
    os.environ["VAR_A"] = "hello"
    os.environ.pop("VAR_B", None)
    try:
        out = ConfigLoader._resolve_env_value("${VAR_A}/${VAR_B:-world}")
        assert out == "hello/world"
    finally:
        del os.environ["VAR_A"]


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content), encoding="utf-8")


def test_judge_profile_model_name_overridden_by_env():
    """端到端：YAML 写 ${OPENAI_JUDGE_MODEL:-gpt-4o}，env 设了就用 env 值。"""
    with tempfile.TemporaryDirectory() as tmp:
        config_dir = Path(tmp) / "configs"
        config_dir.mkdir()

        _write_yaml(config_dir / "judge_profiles.yaml", """\
        judge_profiles:
          test_judge:
            class: "OpenAICompatibleLLM"
            model_name: "${TEST_JUDGE_MODEL:-gpt-4o}"
            endpoint_url: "${TEST_JUDGE_ENDPOINT:-https://api.openai.com/v1/chat/completions}"
            api_key_env: "TEST_JUDGE_API_KEY"
            temperature: 0.0
            max_tokens: 800
            threshold: 0.6
        """)

        os.environ.pop("TEST_JUDGE_MODEL", None)
        os.environ.pop("TEST_JUDGE_ENDPOINT", None)

        loader = ConfigLoader(str(config_dir))
        profile = loader.get_judge_profile("test_judge")
        assert profile.model_name == "gpt-4o"  # 用 default
        assert profile.endpoint_url == "https://api.openai.com/v1/chat/completions"

        # 切环境变量 → 重建 loader 验证覆盖生效
        os.environ["TEST_JUDGE_MODEL"] = "gpt-4o-mini"
        os.environ["TEST_JUDGE_ENDPOINT"] = "https://my-proxy.example.com/v1/chat/completions"
        try:
            loader2 = ConfigLoader(str(config_dir))
            profile2 = loader2.get_judge_profile("test_judge")
            assert profile2.model_name == "gpt-4o-mini"
            assert profile2.endpoint_url == "https://my-proxy.example.com/v1/chat/completions"
        finally:
            del os.environ["TEST_JUDGE_MODEL"]
            del os.environ["TEST_JUDGE_ENDPOINT"]


def test_llm_profile_model_name_overridden_by_env():
    """端到端：LLMProfile 同样支持 model_name 用 ${VAR:-default}。"""
    with tempfile.TemporaryDirectory() as tmp:
        config_dir = Path(tmp) / "configs"
        config_dir.mkdir()

        _write_yaml(config_dir / "llm_profiles.yaml", """\
        llm_profiles:
          test_llm:
            class: "OpenAICompatibleLLM"
            model_name: "${TEST_LLM_MODEL:-qwen-max}"
            endpoint_url: "${TEST_LLM_ENDPOINT:-https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions}"
            api_key_env: "TEST_LLM_API_KEY"
        """)

        os.environ.pop("TEST_LLM_MODEL", None)
        loader = ConfigLoader(str(config_dir))
        profile = loader.get_llm_profile("test_llm")
        assert profile.model_name == "qwen-max"

        os.environ["TEST_LLM_MODEL"] = "qwen-plus"
        try:
            loader2 = ConfigLoader(str(config_dir))
            profile2 = loader2.get_llm_profile("test_llm")
            assert profile2.model_name == "qwen-plus"
        finally:
            del os.environ["TEST_LLM_MODEL"]


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
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
