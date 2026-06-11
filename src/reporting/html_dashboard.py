"""
HTML 仪表盘 — DocForge 风格的可交付评测报告。

设计目标：
  - 一份 .html 单文件，浏览器双击就能看，适合发邮件 / 贴飞书 / PR 附件
  - 视觉层级：Hero → 总体 → 组合 → 维度 → Pairwise → 校准 → 洞察
  - 颜色语义化：score-1..5（红→深绿）的五阶梯，hm-1..5 同梯度热力图
  - Chart.js 渲染条形图 / 雷达图 / Elo 横向条；表格用 CSS class 自动着色
  - 自动洞察：基于数据生成 success / warning / danger / info box，不需人工填

Chart.js 走 CDN（jsdelivr）；CDN 不可达时图表区不渲染，其余区块照常工作。
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.trajectory import ComboResult, ExperimentResult


# ════════════════════════════════════════════════════════════════════════════
# 公共配色 & 评分→class 映射
# ════════════════════════════════════════════════════════════════════════════

# Chart.js 配色：尽量让每个 combo 拿到稳定的颜色
_CHART_PALETTE = [
    ("#4f46e5", "#4f46e5aa"),  # indigo
    ("#e11d48", "#e11d48aa"),  # rose
    ("#0891b2", "#0891b2aa"),  # cyan
    ("#f59e0b", "#f59e0baa"),  # amber
    ("#059669", "#059669aa"),  # emerald
    ("#7c3aed", "#7c3aedaa"),  # violet
    ("#db2777", "#db2777aa"),  # pink
    ("#475569", "#475569aa"),  # slate
]


def _score_class(value: float) -> str:
    """0–1 分数 → 五阶梯 CSS class（score-1 最差，score-5 最佳）。"""
    if value >= 0.9:
        return "score-5"
    if value >= 0.7:
        return "score-4"
    if value >= 0.5:
        return "score-3"
    if value >= 0.3:
        return "score-2"
    return "score-1"


def _heatmap_class(value: float) -> str:
    """0–1 → 五阶梯热力图 class。"""
    if value >= 0.9:
        return "hm-5"
    if value >= 0.7:
        return "hm-4"
    if value >= 0.5:
        return "hm-3"
    if value >= 0.3:
        return "hm-2"
    return "hm-1"


# ════════════════════════════════════════════════════════════════════════════
# Dashboard 主类
# ════════════════════════════════════════════════════════════════════════════

class HTMLDashboard:
    """HTML 仪表盘生成器。"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(self, experiment_result: ExperimentResult, env_name: str = "") -> str:
        stem = (
            f"{experiment_result.experiment_name}_{env_name}"
            if env_name else experiment_result.experiment_name
        )
        filename = f"{stem}_dashboard.html"
        filepath = self.output_dir / filename

        content = self._generate_html(experiment_result)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"  HTML 仪表盘已保存: {filepath}")
        return str(filepath)

    # ── 主组装 ──────────────────────────────────────────────────────────────

    def _generate_html(self, result: ExperimentResult) -> str:
        total_trajs = sum(len(cr.task_results) for cr in result.combo_results)
        total_success = sum(
            sum(1 for t in cr.task_results if t.status == "success")
            for cr in result.combo_results
        )
        overall_rate = total_success / total_trajs if total_trajs else 0.0

        n_llms = len(set(cr.llm_name for cr in result.combo_results))
        n_harnesses = len(set(cr.harness_name for cr in result.combo_results))
        n_envs = len(set(cr.env_name for cr in result.combo_results))
        n_tasks_per_combo = (
            max((len(cr.task_results) for cr in result.combo_results), default=0)
        )

        judge_used = self._detect_judge(result)
        has_pairwise = bool(result.pairwise)
        has_calibration = any(
            cr.summary.get("calibration") for cr in result.combo_results
        )

        # 段落组装（每段独立可空）
        sections = []
        sections.append(self._section_overview(result, total_trajs, total_success, overall_rate))
        sections.append(self._section_combos(result))
        sections.append(self._section_heatmap(result))
        sections.append(self._section_fields(result))
        sections.append(self._section_judge_dims(result))
        sections.append(self._section_pairwise(result))
        sections.append(self._section_calibration(result))
        sections.append(self._section_insights(result, overall_rate, judge_used,
                                                has_pairwise, has_calibration))

        # 仅展示有数据的段，并据此生成 sticky nav
        nav_items = [(sid, label) for sid, label, body in sections if body]
        nav_html = "".join(
            f'<a href="#{sid}">{label}</a>' for sid, label in nav_items
        )
        body_html = "\n".join(body for _, _, body in sections if body)

        chart_js = self._chart_js_block(result)

        gen_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        hero_badges = [
            f"📅 {gen_at}",
            f"🤖 {n_llms} 模型 × {n_harnesses} harness × {n_envs} env",
            f"📋 {total_trajs} 条评测",
        ]
        if judge_used:
            hero_badges.append(f"⚖️ Judge: {judge_used}")
        if has_pairwise:
            hero_badges.append("⚡ Pairwise + Elo")
        if has_calibration:
            hero_badges.append("🔬 Calibration")
        hero_badges_html = "".join(
            f'<span class="badge">{html.escape(b)}</span>' for b in hero_badges
        )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Eval-Anything · {html.escape(result.experiment_name)}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>{_CSS}</style>
</head>
<body>

<nav class="top-nav">{nav_html}</nav>

<div class="hero">
  <div class="hero-pattern"></div>
  <div class="hero-inner">
    <div class="hero-eyebrow">EVAL-ANYTHING REPORT</div>
    <h1>{html.escape(result.experiment_name)}</h1>
    <p class="sub">LLM × Harness × Environment 矩阵评测 · 自动生成可分享的可视化报告</p>
    <div class="meta">{hero_badges_html}</div>
  </div>
