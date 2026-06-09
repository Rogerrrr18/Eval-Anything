# Workflow: design-experiment

主流程 — 从用户的自然语言描述到一份跑完的评测报告。**5 步 4 强制闸门**。

> 这是 skill 的核心 workflow。任何"我想跑个评测 / 对比这些模型 / 测试这个 agent"类请求都走这里。

## 前置：环境检查（自动，不打扰用户）

进入流程前先做：

1. **验证项目已安装**：`which eval-agent` 或 `python -c "import src"`。如果失败，提示用户 `pip install -e .`。
2. **拉真实 profile 列表**：跑一次 `eval-agent --list-profiles --config-dir <repo>/configs`。把输出存住，后面闸门 4 之前用得到。
3. **检查 datasets/ 目录是否非空**：`ls datasets/`。若空，告诉用户"我会引导你配置数据集"。

## Step 1: 任务类型识别

### 输入

用户的自然语言描述。

### 驾驶 LLM 要做的事

1. 仔细听用户描述，归类到下面任务类型之一（中文别名只是触发词，最终归类用英文）：
   - **slot_filling**: 槽位填充 / 信息抽取 / NLU
   - **tool_use**: 工具调用 / function calling / API agent
   - **reasoning**: 数学 / 逻辑 / 多步推理
   - **code**: 代码生成 / 代码补全
   - **dialog_judge**: 多轮对话（裁判评分）
   - **classification**: 分类 / 选择题
   - **custom**: 用户的任务不在上面（垂直业务场景）

2. 根据任务类型推断**评测维度**（默认建议给用户看）：
   - slot_filling: 字段级准确率、JSON 合规率、平均 token
   - tool_use: 工具选择正确率、参数正确率、调用链长度、是否最终交付
   - reasoning: 终答正确率、解题步数、token 效率
   - code: 测试通过率、运行时错误率
   - dialog_judge: judge score、轮数
   - classification: 准确率、混淆矩阵

3. 推断 **harness 推荐集**（按 `SKILL.md` 的 harness 决策树）。

### ⛔ 闸门 1（强制多选确认）

```
question: "我理解你的任务是 [task_type]，关键评测维度是 [a, b, c]，对吗？"
options:
  - "确认，继续下一步"
  - "任务类型不对，让我说清楚"      ← 选这个 → 让用户重新描述任务，回到 Step 1
  - "评测维度要补充/修改"           ← 选这个 → 问用户加哪些维度
  - "我还想多加一个评测维度（自定义）"
```

不要跳过这一步。哪怕你 99% 确定，也要让用户拍板——后续所有工作都建立在这个判断上。

## Step 2: 数据集来源选择

### 驾驶 LLM 要做的事

1. 读 `references/datasets.md`，找该任务类型对应的开源候选。
2. 如果当前 `datasets/` 已有对应任务的 JSONL，把它作为"已有数据"选项列出。

### ⛔ 闸门 2（强制多选确认）

```
question: "评测集从哪儿来？"
options:
  - "A. 用开源数据集（我推荐: <候选1>、<候选2>、<候选3>）"
  - "B. Mock 合成一份（适合垂直业务、没现成集的场景）"
  - "C. 我自己有数据（告诉我路径，我帮你校验格式）"
  - "D. 混合（开源 + mock 补长尾）"
```

按用户选择走不同分支：

### 分支 A：开源数据集

1. 让用户在你列的候选里选一个（再来一轮多选确认）
2. 写一个转换脚本 `scripts/convert_<source>.py`，按 `references/configs.md` 第 3 节的 JSONL schema 输出到 `datasets/<task>/<source>.jsonl`
3. 跑一遍脚本，`head -1` 检查一条
4. 进入 Step 3

### 分支 B：Mock 合成

→ **委托给 `workflows/mock-dataset.md`**。完成后回到本流程的 Step 3。

### 分支 C：自有数据

1. 让用户提供文件路径
2. Read 一条样例，按 `references/configs.md` 第 3 节的 schema 校验
3. 如果字段不匹配，写一个一次性转换脚本，把用户的格式映射到标准 JSONL
4. 进入 Step 3

### 分支 D：混合

A + B 都做，最后把两个 JSONL 合并到一个文件，或者作为两个 environment 条目分别配置。

## Step 3: 自动选 harness + 生成配置 YAML

### 3.1 自动算 harness 集合（不问用户）

**关键变化**：本步骤**不再问用户"要哪些 harness"**——这是工程细节，应该由 skill 内置算法自动决定。

驾驶 LLM 必须读 `references/harness-selection.md` 后按算法心算出：
- `harness_profiles`: 要跑的 harness 名列表（永远含 `raw` 基线）
- `harness_overrides`: 每个 harness 的 `max_steps` 等超参
- `filtered_combos`: 被剔除的 (LLM, harness) 不兼容组合 + 理由
- `reasoning`: 一段说明，告诉用户"为什么这样选"

输入：
- `task_type`（来自闸门 1）
- `eval_dimensions`（来自闸门 1）
- `env_class`（当前固定 `DialogEnvironment`）
- `llm_profiles`（用户要测的 LLM，由你在 Step 1 之后跟用户确认范围）

输出示例：

```
harness_profiles: [raw, react]
harness_overrides:
  raw: {max_steps: 1}
  react: {max_steps: 8}        # 任务类型 reasoning 推荐
filtered_combos: []            # 本例 LLM 都不带 function_call，没有不兼容
reasoning: |
  我自动选了 harness = [raw, react]，理由：
  - 你的任务类型是 reasoning，需要看推理链能力
  - raw 作为不可省的基线
  - react 在多步推理上可能有增益，max_steps 设 8
  - 没加 function_call —— 你的任务不涉及工具调用，加它只是浪费 token
```

