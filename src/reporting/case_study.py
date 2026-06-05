"""
案例研究报告 — Markdown 格式的定性分析报告。

包含：
  - 失败案例分类统计
  - 代表性失败/成功案例
  - 分析洞察
"""
from __future__ import annotations

import html as html_mod
import json
from pathlib import Path
from typing import Any, Dict, List

from ..core.trajectory import Trajectory
from ..metrics.qualitative import QualitativeAnalyzer, QualitativeReport


class CaseStudyWriter:
    """Markdown 案例研究报告生成器。"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        trajectories: List[Trajectory],
        experiment_name: str,
        case_count: int = 10,
    ) -> str:
        """生成案例研究 Markdown 报告。"""
        analyzer = QualitativeAnalyzer()
        report = analyzer.analyze(trajectories)
        cases = analyzer.select_case_studies(trajectories, count=case_count)

        content = self._generate_markdown(report, cases, experiment_name)

        filename = f"{experiment_name}_case_study.md"
        filepath = self.output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"  案例研究报告已保存: {filepath}")
        return str(filepath)

    def _generate_markdown(
        self,
        report: QualitativeReport,
        cases: Dict[str, List[Trajectory]],
        experiment_name: str,
    ) -> str:
        """生成 Markdown 内容。"""
        lines: List[str] = []

        lines.append(f"# Agent 评测案例研究报告: {experiment_name}\n")
        lines.append(f"共分析 {report.total_analyzed} 条评测记录。\n")

        # ── 1. 失败分类 ──
        lines.append("## 1. 失败模式分类\n")
        if report.failure_categories:
            lines.append("| 失败类型 | 数量 | 占比 |")
            lines.append("|----------|------|------|")
            total_failures = sum(report.failure_categories.values())
            for ftype, count in sorted(report.failure_categories.items(), key=lambda x: -x[1]):
                rate = count / total_failures if total_failures else 0
                lines.append(f"| {ftype} | {count} | {rate:.1%} |")
            lines.append("")
        else:
            lines.append("无失败案例。\n")

        # ── 2. 成功模式 ──
        lines.append("## 2. 成功模式分析\n")
        if report.success_patterns:
            lines.append("| 策略 | 次数 |")
            lines.append("|------|------|")
            for pattern, count in sorted(report.success_patterns.items(), key=lambda x: -x[1]):
                lines.append(f"| {pattern} | {count} |")
            lines.append("")
        else:
            lines.append("无成功案例。\n")

        # ── 3. 代表性失败案例 ──
        lines.append("## 3. 代表性失败案例\n")
        for fc in report.failure_cases[:5]:
            lines.append(f"### 案例: {fc.task_id} ({fc.failure_type})\n")
            lines.append(f"- **LLM**: {fc.llm_name}")
            lines.append(f"- **Harness**: {fc.harness_name}")
            lines.append(f"- **失败类型**: {fc.failure_type}")
            lines.append(f"- **描述**: {fc.description}")
            if fc.diff_fields:
                lines.append(f"- **错误字段**: {', '.join(fc.diff_fields)}")
            lines.append(f"- **期望输出**: `{json.dumps(fc.expected, ensure_ascii=False)[:300]}`")
            lines.append(f"- **实际输出**: `{str(fc.actual)[:300]}`")
            lines.append("")

        # ── 4. 接近成功的案例 ──
        near_misses = cases.get("near_misses", [])
        if near_misses:
            lines.append("## 4. 接近成功的案例（Near Misses）\n")
            lines.append("以下案例接近成功，仅差少量字段。修复这些问题可显著提升整体表现。\n")
            for t in near_misses[:5]:
                field_results = t.metadata.get("field_results", {})
                wrong = [k for k, v in field_results.items() if not v]
                score = t.scores.get("partial_completion", 0)
                lines.append(f"### {t.task_id} (得分: {score:.1%})\n")
                lines.append(f"- **组合**: {t.llm_name} + {t.harness_name}")
                lines.append(f"- **差字段**: {', '.join(wrong)}")
                lines.append(f"- **期望**: `{json.dumps(t.ground_truth, ensure_ascii=False)[:200]}`")
                lines.append(f"- **实际**: `{t.final_answer[:200]}`")
                lines.append("")

        # ── 5. 最佳表现 ──
        best = cases.get("best_performers", [])
        if best:
            lines.append("## 5. 最佳表现案例\n")
            for t in best[:3]:
                tokens = t.total_input_tokens + t.total_output_tokens
                lines.append(f"### {t.task_id}\n")
                lines.append(f"- **组合**: {t.llm_name} + {t.harness_name}")
                lines.append(f"- **Token消耗**: {tokens}")
                lines.append(f"- **延迟**: {t.total_latency_ms:.0f}ms")
                lines.append(f"- **步数**: {len(t.steps)}")
                lines.append("")

        # ── 6. 分析洞察 ──
        lines.append("## 6. 分析洞察\n")
        for i, insight in enumerate(report.insights, 1):
            lines.append(f"{i}. {insight}")
        lines.append("")

        return "\n".join(lines)