</div>

<div class="container">
{body_html}
</div>

<footer>
  <div class="footer-brand">📊 <strong>Eval-Anything</strong></div>
  <div class="footer-meta">
    Generated on {gen_at} ·
    <a href="https://github.com/Rogerrrr18/Eval-Anything" target="_blank">github.com/Rogerrrr18/Eval-Anything</a>
  </div>
</footer>

{chart_js}
</body>
</html>"""

    # ════════════════════════════════════════════════════════════════════════
    # 段：一、总体结果
    # ════════════════════════════════════════════════════════════════════════

    def _section_overview(
        self, result: ExperimentResult,
        total_trajs: int, total_success: int, overall_rate: float,
    ) -> Tuple[str, str, str]:
        n_combos = len(result.combo_results)
        n_llms = len(set(cr.llm_name for cr in result.combo_results))

        # 状态分布统计
        status_count: Dict[str, int] = {}
        for cr in result.combo_results:
            for t in cr.task_results:
                status_count[t.status] = status_count.get(t.status, 0) + 1

        status_pills = ""
        status_colors = {
            "success": "var(--success)", "partial": "var(--warning)",
            "failure": "var(--danger)", "error": "var(--danger-dark)",
            "timeout": "var(--gray-500)",
        }
        for status, n in sorted(status_count.items(), key=lambda x: -x[1]):
            color = status_colors.get(status, "var(--gray-500)")
            status_pills += (
                f'<span class="status-pill" style="background:{color}">'
                f'{html.escape(status)} · {n}</span>'
            )

        rate_color_class = _score_class(overall_rate)
        body = f"""
<div class="section" id="overview">
  <h2 class="section-title">总体结果</h2>
  <p class="section-desc">本次实验跨 {n_llms} 个 LLM × {n_combos} 个组合，共 {total_trajs} 条评测记录。</p>

  <div class="stat-grid">
    <div class="stat-card"><div class="num">{total_trajs}</div><div class="label">总评测数</div></div>
    <div class="stat-card" style="border-top-color:var(--success)">
      <div class="num {rate_color_class}">{overall_rate:.1%}</div>
      <div class="label">总体成功率</div>
    </div>
    <div class="stat-card" style="border-top-color:var(--cyan)"><div class="num">{n_combos}</div><div class="label">组合数</div></div>
    <div class="stat-card" style="border-top-color:var(--purple)"><div class="num">{n_llms}</div><div class="label">LLM 数</div></div>
  </div>

  <div class="card">
    <h3>状态分布</h3>
    <div style="margin-top:10px">{status_pills}</div>
  </div>
</div>
"""
        return ("overview", "📊 总体", body)

    # ════════════════════════════════════════════════════════════════════════
    # 段：二、组合排行
    # ════════════════════════════════════════════════════════════════════════

    def _section_combos(self, result: ExperimentResult) -> Tuple[str, str, str]:
        if not result.combo_results:
            return ("combos", "🏁 组合", "")

        # 按 avg_score 降序排
        ranked = sorted(
            result.combo_results,
            key=lambda c: c.summary.get("avg_score", 0),
            reverse=True,
        )
        best_score = ranked[0].summary.get("avg_score", 0) if ranked else 0

        rows = ""
        for idx, cr in enumerate(ranked, 1):
            s = cr.summary
            rate = s.get("success_rate", 0)
            avg_score = s.get("avg_score", 0)
            fmt = s.get("format_compliance_rate", 0)
            judge_score = s.get("avg_judge_score")
            judge_col = (
                f'<td class="{_score_class(judge_score)}">{judge_score:.1%}</td>'
                if judge_score is not None else '<td class="muted">—</td>'
            )
            medal = ["🥇", "🥈", "🥉"][idx - 1] if idx <= 3 else f"{idx}"
            best_cls = ' class="best-row"' if abs(avg_score - best_score) < 1e-6 else ""
            rows += (
                f'<tr{best_cls}>'
                f'<td>{medal}</td>'
                f'<td><strong>{html.escape(cr.llm_name)}</strong></td>'
                f'<td>{html.escape(cr.harness_name)}</td>'
                f'<td>{html.escape(cr.env_name)}</td>'
                f'<td class="{_score_class(rate)}">{rate:.1%}</td>'
                f'<td class="{_score_class(avg_score)}">{avg_score:.1%}</td>'
                f'<td class="{_score_class(fmt)}">{fmt:.1%}</td>'
                f'{judge_col}'
                f'<td>{s.get("avg_tokens", 0):.0f}</td>'
                f'<td>{s.get("avg_latency_ms", 0):.0f}ms</td>'
                f'</tr>'
            )

        body = f"""
<div class="section" id="combos">
  <h2 class="section-title">组合排行</h2>
  <p class="section-desc">按平均得分降序。绿色块 = 表现优秀；红色块 = 需要关注。</p>

  <div class="chart-container"><canvas id="comboBarChart"></canvas></div>

  <div class="card" style="overflow-x:auto">
    <table>
      <thead><tr>
        <th>排名</th><th>LLM</th><th>Harness</th><th>Env</th>
        <th>成功率</th><th>平均得分</th><th>格式合规</th><th>Judge</th>
        <th>平均 Token</th><th>平均延迟</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>
