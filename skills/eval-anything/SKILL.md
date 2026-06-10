# Eval-Anything Agent Skill

本文档是 [Eval-Anything](https://github.com/Rogerrrr18/Eval-Anything) 的 **agent skill**，面向任意 coding agent（Claude Code、Cursor Agent 等）。沉淀了 LLM × Harness × Environment 三维评测的全部领域知识：决策树、自动选择算法、模板、4 道人工闸门规约。

> **你（coding agent）的工作方式**：用你自己原生的工具完成所有操作——`Read` 读文件、`Write`/`Edit` 写 YAML、`Bash` 跑 CLI、直接向用户提问做人工确认。**禁止猜配置字段，禁止跳过闸门。**

## 何时启动本流程

用户在 chat 里表达"评测 / 对比 / 跑 eval / 分析 agent 表现 / 加模型 profile / 加 harness"等意图时，立即进入本流程。所有事实以 `references/` 为准，凭印象回答 = 错。

## 入口：先识别用户意图

| 用户说 | 进入哪个 workflow |
|---|---|
| 我想设计一个新评测 / 跑一遍我的任务 / 对比这些模型在 X 任务上的表现 | `workflows/design-experiment.md`（**主流程**） |
| 加一个新 LLM profile / 接入新模型 / 把 GPT-4 接进来 | `workflows/add-llm.md` |
| 加一个新 harness / 写新 agent 架构 | `workflows/add-harness.md` |
| 横向对比模型 / 横向对比 harness | `workflows/compare-models.md` |
| 我的任务没有现成数据集 / 帮我合成测试集 | `workflows/mock-dataset.md` |
| 我想看跑完的报告怎么读 / 解读 outputs/ 里的文件 | 直接读 `references/reports.md` 后回答 |
| eval-agent 这个 CLI 有哪些参数 | 直接读 `references/cli.md` 后回答 |

不要凭印象回答 CLI 参数或 YAML 字段——先用 `Read` 工具读对应 reference 文档。

## 主流程总览（5 步 4 强制闸门）

`workflows/design-experiment.md` 是主入口，结构如下：

```
Step 1: 任务类型识别  ──► 闸门 1（多选确认）确认任务类型 + 评测维度
Step 2: 数据集来源选择 ──► 闸门 2（多选确认）选 开源 / Mock / 自有 / 混合
                          └─ Mock 分支：先生成 3 条样例 ──► 闸门 2b 用户审核样例
Step 3: 生成 env + experiment + (可选) llm/harness/judge YAML
                          ──► 闸门 3（多选确认）展示 diff 让用户确认
Step 4: --dry-run 展示组合数和预计耗时
                          ──► 闸门 4（多选确认）正式开跑确认
Step 5: 跑完读报告 + 总结洞察
```

**严格闸门模式**：4 道闸门全部向用户提多选确认，不提供 fast-skip。每一步用户确认前不得擅自写盘、改配置、起任务。

## 三层组件的 ground truth（一定要读对应文档再下笔）

- **LLM 注册表**：`OpenAICompatibleLLM`、`HttpxLLM`（复用前者）、`MockLLM`。详见 `references/configs.md` 的 LLM 章节。
- **Harness 注册表**：`RawHarness`（baseline，max_steps=1）、`ReActHarness`（regex 解析 Thought/Action 格式）、`FunctionCallHarness`（用 LLM 原生 tool_calls，默认带 `submit_answer`/`request_info`）。详见 `references/configs.md` 的 Harness 章节。
- **Environment 注册表**：目前**只有** `DialogEnvironment`（JSON 槽位抽取，逐字段对比）。其他任务类型需要先按 `workflows/add-harness.md` 同类思路新建 env 类。详见 `references/configs.md` 的 Environment 章节。
- **数据集来源映射**（任务类型 → 开源候选）：见 `references/datasets.md`。
- **CLI 参数全集**：见 `references/cli.md`。
- **报告产物结构**：见 `references/reports.md`。

## Harness 自动选择（不问用户，自动算）

**Harness 维度的选择对用户是隐藏的工程细节**——用户不应该被问"你要 raw 还是 react"。在 Step 1（任务类型确认）通过后，必须按 `references/harness-selection.md` 的算法**自动**计算：

1. 该跑哪些 harness（默认包含 `raw` 基线 + 按 task_type 推荐 + 按用户评测维度补充）
2. 每个 harness 的 `max_steps`（按 task_type × harness 二维矩阵决定）
3. 哪些 (LLM, harness) 组合不兼容、自动剔除（含理由）
4. 哪些情况下复用现有 harness profile，哪些情况下要新建 profile

算出来的结果**不单独问用户确认**，而是作为闸门 3（配置 diff 确认）的一部分一次性展示。

### 唯一例外：用户主动指定

如果用户在描述里明确说"只用 raw"、"只跑 react"、"加一个 function_call 试试"等，**用户优先级最高**——算法跑出来跟用户说法冲突时，遵循用户。

### 关键不可变约束

- **永远包含 `raw` 作为对照基线**——任何 harness 不能比 raw 显著强就没意义
- **永远不剔除"用户明确要求保留"的组合**
- **不修改现有 harness profile 的字段**，需要新超参就追加新 profile（命名 `<harness>_<task_type>`）
- **不自动改 system_prompt 内容**——只动 max_steps

### 给用户看的"reasoning 段"

闸门 3 的 diff 之前，必须先用一段话告诉用户"我为什么这样选 harness"，参考 `references/harness-selection.md` Step 6 的模板。让用户知道这不是黑盒决策，而是有可推翻的依据。

### 详细算法

→ 见 `references/harness-selection.md`。**实际选择 harness 时必须读这份文档**，不要凭印象。

## 安全护栏（不可绕过）

1. **绝不跳 dry-run**：Step 4 必须先跑 `--dry-run`，把组合数和预计耗时摆给用户。
2. **绝不一上来跑全量**：默认先在小数据集（5-10 条）上验证流程跑通，再跑全量。
3. **绝不污染主配置**：新增 profile 时如果用户没明确说"覆盖现有的"，就追加新条目而不是改旧条目。
4. **绝不替用户填写真实 API key**：endpoint_url 可以代填，api_key 应留 `EMPTY` 或 `${ENV_VAR}` 并提示用户自己设。
5. **Mock 合成器选择闸门**：mock 数据走 `workflows/mock-dataset.md`，必须让用户从已有 `llm_profiles` 里选一个当 synthesizer，不要默认替用户选。

## 输出收尾

跑完后必须做的事：
1. 读 `outputs/<exp>/reports/` 下的 HTML 仪表盘和 case_studies 的 markdown
2. 给用户写一段**洞察小结**：
   - 哪个 (LLM, Harness, Env) 组合赢了，赢多少
   - 主要失败模式是什么
   - 下一步建议（换模型？调 prompt？换 harness？扩数据？）
3. 提示用户 `outputs/<exp>/trajectories/` 下有完整逐步轨迹，可用于深入 debug

## 文件索引

```
skills/eval-anything/
├─ SKILL.md                          ← 你在读的文件
├─ references/
│  ├─ cli.md                         CLI 参数手册
│  ├─ configs.md                     4 类 YAML 的字段 schema
│  ├─ datasets.md                    任务类型 → 开源测试集映射
│  ├─ reports.md                     报告产物解读
│  ├─ extending.md                   新增 LLM / Harness / Env 的注册步骤
│  └─ harness-selection.md           Harness 自动选择算法（Step 3 必读）
├─ workflows/
│  ├─ design-experiment.md           主流程（5 步 4 闸门）
│  ├─ add-llm.md                     接入新模型 profile
│  ├─ add-harness.md                 注册新 harness 类
│  ├─ compare-models.md              横向对比矩阵
│  └─ mock-dataset.md                合成测试集子流程
└─ templates/
   ├─ dataset.jsonl.j2               单条 JSONL task 模板
   ├─ environment.yaml.j2            environments.yaml 新条目模板
   ├─ experiment.yaml.j2             experiments/*.yaml 模板
   └─ mock_synthesis_prompt.md       Mock synthesizer 用的固定 prompt
```