#### 唯一例外

如果用户在描述里明确指定了 harness（"只用 raw"、"加一个 function_call"），用户优先级最高，覆盖算法。

#### 复用 vs 新建 harness profile

- 算法推荐的 `max_steps` 跟 `configs/harness_profiles.yaml` 现有同名 profile 偏差 < 30% → 复用，**不动 yaml**
- 偏差大或推荐 harness 在 yaml 中没有对应 profile → **追加**新 profile，命名 `<harness>_<task_type>`（如 `react_reasoning`），不修改现有 profile

### 3.2 生成 / 修改 YAML

按 `templates/` 下的模板生成：

1. **environment 条目**（追加到 `configs/environments.yaml`）—— 用 `templates/environment.yaml.j2`
2. **experiment 文件**（新建 `configs/experiments/<name>.yaml`）—— 用 `templates/experiment.yaml.j2`，`harness_profiles` 字段来自 3.1
3. **可能**：新 harness profile（追加到 `configs/harness_profiles.yaml`）—— 仅当 3.1 决定要新建
4. **可能**：新 LLM profile（追加到 `configs/llm_profiles.yaml`）—— 用户要测试新模型才加
5. **可能**：judge profile（追加到 `configs/judge_profiles.yaml`）—— dialog_judge 等任务才加

填字段时**严格对齐** `references/configs.md` 里的 schema。

### ⛔ 闸门 3（强制多选确认，展示完整 diff + harness reasoning）

把 **3.1 的 reasoning 段** 和 **3.2 的 YAML diff** 一起完整贴给用户：

```
【Harness 自动选择】
<把 reasoning 段贴这里>

【即将写入的配置】
configs/environments.yaml （追加）：
  <yaml diff>

configs/experiments/<name>.yaml （新建）：
  <yaml 内容>

configs/harness_profiles.yaml （追加，如有）：
  <yaml diff>

【过滤的组合】
<把 filtered_combos 列出来；空就写"无">
```

然后：

```
question: "这是我自动选的 harness + 准备写入的配置，确认吗？"
options:
  - "确认，写盘"
  - "harness 选错了，让我手动指定"      ← 用户保留覆盖权
  - "修改 environment 配置"
  - "修改 experiment 的并发 / 输出参数"
  - "我想换个 LLM profile"
```

**只有用户选"确认"才能调 Write 工具**。如果用户选"手动指定 harness"，本步骤降级为问用户要哪些 harness，但保留自动推荐的 max_steps 作为默认值。

## Step 4: Dry-run

### 驾驶 LLM 要做的事

```bash
eval-agent --experiment <name> --config-dir configs --dry-run
```

捕获输出，提取关键信息：
- 组合数 = |LLM| × |Harness| × |Env|
- 每个组合的 dataset 大小（读 environment 里 dataset 文件的行数）
- 总任务数 = 组合数 × 平均 dataset 大小
- 粗略预估耗时：本地 vLLM 假设单任务 3-10 秒，远程 API 假设 1-3 秒

### ⛔ 闸门 4（强制多选确认）

```
question: "Dry-run: 将运行 N 个组合 × M 条任务 = K 次 LLM 调用，预估 X-Y 分钟。开始正式跑吗？"
options:
  - "开始跑全量"
  - "先跑小集（前 5 条）验证流程"      ← 强烈推荐第一次跑的选项
  - "调整并发参数后再跑"
  - "取消，回到 Step 3 改配置"
```

**重要提醒**：如果配置里含 `function_call` harness，在选项展示前加一句"⚠️ 所选 LLM 必须支持原生 function calling，否则 FunctionCallHarness 会无法触发 submit_answer，结果将全部不合规"。

## Step 5: 正式跑 + 读报告

### 驾驶 LLM 要做的事

1. 跑 `eval-agent --experiment <name> --config-dir configs --output-dir outputs/<name>_<YYYYMMDD_HHMM>`
2. 跑完后按 `references/reports.md` 的"解读顺序"读：
   - HTML dashboard（大盘）
   - case studies markdown（错在哪）
   - trajectories JSONL（深挖时）
3. 按 `references/reports.md` 的"洞察小结模板"给用户**50-150 字的总结**，含：
   - 最佳组合
   - harness 维度对比
   - top-1 失败模式
   - 字段级薄弱点
   - 下一步建议（具体且可执行）
4. 列出产物路径让用户知道去哪儿看详情

## 异常处理

| 情况 | 怎么办 |
|---|---|
| dry-run 报错 profile 不存在 | 回到 Step 3 检查 YAML key 名拼写 |
| 正式跑时大批 timeout | 调高 `execution.task_timeout_seconds` 或调低并发 |
| 正式跑时格式不合规率 > 50% | 大概率是 prompt 没说清楚 JSON 要求 → 改 environment 或 harness 的 system_prompt |
| function_call harness 永远不触发 submit_answer | 所选 LLM 不支持 tools → 换 LLM 或换 harness |
| 报告生成失败 | 检查 `<output_dir>/trajectories/*.jsonl` 是否非空，非空就重跑报告生成（用 `src.reporting` 的 writer 单独调） |

## 流程结束 ≠ 任务结束

跑完一轮后主动问用户：
- "要不要改个 harness 再跑一轮做对比？"（如果只跑了 raw）
- "要不要加几个失败案例进训练集？"
- "要不要把这次配置存成 named experiment 供以后复用？"

不要让用户觉得"跑完就完了"——评测是迭代过程。