"""
        return ("combos", "🏁 组合", body)

    # ════════════════════════════════════════════════════════════════════════
    # 段：三、LLM × Harness 热力图
    # ════════════════════════════════════════════════════════════════════════

    def _section_heatmap(self, result: ExperimentResult) -> Tuple[str, str, str]:
        matrix = result.get_comparison_matrix()
        if not matrix:
            return ("heatmap", "🔥 热力图", "")

        harnesses = sorted({h for d in matrix.values() for h in d.keys()})
        if len(harnesses) == 1 and len(matrix) == 1:
            # 单点矩阵看不出意义，跳过
            return ("heatmap", "🔥 热力图", "")

        header = "<tr><th>LLM \\ Harness</th>"
        for h in harnesses:
            header += f"<th>{html.escape(h)}</th>"
        header += "</tr>"

        rows = ""
        for llm in sorted(matrix.keys()):
            row = f'<tr><td class="row-label">{html.escape(llm)}</td>'
            for h in harnesses:
                data = matrix[llm].get(h, {})
                rate = data.get("success_rate", 0)
                row += f'<td class="{_heatmap_class(rate)}">{rate:.0%}</td>'
            row += "</tr>"
            rows += row

        legend = (
            '<div style="margin-bottom:8px;font-size:.82rem;color:var(--gray-500)">'
            '<span class="hm-5">≥90%</span> '
            '<span class="hm-4">≥70%</span> '
            '<span class="hm-3">≥50%</span> '
            '<span class="hm-2">≥30%</span> '
            '<span class="hm-1">&lt;30%</span></div>'
        )

        body = f"""
<div class="section" id="heatmap">
  <h2 class="section-title">LLM × Harness 热力图</h2>
  <p class="section-desc">每个格子 = 该 LLM + Harness 组合的成功率。</p>
  <div class="card">
    {legend}
    <div class="heatmap-wrap"><table class="hm-table">{header}{rows}</table></div>
  </div>
</div>
"""
        return ("heatmap", "🔥 热力图", body)

    # ════════════════════════════════════════════════════════════════════════
    # 段：四、字段级准确率
    # ════════════════════════════════════════════════════════════════════════

    def _section_fields(self, result: ExperimentResult) -> Tuple[str, str, str]:
        # 收集所有 field_* 分数
        fields: set = set()
        for traj in result.get_all_trajectories():
            for key in traj.scores:
                if key.startswith("field_"):
                    fields.add(key[6:])
        if not fields:
            return ("fields", "🎯 字段", "")

        fields_sorted = sorted(fields)
        groups: Dict[str, Dict[str, List[float]]] = {}
        for traj in result.get_all_trajectories():
            key = f"{traj.llm_name} + {traj.harness_name}"
            g = groups.setdefault(key, {f: [] for f in fields_sorted})
            for f in fields_sorted:
                g[f].append(traj.scores.get(f"field_{f}", 0))

        header = "<tr><th>组合</th>"
        for f in fields_sorted:
            header += f"<th>{html.escape(f)}</th>"
        header += "<th>均值</th></tr>"

        rows = ""
        for combo_name, field_data in groups.items():
            row = f'<tr><td class="row-label">{html.escape(combo_name)}</td>'
            all_vals = []
            for f in fields_sorted:
                vals = field_data[f]
                avg = sum(vals) / len(vals) if vals else 0
                all_vals.append(avg)
                row += f'<td class="{_heatmap_class(avg)}">{avg:.0%}</td>'
            mean = sum(all_vals) / len(all_vals) if all_vals else 0
            row += f'<td class="{_heatmap_class(mean)}"><strong>{mean:.0%}</strong></td>'
            row += "</tr>"
            rows += row

        body = f"""
<div class="section" id="fields">
  <h2 class="section-title">字段级准确率</h2>
  <p class="section-desc">每个组合在各字段上的逐项准确率。一眼看出哪个字段是普遍短板。</p>
  <div class="card">
    <div class="heatmap-wrap"><table class="hm-table">{header}{rows}</table></div>
  </div>
</div>
"""
        return ("fields", "🎯 字段", body)

    # ════════════════════════════════════════════════════════════════════════
    # 段：五、Judge 评分维度（雷达 + 热力表）
    # ════════════════════════════════════════════════════════════════════════

    def _section_judge_dims(self, result: ExperimentResult) -> Tuple[str, str, str]:
        combo_dims: Dict[str, Dict[str, List[float]]] = {}
        for cr in result.combo_results:
            key = f"{cr.llm_name} + {cr.harness_name}"
            dims: Dict[str, List[float]] = {}
            for traj in cr.task_results:
                dimensions = (
                    traj.metadata.get("judge", {})
                    .get("details", {})
                    .get("dimensions", {})
                )
                for dim_name, dim_val in dimensions.items():
                    try:
                        dims.setdefault(dim_name, []).append(float(dim_val))
                    except (TypeError, ValueError):
                        pass
            if dims:
                combo_dims[key] = dims

        if not combo_dims:
            return ("judge", "🎯 Judge 维度", "")

        all_dims = sorted({d for dims in combo_dims.values() for d in dims.keys()})

        # 热力表
        header = "<tr><th>维度</th>"
        for k in combo_dims:
            header += f"<th>{html.escape(k)}</th>"
        header += "</tr>"

        rows = ""
        for dim in all_dims:
            row = f'<tr><td class="row-label">{html.escape(dim)}</td>'
            for dims in combo_dims.values():
                vals = dims.get(dim, [])
                avg = sum(vals) / len(vals) if vals else 0
                row += f'<td class="{_heatmap_class(avg)}">{avg:.0%}</td>'
            row += "</tr>"
            rows += row

        body = f"""
<div class="section" id="judge">
  <h2 class="section-title">Judge 评分维度</h2>
  <p class="section-desc">每个组合在 judge rubric 各维度上的均值。雷达图显示完整画像。</p>
  <div class="card"><div class="chart-container"><canvas id="judgeRadarChart"></canvas></div></div>
  <div class="card">
    <div class="heatmap-wrap"><table class="hm-table">{header}{rows}</table></div>
  </div>
