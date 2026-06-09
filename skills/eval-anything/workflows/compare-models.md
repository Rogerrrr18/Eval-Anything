# Workflow: compare-models

横向对比：固定两轴，变化一轴。

> 用户最常想要的评测形态。本流程专门处理"对比"语义：从研究问题反推 experiment 设计，而不是无脑笛卡尔积。

## 触发条件

- "对比 GPT-4 和 DeepSeek 在 X 任务的表现"
- "ReAct 比 Raw 强多少"
- "我的 agent 在哪类任务上崩"
- "横向 benchmark / 全矩阵 benchmark"

## Step 1: 识别"对比的轴"

⛔ 多选确认：

```
question: "你想对比哪一维？固定其他两维更公平："
options:
  - "对比 LLM（固定 1 个 harness + 1 个 env，变 N 个模型）"
  - "对比 Harness（固定 1 个 LLM + 1 个 env，变 N 个 harness）"
  - "对比 Environment（固定 1 个 LLM + 1 个 harness，变 N 个任务）"
  - "全矩阵对比（笛卡尔积，更贵但最全面）"
```

不要让用户跳这一题。"全矩阵"是默认选项但通常不是最优选——5×3×4=60 组合跑全量是很多人没意识到的成本。

## Step 2: 把"固定的两维"钉死

按用户选的对比轴，问"固定哪一个"：

### 如果对比 LLM
- 固定的 harness：默认 `raw`（最公平，所有 LLM 都能跑）。除非用户明确要"看 LLM 在 ReAct 形态下的差异"。
- 固定的 env：用户的核心任务。如果用户没想清楚，建议挑一个数据集小、覆盖典型场景的 env。

### 如果对比 Harness
- 固定的 LLM：选 1 个**用户已经验证过质量过得去**的模型，不要选未知能力的模型——会让对比变成 LLM 噪声而非 harness 信号。
- 固定的 env：同上。
- **必须**带 `raw` 作为 baseline。

### 如果对比 Environment
- 固定的 LLM + harness：选一对"最常用的生产组合"，看模型在不同任务上的泛化。

### 如果全矩阵
- 提前算总组合数：`|LLM| × |Harness| × |Env|`，超过 12 个组合就强烈建议拆成多个实验。

## Step 3: 起草 experiment YAML

用 `templates/experiment.yaml.j2`，但**用户对比哪个轴**决定哪几行展开：

```yaml
# 对比 LLM 的形态：
experiment:
  name: "llm_comparison_<env_name>"
  llm_profiles: [model_a, model_b, model_c, model_d]   # ← 多个
  harness_profiles: [raw]                              # ← 1 个
  environments: [task]                                 # ← 1 个

# 对比 Harness 的形态：
experiment:
  name: "harness_comparison_<llm_name>_<env_name>"
  llm_profiles: [fixed_llm]                            # ← 1 个
  harness_profiles: [raw, react, function_call]        # ← 多个
  environments: [task]                                 # ← 1 个

# 全矩阵：
experiment:
  name: "full_matrix"
  llm_profiles: [...]
  harness_profiles: [...]
  environments: [...]
```

## Step 4: 兼容性预检（关键）

在生成全矩阵 YAML 时驾驶 LLM 必须主动做这一步：

1. 对每个 (llm, harness) 组合检查：
   - 该 harness 用 `chat_with_tools` 吗？（FunctionCall 用）
   - 该 LLM 是否支持 function calling？（按经验或问用户）
2. 列出**预计无效组合**，让用户决定剔除还是保留：

```
⚠️ 兼容性预检：
- (model_a, function_call): model_a 不支持 function calling，预计 submit_answer 不会被触发
- (model_b, function_call): 已知支持，保留
- ...

要剔除不兼容组合吗？
  [是，自动剔除]
  [否，全部保留（作为反面案例）]
```

## Step 5: 走 design-experiment 的剩余流程

走完 Step 3 之后回到 `workflows/design-experiment.md` 的 Step 3（生成配置 diff + 闸门 3）继续。

## Step 6: 解读对比报告

对比类 experiment 跑完后，**报告解读重点不同**：

### 对比 LLM 时

- 看 `comparison_*.xlsx`：模型按成功率排序
- 看 token vs success 散点：找性价比最优解
- 看 case study：哪些模型在哪类任务上崩
- **给用户的关键问题**：你预算允许的话上最强的；预算紧的话哪个性价比最高？

### 对比 Harness 时

- 看 raw baseline 的成功率
- 算"相对增益"：(harness_X - raw) / raw
- 看 token 比：harness_X 用了 raw 几倍的 token？
- **给用户的关键问题**：harness_X 的增益是否值得它多花的 token？通常 < 3% 增益但 > 2x token 是不值得的。

### 对比 Environment 时

- 看 LLM 在不同 env 上的成功率方差
- 方差大 → 泛化差
- **给用户的关键问题**：你最终上线场景跟测试 env 哪个最像？以那个为准。

## 输出：对比矩阵 + 一段话结论

最后一定要给用户一段**结论性的话**，而不是堆数字：

```
对比结论:

最优组合是 (model_X, harness_Y, env_Z)，成功率 A%，平均 B tokens。

LLM 维度：model_X 在准确性上领先 model_W 约 C 个百分点，但 token 用量低 D%，性价比最高。
Harness 维度：react 相对 raw 的增益仅 E%，但 token 增加 F 倍 — 不建议为这点收益换 harness。
失败模式：跨所有组合，共同的薄弱点是 <field_X 字段>，建议针对性优化 prompt 或扩数据。

下一步：
  - 把 model_X + raw 放到生产环境
  - 针对 field_X 收集 100 条反例做 in-context examples
  - 不必继续投入 react / function_call 的工程化
```
