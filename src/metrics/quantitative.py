"""
定量评测指标。

提供多种指标计算函数，输入为 Trajectory 列表，输出为汇总统计。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.trajectory import Trajectory


@dataclass
class MetricResult:
    """单个指标的统计结果。"""
    name: str
    value: float
    description: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class QuantitativeMetrics:
    """定量指标计算引擎。"""

    @staticmethod
    def task_completion_rate(trajectories: List[Trajectory]) -> MetricResult:
        """任务完全正确率（所有字段全部正确）。"""
        if not trajectories:
            return MetricResult("task_completion_rate", 0.0, "无轨迹数据")
        success = sum(1 for t in trajectories if t.status == "success")
        total = len(trajectories)
        rate = success / total
        return MetricResult(
            "task_completion_rate", rate,
            f"{success}/{total} 任务完全正确",
            {"success": success, "total": total},
        )

    @staticmethod
    def partial_completion_score(trajectories: List[Trajectory]) -> MetricResult:
        """字段级平均准确率。"""
        if not trajectories:
            return MetricResult("partial_completion_score", 0.0, "无轨迹数据")
        scores = [t.scores.get("partial_completion", 0.0) for t in trajectories]
        avg = sum(scores) / len(scores)
        return MetricResult(
            "partial_completion_score", avg,
            f"平均字段准确率 {avg:.1%}",
            {"scores": scores},
        )

    @staticmethod
    def format_compliance_rate(trajectories: List[Trajectory]) -> MetricResult:
        """JSON 格式合规率。"""
        if not trajectories:
            return MetricResult("format_compliance_rate", 0.0, "无轨迹数据")
        compliant = sum(1 for t in trajectories if t.scores.get("format_compliance", 0) > 0)
        total = len(trajectories)
        rate = compliant / total
        return MetricResult(
            "format_compliance_rate", rate,
            f"{compliant}/{total} 输出格式正确",
            {"compliant": compliant, "total": total},
        )

    @staticmethod
    def token_efficiency(trajectories: List[Trajectory]) -> MetricResult:
        """Token 使用效率：每成功任务的平均 token 消耗。"""
        success_trajs = [t for t in trajectories if t.status == "success"]
        if not success_trajs:
            return MetricResult("token_efficiency", float("inf"), "无成功任务")

        total_tokens = sum(t.total_input_tokens + t.total_output_tokens for t in success_trajs)
        avg = total_tokens / len(success_trajs)

        all_tokens = sum(t.total_input_tokens + t.total_output_tokens for t in trajectories)
        return MetricResult(
            "token_efficiency", avg,
            f"每成功任务平均消耗 {avg:.0f} tokens",
            {
                "avg_per_success": avg,
                "total_all": all_tokens,
                "success_count": len(success_trajs),
                "total_count": len(trajectories),
            },
        )

    @staticmethod
    def avg_steps_to_completion(trajectories: List[Trajectory]) -> MetricResult:
        """平均完成步数。"""
        success_trajs = [t for t in trajectories if t.status == "success"]
        if not success_trajs:
            return MetricResult("avg_steps_to_completion", 0.0, "无成功任务")

        steps = [len(t.steps) for t in success_trajs]
        avg = sum(steps) / len(steps)
        return MetricResult(
            "avg_steps_to_completion", avg,
            f"平均 {avg:.1f} 步完成",
            {"steps": steps},
        )

    @staticmethod
    def error_recovery_rate(trajectories: List[Trajectory]) -> MetricResult:
        """错误恢复率：有错误但最终成功的任务占比。"""
        trajs_with_errors = [t for t in trajectories if any(s.error for s in t.steps)]
        if not trajs_with_errors:
            return MetricResult("error_recovery_rate", 1.0, "无错误发生", {"total_with_errors": 0})

        recovered = sum(1 for t in trajs_with_errors if t.status == "success")
        rate = recovered / len(trajs_with_errors)
        return MetricResult(
            "error_recovery_rate", rate,
            f"{recovered}/{len(trajs_with_errors)} 从错误中恢复",
            {"recovered": recovered, "total_with_errors": len(trajs_with_errors)},
        )

    @staticmethod
    def avg_latency(trajectories: List[Trajectory]) -> MetricResult:
        """平均延迟（毫秒）。"""
        if not trajectories:
            return MetricResult("avg_latency", 0.0, "无轨迹数据")
        latencies = [t.total_latency_ms for t in trajectories]
        avg = sum(latencies) / len(latencies)
        return MetricResult(
            "avg_latency", avg,
            f"平均延迟 {avg:.0f}ms",
            {"latencies": latencies},
        )

    @staticmethod
    def status_distribution(trajectories: List[Trajectory]) -> MetricResult:
        """状态分布统计。"""
        counts: Dict[str, int] = {}
        for t in trajectories:
            counts[t.status] = counts.get(t.status, 0) + 1
        total = len(trajectories)
        rates = {k: v / total for k, v in counts.items()} if total else {}
        return MetricResult(
            "status_distribution", 0.0,
            f"状态分布: {counts}",
            {"counts": counts, "rates": rates},
        )

    def compute_all(self, trajectories: List[Trajectory]) -> Dict[str, MetricResult]:
        """计算所有指标。"""
        return {
            "task_completion_rate": self.task_completion_rate(trajectories),
            "partial_completion_score": self.partial_completion_score(trajectories),
            "format_compliance_rate": self.format_compliance_rate(trajectories),
            "token_efficiency": self.token_efficiency(trajectories),
            "avg_steps": self.avg_steps_to_completion(trajectories),
            "error_recovery_rate": self.error_recovery_rate(trajectories),
            "avg_latency": self.avg_latency(trajectories),
            "status_distribution": self.status_distribution(trajectories),
        }