</div>
"""
        return ("judge", "🎯 Judge 维度", body)

    # ════════════════════════════════════════════════════════════════════════
    # 段：六、Pairwise + Elo
    # ════════════════════════════════════════════════════════════════════════

    def _section_pairwise(self, result: ExperimentResult) -> Tuple[str, str, str]:
        pw = result.pairwise
        if not pw:
            return ("pairwise", "⚡ Pairwise", "")

        models = pw.get("models", [])
        ranking = pw.get("ranking", [])
        win_matrix = pw.get("win_matrix", {})
        n_cmp = pw.get("n_comparisons", 0)
        judge_name = pw.get("judge", "")

        # Elo 排行表
        rank_rows = ""
        for idx, (model, elo) in enumerate(ranking, 1):
            medal = ["🥇", "🥈", "🥉"][idx - 1] if idx <= 3 else f"{idx}"
            rank_rows += (
                f'<tr><td>{medal}</td><td><strong>{html.escape(model)}</strong></td>'
                f'<td class="elo">{elo:.0f}</td></tr>'
            )

        # Win 矩阵
        win_html = ""
        if models and win_matrix:
            header = "<tr><th>A \\ B</th>"
            for m in models:
                header += f"<th>{html.escape(m)}</th>"
            header += "</tr>"
            rows = ""
            for ma in models:
                row = f'<tr><td class="row-label">{html.escape(ma)}</td>'
                for mb in models:
                    if ma == mb:
                        row += '<td class="muted">—</td>'
                    else:
                        cell = win_matrix.get(ma, {}).get(mb, {})
                        w = cell.get("wins", 0)
                        l_ = cell.get("losses", 0)
                        t = cell.get("ties", 0)
                        total = cell.get("total", 0)
                        if total == 0:
                            row += '<td class="muted">N/A</td>'
                        else:
                            wr = (w + 0.5 * t) / total
                            row += (
                                f'<td class="{_heatmap_class(wr)}">'
                                f'<strong>{w}</strong>W·{l_}L·{t}T<br>'
                                f'<small>{wr:.0%}</small></td>'
                            )
                row += "</tr>"
                rows += row
            win_html = f"""
  <div class="card">
    <h3>Win 矩阵</h3>
    <p class="section-desc">行 = A 模型，列 = B 模型。绿底 = A 胜率高。</p>
    <div class="heatmap-wrap"><table class="hm-table">{header}{rows}</table></div>
  </div>
"""

        body = f"""
<div class="section" id="pairwise">
  <h2 class="section-title">Pairwise 对比 &amp; Elo 排名</h2>
  <p class="section-desc">{n_cmp} 次成对对比 · Judge: <code>{html.escape(judge_name)}</code></p>

  <div class="card">
    <div class="chart-container"><canvas id="eloBarChart"></canvas></div>
    <table style="margin-top:14px">
      <thead><tr><th>排名</th><th>模型</th><th>Elo</th></tr></thead>
      <tbody>{rank_rows}</tbody>
    </table>
  </div>
  {win_html}
</div>
"""
        return ("pairwise", "⚡ Pairwise", body)

    # ════════════════════════════════════════════════════════════════════════
    # 段：七、Judge 校准
    # ════════════════════════════════════════════════════════════════════════

    def _section_calibration(self, result: ExperimentResult) -> Tuple[str, str, str]:
        any_calibration = False
        cards_html = ""
        for cr in result.combo_results:
            cal = cr.summary.get("calibration")
            if not cal:
                continue
            any_calibration = True
            combo_key = f"{cr.llm_name} + {cr.harness_name} + {cr.env_name}"
            cards_html += f'<h3 style="margin-top:18px">{html.escape(combo_key)}</h3>'
            cards_html += '<div class="cal-grid">'
            cards_html += self._cal_card(
                cal.get("score_pearson_r"), "Pearson r",
                "judge 分 ↔ 人工分相关 (≥0.7 佳)", hi=0.7, lo=0.4,
            )
            cards_html += self._cal_card(
                cal.get("pass_accuracy"), "Pass 准确率",
                "passed 与人工一致率 (≥0.8 佳)", hi=0.8, lo=0.6,
            )
            cards_html += self._cal_card(
                cal.get("label_macro_f1"), "Macro F1",
                "label 多分类 (≥0.5 合格)", hi=0.6, lo=0.4,
            )
            n_eval = cal.get("n_evaluated", cal.get("n_samples", 0))
            n_total = cal.get("n_samples", 0)
            cards_html += (
                f'<div class="cal-card" style="border-left-color:var(--gray-500)">'
                f'<div class="num">{n_eval}/{n_total}</div>'
                f'<div class="cal-label">校准集 ({n_eval}/{n_total} 成功)</div>'
                f'</div>'
            )
            cards_html += "</div>"
            warn = cal.get("warning")
            if warn:
                cards_html += f'<div class="warning-box">⚠️ {html.escape(warn)}</div>'

        if not any_calibration:
            return ("calibration", "🔬 校准", "")

        body = f"""
<div class="section" id="calibration">
  <h2 class="section-title">Judge 校准</h2>
  <p class="section-desc">人工标注 vs. judge 评分的一致性分析。可信度红绿灯。</p>
  <div class="card">{cards_html}</div>
