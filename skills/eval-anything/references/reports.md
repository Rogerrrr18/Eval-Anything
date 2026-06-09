# 报告产物解读

跑完一个实验后，`<output_dir>/` 下会有 4 类产物。本文档告诉 skill 怎么按顺序解读、给用户总结洞察。

事实来源：`src/reporting/` 下的 4 个 writer。

## 产物总览

```
<output_dir>/
├─ reports/
│  ├─ details_<exp_name>.xlsx        逐条结果（每行一条任务 × 组合）
│  ├─ summary_<exp_name>.xlsx        每个组合的统计汇总
│  ├─ comparison_<exp_name>.xlsx     LLM × Harness 成功率热力图
│  └─ dashboard_<exp_name>.html      HTML 交互看板（推荐先看这个）
├─ trajectories/
│  └─ <exp_name>.jsonl               每条任务的完整步骤记录
└─ case_studies/
   └─ <exp_name>.md                  失败分类 + 代表性案例 + 分析洞察
```

## 解读顺序（强烈建议遵守）

skill 在跑完后给用户总结时，按以下顺序读：

### 1. 先看 HTML 仪表盘（30 秒拿到大盘）

打开 `reports/dashboard_<exp_name>.html`，关注：
- **总体成功率柱状图**：每个组合的成功率，一眼看出谁强谁弱
- **LLM × Harness 热力图**：成功率矩阵，看 harness 切换的增益
- **字段级正确率分布**：哪些槽位/字段最容易错
- **Token 使用 vs 成功率散点**：性价比对比

### 2. 再看 case study markdown（看具体在哪儿错）

打开 `case_studies/<exp_name>.md`，里面有：
- **失败模式分类**：自动聚类的错误类型（格式错、字段缺失、幻觉等）
- **代表性失败案例**（默认 10 条，由 experiment.reporting.case_study_count 控制）：每条含 prompt、ground truth、model output、错在哪
- **near miss 案例**：接近成功但差一点的，最有指导价值
- **成功模式**：哪些模式上模型都能做对

### 3. 需要深挖时再看 trajectories JSONL

`trajectories/<exp_name>.jsonl` 每行是一个完整 `Trajectory`：

```json
{
  "experiment_name": "...",
  "task_id": "repair_001",
  "llm_name": "deepseek_v4_flash",
  "harness_name": "react",
  "env_name": "slot_filling_xiu",
  "steps": [
    {
      "step_number": 1,
      "observation": "<env 给 agent 看的>",
      "thought": "<ReAct 解析出来的 Thought>",
      "action": {"action_type": "respond", "content": "..."},
      "action_result": "<env 反馈>",
      "latency_ms": 1234,
      "input_tokens": 567,
      "output_tokens": 89
    }
  ],
  "final_answer": "...",
  "ground_truth": {...},
  "scores": {
    "partial_completion": 0.91,
    "format_compliance": 1.0,
    "task_completion": 0.0,
    "field_product_name": 1.0,
    "field_phone_number": 0.0
  },
  "total_input_tokens": 567,
  "total_output_tokens": 89,
  "total_latency_ms": 1234,
  "status": "partial",
  "metadata": {"field_results": {...}, "format_ok": true}
}
```

**典型用法**：
- 用户问"为啥 react 比 raw 慢但准确率没提升" → 抓 trajectories 里 `react` 的 steps，看有多少步是空转 / 跑去想了没用的东西
- 用户问"phone_number 错最多，错在哪儿" → grep `"field_phone_number": 0.0` 的行看 `final_answer`

### 4. Excel 三件套（需要给老板看时）

- `details_*.xlsx`：每行一条 (task, combo)，最后一列 `status` 标 success/partial/failure。**正确字段绿色，错误字段黄色**（仿 evalv3 习惯）。
- `summary_*.xlsx`：组合粒度，列含 success_rate / avg_score / avg_latency_ms / avg_tokens / total_tasks。
- `comparison_*.xlsx`：LLM 行 × Harness 列的成功率热力图。多 env 时分 sheet。

## `scores` 字段的语义

`scores` dict 里的 key：

| key | 范围 | 含义 |
|---|---|---|
| `partial_completion` | [0, 1] | 字段级准确率（正确字段数 / 总字段数） |
| `format_compliance` | {0, 1} | JSON 解析是否成功 |
| `task_completion` | {0, 1} | 是否**全部**字段都对 |
| `field_<key>` | {0, 1} | 字段 `<key>` 是否对 |

`status` ∈ {success, partial, failure, timeout, error}：
- `success`: reward >= 1.0（所有字段全对）
- `partial`: 0 < reward < 1.0
- `failure`: reward == 0（format 错或所有字段都错）
- `timeout`: 任务执行超时
- `error`: 任务执行抛异常

## 给用户的洞察小结模板

跑完之后，**必须**给用户一个 50-150 字的洞察小结。模板：

```
✅ 评测完成。

▸ 最佳组合: (<llm>, <harness>, <env>) — 成功率 X%，平均 Y tokens
▸ Harness 维度对比: <raw 基线 vs 其他 harness 的相对增益/退化>
▸ 最常见的失败模式: <从 case study 提取的 top-1 错因>
▸ 字段级薄弱点: <field_*.0 比例最高的 1-2 个字段>
▸ 建议下一步:
  - <若 raw 已经够好> → 考虑省下 harness 这一层的复杂度
  - <若 react 显著更好> → 优化 react system prompt 或上 function_call
  - <若所有 LLM 都在某个字段上崩> → 数据/prompt 问题而非模型问题
  - <若 token 用量爆炸> → 调小 max_steps 或换轻量模型

📁 详细产物:
  - HTML 仪表盘: <output_dir>/reports/dashboard_*.html
  - 失败案例分析: <output_dir>/case_studies/*.md
  - 完整轨迹: <output_dir>/trajectories/*.jsonl
```

不要省掉这个总结——它是用户消化几十兆报告的唯一捷径。
