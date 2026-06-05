"""
定性分析 — 失败分类、模式识别、案例选择。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.trajectory import Trajectory


@dataclass
class FailureCase:
    """一个失败案例的分析。"""
    task_id: str
    llm_name: str
    harness_name: str
    env_name: str
    failure_type: str         # "format_error" | "reasoning_error" | "partial_completion" | "timeout" | "error"
    description: str
    expected: Any
    actual: Any
    diff_fields: List[str]    # 哪些字段错了
    trajectory_summary: str   # 轨迹摘要
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SuccessCase:
    """一个成功案例的分析。"""
    task_id: str
    llm_name: str
    harness_name: str
    env_name: str
    strategy: str             # 成功使用的策略
    steps: int
    tokens: int
    latency_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QualitativeReport:
    """定性分析报告。"""
    total_analyzed: int
    failure_categories: Dict[str, int]       # 失败类型 → 数量
    failure_cases: List[FailureCase]         # 代表性失败案例
    success_patterns: Dict[str, int]         # 成功模式 → 数量
    success_cases: List[SuccessCase]         # 代表性成功案例
    insights: List[str]                      # 分析洞察


class QualitativeAnalyzer:
    """定性分析器。"""

    FAILURE_TYPES = [
        "format_error",         # 输出不是合法 JSON
        "partial_completion",   # 部分字段正确，部分错误
        "reasoning_error",      # 推理过程错误
        "tool_misuse",          # 工具使用错误
        "timeout",              # 超时
        "error",                # 系统错误
    ]

    def analyze(self, trajectories: List[Trajectory]) -> QualitativeReport:
        """对一批轨迹进行定性分析。"""
        failures: List[FailureCase] = []
        successes: List[SuccessCase] = []
        failure_categories: Dict[str, int] = {}
        success_patterns: Dict[str, int] = {}

        for traj in trajectories:
            if traj.status == "success":
                sc = self._analyze_success(traj)
                successes.append(sc)
                pattern = sc.strategy
                success_patterns[pattern] = success_patterns.get(pattern, 0) + 1
            elif traj.status in ("partial", "failure", "timeout", "error"):
                fc = self._analyze_failure(traj)
                failures.append(fc)
                failure_categories[fc.failure_type] = failure_categories.get(fc.failure_type, 0) + 1

        # 生成洞察
        insights = self._generate_insights(trajectories, failure_categories, success_patterns)

        return QualitativeReport(
            total_analyzed=len(trajectories),
            failure_categories=failure_categories,
            failure_cases=failures,
            success_patterns=success_patterns,
            success_cases=successes,
            insights=insights,
        )

    def _analyze_failure(self, traj: Trajectory) -> FailureCase:
        """分析单个失败案例。"""
        # 确定失败类型
        if traj.status == "timeout":
            failure_type = "timeout"
            description = "任务执行超时"
        elif traj.status == "error":
            failure_type = "error"
            description = traj.error_message or "系统错误"
        elif traj.scores.get("format_compliance", 1.0) == 0.0:
            failure_type = "format_error"
            description = "输出不是合法 JSON 格式"
        elif traj.status == "partial":
            failure_type = "partial_completion"
            description = "部分字段正确，部分字段错误"
        else:
            failure_type = "reasoning_error"
            description = "推理过程导致错误输出"

        # 找出哪些字段错了
        diff_fields = []
        field_results = traj.metadata.get("field_results", {})
        for k, v in field_results.items():
            if not v:
                diff_fields.append(k)

        # 轨迹摘要
        steps_summary = f"共 {len(traj.steps)} 步"
        if traj.steps:
            last_step = traj.steps[-1]
            steps_summary += f"，最后输出: {traj.final_answer[:200]}"

        return FailureCase(
            task_id=traj.task_id,
            llm_name=traj.llm_name,
            harness_name=traj.harness_name,
            env_name=traj.env_name,
            failure_type=failure_type,
            description=description,
            expected=traj.ground_truth,
            actual=traj.final_answer,
            diff_fields=diff_fields,
            trajectory_summary=steps_summary,
        )

    def _analyze_success(self, traj: Trajectory) -> SuccessCase:
        """分析单个成功案例。"""
        # 推断成功策略
        if traj.harness_name == "raw":
            strategy = "直接回答"
        elif traj.harness_name == "react":
            strategy = f"ReAct ({len(traj.steps)}步推理)"
        elif traj.harness_name == "function_call":
            strategy = f"工具调用 ({len(traj.steps)}步)"
        else:
            strategy = f"{traj.harness_name} ({len(traj.steps)}步)"

        return SuccessCase(
            task_id=traj.task_id,
            llm_name=traj.llm_name,
            harness_name=traj.harness_name,
            env_name=traj.env_name,
            strategy=strategy,
            steps=len(traj.steps),
            tokens=traj.total_input_tokens + traj.total_output_tokens,
            latency_ms=traj.total_latency_ms,
        )

    def _generate_insights(
        self,
        trajectories: List[Trajectory],
        failure_categories: Dict[str, int],
        success_patterns: Dict[str, int],
    ) -> List[str]:
        """生成分析洞察。"""
        insights: List[str] = []

        # 1. 最常见失败类型
        if failure_categories:
            top_failure = max(failure_categories, key=failure_categories.get)
            insights.append(
                f"最常见的失败类型是「{top_failure}」({failure_categories[top_failure]}次)，"
                f"建议优先优化该方面。"
            )

        # 2. 格式错误占比
        total = len(trajectories)
        format_errors = failure_categories.get("format_error", 0)
        if format_errors > 0:
            insights.append(
                f"JSON 格式错误共 {format_errors} 次 ({format_errors/total*100:.1f}%)，"
                f"可通过 few-shot 示例或更强的格式约束来改善。"
            )

        # 3. 成功率最高的策略
        if success_patterns:
            best_strategy = max(success_patterns, key=success_patterns.get)
            insights.append(
                f"成功率最高的策略是「{best_strategy}」({success_patterns[best_strategy]}次成功)。"
            )

        # 4. 不同 Harness 的效率对比
        harness_results: Dict[str, List[Trajectory]] = {}
        for t in trajectories:
            harness_results.setdefault(t.harness_name, []).append(t)

        if len(harness_results) > 1:
            eff = {}
            for h, trajs in harness_results.items():
                success = [t for t in trajs if t.status == "success"]
                if success:
                    avg_tokens = sum(t.total_input_tokens + t.total_output_tokens for t in success) / len(success)
                    eff[h] = avg_tokens
            if eff:
                best = min(eff, key=eff.get)
                worst = max(eff, key=eff.get)
                insights.append(
                    f"Token 效率最高: {best} (平均 {eff[best]:.0f} tokens/任务)，"
                    f"最低: {worst} (平均 {eff[worst]:.0f} tokens/任务)。"
                )

        if not insights:
            insights.append("样本量不足，无法生成有意义的洞察。")

        return insights

    def select_case_studies(
        self, trajectories: List[Trajectory], count: int = 10
    ) -> Dict[str, List[Trajectory]]:
        """选择代表性案例用于深入研究。

        选择标准:
          1. 最大改进案例（同一任务，不同组合间差异最大）
          2. 典型失败案例（每种失败类型选一个）
          3. 边界案例（接近成功但差一个字段）
        """
        cases: Dict[str, List[Trajectory]] = {
            "typical_failures": [],
            "near_misses": [],
            "best_performers": [],
            "biggest_improvements": [],
        }

        # 典型失败
        failures = [t for t in trajectories if t.status in ("failure", "partial")]
        cases["typical_failures"] = failures[:count]

        # 接近成功（只差一个字段）
        near_misses = [
            t for t in trajectories
            if t.status == "partial"
            and t.scores.get("partial_completion", 0) >= 0.8
        ]
        cases["near_misses"] = near_misses[:count]

        # 最佳表现
        successes = [t for t in trajectories if t.status == "success"]
        # 按 token 效率排序
        successes.sort(key=lambda t: t.total_input_tokens + t.total_output_tokens)
        cases["best_performers"] = successes[:count]

        # 同任务不同组合的差异
        by_task: Dict[str, List[Trajectory]] = {}
        for t in trajectories:
            by_task.setdefault(t.task_id, []).append(t)

        improvements = []
        for task_id, task_trajs in by_task.items():
            if len(task_trajs) < 2:
                continue
            scores = {tr.scores.get("partial_completion", 0) for tr in task_trajs}
            if max(scores) > min(scores):
                improvements.extend(task_trajs)
        cases["biggest_improvements"] = improvements[:count * 2]

        return cases