</div>
"""
        return ("calibration", "🔬 校准", body)

    def _cal_card(self, value, label: str, desc: str, hi: float, lo: float) -> str:
        if value is None:
            return ""
        if value >= hi:
            color = "var(--success)"
        elif value >= lo:
            color = "var(--warning)"
        else:
            color = "var(--danger)"
        return (
            f'<div class="cal-card" style="border-left-color:{color}">'
            f'<div class="num" style="color:{color}">{value:.3f}</div>'
            f'<div class="cal-label"><strong>{label}</strong></div>'
            f'<div class="cal-desc">{desc}</div></div>'
        )

    # ════════════════════════════════════════════════════════════════════════
    # 段：八、自动洞察 + 结论
    # ════════════════════════════════════════════════════════════════════════

    def _section_insights(
        self, result: ExperimentResult,
        overall_rate: float, judge_used: str,
        has_pairwise: bool, has_calibration: bool,
    ) -> Tuple[str, str, str]:
        insights = self._derive_insights(result, overall_rate)
        if not insights:
            return ("insights", "💡 洞察", "")

        boxes = ""
        for kind, title, content in insights:
            boxes += f'<div class="{kind}-box"><strong>{html.escape(title)}</strong><br>{content}</div>'

        body = f"""
<div class="section" id="insights">
  <h2 class="section-title">洞察与建议</h2>
  <p class="section-desc">基于数据自动生成。绿色 = 亮点；红色 = 待修复风险。</p>
  <div class="card">{boxes}</div>
</div>
"""
        return ("insights", "💡 洞察", body)

    def _derive_insights(
        self, result: ExperimentResult, overall_rate: float,
    ) -> List[Tuple[str, str, str]]:
        """从数据派生 4-6 条洞察 box。"""
        out: List[Tuple[str, str, str]] = []
        if not result.combo_results:
            return out

        ranked = sorted(
            result.combo_results,
            key=lambda c: c.summary.get("avg_score", 0),
            reverse=True,
        )
        best = ranked[0]
        worst = ranked[-1]
        best_score = best.summary.get("avg_score", 0)
        worst_score = worst.summary.get("avg_score", 0)

        # 1. Top performer
        if best_score >= 0.8:
            out.append((
                "success", "🏆 表现最佳",
                f"<code>{html.escape(best.llm_name)} + {html.escape(best.harness_name)}</code> "
                f"在 <code>{html.escape(best.env_name)}</code> 上拿到 "
                f"<strong>{best_score:.1%}</strong> 平均得分。可作为本场景的首选组合。"
            ))
        # 2. Weak performer
        if worst_score < 0.3 and worst is not best:
            out.append((
                "danger", "⚠️ 表现最弱",
                f"<code>{html.escape(worst.llm_name)} + {html.escape(worst.harness_name)}</code> "
                f"平均得分仅 <strong>{worst_score:.1%}</strong>，"
                f"不建议直接用于该场景，优先排查 format 合规性与 rubric 对齐。"
            ))

        # 3. Format compliance issue
        for cr in ranked:
            fmt = cr.summary.get("format_compliance_rate", 1.0)
            if fmt < 0.8:
                out.append((
                    "warning", "📐 格式合规率偏低",
                    f"<code>{html.escape(cr.llm_name)}</code> 仅 <strong>{fmt:.0%}</strong> "
                    f"产出合法 JSON。建议加 few-shot 示例或更严格的 system prompt 约束。"
                ))
                break

        # 4. Field-level worst
        field_totals: Dict[str, List[float]] = {}
        for traj in result.get_all_trajectories():
            for key, val in traj.scores.items():
                if key.startswith("field_"):
                    field_totals.setdefault(key[6:], []).append(val)
        if field_totals:
            field_avgs = {
                f: sum(v) / len(v) for f, v in field_totals.items() if v
            }
            if field_avgs:
                worst_field = min(field_avgs.items(), key=lambda x: x[1])
                if worst_field[1] < 0.5:
                    out.append((
                        "warning", "🎯 最弱字段",
                        f"<code>{html.escape(worst_field[0])}</code> 字段平均准确率仅 "
                        f"<strong>{worst_field[1]:.0%}</strong>，"
                        f"优先排查该字段的 prompt 表述与 evaluator 严格度。"
                    ))

        # 5. Judge / panel disagreement
        disagree_count = 0
        for traj in result.get_all_trajectories():
            labels = (
                traj.metadata.get("judge", {})
                .get("details", {})
                .get("consensus_labels", [])
            )
            if "panel_disagree" in labels:
                disagree_count += 1
        if disagree_count > 0:
            out.append((
                "info", "🔍 Panel 分歧",
                f"<strong>{disagree_count}</strong> 条评测出现 panel_disagree —— "
                f"这些 case 是 rubric 歧义或边界 case 的金矿，优先人工 review。"
            ))

        # 6. Calibration warning
        for cr in result.combo_results:
            cal = cr.summary.get("calibration") or {}
            r = cal.get("score_pearson_r")
            if r is not None and r < 0.4:
                out.append((
                    "danger", "🔬 Judge 可信度不足",
                    f"<code>{html.escape(cr.env_name)}</code> 校准 Pearson r = "
                    f"<strong>{r:.2f}</strong>，judge 与人工标注一致性偏低，"
                    f"在依赖 judge 分数下结论前应人工抽检。"
                ))
                break

        # 7. Pairwise top
        if result.pairwise and result.pairwise.get("ranking"):
            top = result.pairwise["ranking"][0]
            out.append((
                "info", "⚡ Pairwise 冠军",
                f"成对对比聚合 Elo 排名第一：<code>{html.escape(top[0])}</code> "
                f"({top[1]:.0f})。相比绝对分排名，pairwise 抗 rubric scale 偏差更稳。"
            ))

        return out

    # ════════════════════════════════════════════════════════════════════════
    # Chart.js 数据块
    # ════════════════════════════════════════════════════════════════════════

    def _chart_js_block(self, result: ExperimentResult) -> str:
        """生成所有 Chart.js 初始化脚本。无数据则该图表区不渲染。"""
        scripts = []

        # 1. combo 平均得分条形图
        if result.combo_results:
            ranked = sorted(
                result.combo_results,
                key=lambda c: c.summary.get("avg_score", 0),
                reverse=True,
            )
            labels = [
                f"{c.llm_name}+{c.harness_name}" for c in ranked
            ]
            scores = [c.summary.get("avg_score", 0) * 100 for c in ranked]
            success = [c.summary.get("success_rate", 0) * 100 for c in ranked]
            colors = [_CHART_PALETTE[i % len(_CHART_PALETTE)][1] for i in range(len(ranked))]
            borders = [_CHART_PALETTE[i % len(_CHART_PALETTE)][0] for i in range(len(ranked))]
            scripts.append(f"""
