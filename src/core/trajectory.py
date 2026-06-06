"""
轨迹数据模型 — 完整记录一个任务的执行过程。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..harness.base import StepRecord


@dataclass
class Trajectory:
    """一个任务的完整执行轨迹。"""
    experiment_name: str
    task_id: str
    llm_name: str
    harness_name: str
    env_name: str
    steps: List[StepRecord]
    final_answer: str
    ground_truth: Any
    scores: Dict[str, float]
    total_input_tokens: int
    total_output_tokens: int
    total_latency_ms: float
    status: str               # "success" | "partial" | "failure" | "timeout" | "error"
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转为可序列化的字典。"""
        return asdict(self)

    def to_jsonl(self) -> str:
        """序列化为单行 JSON，用于 JSONL 日志。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


@dataclass
class ComboResult:
    """一个 (LLM × Harness × Environment) 组合的汇总结果。"""
    llm_name: str
    harness_name: str
    env_name: str
    task_results: List[Trajectory]
    summary: Dict[str, Any] = field(default_factory=dict)

    def compute_summary(self) -> Dict[str, Any]:
        """计算该组合的汇总统计。"""
        if not self.task_results:
            self.summary = {}
            return self.summary

        total = len(self.task_results)
        success = sum(1 for t in self.task_results if t.status == "success")
        partial = sum(1 for t in self.task_results if t.status == "partial")
        failure = sum(1 for t in self.task_results if t.status == "failure")
        timeout = sum(1 for t in self.task_results if t.status == "timeout")
        error = sum(1 for t in self.task_results if t.status == "error")

        avg_latency = sum(t.total_latency_ms for t in self.task_results) / total if total else 0
        avg_tokens = sum(t.total_input_tokens + t.total_output_tokens for t in self.task_results) / total if total else 0
        avg_score = sum(t.scores.get("partial_completion", 0.0) for t in self.task_results) / total if total else 0
        format_ok = sum(1 for t in self.task_results if t.scores.get("format_compliance", 0.0) > 0.0)

        self.summary = {
            "total_tasks": total,
            "success_count": success,
            "partial_count": partial,
            "failure_count": failure,
            "timeout_count": timeout,
            "error_count": error,
            "success_rate": success / total if total else 0,
            "partial_rate": partial / total if total else 0,
            "failure_rate": failure / total if total else 0,
            "avg_latency_ms": avg_latency,
            "avg_tokens": avg_tokens,
            "avg_score": avg_score,
            "format_compliance_rate": format_ok / total if total else 0,
            "all_correct_rate": success / total if total else 0,
        }
        return self.summary


@dataclass
class ExperimentResult:
    """整个实验的汇总结果。"""
    experiment_name: str
    combo_results: List[ComboResult]
    config_snapshot: Dict[str, Any] = field(default_factory=dict)

    def get_all_trajectories(self) -> List[Trajectory]:
        """获取所有轨迹。"""
        return [t for cr in self.combo_results for t in cr.task_results]

    def get_comparison_matrix(self) -> Dict[str, Dict[str, Dict[str, float]]]:
        """生成 LLM × Harness → metrics 的对比矩阵。

        Returns:
            {llm_name: {harness_name: {metric: value}}}
        """
        matrix: Dict[str, Dict[str, Dict[str, float]]] = {}
        for cr in self.combo_results:
            if cr.llm_name not in matrix:
                matrix[cr.llm_name] = {}
            matrix[cr.llm_name][cr.harness_name] = {
                "success_rate": cr.summary.get("success_rate", 0),
                "avg_score": cr.summary.get("avg_score", 0),
                "avg_latency_ms": cr.summary.get("avg_latency_ms", 0),
                "avg_tokens": cr.summary.get("avg_tokens", 0),
                "all_correct_rate": cr.summary.get("all_correct_rate", 0),
            }
        return matrix
