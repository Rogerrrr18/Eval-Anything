"""
配置 / 缓存 / 输出 目录的智能解析。

解析顺序（优先级从高到低）：
  1. CLI 参数 --config-dir 显式传入
  2. 环境变量 EVAL_ANYTHING_CONFIG_DIR
  3. 用户级: ~/.config/eval-anything/ （macOS/Linux 走 XDG，Windows 走 APPDATA）
  4. 当前工作目录下的 ./configs/ （如果存在）
  5. repo 内打包的 configs/ （pip install 时一并安装的默认值）

设计意图：
  - 全局安装（pipx）后，默认走用户配置目录
  - 在 repo 里开发时，用 repo 内 configs/
  - CI / 临时实验，用 EVAL_ANYTHING_CONFIG_DIR 切换
"""
from __future__ import annotations

import os
import shutil
import sysconfig
from pathlib import Path
from typing import Optional


APP_NAME = "eval-anything"


def user_config_dir() -> Path:
    """用户配置目录。

    优先 XDG_CONFIG_HOME，否则按平台默认：
      - Linux/macOS: ~/.config/eval-anything/
      - Windows: %APPDATA%/eval-anything/
    """
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_NAME

    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME

    return Path.home() / ".config" / APP_NAME


def user_cache_dir() -> Path:
    """用户缓存目录（用于 session 历史、临时实验输出）。"""
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / APP_NAME

    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / APP_NAME / "Cache"

    return Path.home() / ".cache" / APP_NAME


def user_data_dir() -> Path:
    """用户数据目录（用于持久化输出、自定义数据集等）。"""
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_NAME

    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            return Path(local_appdata) / APP_NAME

    return Path.home() / ".local" / "share" / APP_NAME


def packaged_config_dir() -> Optional[Path]:
    """pip install 时通过 data-files 安装的默认 configs/ 目录。

    在 pyproject.toml 的 [tool.setuptools.data-files] 里指定。
    可能不存在（开发模式 pip install -e .）。
    """
    candidates = [
        Path(sysconfig.get_path("data")) / "eval-anything" / "configs",
        Path(sysconfig.get_path("data")) / APP_NAME / "configs",
    ]
    for c in candidates:
        if c.exists() and (c / "llm_profiles.yaml").exists():
            return c
    return None


def repo_config_dir() -> Optional[Path]:
    """开发模式下源码内的 configs/ 目录。"""
    here = Path(__file__).resolve()
    # src/config_paths.py → repo_root/configs
    candidate = here.parents[1] / "configs"
    if candidate.exists() and (candidate / "llm_profiles.yaml").exists():
        return candidate
    return None


def resolve_config_dir(explicit: Optional[str] = None) -> tuple[Path, str]:
    """统一入口：找配置目录。

    Args:
        explicit: CLI 上 --config-dir 显式传入的值

    Returns:
        (path, source) — source ∈ {"explicit", "env", "user", "cwd", "packaged", "repo"}
        path 一定 .exists()；如果哪个都没找到，回退到 user_config_dir() 且 source=="user"，
        调用方需要自己处理"目录不存在 → 跑向导"的逻辑。
    """
    if explicit:
        p = Path(explicit).expanduser().resolve()
        return p, "explicit"

    env = os.environ.get("EVAL_ANYTHING_CONFIG_DIR")
    if env:
        p = Path(env).expanduser().resolve()
        return p, "env"

    user = user_config_dir()
    if (user / "llm_profiles.yaml").exists():
        return user, "user"

    cwd = Path.cwd() / "configs"
    if (cwd / "llm_profiles.yaml").exists():
        return cwd.resolve(), "cwd"

    packaged = packaged_config_dir()
    if packaged is not None:
        return packaged.resolve(), "packaged"

    repo = repo_config_dir()
    if repo is not None:
        return repo.resolve(), "repo"

    # 都没找到：返回 user 路径让调用方知道"该跑向导往这写"
    return user, "user"


def has_user_config() -> bool:
    """用户配置是否已初始化（决定要不要跑向导）。"""
    return (user_config_dir() / "llm_profiles.yaml").exists() and (
        user_config_dir() / "config.yaml"
    ).exists()


def bootstrap_user_config(source_dir: Path) -> Path:
    """把 source_dir 下的默认 configs 复制到用户配置目录，作为初始化。

    通常在向导启动时调用，复制 packaged/repo configs 作为骨架，再让向导补 LLM profile。
    """
    target = user_config_dir()
    target.mkdir(parents=True, exist_ok=True)
    for item in source_dir.iterdir():
        dest = target / item.name
        if dest.exists():
            continue
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    return target
