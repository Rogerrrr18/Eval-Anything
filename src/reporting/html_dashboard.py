"""
HTML 仪表盘 — 自包含的 HTML 报告，带内嵌图表。

不依赖外部 JS/CSS 库，生成完全离线可查看的 HTML。

新增区块（均按需显示，没数据时自动隐藏）：
  - Judge 评分维度：SVG 雷达图 + 维度热力表（来自 trajectory.metadata.judge.details.dimensions）
  - Pairwise 对比：Elo 排名 + win 矩阵（来自 ExperimentResult.pairwise）
  - Judge 校准：pearson_r / pass_accuracy / macro_f1 卡片（来自 combo.summary.calibration）
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..core.trajectory import ComboResult, ExperimentResult


# ── SVG 工具 ─────────────────────────────────────────────────────────────────

def _svg_radar(
    labels: List[str],
    values: List[float],
    *,
    color: str = "#4472c4",
    size: int = 220,
    title: str = "",
) -> str:
    """生成 SVG 雷达图（不依赖任何外部库）。"""
    n = len(labels)
    if n < 3:
        return ""
    cx = cy = size // 2
    r = size * 0.32
    title_offset = 18 if title else 0
    cy += title_offset // 2
    angles = [2 * math.pi * i / n - math.pi / 2 for i in range(n)]

    # 背景网格
    grid_svg = ""
    for frac in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(
            f"{cx + r * frac * math.cos(a):.1f},{cy + r * frac * math.sin(a):.1f}"
            for a in angles
        )
        stroke = "#e0e0e0" if frac < 1.0 else "#bbb"
        grid_svg += f'<polygon points="{pts}" fill="none" stroke="{stroke}" stroke-width="1"/>'

    # 轴线
    for a in angles:
        grid_svg += (
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" '
            f'x2="{cx + r * math.cos(a):.1f}" y2="{cy + r * math.sin(a):.1f}" '
            f'stroke="#e0e0e0" stroke-width="1"/>'
        )

    # 数据多边形
    pts = " ".join(
        f"{cx + r * max(0.0, min(1.0, v)) * math.cos(a):.1f},"
        f"{cy + r * max(0.0, min(1.0, v)) * math.sin(a):.1f}"
        for v, a in zip(values, angles)
    )
    data_svg = (
        f'<polygon points="{pts}" fill="{color}" fill-opacity="0.22" '
        f'stroke="{color}" stroke-width="2"/>'
    )

    # 顶点小圆
    dots_svg = ""
    for v, a in zip(values, angles):
        dx = cx + r * max(0.0, min(1.0, v)) * math.cos(a)
        dy = cy + r * max(0.0, min(1.0, v)) * math.sin(a)
        dots_svg += f'<circle cx="{dx:.1f}" cy="{dy:.1f}" r="3" fill="{color}"/>'

    # 标签
    labels_svg = ""
    margin = 15
    for lbl, a in zip(labels, angles):
        lx = cx + (r + margin) * math.cos(a)
        ly = cy + (r + margin) * math.sin(a)
        # 垂直微调，让文字不压线
        dy_adj = 4 if ly >= cy + 2 else (-2 if ly <= cy - 2 else 1)
        anchor = "start" if lx > cx + 4 else ("end" if lx < cx - 4 else "middle")
        short = (lbl[:10] + "…") if len(lbl) > 11 else lbl
        labels_svg += (
            f'<text x="{lx:.1f}" y="{ly + dy_adj:.1f}" '
            f'text-anchor="{anchor}" font-size="10" fill="#555">{html.escape(short)}</text>'
        )

    title_svg = (
        f'<text x="{cx}" y="14" text-anchor="middle" font-size="11" '
        f'font-weight="bold" fill="#333">{html.escape(title)}</text>'
        if title else ""
    )

    h = size + title_offset
    return (
        f'<svg width="{size}" height="{h}" viewBox="0 0 {size} {h}" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'{title_svg}{grid_svg}{data_svg}{dots_svg}{labels_svg}</svg>'
    )


_CHART_COLORS = [
    "#4472c4", "#ed7d31", "#a5a5a5", "#ffc000",
    "#5b9bd5", "#70ad47", "#7030a0", "#ff0000",
]


# ── Dashboard ────────────────────────────────────────────────────────────────

class HTMLDashboard:
    """HTML 仪表盘生成器。"""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(self, experiment_result: ExperimentResult, env_name: str = "") -> str:
        """生成 HTML 仪表盘。"""
        filename = f"{experiment_result.experiment_name}_{env_name}_dashboard.html"
        filepath = self.output_dir / filename

        content = self._generate_html(experiment_result)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        print(f"  HTML 仪表盘已保存: {filepath}")
        return str(filepath)

    def _generate_html(self, result: ExperimentResult) -> str:
        """生成完整的 HTML 内容。"""
        # 汇总数据
        total_trajs = sum(len(cr.task_results) for cr in result.combo_results)
        total_success = sum(
            sum(1 for t in cr.task_results if t.status == "success")
            for cr in result.combo_results
        )
        overall_rate = total_success / total_trajs if total_trajs else 0

        # 各组合数据
        combo_rows = ""
        for cr in result.combo_results:
            s = cr.summary
            if not s:
                continue
            rate = s.get("success_rate", 0)
            color = "#c6efce" if rate >= 0.8 else ("#ffff00" if rate >= 0.5 else "#ffc7ce")
            combo_rows += f"""
            <tr>
                <td>{html.escape(cr.llm_name)}</td>
                <td>{html.escape(cr.harness_name)}</td>
                <td>{html.escape(cr.env_name)}</td>
                <td>{s.get('total_tasks', 0)}</td>
                <td style="background-color:{color}; font-weight:bold">{rate:.1%}</td>
                <td>{s.get('avg_score', 0):.1%}</td>
                <td>{s.get('avg_latency_ms', 0):.0f}ms</td>
                <td>{s.get('avg_tokens', 0):.0f}</td>
            </tr>"""

        # 热力图数据（LLM × Harness）
        matrix = result.get_comparison_matrix()
        heatmap_html = self._generate_heatmap(matrix)

        # 字段级准确率
        radar_html = self._generate_field_chart(result)

        # Judge 维度雷达图（按需）
        judge_dims_html = self._generate_judge_dimensions_section(result)
        judge_dims_section = (
            f'\n  <h2>🎯 Judge 评分维度</h2>\n  <div class="section">{judge_dims_html}</div>'
            if judge_dims_html else ""
        )

        # Pairwise 对比（按需）
        pairwise_html = self._generate_pairwise_section(result)
        pairwise_section = (
            f'\n  <h2>⚡ Pairwise 对比 &amp; Elo 排名</h2>\n  <div class="section">{pairwise_html}</div>'
            if pairwise_html else ""
        )

        # Judge 校准（按需）
        calibration_html = self._generate_calibration_section(result)
        calibration_section = (
            f'\n  <h2>🔬 Judge 校准</h2>\n  <div class="section">{calibration_html}</div>'
            if calibration_html else ""
        )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent 评测报告 - {html.escape(result.experiment_name)}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f5f5f5; padding: 20px; }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  h1 {{ color: #1a1a2e; margin-bottom: 5px; }}
  h2 {{ color: #16213e; margin: 20px 0 10px; border-bottom: 2px solid #0f3460; padding-bottom: 5px; }}
  .summary {{ display: flex; gap: 15px; margin: 15px 0; flex-wrap: wrap; }}
  .card {{ background: white; border-radius: 8px; padding: 15px 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); min-width: 150px; }}
  .card .label {{ font-size: 12px; color: #666; }}
  .card .value {{ font-size: 24px; font-weight: bold; color: #1a1a2e; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  th {{ background: #4472c4; color: white; padding: 10px 8px; text-align: center; font-size: 13px; }}
  td {{ padding: 8px; text-align: center; border-bottom: 1px solid #eee; font-size: 13px; }}
  tr:hover {{ background: #f0f4ff; }}
  .section {{ background: white; border-radius: 8px; padding: 15px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .heatmap-cell {{ display: inline-block; width: 60px; height: 30px; text-align: center; line-height: 30px; font-size: 11px; border: 1px solid #ddd; }}
  .radar-wrap {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin-bottom: 12px; }}
  .elo-badge {{ display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 12px; font-weight: bold; color: white; background: #4472c4; margin: 2px; }}
  .cal-grid {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 10px; }}
  .cal-card {{ background: #f8f9fa; border-radius: 8px; padding: 12px 16px; min-width: 160px; border-left: 4px solid #4472c4; }}
  .cal-card .metric {{ font-size: 22px; font-weight: bold; color: #1a1a2e; }}
  .cal-card .desc {{ font-size: 11px; color: #888; margin-top: 2px; }}
  .warn-box {{ background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; padding: 8px 12px; font-size: 12px; color: #856404; margin-top: 8px; }}
</style>
</head>
<body>
<div class="container">
  <h1>🤖 Agent 评测报告</h1>
  <p style="color:#666">实验: {html.escape(result.experiment_name)} | 共 {total_trajs} 条评测记录</p>

  <div class="summary">
    <div class="card">
      <div class="label">总评测数</div>
      <div class="value">{total_trajs}</div>
    </div>
    <div class="card">
      <div class="label">总体成功率</div>
      <div class="value" style="color:{'#27ae60' if overall_rate >= 0.8 else '#e74c3c'}">{overall_rate:.1%}</div>
    </div>
    <div class="card">
      <div class="label">组合数</div>
      <div class="value">{len(result.combo_results)}</div>
    </div>
    <div class="card">
      <div class="label">LLM 数</div>
      <div class="value">{len(set(cr.llm_name for cr in result.combo_results))}</div>
    </div>
  </div>

  <h2>📊 组合评测结果</h2>
  <table>
    <tr><th>LLM</th><th>Harness</th><th>Environment</th><th>任务数</th><th>成功率</th><th>平均得分</th><th>平均延迟</th><th>平均Token</th></tr>
    {combo_rows}
  </table>

  <h2>🔥 LLM × Harness 热力图</h2>
  <div class="section">
    {heatmap_html}
  </div>

  <h2>📈 字段级准确率</h2>
  <div class="section">
    {radar_html}
  </div>
  {judge_dims_section}
  {pairwise_section}
  {calibration_section}

  <footer style="margin-top:30px; color:#999; font-size:12px; text-align:center;">
    Agent Eval Pipeline Report | Generated by eval-anything
  </footer>
</div>
</body>
</html>"""

    # ── 原有区块 ──────────────────────────────────────────────────────────────

    def _generate_heatmap(self, matrix: Dict[str, Dict[str, Dict[str, float]]]) -> str:
        if not matrix:
            return "<p>暂无数据</p>"

        all_harnesses = sorted(set(h for d in matrix.values() for h in d.keys()))

        header = (
            '<div style="display:flex">'
            '<div class="heatmap-cell" style="font-weight:bold;background:#4472c4;color:white">LLM \\ Harness</div>'
        )
        for h in all_harnesses:
            header += f'<div class="heatmap-cell" style="font-weight:bold;background:#4472c4;color:white">{html.escape(h)}</div>'
        header += "</div>"

        rows = ""
        for llm in sorted(matrix.keys()):
            row = f'<div style="display:flex"><div class="heatmap-cell" style="font-weight:bold;background:#f0f0f0">{html.escape(llm)}</div>'
            for h in all_harnesses:
                data = matrix[llm].get(h, {})
                rate = data.get("success_rate", 0)
                if rate >= 0.8:
                    bg, fg = "#27ae60", "white"
                elif rate >= 0.5:
                    bg, fg = "#f39c12", "white"
                else:
                    bg, fg = ("#e74c3c" if rate > 0 else "#bdc3c7"), "white"
                row += f'<div class="heatmap-cell" style="background:{bg};color:{fg}">{rate:.0%}</div>'
            row += "</div>"
            rows += row

        return header + rows

    def _generate_field_chart(self, result: ExperimentResult) -> str:
        all_fields: set = set()
        for traj in result.get_all_trajectories():
            for key in traj.scores:
                if key.startswith("field_"):
                    all_fields.add(key[6:])

        if not all_fields:
            return "<p>暂无字段级数据</p>"

        fields = sorted(all_fields)

        groups: Dict[str, Dict[str, List[float]]] = {}
        for traj in result.get_all_trajectories():
            key = f"{traj.llm_name} + {traj.harness_name}"
            if key not in groups:
                groups[key] = {f: [] for f in fields}
            for f in fields:
                groups[key][f].append(traj.scores.get(f"field_{f}", 0))

        header = "<tr><th>组合</th>" + "".join(f"<th>{html.escape(f)}</th>" for f in fields) + "</tr>"
        rows = ""
        for combo_name, field_data in groups.items():
            row = f"<tr><td style='font-weight:bold'>{html.escape(combo_name)}</td>"
            for f in fields:
                vals = field_data[f]
                avg = sum(vals) / len(vals) if vals else 0
                color = "#c6efce" if avg >= 0.8 else ("#ffff00" if avg >= 0.5 else "#ffc7ce")
                row += f'<td style="background:{color}">{avg:.1%}</td>'
            row += "</tr>"
            rows += row

        return f"<table><tr>{header}</tr>{rows}</table>"

    # ── 新区块：Judge 维度雷达图 ──────────────────────────────────────────────

    def _generate_judge_dimensions_section(self, result: ExperimentResult) -> str:
        """收集 judge 维度得分，生成每个 combo 的雷达图 + 汇总热力表。"""
        # 收集数据：combo_key → dim → [scores]
        combo_dims: Dict[str, Dict[str, List[float]]] = {}
        for cr in result.combo_results:
            key = f"{cr.llm_name} + {cr.harness_name}"
            dims: Dict[str, List[float]] = {}
            for traj in cr.task_results:
                dimensions = (
                    traj.metadata
                    .get("judge", {})
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
            return ""

        all_dims = sorted({d for dims in combo_dims.values() for d in dims.keys()})

        # 雷达图排列
        charts_html = '<div class="radar-wrap">'
        for idx, (combo_key, dims) in enumerate(combo_dims.items()):
            avg_vals = [
                sum(dims.get(d, [0])) / max(len(dims.get(d, [1])), 1)
                for d in all_dims
            ]
            color = _CHART_COLORS[idx % len(_CHART_COLORS)]
            svg = _svg_radar(all_dims, avg_vals, color=color, title=combo_key)
            charts_html += f'<div style="text-align:center">{svg}</div>'
        charts_html += "</div>"

        # 热力表
        header = "<tr><th>维度</th>" + "".join(
            f"<th>{html.escape(k)}</th>" for k in combo_dims
        ) + "</tr>"
        rows = ""
        for dim in all_dims:
            row = f"<tr><td style='font-weight:bold;text-align:left;padding-left:8px'>{html.escape(dim)}</td>"
            for dims in combo_dims.values():
                vals = dims.get(dim, [])
                avg = sum(vals) / len(vals) if vals else 0.0
                bg = "#c6efce" if avg >= 0.8 else ("#ffff00" if avg >= 0.5 else "#ffc7ce")
                row += f'<td style="background:{bg}">{avg:.1%}</td>'
            row += "</tr>"
            rows += row

        table_html = f'<div style="margin-top:12px"><table>{header}{rows}</table></div>'
        return charts_html + table_html

    # ── 新区块：Pairwise + Elo ────────────────────────────────────────────────

    def _generate_pairwise_section(self, result: ExperimentResult) -> str:
        """Elo 排名 + win 矩阵。"""
        pw = result.pairwise
        if not pw:
            return ""

        models = pw.get("models", [])
        ranking = pw.get("ranking", [])
        win_matrix = pw.get("win_matrix", {})
        n_cmp = pw.get("n_comparisons", 0)
        judge_name = pw.get("judge", "")

        # Elo 排名卡片
        rank_html = '<div style="margin-bottom:12px"><strong>Elo 排名</strong>（越高越好）：<br/><br/>'
        for rank_idx, (model, elo) in enumerate(ranking, 1):
            medal = ["🥇", "🥈", "🥉"][rank_idx - 1] if rank_idx <= 3 else f"{rank_idx}."
            rank_html += f'<span class="elo-badge">{medal} {html.escape(model)} {elo:.0f}</span> '
        rank_html += f'<br/><small style="color:#888;margin-top:6px;display:block">'
        rank_html += f'{n_cmp} 次对比 | Judge: {html.escape(judge_name)}</small></div>'

        # Win 矩阵表
        if not models or not win_matrix:
            return rank_html

        header = "<tr><th>Model A \\ Model B</th>" + "".join(
            f"<th>{html.escape(m)}</th>" for m in models
        ) + "</tr>"
        rows = ""
        for ma in models:
            row = f"<tr><td style='font-weight:bold;background:#f0f0f0'>{html.escape(ma)}</td>"
            for mb in models:
                if ma == mb:
                    row += '<td style="background:#eee">—</td>'
                else:
                    cell = win_matrix.get(ma, {}).get(mb, {})
                    w = cell.get("wins", 0)
                    l = cell.get("losses", 0)
                    t = cell.get("ties", 0)
                    total = cell.get("total", 0)
                    if total == 0:
                        row += "<td>N/A</td>"
                    else:
                        wr = (w + 0.5 * t) / total
                        bg = "#c6efce" if wr >= 0.6 else ("#ffc7ce" if wr < 0.4 else "#ffff00")
                        row += f'<td style="background:{bg}">{w}W {l}L {t}T<br/><small>{wr:.0%}</small></td>'
            row += "</tr>"
            rows += row

        table_html = (
            f'<p style="font-size:12px;color:#888;margin-bottom:6px">'
            f'单元格 = A 赢 B 的结果（行=A，列=B）</p>'
            f"<table>{header}{rows}</table>"
        )
        return rank_html + table_html

    # ── 新区块：Calibration ───────────────────────────────────────────────────

    def _generate_calibration_section(self, result: ExperimentResult) -> str:
        """展示 judge 校准指标卡片（每个有 calibration_set 的 combo 一组）。"""
        sections = []
        for cr in result.combo_results:
            cal = cr.summary.get("calibration")
            if not cal:
                continue

            combo_key = f"{cr.llm_name} + {cr.harness_name} + {cr.env_name}"
            n = cal.get("n_samples", 0)
            n_eval = cal.get("n_evaluated", n)
            warn = cal.get("warning", "")

            cards = f'<p style="font-weight:bold;margin-bottom:8px">{html.escape(combo_key)}</p>'
            cards += '<div class="cal-grid">'

            def _card(metric_val, label, desc, threshold_hi=0.7, threshold_lo=0.4):
                if metric_val is None:
                    return ""
                color = (
                    "#27ae60" if metric_val >= threshold_hi
                    else ("#e67e22" if metric_val >= threshold_lo else "#e74c3c")
                )
                return (
                    f'<div class="cal-card">'
                    f'<div class="metric" style="color:{color}">{metric_val:.3f}</div>'
                    f'<div style="font-size:13px;font-weight:bold;margin-top:2px">{label}</div>'
                    f'<div class="desc">{desc}</div></div>'
                )

            cards += _card(cal.get("score_pearson_r"), "Pearson r",
                           "judge分 ↔ 人工分相关 (≥0.7 佳)")
            cards += _card(cal.get("pass_accuracy"), "Pass 准确率",
                           "passed 与人工一致率 (≥0.8 佳)", threshold_hi=0.8, threshold_lo=0.6)
            cards += _card(cal.get("label_macro_f1"), "Macro F1",
                           "label 多分类 macro-F1 (≥0.5 合格)", threshold_hi=0.6, threshold_lo=0.4)

            # n_samples card
            cards += (
                f'<div class="cal-card">'
                f'<div class="metric">{n_eval}/{n}</div>'
                f'<div style="font-size:13px;font-weight:bold;margin-top:2px">评估成功</div>'
                f'<div class="desc">校准集样本 / judge 成功</div></div>'
            )
            cards += "</div>"

            if warn:
                cards += f'<div class="warn-box">⚠️ {html.escape(warn)}</div>'

            sections.append(cards)

        return "<hr/>".join(sections) if sections else ""
