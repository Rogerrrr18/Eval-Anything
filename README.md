<div align="center">

# Eval-Anything

---

### The Agent-Driven Evaluation Engine for<br/>**LLM** × **Harness** × **Environment** Matrix Benchmarking

<p>

![version](https://img.shields.io/badge/version-0.1.0-2188ff?style=for-the-badge)
![python](https://img.shields.io/badge/python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![license](https://img.shields.io/github/license/Rogerrrr18/Eval-Anything?style=for-the-badge&color=informational)
![driven by](https://img.shields.io/badge/driven_by-any_coding_agent-7e57c2?style=for-the-badge)
![stars](https://img.shields.io/github/stars/Rogerrrr18/Eval-Anything?style=for-the-badge&logo=github&color=yellow)

</p>

### Repo: **[github.com/Rogerrrr18/Eval-Anything](https://github.com/Rogerrrr18/Eval-Anything)**

[English](#english) · [中文](#中文) · [Star History](#star-history) · [Skill](skills/eval-anything/SKILL.md)

<sub>One pipeline. Any coding agent (Claude Code · Cursor · Codex · Gemini CLI · …) drives it.<br/>Plug in your LLM via OpenAI-compatible endpoint — vLLM, SGLang, Ollama, DeepSeek, Qwen, Kimi, GLM.</sub>

</div>

---

## English

`skills/eval-anything/` is a self-contained agent skill: decision trees,
auto-selection algorithm, templates, and a 4-gate human-in-the-loop
protocol. Feed it to any coding agent (Claude Code, Cursor Agent, …) and
the agent will drive a full evaluation for you using its own native
`Read` / `Write` / `Edit` / `Bash` tools.

### 1. Install

```bash
# pipx (isolated, recommended)
pipx install "git+https://github.com/Rogerrrr18/Eval-Anything.git"

# or from source for development
git clone https://github.com/Rogerrrr18/Eval-Anything.git
cd Eval-Anything
pip install -e .
```

### 2. Drive it with a coding agent

#### With Claude Code

Open a Claude Code session at the repo root and say:

> "Read `skills/eval-anything/SKILL.md` as your system prompt. I want
> to run an eval / compare these models / add a new LLM / ..."

The agent routes to the matching workflow in `skills/eval-anything/workflows/`
and enforces 4 human-confirmation gates along the way.

#### With any other coding agent

Anything that can read files and run a shell works. Tell it:

> "Read `skills/eval-anything/SKILL.md` and follow the workflow it
> prescribes to design / run / interpret an evaluation. Ask me directly
> at every human-confirmation gate."

### 3. The skill, at a glance

```
skills/eval-anything/
├─ SKILL.md                          ← Entry point: routing + gate protocol
├─ references/                       ← Ground truth — the agent MUST Read these
│  ├─ cli.md                         CLI flag reference (used internally by the agent)
│  ├─ configs.md                     Schema for the 4 YAML config kinds
│  ├─ datasets.md                    Task type → open-source dataset map
│  ├─ reports.md                     How to read evaluation outputs
│  ├─ extending.md                   How to register new LLM / Harness / Env
│  └─ harness-selection.md           Harness auto-selection algorithm
├─ workflows/                        ← Step-by-step playbooks
│  ├─ design-experiment.md           Main flow: 5 steps × 4 gates
│  ├─ add-llm.md
│  ├─ add-harness.md
│  ├─ compare-models.md
│  └─ mock-dataset.md
└─ templates/                        ← Jinja templates the agent fills in via Write
   ├─ dataset.jsonl.j2
   ├─ environment.yaml.j2
   ├─ experiment.yaml.j2
   └─ mock_synthesis_prompt.md
```

### 4. Main flow: 5 steps × 4 mandatory gates

```
Step 1: Identify task type        ──► Gate 1 (confirm task type + eval dims)
Step 2: Pick dataset source       ──► Gate 2 (open-source / mock / yours / mix)
                                     └─ Mock branch ──► Gate 2b (review 3 samples)
Step 3: Auto-select harness +     ──► Gate 3 (review YAML diff, then write)
        generate config YAML
Step 4: Dry-run shows combos +    ──► Gate 4 (start the full run?)
        ETA
Step 5: Run + read report + write insight summary
```

The agent does **not** ask "do you want raw or react?" — Step 3 runs
the algorithm in `references/harness-selection.md` automatically and
shows its reasoning in Gate 3.

### 5. Architecture

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  LLM layer  │   │Harness layer│   │   Env layer │
│  (backend)  │   │(agent arch) │   │   (task)    │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       └──────────┬──────┴──────────┬──────┘
                  ▼                 ▼
           ┌────────────┐    ┌──────────────┐
           │Orchestrator│    │Metrics engine│
           └──────┬─────┘    └──────┬───────┘
                  ▼                 ▼
         ┌──────────────────────────────┐
         │  Reports                     │
         │  Excel | HTML | JSONL | MD   │
         └──────────────────────────────┘
```

| Layer | Description | Built-in |
|----|------|--------|
| **LLM** | Model backend | `OpenAICompatibleLLM` (any OpenAI-compatible API: vLLM / SGLang / Ollama / DeepSeek / Qwen / Kimi / GLM …), `MockLLM` |
| **Harness** | Agent architecture | `RawHarness` (baseline), `ReActHarness`, `FunctionCallHarness` |
| **Environment** | Task environment | `DialogEnvironment` (slot filling / JSONL datasets), extensible |

### 6. Config reference

All config lives under `--config-dir` (default `./configs/`). The agent
will read and write these files for you; the schemas are documented in
`skills/eval-anything/references/configs.md`.

```yaml
# configs/llm_profiles.yaml
llm_profiles:
  my_model:
    class: "OpenAICompatibleLLM"
    model_name: "my-model"
    endpoint_url: "http://your-host:port/v1/chat/completions"
    api_key_env: "MY_MODEL_API_KEY"   # read from env var
    # or:  api_key: "${MY_MODEL_API_KEY}"   # inline placeholder
    temperature: 0.0
    max_tokens: 600
```

> **Never** write real API keys into YAML. Use `api_key_env` or `${VAR}`.

### 7. LLM-as-Judge

```yaml
# configs/judge_profiles.yaml
judge_profiles:
  default_judge:
    class: "OpenAICompatibleLLM"
    model_name: "your-judge-model"
    endpoint_url: "https://your-endpoint/v1/chat/completions"
    api_key_env: "JUDGE_API_KEY"
    threshold: 0.6
    rubric: |
      Evaluate the model output against the reference. Return JSON only.
```

```python
from src.core.config import ConfigLoader
from src.metrics import LLMJudgeEvaluator

loader = ConfigLoader("configs")
profile = loader.get_judge_profile("default_judge")
judge = LLMJudgeEvaluator.from_profile(profile)
result = await judge.evaluate_async(prediction, reference, task=task_prompt)
```

Judge response JSON: `score`, `passed`, `labels`, `comment`, `evidence`, `dimensions`.

### 8. Reports

| Report | Format | Content |
|------|------|------|
| Detail | Excel | Per-row results, field-level diff, errors highlighted |
| Summary | Excel | Per-combo success rate and mean score |
| Comparison | Excel | LLM × Harness success-rate heatmap |
| Dashboard | HTML | Visual dashboard (heatmap + field analysis) |
| Trajectories | JSONL | Full per-step execution log |
| Case studies | Markdown | Failure clustering + representative cases |

### 9. Extending

- **New LLM** → subclass `BaseLLM` in `src/llm/`, then add a profile in `configs/llm_profiles.yaml`
- **New Harness** → subclass `BaseHarness` in `src/harness/`, register in `_HARNESS_REGISTRY`, add a profile
- **New Environment** → subclass `BaseEnvironment` in `src/environment/`, register in `_ENV_REGISTRY`, add a profile

Full steps in `skills/eval-anything/references/extending.md`.

---

## 中文

`skills/eval-anything/` 是一份**自包含的 agent skill**：决策树、自动选择算法、模板、4 道人工闸门规约全在里面。把它喂给任意 coding agent（Claude Code、Cursor Agent 等），agent 用自己原生的 `Read` / `Write` / `Edit` / `Bash` 工具就能驱动你跑完整轮评测。

### 1. 安装

```bash
# pipx 隔离（推荐）
pipx install "git+https://github.com/Rogerrrr18/Eval-Anything.git"

# 或源码开发模式
git clone https://github.com/Rogerrrr18/Eval-Anything.git
cd Eval-Anything
pip install -e .
```

### 2. 让 coding agent 驱动评测

#### Claude Code

在仓库根目录起一个 Claude Code 会话，告诉它：

> "把 `skills/eval-anything/SKILL.md` 当作 system prompt 读进来。我想跑一个评测 / 对比这些模型 / 接入新 LLM / …"

它会按 SKILL.md 入口路由分发到对应 workflow，并强制走 4 道闸门让你确认。

#### 其他 coding agent

任何能读文件 + 跑 shell 的 agent 都行。告诉它：

> "Read `skills/eval-anything/SKILL.md`，按里面规定的流程帮我设计/运行/解读评测。所有人工确认环节直接向我提问。"

### 3. Skill 内部结构

```
skills/eval-anything/
├─ SKILL.md                          ← 入口路由（决策树 + 闸门规约）
├─ references/                       ← Ground truth，agent 必须 Read 后再下笔
│  ├─ cli.md                         CLI 参数手册（agent 内部调用用）
│  ├─ configs.md                     4 类 YAML 的字段 schema
│  ├─ datasets.md                    任务类型 → 开源测试集映射
│  ├─ reports.md                     报告产物解读
│  ├─ extending.md                   新增 LLM / Harness / Env 注册步骤
│  └─ harness-selection.md           Harness 自动选择算法
├─ workflows/                        ← 流程剧本
│  ├─ design-experiment.md           主流程：5 步 4 闸门
│  ├─ add-llm.md
│  ├─ add-harness.md
│  ├─ compare-models.md
│  └─ mock-dataset.md
└─ templates/                        ← Jinja 模板，agent 用 Write 工具落盘
   ├─ dataset.jsonl.j2
   ├─ environment.yaml.j2
   ├─ experiment.yaml.j2
   └─ mock_synthesis_prompt.md
```

### 4. 主流程：5 步 4 强制闸门

```
Step 1: 任务类型识别        ──► 闸门 1（确认任务类型 + 评测维度）
Step 2: 数据集来源选择      ──► 闸门 2（开源 / Mock / 自有 / 混合）
                              └─ Mock 分支 ──► 闸门 2b（审核 3 条样例）
Step 3: 自动选 harness +    ──► 闸门 3（看 YAML diff 后确认写盘）
        生成配置 YAML
Step 4: --dry-run 展示组合数 + 预估耗时
                              ──► 闸门 4（开跑确认）
Step 5: 跑完读报告 + 输出洞察小结
```

Step 3 不会问 "你要 raw 还是 react"——agent 按 `references/harness-selection.md` 内嵌算法**自动算**，只在闸门 3 的 diff 里展示决策依据让用户拍板。

### 5. 架构

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  LLM 层     │   │ Harness 层  │   │Environment层 │
│ (可替换后端) │   │ (可替换架构) │   │ (可替换环境) │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       └──────────┬──────┴──────────┬──────┘
                  ▼                 ▼
           ┌────────────┐    ┌──────────────┐
           │Orchestrator│    │ Metrics 引擎 │
           └──────┬─────┘    └──────┬───────┘
                  ▼                 ▼
         ┌──────────────────────────────┐
         │  报告生成                    │
         │  Excel | HTML | JSONL | MD   │
         └──────────────────────────────┘
```

| 层 | 说明 | 已实现 |
|----|------|--------|
| **LLM** | 大模型后端 | `OpenAICompatibleLLM`（任何 OpenAI 兼容 API：vLLM / SGLang / Ollama / DeepSeek / Qwen / Kimi / GLM …）、`MockLLM` |
| **Harness** | Agent 架构 | `RawHarness` (baseline)、`ReActHarness`、`FunctionCallHarness` |
| **Environment** | 任务环境 | `DialogEnvironment`（槽位填充 / JSONL 数据集），可扩展 |

### 6. 配置说明

所有配置都在 `--config-dir` 指向的目录里（默认 `./configs/`），agent 会替你读写它们；字段 schema 见 `skills/eval-anything/references/configs.md`。

```yaml
# configs/llm_profiles.yaml
llm_profiles:
  my_model:
    class: "OpenAICompatibleLLM"
    model_name: "my-model"
    endpoint_url: "http://your-host:port/v1/chat/completions"
    api_key_env: "MY_MODEL_API_KEY"   # 推荐：从环境变量读
    # 或：api_key: "${MY_MODEL_API_KEY}"   # 也支持 ${VAR} 内联占位
    temperature: 0.0
    max_tokens: 600
```

> **绝不要**把真实 key 写进 yaml。用 `api_key_env` 或 `${VAR}` 占位。

### 7. LLM-as-Judge

```yaml
# configs/judge_profiles.yaml
judge_profiles:
  default_judge:
    class: "OpenAICompatibleLLM"
    model_name: "your-judge-model"
    endpoint_url: "https://your-endpoint/v1/chat/completions"
    api_key_env: "JUDGE_API_KEY"
    threshold: 0.6
    rubric: |
      请根据任务、参考答案和模型输出进行评审，只输出合法 JSON。
```

```python
from src.core.config import ConfigLoader
from src.metrics import LLMJudgeEvaluator

loader = ConfigLoader("configs")
profile = loader.get_judge_profile("default_judge")
judge = LLMJudgeEvaluator.from_profile(profile)
result = await judge.evaluate_async(prediction, reference, task=task_prompt)
```

Judge 返回 JSON：`score`、`passed`、`labels`、`comment`、`evidence`、`dimensions`。

### 8. 输出报告

| 报告 | 格式 | 内容 |
|------|------|------|
| 详细结果 | Excel | 逐条结果、字段对比、黄色标错 |
| 统计汇总 | Excel | 每个组合的成功率、平均得分 |
| 模型对比 | Excel | LLM × Harness 成功率热力图 |
| 仪表盘 | HTML | 可视化看板（热力图、字段级分析） |
| 轨迹日志 | JSONL | 完整执行步骤记录 |
| 案例研究 | Markdown | 失败分类、代表性案例、分析洞察 |

### 9. 扩展

- **新 LLM** → `src/llm/` 下继承 `BaseLLM`，再到 `configs/llm_profiles.yaml` 加 profile
- **新 Harness** → `src/harness/` 下继承 `BaseHarness`，注册到 `_HARNESS_REGISTRY`，加 profile
- **新 Environment** → `src/environment/` 下继承 `BaseEnvironment`，注册到 `_ENV_REGISTRY`，加 profile

完整步骤见 `skills/eval-anything/references/extending.md`。

---

## Star History

<div align="center">

<a href="https://www.star-history.com/#Rogerrrr18/Eval-Anything&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=Rogerrrr18/Eval-Anything&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=Rogerrrr18/Eval-Anything&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=Rogerrrr18/Eval-Anything&type=Date" width="720" />
 </picture>
</a>

</div>
