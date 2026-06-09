"""
把 skills/eval-anything/ 下的 markdown 拼成驾驶 LLM 的 system prompt。

策略：
  - 启动时加载 SKILL.md 全文（必选）
  - 懒加载 references/* 和 workflows/*：驾驶 LLM 通过 read_file 工具按需读
  - 模板（templates/*）不入 system prompt，由驾驶 LLM 按需 read_file
"""
from __future__ import annotations

import sysconfig
from pathlib import Path
from typing import Optional


def _candidates() -> list[Path]:
    """返回 skill 目录的候选路径，按优先级。

    1. 用户配置目录下的 skills/eval-anything（少见，但允许用户覆盖）
    2. 项目源码内 skills/eval-anything/（开发模式 pip install -e .）
    3. 通过 pyproject data-files 安装的位置（pipx / pip install 后）
    4. site-packages 同级 share/eval-anything/skills/eval-anything（部分 sysconfig 布局）
    """
    cands: list[Path] = []

    # 1. 用户自定义覆盖
    try:
        from .. import config_paths
        user_skill = config_paths.user_config_dir().parent / "eval-anything" / "skills" / "eval-anything"
        cands.append(user_skill)
    except Exception:
        pass

    # 2. 源码同级（开发模式）
    cands.append(Path(__file__).resolve().parents[2] / "skills" / "eval-anything")

    # 3. data-files 安装位置
    cands.append(Path(sysconfig.get_path("data")) / "eval-anything" / "skills" / "eval-anything")

    # 4. 一些发行版会把 data-files 放到 share/ 下
    cands.append(Path(sysconfig.get_path("data")) / "share" / "eval-anything" / "skills" / "eval-anything")

    return cands


def find_skill_dir() -> Optional[Path]:
    """定位 skill 内容目录。按优先级返回第一个存在的。"""
    for cand in _candidates():
        if cand.exists() and (cand / "SKILL.md").exists():
            return cand
    return None


def load_system_prompt(skill_dir: Optional[Path] = None) -> str:
    """构造完整 system prompt。

    包含：
      1. 角色说明（驾驶 LLM 的身份与边界）
      2. SKILL.md 全文（领域决策树）
      3. 工具调用协议说明（function calling 优先，文本标记 fallback）
      4. 文件索引（提示驾驶 LLM 有哪些可懒加载的 references/workflows/templates）
    """
    skill_dir = skill_dir or find_skill_dir()
    if skill_dir is None:
        raise FileNotFoundError(
            "找不到 skills/eval-anything/ 目录。请确认在 Eval-Anything 项目根目录运行，"
            "或检查 skill 内容是否随包正确分发。"
        )

    skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")

    refs = sorted((skill_dir / "references").glob("*.md")) if (skill_dir / "references").exists() else []
    workflows = sorted((skill_dir / "workflows").glob("*.md")) if (skill_dir / "workflows").exists() else []
    templates = sorted((skill_dir / "templates").glob("*")) if (skill_dir / "templates").exists() else []

    file_index = []
    for f in refs:
        file_index.append(f"  references/{f.name}")
    for f in workflows:
        file_index.append(f"  workflows/{f.name}")
    for f in templates:
        file_index.append(f"  templates/{f.name}")
    file_index_str = "\n".join(file_index) if file_index else "  (无)"

    return _SYSTEM_PROMPT_TEMPLATE.format(
        skill_md=skill_md,
        skill_dir=skill_dir,
        file_index=file_index_str,
    )


_SYSTEM_PROMPT_TEMPLATE = """\
你是 Eval-Anything 评测管线的**驾驶 LLM**。你的任务是按下面的 skill 内容
帮用户设计 / 运行 / 解读 LLM × Harness × Environment 评测，并通过工具调用与
用户/系统交互。

## 你的边界
- 你**不是** Claude，也不是 GPT、Gemini 等特定品牌——你是被用户挑选出来驾驶
  本管线的那个 LLM，名字以系统配置为准
- 你**不能**直接读写文件、跑命令——必须通过下方的工具调用
- 你**必须**严格遵守 skill 里规定的 4 道人工闸门（任务类型 / 数据集来源 /
  配置 diff / dry-run），任何闸门通过前不得擅自写盘或起任务

## Skill 内容（领域决策树，遵循它做决策）

{skill_md}

## 可懒加载的 skill 文件

skill 内容根目录: {skill_dir}

下面的文件你可以通过 read_file 工具按需读取，**不要凭印象回答里面的内容**：

{file_index}

## 工具调用协议

如果你的 LLM 后端支持原生 function calling（OpenAI tool_calls 协议），优先使用。

如果不支持，输出文本形式的 tool call：

  <TOOL>tool_name(arg1=value1, arg2=value2)</TOOL>

每次输出最多调用 1 个工具。等待用户/系统返回 <TOOL_RESULT>...</TOOL_RESULT>
后再继续。如果你想直接回复用户而不调工具，正常输出文本即可。

完成任务后调 show_summary 给用户总结收尾。
"""