if (document.getElementById('comboBarChart')) {{
  new Chart(document.getElementById('comboBarChart'), {{
    type: 'bar',
    data: {{
      labels: {json.dumps(labels)},
      datasets: [
        {{label: '平均得分 (%)', data: {json.dumps(scores)},
          backgroundColor: {json.dumps(colors)}, borderColor: {json.dumps(borders)},
          borderWidth: 2, borderRadius: 6}},
        {{label: '成功率 (%)', data: {json.dumps(success)},
          backgroundColor: 'rgba(124,58,237,0.25)', borderColor: '#7c3aed',
          borderWidth: 2, borderRadius: 6}}
      ]
    }},
    options: {{
      responsive: true,
      plugins: {{title: {{display: true, text: '组合表现对比', font: {{size: 14, weight: 'bold'}}}}}},
      scales: {{y: {{beginAtZero: true, max: 100, ticks: {{callback: v => v + '%'}}}}}}
    }}
  }});
}}
""")

        # 2. judge 维度雷达图
        combo_dims: Dict[str, Dict[str, float]] = {}
        for cr in result.combo_results:
            key = f"{cr.llm_name}+{cr.harness_name}"
            dims_sum: Dict[str, List[float]] = {}
            for traj in cr.task_results:
                ds = traj.metadata.get("judge", {}).get("details", {}).get("dimensions", {})
                for k, v in ds.items():
                    try:
                        dims_sum.setdefault(k, []).append(float(v))
                    except (TypeError, ValueError):
                        pass
            if dims_sum:
                combo_dims[key] = {
                    k: (sum(vs) / len(vs)) for k, vs in dims_sum.items()
                }
        if combo_dims:
            all_dims = sorted({d for dv in combo_dims.values() for d in dv.keys()})
            datasets = []
            for i, (combo, dv) in enumerate(combo_dims.items()):
                fg, bg = _CHART_PALETTE[i % len(_CHART_PALETTE)]
                datasets.append({
                    "label": combo,
                    "data": [dv.get(d, 0) for d in all_dims],
                    "backgroundColor": fg + "33",
                    "borderColor": fg,
                    "borderWidth": 2,
                    "pointRadius": 3,
                })
            scripts.append(f"""
if (document.getElementById('judgeRadarChart')) {{
  new Chart(document.getElementById('judgeRadarChart'), {{
    type: 'radar',
    data: {{labels: {json.dumps(all_dims)}, datasets: {json.dumps(datasets)}}},
    options: {{
      responsive: true,
      plugins: {{title: {{display: true, text: 'Judge 评分维度雷达图', font: {{size: 14, weight: 'bold'}}}}}},
      scales: {{r: {{beginAtZero: true, max: 1, ticks: {{stepSize: 0.2}}}}}}
    }}
  }});
}}
""")

        # 3. Elo 横向条
        pw = result.pairwise
        if pw and pw.get("ranking"):
            ranking = pw["ranking"]
            labels = [r[0] for r in ranking]
            elos = [r[1] for r in ranking]
            colors = [_CHART_PALETTE[i % len(_CHART_PALETTE)][1] for i in range(len(ranking))]
            scripts.append(f"""
if (document.getElementById('eloBarChart')) {{
  new Chart(document.getElementById('eloBarChart'), {{
    type: 'bar',
    data: {{
      labels: {json.dumps(labels)},
      datasets: [{{label: 'Elo', data: {json.dumps(elos)},
                   backgroundColor: {json.dumps(colors)}, borderRadius: 6}}]
    }},
    options: {{
      indexAxis: 'y',
      responsive: true,
      plugins: {{legend: {{display: false}},
                 title: {{display: true, text: 'Elo 排名', font: {{size: 14, weight: 'bold'}}}}}}
    }}
  }});
}}
""")

        if not scripts:
            return ""
        return (
            "<script>\n"
            "Chart.defaults.font.family = "
            "'-apple-system,BlinkMacSystemFont,\"PingFang SC\",sans-serif';\n"
            "Chart.defaults.font.size = 12;\n"
            + "\n".join(scripts) +
            "\n</script>"
        )

    # ── helpers ─────────────────────────────────────────────────────────────

    def _detect_judge(self, result: ExperimentResult) -> str:
        """从 trajectory metadata 里反查使用了哪个 judge / panel。"""
        for traj in result.get_all_trajectories():
            jm = traj.metadata.get("judge", {})
            name = jm.get("panel_name") or jm.get("judge_name") or jm.get("name", "")
            if name:
                return str(name)
            details = jm.get("details", {})
            if details.get("panel_name"):
                return str(details["panel_name"])
        return ""


# ════════════════════════════════════════════════════════════════════════════
# CSS — 提到模块级，方便调色（一处改全场生效）
# ════════════════════════════════════════════════════════════════════════════

_CSS = """
:root {
  --primary: #4f46e5; --primary-light: #eef2ff; --primary-dark: #3730a3;
  --success: #059669; --success-light: #ecfdf5;
  --warning: #d97706; --warning-light: #fffbeb;
  --danger: #dc2626; --danger-light: #fef2f2; --danger-dark: #991b1b;
  --cyan: #0891b2; --cyan-light: #ecfeff;
  --purple: #7c3aed;
  --gray-50: #f9fafb; --gray-100: #f3f4f6; --gray-200: #e5e7eb;
  --gray-300: #d1d5db; --gray-500: #6b7280;
  --gray-700: #374151; --gray-900: #111827;
  --shadow-sm: 0 1px 2px rgba(0,0,0,.04);
  --shadow: 0 1px 3px rgba(0,0,0,.06), 0 1px 2px rgba(0,0,0,.04);
  --shadow-lg: 0 10px 25px rgba(0,0,0,.08), 0 4px 10px rgba(0,0,0,.04);
  --radius: 14px;
  --radius-sm: 8px;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 60px; }
