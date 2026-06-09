"""
Eval-Anything CLI chat mode.

让用户用任意 LLM（从 llm_profiles.yaml 选）当"驾驶 LLM"在终端里
跟 Eval-Anything 对话，跑评测的整个流程。

skill markdown 同时为 Claude Code 和本模式服务，是同一份"领域知识"。

入口: src/__main__.py 在 --chat 模式下调 run_chat()。
"""
from __future__ import annotations

from .agent import run_chat

__all__ = ["run_chat"]
