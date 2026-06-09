"""
终端 UI 辅助 — stdlib 实现，不依赖 rich / prompt_toolkit。

提供：
  - print_banner: chat 启动横幅
  - print_assistant / print_user / print_system: 带前缀的颜色输出
  - ask_user_multichoice: 多选题渲染（闸门用）
  - show_yaml_diff: 简单 diff 渲染
  - prompt_input: 多行用户输入
"""
from __future__ import annotations

import sys
from typing import List, Optional


# ── ANSI 颜色（终端不支持时降级为空串） ──
def _supports_color() -> bool:
    return sys.stdout.isatty() and sys.platform != "win32"


if _supports_color():
    CYAN = "\033[36m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    GRAY = "\033[90m"
    BOLD = "\033[1m"
    RESET = "\033[0m"
else:
    CYAN = GREEN = YELLOW = RED = GRAY = BOLD = RESET = ""


def print_banner(driver_name: str, model_name: str) -> None:
    """启动横幅。"""
    bar = "═" * 60
    print(f"\n{CYAN}{bar}{RESET}")
    print(f"{CYAN}  Eval-Anything CLI Chat{RESET}")
    print(f"{GRAY}  driver: {driver_name} ({model_name}){RESET}")
    print(f"{GRAY}  输入 /exit 退出，/help 查看命令{RESET}")
    print(f"{CYAN}{bar}{RESET}\n")


def print_assistant(content: str) -> None:
    print(f"{GREEN}{BOLD}[Assistant]{RESET} {content}")


def print_tool_call(name: str, args: dict) -> None:
    print(f"{GRAY}  → {name}({_short_args(args)}){RESET}")


def print_tool_result(name: str, result: str, ok: bool = True) -> None:
    icon = "✓" if ok else "✗"
    color = GRAY if ok else RED
    truncated = result if len(result) < 500 else result[:500] + f" ...[{len(result)} chars total]"
    print(f"{color}  {icon} {name}: {truncated}{RESET}")


def print_system(msg: str) -> None:
    print(f"{YELLOW}[System] {msg}{RESET}")


def print_error(msg: str) -> None:
    print(f"{RED}[Error] {msg}{RESET}")


def prompt_input(prefix: str = "You") -> str:
    """读一行用户输入。支持空行结束的多行。"""
    print(f"{CYAN}{BOLD}[{prefix}]{RESET} ", end="", flush=True)
    try:
        return input()
    except (EOFError, KeyboardInterrupt):
        return "/exit"


def ask_user_multichoice(
    question: str,
    options: List[str],
    multi_select: bool = False,
) -> str:
    """渲染一道多选题，返回用户输入（编号或自定义文本）。

    skill 的"闸门"通过本函数实现。
    """
    print(f"\n{YELLOW}[Gate] {question}{RESET}")
    for i, opt in enumerate(options, 1):
        print(f"  {YELLOW}{i}.{RESET} {opt}")
    if multi_select:
        print(f"  {GRAY}(可多选，用逗号分隔编号；或输入自定义答案){RESET}")
    else:
        print(f"  {GRAY}(输入编号选项，或输入自定义答案){RESET}")
    print(f"{CYAN}{BOLD}[Choose]{RESET} ", end="", flush=True)
    try:
        ans = input().strip()
    except (EOFError, KeyboardInterrupt):
        return ""

    # 数字 → 转回选项文本
    if ans.isdigit():
        idx = int(ans) - 1
        if 0 <= idx < len(options):
            return options[idx]
    if multi_select and "," in ans:
        parts = []
        for p in ans.split(","):
            p = p.strip()
            if p.isdigit():
                idx = int(p) - 1
                if 0 <= idx < len(options):
                    parts.append(options[idx])
                    continue
            parts.append(p)
        return " | ".join(parts)
    return ans  # 自定义答案


def show_yaml_diff(path: str, new_content: str, old_content: Optional[str] = None) -> None:
    """展示 yaml 写入前的 diff。简化版：只 print 新内容。"""
    print(f"\n{YELLOW}--- 即将写入 {path} ---{RESET}")
    if old_content:
        print(f"{GRAY}(已存在内容长度: {len(old_content)} 字符){RESET}")
    for line in new_content.splitlines():
        print(f"  {GREEN}+ {line}{RESET}")
    print(f"{YELLOW}--- end of diff ---{RESET}\n")


def confirm(prompt: str = "继续？") -> bool:
    """简单 y/n 确认。"""
    print(f"{YELLOW}{prompt} [y/N]{RESET} ", end="", flush=True)
    try:
        ans = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("y", "yes")


def _short_args(args: dict) -> str:
    items = []
    for k, v in args.items():
        sv = str(v)
        if len(sv) > 40:
            sv = sv[:40] + "..."
        items.append(f"{k}={sv}")
    return ", ".join(items)
