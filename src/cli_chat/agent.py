"""
CLI chat 主对话循环。

流程:
  1. 加载驾驶 LLM（从 llm_profiles 选 / 命令行指定）
  2. 加载 skill markdown 当 system prompt
  3. 进入 REPL: user input → llm.chat_with_tools → 解析 tool calls →
     dispatch → 把结果灌回 messages → 循环
  4. 用户输入 /exit 退出，/help 帮助

工具调用协议:
  - 优先用 LLM 原生 function calling（chat_with_tools）
  - LLM 不返回 tool_calls 但文本含 <TOOL>...</TOOL> 标记时 fallback 解析
  - 都没有时把整段当 assistant message 输出给用户
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import ConfigLoader
from ..llm.base import BaseLLM, LLMResponse
from .driver import load_driver
from .prompt_loader import load_system_prompt, find_skill_dir
from .terminal_ui import (
    print_banner, print_assistant, print_system, print_error, prompt_input,
)
from .tools import TOOL_SCHEMAS, dispatch


# 文本 fallback 解析 <TOOL>name(args)</TOOL>
_TOOL_TEXT_RE = re.compile(r"<TOOL>\s*(\w+)\s*\((.*?)\)\s*</TOOL>", re.DOTALL)

# 一轮对话内允许的最大工具调用次数（防失控）
_MAX_TOOL_TURNS_PER_USER_MESSAGE = 20


async def run_chat(
    config_dir: str = "configs",
    driver_name: Optional[str] = None,
) -> None:
    """启动 chat 模式主循环。"""
    config_loader = ConfigLoader(config_dir=config_dir)

    skill_dir = find_skill_dir()
    if skill_dir is None:
        print_error(
            "找不到 skills/eval-anything/ 目录。请在 Eval-Anything 项目根目录运行。"
        )
        return

    try:
        llm, profile = load_driver(config_loader, driver_name=driver_name)
    except Exception as e:
        print_error(f"加载驾驶 LLM 失败: {e}")
        return

    print_banner(profile.name, profile.model_name)

    system_prompt = load_system_prompt(skill_dir)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    while True:
        user_input = prompt_input("You")
        if not user_input.strip():
            continue
        if user_input.strip() in ("/exit", "/quit", "/q"):
            print_system("退出。")
            break
        if user_input.strip() == "/help":
            _print_help()
            continue
        if user_input.strip().startswith("/reload"):
            system_prompt = load_system_prompt(skill_dir)
            messages[0] = {"role": "system", "content": system_prompt}
            print_system("已重载 skill 内容。")
            continue

        messages.append({"role": "user", "content": user_input})

        # 一轮 user message 可能触发多个工具循环
        try:
            await _drive_one_turn(llm, messages)
        except KeyboardInterrupt:
            print_system("中断当前轮，输入 /exit 退出。")
            continue
        except Exception as e:
            print_error(f"驾驶 LLM 调用失败: {e}")
            # 把错误也喂回去，让 LLM 能感知到（可选）
            messages.append({
                "role": "user",
                "content": f"[系统消息] 上一轮发生错误: {e}",
            })

    await llm.close()


async def _drive_one_turn(llm: BaseLLM, messages: List[Dict[str, Any]]) -> None:
    """处理一次 user message 触发的全部 tool-call 循环，直到 LLM 输出非 tool 文本。"""
    for turn in range(_MAX_TOOL_TURNS_PER_USER_MESSAGE):
        try:
            response: LLMResponse = await llm.chat_with_tools(
                messages=messages,
                tools=TOOL_SCHEMAS,
                tool_choice="auto",
            )
        except Exception as e:
            # 退化：尝试 chat() 不带 tools（部分 LLM 不支持 chat_with_tools 时）
            print_system(f"chat_with_tools 失败 ({e})，退化为 chat() 文本模式")
            response = await llm.chat(messages=messages)

        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": response.content or "",
        }
        if response.tool_calls:
            assistant_msg["tool_calls"] = response.tool_calls
        messages.append(assistant_msg)

        # 1) 优先处理 native tool_calls
        tool_calls = response.tool_calls or []

        # 2) Fallback: 文本里含 <TOOL>...</TOOL>
        if not tool_calls and response.content:
            text_calls = _parse_text_tool_calls(response.content)
            for i, (name, args) in enumerate(text_calls):
                tool_calls.append({
                    "id": f"text_call_{i}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                })

        if not tool_calls:
            # 纯文本回复 → 输出给用户，结束本轮
            if response.content:
                print_assistant(response.content)
            return

        # 执行所有 tool calls
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {"raw": raw_args}

            result = dispatch(name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "name": name,
                "content": json.dumps(result, ensure_ascii=False),
            })

        # 继续下一轮（LLM 拿到 tool result 后可能要么继续调工具、要么给最终回复）
        continue

    print_system(f"工具调用次数超过 {_MAX_TOOL_TURNS_PER_USER_MESSAGE}，强制结束本轮。")


def _parse_text_tool_calls(text: str) -> List[tuple[str, Dict[str, Any]]]:
    """从 LLM 文本输出中解析 <TOOL>name(arg=val, ...)</TOOL>。

    简化解析：args 用 `k=v` 形式，逗号分隔；val 可加引号。
    """
    results: List[tuple[str, Dict[str, Any]]] = []
    for m in _TOOL_TEXT_RE.finditer(text):
        name = m.group(1).strip()
        arg_str = m.group(2).strip()
        args: Dict[str, Any] = {}
        if arg_str:
            # 朴素解析：split by `, ` 然后 `=`
            # 真实场景建议用 ast.literal_eval 或更严格的 parser，这里 MVP 够用
            for part in _split_args(arg_str):
                if "=" not in part:
                    continue
                k, v = part.split("=", 1)
                k = k.strip()
                v = v.strip()
                # 去引号
                if (v.startswith("\"") and v.endswith("\"")) or (
                    v.startswith("'") and v.endswith("'")
                ):
                    v = v[1:-1]
                # 简单 JSON 数组识别
                if v.startswith("[") and v.endswith("]"):
                    try:
                        v = json.loads(v)
                    except json.JSONDecodeError:
                        pass
                args[k] = v
        results.append((name, args))
    return results


def _split_args(arg_str: str) -> List[str]:
    """逗号分隔但跳过引号 / 方括号内部。"""
    parts: List[str] = []
    buf = ""
    depth = 0
    quote: Optional[str] = None
    for ch in arg_str:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf += ch
        elif ch in "[(":
            depth += 1
            buf += ch
        elif ch in "])":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return parts


def _print_help() -> None:
    print_system(
        "命令:\n"
        "  /exit /quit /q  退出\n"
        "  /reload         重载 skill 内容\n"
        "  /help           本帮助\n"
        "\n"
        "正常对话直接输入你的需求，如:\n"
        "  我想评测 GPT-4 和 DeepSeek 在槽位填充上的表现\n"
        "  帮我加一个 GPT-4 的 LLM profile\n"
        "  解读一下 outputs/slot_filling_eval 的报告\n"
    )
