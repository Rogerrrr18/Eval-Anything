"""
首次启动配置向导 — 像 hermes / open-interpreter / aider 那种一键上手体验。

流程：
  1. 检测用户配置是否已存在；存在时除非 --init 否则跳过
  2. 选 LLM provider
  3. 收集 API key（明文 / 环境变量 / 已 export）
  4. 选默认模型
  5. 写 ~/.config/eval-anything/llm_profiles.yaml 和 config.yaml

config.yaml 长这样:
  default_driver: deepseek_chat
  setup_version: 1

llm_profiles.yaml 跟现有 schema 完全一致，从 packaged/repo 的模板复制 + 追加本次新建的 profile。
"""
from __future__ import annotations

import os
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .. import config_paths


# ── Provider 预设表 ──

@dataclass
class ProviderPreset:
    id: str
    label: str
    profile_name: str
    model_name: str
    endpoint_url: str
    env_var: str
    api_key_url: str
    supports_tools: bool
    default_max_tokens: int = 2000
    default_timeout: int = 60
    enable_thinking: bool = False


PROVIDER_PRESETS: List[ProviderPreset] = [
    ProviderPreset(
        id="openai",
        label="OpenAI (gpt-4o / gpt-4o-mini)",
        profile_name="openai_gpt4o_mini",
        model_name="gpt-4o-mini",
        endpoint_url="https://api.openai.com/v1/chat/completions",
        env_var="OPENAI_API_KEY",
        api_key_url="https://platform.openai.com/api-keys",
        supports_tools=True,
    ),
    ProviderPreset(
        id="deepseek",
        label="DeepSeek (deepseek-chat / deepseek-reasoner)",
        profile_name="deepseek_chat",
        model_name="deepseek-chat",
        endpoint_url="https://api.deepseek.com/v1/chat/completions",
        env_var="DEEPSEEK_API_KEY",
        api_key_url="https://platform.deepseek.com/api_keys",
        supports_tools=True,
    ),
    ProviderPreset(
        id="qwen",
        label="阿里云 DashScope / Qwen (qwen-max / qwen3-*-instruct)",
        profile_name="qwen_max",
        model_name="qwen-max",
        endpoint_url="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        env_var="DASHSCOPE_API_KEY",
        api_key_url="https://dashscope.aliyun.com/",
        supports_tools=True,
    ),
    ProviderPreset(
        id="moonshot",
        label="Moonshot / Kimi (moonshot-v1-32k)",
        profile_name="kimi_v1",
        model_name="moonshot-v1-32k",
        endpoint_url="https://api.moonshot.cn/v1/chat/completions",
        env_var="MOONSHOT_API_KEY",
        api_key_url="https://platform.moonshot.cn/console/api-keys",
        supports_tools=True,
    ),
    ProviderPreset(
        id="zhipu",
        label="智谱 GLM (glm-4)",
        profile_name="glm4",
        model_name="glm-4",
        endpoint_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        env_var="ZHIPU_API_KEY",
        api_key_url="https://open.bigmodel.cn/usercenter/apikeys",
        supports_tools=True,
    ),
    ProviderPreset(
        id="local",
        label="本地 OpenAI 兼容端点 (vLLM / SGLang / Ollama / LMStudio)",
        profile_name="local_vllm",
        model_name="your-local-model",
        endpoint_url="http://localhost:8000/v1/chat/completions",
        env_var="",
        api_key_url="(无需 key，本地端点)",
        supports_tools=False,  # 取决于具体模型，保守标 False
    ),
    ProviderPreset(
        id="custom",
        label="其他自定义 OpenAI 兼容端点",
        profile_name="custom_endpoint",
        model_name="your-model",
        endpoint_url="https://your-endpoint/v1/chat/completions",
        env_var="CUSTOM_API_KEY",
        api_key_url="(填你自己的 API key 获取地址)",
        supports_tools=False,
    ),
]


# ── 终端 IO 辅助 ──

def _color() -> bool:
    return sys.stdout.isatty() and os.name != "nt"

C = _color()
CYAN = "\033[36m" if C else ""
GREEN = "\033[32m" if C else ""
YELLOW = "\033[33m" if C else ""
RED = "\033[31m" if C else ""
GRAY = "\033[90m" if C else ""
BOLD = "\033[1m" if C else ""
RESET = "\033[0m" if C else ""


def _info(msg: str) -> None:
    print(f"{CYAN}{msg}{RESET}")


def _ok(msg: str) -> None:
    print(f"{GREEN}{msg}{RESET}")


def _warn(msg: str) -> None:
    print(f"{YELLOW}{msg}{RESET}")


def _err(msg: str) -> None:
    print(f"{RED}{msg}{RESET}")


def _prompt(text: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    print(f"{BOLD}{text}{suffix}{RESET}: ", end="", flush=True)
    try:
        ans = input().strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise
    return ans or (default or "")


def _choose(prompt: str, options: List[str]) -> int:
    """让用户从 options 里选一个，返回 index。"""
    print(f"\n{BOLD}{prompt}{RESET}")
    for i, opt in enumerate(options, 1):
        print(f"  {YELLOW}{i}.{RESET} {opt}")
    while True:
        ans = _prompt("Choose")
        if not ans:
            continue
        if ans.isdigit() and 1 <= int(ans) <= len(options):
            return int(ans) - 1
        _err(f"请输入 1-{len(options)} 之间的数字")


# ── 主向导 ──

def run_wizard(force: bool = False) -> Path:
    """运行配置向导。

    Args:
        force: 即使用户配置已存在也强制重跑

    Returns:
        生成的 user config dir 路径
    """
    user_dir = config_paths.user_config_dir()

    print(f"\n{CYAN}{BOLD}═══════════════════════════════════════════════════════════════{RESET}")
    print(f"{CYAN}{BOLD}  Eval-Anything 配置向导{RESET}")
    print(f"{GRAY}  配置将保存到: {user_dir}{RESET}")
    print(f"{CYAN}{BOLD}═══════════════════════════════════════════════════════════════{RESET}\n")

    if config_paths.has_user_config() and not force:
        _warn("检测到已有用户配置。如需重新配置请用 --init。")
        return user_dir

    # Step 1: 从 packaged/repo 复制默认 configs/ 作为骨架
    seed_dir = _find_seed_config_dir()
    if seed_dir:
        _info(f"从 {seed_dir} 复制默认配置骨架...")
        config_paths.bootstrap_user_config(seed_dir)
    else:
        _warn("找不到默认配置骨架，将从零生成最小配置")
        user_dir.mkdir(parents=True, exist_ok=True)
        _create_minimal_skeleton(user_dir)

    # Step 2: 选 provider
    preset = _choose_provider()

    # Step 3: 收集 API key
    api_key_value, api_key_env, store_method = _collect_api_key(preset)

    # Step 4: 模型名（允许用户改成同 provider 的其他模型）
    model_name = _prompt(
        f"使用哪个模型？(provider 默认 {preset.model_name}，可改成同 provider 其他模型)",
        default=preset.model_name,
    )

    # Step 5: profile name
    profile_name = _prompt(
        f"给这个 profile 取个名字 (字母数字下划线)",
        default=preset.profile_name,
    )
    profile_name = profile_name.replace("-", "_")

    # Step 6: 写入 llm_profiles.yaml
    profile_dict = _build_profile_dict(
        preset=preset,
        model_name=model_name,
        api_key_value=api_key_value,
        api_key_env=api_key_env,
        store_method=store_method,
    )
    _append_llm_profile(user_dir / "llm_profiles.yaml", profile_name, profile_dict)
    _ok(f"已写入 {user_dir / 'llm_profiles.yaml'} (profile: {profile_name})")

    # Step 7: 写 config.yaml 设默认 driver
    _write_config_yaml(user_dir / "config.yaml", default_driver=profile_name)
    _ok(f"已写入 {user_dir / 'config.yaml'} (default_driver: {profile_name})")

    # Step 8: env 变量提示
    if store_method == "env":
        _warn(
            f"\n⚠️  你选择了用环境变量存 key。请确保已 export {api_key_env}=...\n"
            f"    可加进 ~/.bashrc / ~/.zshrc 让重启 shell 后仍生效。"
        )
    elif store_method == "already_exported":
        cur = os.getenv(api_key_env)
        if not cur:
            _err(
                f"\n⚠️  你说已 export 但环境变量 {api_key_env} 当前为空。\n"
                f"    请确认后再启动 chat 模式。"
            )

    # 完成
    print(f"\n{GREEN}{BOLD}═══ 配置完成 ═══{RESET}")
    print(f"{GREEN}下一步：直接运行 `eval-anything` 进入对话模式{RESET}")
    print(f"{GRAY}也可以用 `eval-anything --driver <other_profile>` 切驾驶 LLM{RESET}")
    print(f"{GRAY}重新配置：`eval-anything --init`{RESET}\n")

    return user_dir


# ── 内部 ──

def _find_seed_config_dir() -> Optional[Path]:
    """找一个默认配置目录用于初始化骨架。"""
    packaged = config_paths.packaged_config_dir()
    if packaged:
        return packaged
    repo = config_paths.repo_config_dir()
    if repo:
        return repo
    return None


def _create_minimal_skeleton(target: Path) -> None:
    """没找到 seed 时创建最小骨架，避免后续打开文件失败。"""
    (target / "llm_profiles.yaml").write_text("llm_profiles: {}\n", encoding="utf-8")
    (target / "harness_profiles.yaml").write_text(
        "harness_profiles:\n"
        "  raw:\n"
        "    class: RawHarness\n"
        "    max_steps: 1\n"
        "    description: 直接 prompt-in / response-out 基线\n",
        encoding="utf-8",
    )
    (target / "environments.yaml").write_text("environments: {}\n", encoding="utf-8")


def _choose_provider() -> ProviderPreset:
    options = [p.label for p in PROVIDER_PRESETS]
    idx = _choose("选一个 LLM provider", options)
    return PROVIDER_PRESETS[idx]


def _collect_api_key(preset: ProviderPreset) -> tuple[str, Optional[str], str]:
    """收集 API key。

    Returns:
        (api_key_value, api_key_env, store_method)
        - store_method: "plaintext" / "env" / "already_exported" / "none"
    """
    if not preset.env_var:
        _info("该端点无需 API key（本地端点）")
        return "EMPTY", None, "none"

    print()
    _info(f"获取 API key: {preset.api_key_url}")
    print(f"  环境变量名建议: {YELLOW}{preset.env_var}{RESET}")

    options = [
        "我已经 export 过环境变量了（推荐）",
        f"我想现在 export，向导提示我命令",
        "把 key 写进配置文件（明文，方便但不安全）",
    ]
    idx = _choose("API key 怎么存？", options)

    if idx == 0:
        return "EMPTY_PLACEHOLDER", preset.env_var, "already_exported"

    if idx == 1:
        key = _prompt(f"先在这里粘贴你的 API key（不会写入文件，只用于提示命令）")
        if not key:
            _warn("没输入 key，回退到明文模式")
            idx = 2
        else:
            print(f"\n{YELLOW}请运行下面这行命令（推荐加进 ~/.zshrc 或 ~/.bashrc）：{RESET}")
            print(f"{GREEN}  export {preset.env_var}={key}{RESET}\n")
            _prompt("做完后回车继续")
            return "EMPTY_PLACEHOLDER", preset.env_var, "env"

    # 明文
    key = _prompt(f"直接输入你的 {preset.label} API key")
    if not key:
        _err("API key 为空，向导无法继续")
        raise SystemExit(1)
    return key, None, "plaintext"


def _build_profile_dict(
    preset: ProviderPreset,
    model_name: str,
    api_key_value: str,
    api_key_env: Optional[str],
    store_method: str,
) -> Dict[str, Any]:
    """构造 yaml 里的 profile 字典。"""
    profile: Dict[str, Any] = {
        "class": "OpenAICompatibleLLM",
        "model_name": model_name,
        "endpoint_url": preset.endpoint_url,
        "temperature": 0.0,
        "max_tokens": preset.default_max_tokens,
        "top_p": 1.0,
        "timeout_seconds": preset.default_timeout,
        "enable_thinking": preset.enable_thinking,
    }
    if store_method == "plaintext":
        profile["api_key"] = api_key_value
    elif store_method in ("env", "already_exported"):
        profile["api_key_env"] = api_key_env
    else:
        profile["api_key"] = "EMPTY"
    return profile


def _append_llm_profile(yaml_path: Path, name: str, profile: Dict[str, Any]) -> None:
    """把一个 profile 追加到 llm_profiles.yaml。

    保留现有内容，幂等地追加 / 覆盖同名 profile。
    """
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    if yaml_path.exists():
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    else:
        raw = {}
    profiles = raw.get("llm_profiles") or {}
    profiles[name] = profile
    raw["llm_profiles"] = profiles
    yaml_path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _write_config_yaml(path: Path, default_driver: str) -> None:
    """写用户主配置 config.yaml。"""
    cfg = {
        "setup_version": 1,
        "default_driver": default_driver,
    }
    existing = {}
    if path.exists():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
    existing.update(cfg)
    path.write_text(
        yaml.safe_dump(existing, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def load_user_config() -> Dict[str, Any]:
    """读用户 config.yaml。不存在时返回空 dict。"""
    path = config_paths.user_config_dir() / "config.yaml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
