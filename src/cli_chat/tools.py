"""
驾驶 LLM 能调的工具集。

MVP 状态:
  - ✅ run_cli: 跑 eval-agent / list_profiles / dry_run 等子命令
  - ✅ read_file: 读 configs / datasets / reports / skill 文档
  - ✅ ask_user: 终端多选题（替代 Claude Code 的 AskUserQuestion）
  - 🚧 write_file: 写 yaml；含 diff 预览 + 强制 confirm（MVP 已具备）
  - 🚧 list_dir: 列目录（基础已有）
  - 🚧 show_summary: 总结性输出（直接 print）

每个工具返回 dict {"ok": bool, "result": str, "error": str?}。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List

from . import terminal_ui as ui


# ── 工具实现 ──

def tool_run_cli(args: List[str], cwd: str = ".") -> Dict[str, Any]:
    """运行 eval-anything CLI 子命令。

    Args:
        args: 完整参数列表，如 ["--list-profiles", "--config-dir", "configs"]
        cwd: 工作目录
    """
    # 安全护栏：必须以本项目的 CLI 入口起头
    cmd = ["python", "-m", "src"] + args
    ui.print_tool_call("run_cli", {"cmd": " ".join(cmd)})
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        result = (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()
        ok = proc.returncode == 0
        ui.print_tool_result("run_cli", result, ok=ok)
        return {"ok": ok, "result": result, "returncode": proc.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": "", "error": "命令执行超时（300s）"}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)}


def tool_read_file(path: str) -> Dict[str, Any]:
    """读文件全文。"""
    ui.print_tool_call("read_file", {"path": path})
    try:
        content = Path(path).read_text(encoding="utf-8")
        # 防止 token 爆炸：超过 50KB 截断
        truncated = False
        if len(content) > 50_000:
            content = content[:50_000]
            truncated = True
        ui.print_tool_result("read_file", f"{len(content)} chars{' (truncated)' if truncated else ''}")
        return {"ok": True, "result": content, "truncated": truncated}
    except FileNotFoundError:
        return {"ok": False, "result": "", "error": f"文件不存在: {path}"}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)}


def tool_ask_user(question: str, options: List[str], multi_select: bool = False) -> Dict[str, Any]:
    """向用户提多选题（闸门）。

    驾驶 LLM 调它来实现 skill 里的 4 道闸门。
    """
    ui.print_tool_call("ask_user", {"question": question[:40], "n_options": len(options)})
    answer = ui.ask_user_multichoice(question, options, multi_select=multi_select)
    return {"ok": True, "result": answer}


def tool_write_file(path: str, content: str) -> Dict[str, Any]:
    """写文件 — 强制先展示 diff，让用户终端确认。

    驾驶 LLM 调它来写 configs / datasets。
    """
    ui.print_tool_call("write_file", {"path": path, "size": len(content)})
    p = Path(path)
    old = None
    if p.exists():
        try:
            old = p.read_text(encoding="utf-8")
        except Exception:
            old = None

    ui.show_yaml_diff(path, content, old_content=old)
    if not ui.confirm(f"写入 {path}？"):
        return {"ok": False, "result": "", "error": "用户取消写盘"}

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        ui.print_tool_result("write_file", f"已写入 {path}")
        return {"ok": True, "result": f"已写入 {path}"}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)}


def tool_list_dir(path: str) -> Dict[str, Any]:
    """列目录。"""
    ui.print_tool_call("list_dir", {"path": path})
    try:
        p = Path(path)
        if not p.exists():
            return {"ok": False, "result": "", "error": f"路径不存在: {path}"}
        items = []
        for child in sorted(p.iterdir()):
            kind = "d" if child.is_dir() else "f"
            size = child.stat().st_size if child.is_file() else "-"
            items.append(f"{kind} {child.name} ({size})")
        result = "\n".join(items)
        ui.print_tool_result("list_dir", f"{len(items)} items")
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)}


def tool_show_summary(text: str) -> Dict[str, Any]:
    """渲染总结性输出，用于评测跑完后给用户的洞察。"""
    ui.print_tool_call("show_summary", {"len": len(text)})
    print(f"\n{ui.GREEN}{ui.BOLD}═══ Summary ═══{ui.RESET}\n")
    print(text)
    print(f"\n{ui.GREEN}{ui.BOLD}═══════════════{ui.RESET}\n")
    return {"ok": True, "result": "shown"}


# ── 工具 schema（OpenAI tool_calls 协议格式） ──

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "run_cli",
            "description": "运行 eval-anything CLI 子命令（如 --list-profiles、--experiment、--dry-run）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "完整 CLI 参数数组，如 ['--list-profiles', '--config-dir', 'configs']",
                    },
                    "cwd": {"type": "string", "description": "工作目录，默认 '.'"},
                },
                "required": ["args"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读文件全文（用于读 skill references / configs / datasets / reports）。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "向用户提多选题。4 道闸门必须用本工具，不要在文本里假装问。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "multi_select": {"type": "boolean", "default": False},
                },
                "required": ["question", "options"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写文件（YAML 配置 / dataset JSONL）。会先展示 diff 让用户在终端确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列目录内容。",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_summary",
            "description": "向用户输出最终总结（评测跑完后的洞察小结）。",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
]


# ── 工具分发表 ──

TOOL_DISPATCH: Dict[str, Callable[..., Dict[str, Any]]] = {
    "run_cli": tool_run_cli,
    "read_file": tool_read_file,
    "ask_user": tool_ask_user,
    "write_file": tool_write_file,
    "list_dir": tool_list_dir,
    "show_summary": tool_show_summary,
}


def dispatch(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """根据工具名分发调用。"""
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return {"ok": False, "result": "", "error": f"未知工具: {name}"}
    try:
        return fn(**args)
    except TypeError as e:
        return {"ok": False, "result": "", "error": f"参数错误: {e}"}
    except Exception as e:
        return {"ok": False, "result": "", "error": str(e)}
