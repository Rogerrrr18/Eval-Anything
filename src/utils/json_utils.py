"""
工具函数 — JSON 解析、重试、日志。
"""
from __future__ import annotations

import json
import re
import logging
from typing import Any, Dict, Optional


def robust_json_parse(text: str) -> Optional[Dict[str, Any]]:
    """鲁棒的 JSON 解析，处理各种常见格式问题。

    尝试多种策略解析 JSON：
      1. 直接解析
      2. 提取 ```json ... ``` 代码块
      3. 提取第一个 { ... } 块
      4. 修复常见格式错误（尾部逗号、单引号等）
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # 策略 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 策略 2: 提取 ```json ... ``` 代码块
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 策略 3: 提取第一个 { ... } 块
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 策略 4: 修复常见格式错误
    fixed = text
    # 移除尾部逗号
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
    # 单引号 → 双引号
    fixed = fixed.replace("'", '"')
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    return None


def setup_logging(level: str = "INFO") -> logging.Logger:
    """配置日志。"""
    logger = logging.getLogger("agent-eval")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger
