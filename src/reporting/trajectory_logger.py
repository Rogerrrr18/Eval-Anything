"""
JSONL 轨迹日志 — 将所有轨迹写入 JSONL 文件用于后续分析。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from ..core.trajectory import Trajectory


class TrajectoryLogger:
    """轨迹 JSONL 日志写入器。"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_combo(
        self,
        llm_name: str,
        harness_name: str,
        env_name: str,
        trajectories: List[Trajectory],
    ) -> str:
        """将一个组合的所有轨迹写入一个 JSONL 文件。"""
        filename = f"{llm_name}_{harness_name}_{env_name}_trajectories.jsonl"
        # 清理文件名中的特殊字符
        filename = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
        filepath = self.output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            for traj in trajectories:
                f.write(traj.to_jsonl() + "\n")

        print(f"  轨迹日志已保存: {filepath} ({len(trajectories)} 条)")
        return str(filepath)

    def write_all(self, trajectories: List[Trajectory], experiment_name: str) -> str:
        """将所有轨迹写入一个统一的 JSONL 文件。"""
        filename = f"{experiment_name}_all_trajectories.jsonl"
        filepath = self.output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            for traj in trajectories:
                f.write(traj.to_jsonl() + "\n")

        print(f"  全量轨迹已保存: {filepath} ({len(trajectories)} 条)")
        return str(filepath)
