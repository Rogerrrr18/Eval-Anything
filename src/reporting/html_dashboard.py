"""
HTML 仪表盘 — 自包含的 HTML 报告，带内嵌图表。

不依赖外部 JS/CSS 库，生成完全离线可查看的 HTML。
"""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List

from ..core.trajectory import ComboResult, ExperimentResult


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

        # 字段级准确率雷达图
        radar_html = self._generate_field_chart(result)

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

  <footer style="margin-top:30px; color:#999; font-size:12px; text-align:center;">
    Agent Eval Pipeline Report | Generated by agent-eval-pipeline
  </footer>
</div>
</body>
</html>"""

    def _generate_heatmap(self, matrix: Dict[str, Dict[str, Dict[str, float]]]) -> str:
        """生成热力图 HTML。"""
        if not matrix:
            return "<p>暂无数据</p>"

        all_harnesses = sorted(set(h for d in matrix.values() for h in d.keys()))

        header = '<div style="display:flex"><div class="heatmap-cell" style="font-weight:bold;background:#4472c4;color:white">LLM \\ Harness</div>'
        for h in all_harnesses:
            header += f'<div class="heatmap-cell" style="font-weight:bold;background:#4472c4;color:white">{html.escape(h)}</div>'
        header += '</div>'

        rows = ""
        for llm in sorted(matrix.keys()):
            row = f'<div style="display:flex"><div class="heatmap-cell" style="font-weight:bold;background:#f0f0f0">{html.escape(llm)}</div>'
            for h in all_harnesses:
                data = matrix[llm].get(h, {})
                rate = data.get("success_rate", 0)
                if rate >= 0.8:
                    bg = "#27ae60"
                    fg = "white"
                elif rate >= 0.5:
                    bg = "#f39c12"
                    fg = "white"
                else:
                    bg = "#e74c3c" if rate > 0 else "#bdc3c7"
                    fg = "white"
                row += f'<div class="heatmap-cell" style="background:{bg};color:{fg}">{rate:.0%}</div>'
            row += '</div>'
            rows += row

        return header + rows

    def _generate_field_chart(self, result: ExperimentResult) -> str:
        """生成字段级准确率表格。"""
        # 收集所有字段名
        all_fields: set = set()
        for traj in result.get_all_trajectories():
            for key in traj.scores:
                if key.startswith("field_"):
                    all_fields.add(key[6:])

        if not all_fields:
            return "<p>暂无字段级数据</p>"

        fields = sorted(all_fields)

        # 按 (LLM, Harness) 分组计算字段准确率
        groups: Dict[str, Dict[str, List[float]]] = {}
        for traj in result.get_all_trajectories():
            key = f"{traj.llm_name} + {traj.harness_name}"
            if key not in groups:
                groups[key] = {f: [] for f in fields}
            for f in fields:
                val = traj.scores.get(f"field_{f}", 0)
                groups[key][f].append(val)

        # 生成表格
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
