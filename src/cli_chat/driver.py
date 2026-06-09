"""
驾驶 LLM 包装层。

从 llm_profiles.yaml 取一个 profile，构造 BaseLLM 实例当 chat 模式的驾驶端。
跟"被评测 LLM"用同一份 profile 配置，差别只是这个实例的用途是跟用户对话
而不是跑评测。
"""
from __future__ import annotations

from typing import Optional

from ..core.config import ConfigLoader, LLMProfile
from ..llm import create_llm
from ..llm.base import BaseLLM, LLMConfig


def load_driver(
    config_loader: ConfigLoader,
    driver_name: Optional[str] = None,
) -> tuple[BaseLLM, LLMProfile]:
    """从 llm_profiles 加载驾驶 LLM。

    Args:
        config_loader: 已构造好的 ConfigLoader
        driver_name: 用户指定的 profile name。None 时交互式让用户选。

    Returns:
        (llm 实例, 对应 profile)
    """
    profiles = config_loader.load_llm_profiles()
    if not profiles:
        raise RuntimeError(
            "llm_profiles.yaml 中没有任何 profile。请先添加一个驾驶 LLM 配置。"
        )

    if driver_name is None:
        driver_name = _interactive_pick(profiles)
    if driver_name not in profiles:
        raise KeyError(
            f"未找到 LLM profile: {driver_name!r}。可用: {list(profiles.keys())}"
        )

    profile = profiles[driver_name]
    config = LLMConfig(
        model_name=profile.model_name,
        endpoint_url=profile.endpoint_url,
        api_key=profile.api_key,
        temperature=profile.temperature,
        max_tokens=max(profile.max_tokens, 2000),  # 驾驶要更多 token 输出 tool calls
        top_p=profile.top_p,
        timeout_seconds=max(profile.timeout_seconds, 60),
        enable_thinking=profile.enable_thinking,
        extra_params=profile.extra_params,
    )
    llm = create_llm(config, class_name=profile.class_name)
    return llm, profile


def _interactive_pick(profiles: dict) -> str:
    """交互式让用户选驾驶 LLM。"""
    print("\n请选驾驶 LLM:")
    names = list(profiles.keys())
    for i, name in enumerate(names, 1):
        p = profiles[name]
        print(f"  {i}. {name}  ({p.model_name} @ {p.endpoint_url})")
    print("输入编号或 profile 名: ", end="", flush=True)
    ans = input().strip()
    if ans.isdigit():
        idx = int(ans) - 1
        if 0 <= idx < len(names):
            return names[idx]
    return ans