body { font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
       "Microsoft YaHei", sans-serif;
       background: var(--gray-50); color: var(--gray-900); line-height: 1.65;
       font-feature-settings: "tnum" 1; }

/* === Sticky Nav === */
.top-nav { background: rgba(255,255,255,.85); backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border-bottom: 1px solid var(--gray-200); padding: 10px 24px;
  position: sticky; top: 0; z-index: 100; display: flex; gap: 4px;
  flex-wrap: wrap; justify-content: center; }
.top-nav a { padding: 7px 14px; border-radius: 999px; font-size: .82rem;
  color: var(--gray-700); text-decoration: none;
  transition: background .18s, color .18s; }
.top-nav a:hover { background: var(--primary-light); color: var(--primary); }

/* === Hero === */
.hero { position: relative; overflow: hidden;
  background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 40%, #4f46e5 100%);
  color: #fff; padding: 64px 24px 56px; text-align: center; }
.hero-pattern { position: absolute; inset: 0;
  background-image:
    radial-gradient(circle at 25% 25%, rgba(255,255,255,.08) 0, transparent 40%),
    radial-gradient(circle at 75% 75%, rgba(124,58,237,.25) 0, transparent 50%),
    linear-gradient(rgba(255,255,255,.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.04) 1px, transparent 1px);
  background-size: auto, auto, 32px 32px, 32px 32px;
  pointer-events: none; }
.hero-inner { position: relative; z-index: 1; max-width: 920px;
  margin: 0 auto; }
.hero-eyebrow { font-size: .7rem; font-weight: 700; letter-spacing: .25em;
  opacity: .65; margin-bottom: 14px; text-transform: uppercase; }
.hero h1 { font-size: 2.4rem; font-weight: 800; margin-bottom: 12px;
  letter-spacing: -.01em; line-height: 1.15; }
.hero .sub { font-size: 1.02rem; opacity: .85; max-width: 660px;
  margin: 0 auto; }
.hero .meta { display: flex; justify-content: center; gap: 10px;
  margin-top: 22px; flex-wrap: wrap; }
.hero .badge { background: rgba(255,255,255,.12); padding: 6px 16px;
  border-radius: 999px; font-size: .85rem;
  border: 1px solid rgba(255,255,255,.22);
  backdrop-filter: blur(8px); }

/* === Container & sections === */
.container { max-width: 1180px; margin: 0 auto; padding: 0 24px;
  counter-reset: section; }
.section { margin: 48px 0; counter-increment: section; }
.section-title { font-size: 1.45rem; font-weight: 700;
  color: var(--gray-900); margin-bottom: 6px; display: flex;
  align-items: center; gap: 12px; }
.section-title::before {
  content: counter(section);
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border-radius: 50%;
  background: linear-gradient(135deg, var(--primary), var(--purple));
  color: #fff; font-size: .9rem; font-weight: 700;
  box-shadow: 0 2px 8px rgba(79,70,229,.3);
}
.section-desc { color: var(--gray-500); margin-bottom: 18px;
  font-size: .92rem; padding-left: 44px; }

/* === Cards === */
.card { background: #fff; border-radius: var(--radius); padding: 22px;
  box-shadow: var(--shadow); margin-bottom: 14px;
  transition: box-shadow .25s, transform .25s; }
.card:hover { box-shadow: var(--shadow-lg); }
.card h3 { font-size: 1rem; color: var(--gray-900); margin-bottom: 8px;
  font-weight: 600; }

/* === Stat cards === */
.stat-grid { display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 14px; margin: 18px 0; }
.stat-card { background: #fff; border-radius: var(--radius); padding: 22px 20px;
  box-shadow: var(--shadow); text-align: center;
  border-top: 4px solid var(--primary);
  transition: transform .2s, box-shadow .2s; }
.stat-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg); }
.stat-card .num { font-size: 2.2rem; font-weight: 800; color: var(--primary);
  line-height: 1.1; letter-spacing: -.02em; }
.stat-card .label { font-size: .8rem; color: var(--gray-500); margin-top: 6px;
  text-transform: uppercase; letter-spacing: .04em; font-weight: 500; }

/* === Tables === */
table { width: 100%; border-collapse: collapse; background: #fff;
  border-radius: var(--radius); overflow: hidden; box-shadow: var(--shadow);
  font-size: .87rem; }
