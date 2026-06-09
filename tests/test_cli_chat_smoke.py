"""
CLI chat 模式的无依赖 smoke test。

测什么：
  - prompt_loader 能找到 skill 目录并加载 system prompt
  - 6 个工具的纯函数路径（read_file / list_dir / run_cli 不报错）
  - text-tool-call parser 能正确解析 <TOOL>...</TOOL>
  - _split_args 处理引号 / 嵌套 / 逗号边界
  - 用 MockLLM 当驾驶 LLM 跑一轮对话循环，验证 tool dispatch 链路通

不测：
  - 真实 LLM 端点（需要 endpoint）
  - 终端 UI 渲染（需要 tty）
  - write_file 的 confirm（需要 stdin）
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

# 让 import 路径包含项目根
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def test_prompt_loader_finds_skill_dir() -> None:
    from src.cli_chat.prompt_loader import find_skill_dir, load_system_prompt
    skill_dir = find_skill_dir()
    assert skill_dir is not None, "找不到 skill 目录"
    assert (skill_dir / "SKILL.md").exists()

    prompt = load_system_prompt(skill_dir)
    assert len(prompt) > 1000, f"system prompt 太短 ({len(prompt)} 字符)"
    assert "Eval-Anything" in prompt
    assert "闸门" in prompt
    assert "harness" in prompt.lower()
    assert "references/harness-selection.md" in prompt or "harness-selection.md" in prompt
    print(f"✓ prompt_loader: system prompt = {len(prompt)} 字符, 含关键字段")


def test_text_tool_call_parser() -> None:
    from src.cli_chat.agent import _parse_text_tool_calls

    text = '我需要看一下当前的 profile：<TOOL>run_cli(args=["--list-profiles"])</TOOL>'
    calls = _parse_text_tool_calls(text)
    assert len(calls) == 1
    assert calls[0][0] == "run_cli"
    assert calls[0][1] == {"args": ["--list-profiles"]}
    print(f"✓ text parser: 单工具调用 OK -> {calls}")

    text2 = '<TOOL>read_file(path="configs/llm_profiles.yaml")</TOOL>之后<TOOL>show_summary(text="done")</TOOL>'
    calls2 = _parse_text_tool_calls(text2)
    assert len(calls2) == 2
    assert calls2[0][0] == "read_file"
    assert calls2[0][1]["path"] == "configs/llm_profiles.yaml"
    assert calls2[1][0] == "show_summary"
    print(f"✓ text parser: 多工具调用 OK -> {[c[0] for c in calls2]}")


def test_split_args_edge_cases() -> None:
    from src.cli_chat.agent import _split_args
    assert _split_args('args=["a", "b, c"], cwd="."') == ['args=["a", "b, c"]', 'cwd="."']
    assert _split_args('q="why,how", opts=[1,2,3]') == ['q="why,how"', 'opts=[1,2,3]']
    print("✓ _split_args 边界情况 OK")


def test_tool_read_file() -> None:
    from src.cli_chat.tools import tool_read_file
    # 读项目根的 README，肯定存在
    result = tool_read_file(str(PROJECT_ROOT / "README.md"))
    assert result["ok"] is True
    assert "Eval Pipeline" in result["result"] or "评测" in result["result"]
    print(f"✓ tool_read_file: 读到 {len(result['result'])} 字符")

    bad = tool_read_file("/nonexistent/foo.md")
    assert bad["ok"] is False
    assert "不存在" in bad.get("error", "")
    print(f"✓ tool_read_file: 不存在文件正确报错")


def test_tool_list_dir() -> None:
    from src.cli_chat.tools import tool_list_dir
    result = tool_list_dir(str(PROJECT_ROOT / "src"))
    assert result["ok"] is True
    assert "cli_chat" in result["result"]
    assert "core" in result["result"]
    print(f"✓ tool_list_dir: src/ 下 {len(result['result'].splitlines())} 项")


def test_tool_run_cli() -> None:
    """run_cli 调真实子进程 — 用 --list-profiles 是安全的（只读）。"""
    from src.cli_chat.tools import tool_run_cli
    result = tool_run_cli(
        ["--list-profiles", "--config-dir", str(PROJECT_ROOT / "configs")],
        cwd=str(PROJECT_ROOT),
    )
    # 应该能成功列出 profile
    assert result["ok"] is True, f"run_cli 失败: {result}"
    assert "Profiles" in result["result"]
    assert "deepseek_v4_flash" in result["result"]
    print(f"✓ tool_run_cli: --list-profiles 成功，返回 {len(result['result'])} 字符")


def test_tool_dispatch_unknown() -> None:
    from src.cli_chat.tools import dispatch
    result = dispatch("no_such_tool", {})
    assert result["ok"] is False
    assert "未知工具" in result.get("error", "")
    print("✓ dispatch: 未知工具正确报错")


def test_tool_dispatch_bad_args() -> None:
    from src.cli_chat.tools import dispatch
    result = dispatch("read_file", {"wrong_arg": "x"})
    assert result["ok"] is False
    assert "参数" in result.get("error", "")
    print("✓ dispatch: 参数错误正确报错")


def test_agent_loop_with_mock_driver() -> None:
    """端到端：用 MockLLM 当驾驶 LLM 跑一轮对话循环。

    流程:
      1. MockLLM 第一次返回 <TOOL>read_file(path="README.md")</TOOL>
      2. agent 解析、dispatch、把 tool result 灌回 messages
      3. MockLLM 第二次返回纯文本（结束本轮）
      4. 验证 messages 链路完整、最终输出文本被打印
    """
    from src.cli_chat.agent import _drive_one_turn
    from src.llm.mock import MockLLM
    from src.llm.base import LLMConfig

    mock = MockLLM(LLMConfig(model_name="mock_driver", endpoint_url=""))
    mock.set_response(f'<TOOL>read_file(path="{PROJECT_ROOT}/pyproject.toml")</TOOL>')
    mock.set_response("我读完了 pyproject.toml，里面定义了两个 CLI 入口：eval-anything 和 eval-agent。")

    messages = [
        {"role": "system", "content": "system prompt placeholder"},
        {"role": "user", "content": "看一下 pyproject.toml"},
    ]

    asyncio.run(_drive_one_turn(mock, messages))

    # 验证消息链：system + user + assistant1(tool_call) + tool_result + assistant2(text)
    assert len(messages) >= 4, f"消息数太少: {len(messages)}"
    assert any(m.get("role") == "tool" for m in messages), "没产生 tool 消息"
    assert messages[-1]["role"] == "assistant"
    assert "pyproject" in messages[-1]["content"] or "eval-anything" in messages[-1]["content"]
    print(f"✓ agent loop: {len(messages)} 条消息，最后是 assistant 文本回复")
    print(f"  最后一条 assistant: {messages[-1]['content'][:80]}")


def test_driver_loader_picks_profile() -> None:
    """driver.load_driver 能从 llm_profiles 拿一个 profile 构造 LLM。"""
    from src.core.config import ConfigLoader
    from src.cli_chat.driver import load_driver

    loader = ConfigLoader(config_dir=str(PROJECT_ROOT / "configs"))
    # 直接指定一个已存在的 profile 名
    llm, profile = load_driver(loader, driver_name="deepseek_v4_flash")
    assert profile.name == "deepseek_v4_flash"
    assert profile.model_name == "DeepSeek-V4-Flash"
    # 不真调，只验证构造
    print(f"✓ driver loader: 加载 {profile.name} -> {llm.__class__.__name__}")


def test_config_paths_resolution() -> None:
    """config_paths.resolve_config_dir 按优先级回退。"""
    import os
    import tempfile
    from src import config_paths

    # 1. 显式 explicit
    with tempfile.TemporaryDirectory() as tmp:
        p, src = config_paths.resolve_config_dir(explicit=tmp)
        assert str(p) == str(Path(tmp).resolve())
        assert src == "explicit"

    # 2. ENV 变量
    os.environ.pop("EVAL_ANYTHING_CONFIG_DIR", None)
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["EVAL_ANYTHING_CONFIG_DIR"] = tmp
        try:
            p, src = config_paths.resolve_config_dir(None)
            assert str(p) == str(Path(tmp).resolve())
            assert src == "env"
        finally:
            os.environ.pop("EVAL_ANYTHING_CONFIG_DIR", None)

    # 3. cwd 回退（仓库根目录有 configs/）
    p, src = config_paths.resolve_config_dir(None)
    # 当前工作目录是项目根，应该走 cwd 或 user
    assert src in ("user", "cwd", "repo")

    # 4. user_config_dir 路径合理
    user_dir = config_paths.user_config_dir()
    assert "eval-anything" in str(user_dir)
    print(f"✓ config_paths: 解析路径正确，user_dir = {user_dir}")


def test_wizard_helper_functions() -> None:
    """wizard 的非交互辅助函数（不真跑 input()）。"""
    import tempfile
    from src.setup_wizard import wizard, PROVIDER_PRESETS

    # 1. provider 表非空、字段完整
    assert len(PROVIDER_PRESETS) >= 6
    for p in PROVIDER_PRESETS:
        assert p.id and p.label and p.profile_name and p.endpoint_url
    print(f"✓ wizard: {len(PROVIDER_PRESETS)} 个 provider 预设")

    # 2. _append_llm_profile 正确写入 / 幂等
    with tempfile.TemporaryDirectory() as tmp:
        yaml_path = Path(tmp) / "llm_profiles.yaml"
        wizard._append_llm_profile(
            yaml_path,
            "test_profile",
            {"class": "OpenAICompatibleLLM", "model_name": "test", "endpoint_url": "x"},
        )
        assert yaml_path.exists()
        content = yaml_path.read_text(encoding="utf-8")
        assert "test_profile" in content
        assert "OpenAICompatibleLLM" in content

        # 幂等：再追加一次同名 profile（覆盖）
        wizard._append_llm_profile(
            yaml_path,
            "test_profile",
            {"class": "OpenAICompatibleLLM", "model_name": "test_v2", "endpoint_url": "y"},
        )
        content = yaml_path.read_text(encoding="utf-8")
        assert "test_v2" in content
    print("✓ wizard: _append_llm_profile 写入 / 幂等覆盖 OK")

    # 3. _write_config_yaml 写出可读
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = Path(tmp) / "config.yaml"
        wizard._write_config_yaml(cfg_path, default_driver="my_driver")
        assert cfg_path.exists()
        loaded = wizard.load_user_config.__wrapped__() if hasattr(wizard.load_user_config, "__wrapped__") else None
        import yaml as yml
        loaded_data = yml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert loaded_data["default_driver"] == "my_driver"
        assert loaded_data["setup_version"] == 1
    print("✓ wizard: _write_config_yaml 写入 OK")

    # 4. _build_profile_dict 三种 store_method
    p = PROVIDER_PRESETS[1]  # deepseek
    d_plain = wizard._build_profile_dict(p, p.model_name, "sk-xxx", None, "plaintext")
    assert d_plain["api_key"] == "sk-xxx"
    assert "api_key_env" not in d_plain

    d_env = wizard._build_profile_dict(p, p.model_name, "EMPTY_PLACEHOLDER", p.env_var, "env")
    assert d_env["api_key_env"] == p.env_var
    assert "api_key" not in d_env

    d_already = wizard._build_profile_dict(p, p.model_name, "EMPTY_PLACEHOLDER", p.env_var, "already_exported")
    assert d_already["api_key_env"] == p.env_var
    print("✓ wizard: _build_profile_dict 三种 store_method OK")


def test_api_key_env_resolution() -> None:
    """验证 ConfigLoader 能正确从环境变量解析 api_key。"""
    import os
    import tempfile
    from src.core.config import ConfigLoader

    # 创建一个临时 configs/ 目录，里面 llm_profiles.yaml 用三种 api_key 形态
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "llm_profiles.yaml").write_text(
            "llm_profiles:\n"
            "  profile_a_envkey:\n"
            "    class: OpenAICompatibleLLM\n"
            "    model_name: a\n"
            "    endpoint_url: https://x/v1/chat/completions\n"
            "    api_key_env: TEST_FAKE_KEY_A\n"
            "  profile_b_dollar:\n"
            "    class: OpenAICompatibleLLM\n"
            "    model_name: b\n"
            "    endpoint_url: https://x/v1/chat/completions\n"
            "    api_key: ${TEST_FAKE_KEY_B}\n"
            "  profile_c_plain:\n"
            "    class: OpenAICompatibleLLM\n"
            "    model_name: c\n"
            "    endpoint_url: https://x/v1/chat/completions\n"
            "    api_key: literal_value\n"
            "  profile_d_missing_env:\n"
            "    class: OpenAICompatibleLLM\n"
            "    model_name: d\n"
            "    endpoint_url: https://x/v1/chat/completions\n"
            "    api_key: ${TEST_DEFINITELY_UNSET_VAR}\n",
            encoding="utf-8",
        )
        # 还要 environments.yaml / harness_profiles.yaml 文件存在（ConfigLoader 在 load 时按需打开）
        (tmp_path / "environments.yaml").write_text("environments: {}\n", encoding="utf-8")
        (tmp_path / "harness_profiles.yaml").write_text("harness_profiles: {}\n", encoding="utf-8")

        os.environ["TEST_FAKE_KEY_A"] = "key_from_env_a"
        os.environ["TEST_FAKE_KEY_B"] = "key_from_env_b"
        os.environ.pop("TEST_DEFINITELY_UNSET_VAR", None)

        try:
            loader = ConfigLoader(config_dir=str(tmp_path))
            profiles = loader.load_llm_profiles()
            assert profiles["profile_a_envkey"].api_key == "key_from_env_a"
            assert profiles["profile_b_dollar"].api_key == "key_from_env_b"
            assert profiles["profile_c_plain"].api_key == "literal_value"
            # 没设的环境变量保留 placeholder，让端点真打 401 而不是悄悄发空 key
            assert profiles["profile_d_missing_env"].api_key == "${TEST_DEFINITELY_UNSET_VAR}"
        finally:
            os.environ.pop("TEST_FAKE_KEY_A", None)
            os.environ.pop("TEST_FAKE_KEY_B", None)

    print("✓ api_key 解析: api_key_env / ${VAR} / 明文 / 未设变量 4 种路径都对")


def run_all() -> None:
    tests = [
        test_prompt_loader_finds_skill_dir,
        test_text_tool_call_parser,
        test_split_args_edge_cases,
        test_tool_read_file,
        test_tool_list_dir,
        test_tool_run_cli,
        test_tool_dispatch_unknown,
        test_tool_dispatch_bad_args,
        test_driver_loader_picks_profile,
        test_api_key_env_resolution,
        test_config_paths_resolution,
        test_wizard_helper_functions,
        test_agent_loop_with_mock_driver,
    ]
    passed = 0
    failed = 0
    for t in tests:
        name = t.__name__
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"✗ {name}: 断言失败: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {name}: 异常: {type(e).__name__}: {e}")
            failed += 1

    total = passed + failed
    print(f"\n{'='*60}")
    print(f"Smoke test 结果: {passed}/{total} 通过, {failed} 失败")
    print(f"{'='*60}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    run_all()