th { background: linear-gradient(180deg, #1f2937 0%, #374151 100%);
  color: #fff; padding: 12px 14px; text-align: left; font-weight: 600;
  font-size: .82rem; letter-spacing: .02em; text-transform: uppercase; }
td { padding: 11px 14px; border-bottom: 1px solid var(--gray-100);
  text-align: center; transition: background .15s; }
td.row-label { text-align: left; font-weight: 600; color: var(--gray-900); }
td.muted { color: var(--gray-500); }
td.elo { font-weight: 800; color: var(--primary); font-size: 1.1rem;
  letter-spacing: -.01em; }
tbody tr:nth-child(even) td { background: var(--gray-50); }
tbody tr:hover td { background: var(--primary-light); }
tbody tr:last-child td { border-bottom: none; }
tr.best-row td { background: var(--success-light) !important;
  font-weight: 600; }

/* 5 阶梯评分（0-1 分） */
.score-5 { color: #fff !important; background: #059669; font-weight: 700; }
.score-4 { color: #fff !important; background: #34d399; font-weight: 600; }
.score-3 { color: #78350f !important; background: #fbbf24; font-weight: 600; }
.score-2 { color: #fff !important; background: #fb923c; }
.score-1 { color: #fff !important; background: #f87171; font-weight: 600; }

/* 5 阶梯热力图（成功率 / 准确率） */
.hm-5 { background: #059669; color: #fff; font-weight: 700; padding: 4px 8px;
        border-radius: 4px; display: inline-block; }
.hm-4 { background: #34d399; color: #064e3b; padding: 4px 8px;
        border-radius: 4px; display: inline-block; }
.hm-3 { background: #fbbf24; color: #78350f; padding: 4px 8px;
        border-radius: 4px; display: inline-block; }
.hm-2 { background: #fb923c; color: #fff; padding: 4px 8px;
        border-radius: 4px; display: inline-block; }
.hm-1 { background: #f87171; color: #fff; font-weight: 600;
        padding: 4px 8px; border-radius: 4px; display: inline-block; }

/* hm-table 单元格也铺色 */
.hm-table td.hm-5, .hm-table td.hm-4, .hm-table td.hm-3,
.hm-table td.hm-2, .hm-table td.hm-1 {
  display: table-cell; padding: 8px 12px; border-radius: 0;
}
.hm-table td:not([class]) { background: var(--gray-50); }

.heatmap-wrap { overflow-x: auto; }

/* 状态标签 */
.status-pill { display: inline-block; padding: 5px 14px; border-radius: 999px;
  color: #fff; font-size: .8rem; font-weight: 600; margin-right: 6px;
  margin-bottom: 4px;
  box-shadow: 0 1px 3px rgba(0,0,0,.12); }

/* 洞察 box */
.info-box, .warning-box, .success-box, .danger-box {
  padding: 16px 20px; border-radius: var(--radius-sm); margin: 12px 0;
  font-size: .92rem; border-left: 4px solid; line-height: 1.6;
}
.info-box strong, .warning-box strong, .success-box strong, .danger-box strong {
  display: inline-block; margin-bottom: 4px; font-size: .98rem;
}
.info-box { background: var(--cyan-light); border-left-color: var(--cyan);
  color: #155e75; }
.success-box { background: var(--success-light); border-left-color: var(--success);
  color: #064e3b; }
.warning-box { background: var(--warning-light); border-left-color: var(--warning);
  color: #78350f; }
.danger-box { background: var(--danger-light); border-left-color: var(--danger);
  color: #7f1d1d; }

.chart-container { background: #fff; border-radius: var(--radius-sm);
  padding: 12px; margin: 8px 0; }
.chart-container canvas { max-height: 380px; }

/* Calibration cards */
.cal-grid { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }
.cal-card { background: var(--gray-50); border-radius: var(--radius-sm);
  padding: 18px 22px; min-width: 180px;
  border-left: 4px solid var(--primary);
  transition: transform .15s, box-shadow .15s; }
.cal-card:hover { transform: translateY(-2px); box-shadow: var(--shadow); }
.cal-card .num { font-size: 1.9rem; font-weight: 800; color: var(--primary);
  line-height: 1.1; letter-spacing: -.02em; }
.cal-card .cal-label { font-size: .85rem; color: var(--gray-700); margin-top: 6px;
  font-weight: 600; }
.cal-card .cal-desc { font-size: .75rem; color: var(--gray-500); margin-top: 2px; }

/* === Footer === */
footer { text-align: center; padding: 36px 24px 28px; color: var(--gray-500);
  font-size: .85rem; margin-top: 56px;
  background: linear-gradient(180deg, transparent 0%, var(--gray-100) 100%); }
.footer-brand { font-size: 1.05rem; color: var(--gray-700);
  margin-bottom: 6px; letter-spacing: .01em; }
.footer-brand strong { background: linear-gradient(135deg, var(--primary), var(--purple));
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; font-weight: 800; }
.footer-meta a { color: var(--primary); text-decoration: none;
  font-weight: 600; }
.footer-meta a:hover { text-decoration: underline; }

code { background: var(--gray-100); padding: 2px 7px; border-radius: 4px;
  font-family: "SF Mono", Menlo, monospace; font-size: .85em;
  color: var(--primary-dark); }

/* === Mobile === */
@media (max-width: 720px) {
  .hero { padding: 40px 16px 36px; }
  .hero h1 { font-size: 1.6rem; }
  .container { padding: 0 16px; }
  .section { margin: 32px 0; }
  .section-desc { padding-left: 0; }
  .section-title { font-size: 1.15rem; gap: 10px; }
  .section-title::before { width: 26px; height: 26px; font-size: .8rem; }
  .stat-card .num { font-size: 1.7rem; }
  .top-nav { padding: 8px 12px; gap: 2px; overflow-x: auto;
             flex-wrap: nowrap; justify-content: flex-start; }
  .top-nav a { white-space: nowrap; font-size: .76rem; padding: 6px 10px; }
}
"""
