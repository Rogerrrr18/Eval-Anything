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
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  LLM layer  │   │ Target layer│   │Harness layer│   │   Env layer │
│  (backend)  │   │ (app/API)   │   │(agent arch) │   │   (task)    │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       └─────────────────┴──────────┬──────┴─────────────────┘
                                    ▼
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
| **Target** | System under evaluation | `HTTPAppTarget` (apps/APIs such as RAG systems), `MockTarget` |
| **Harness** | Agent architecture | `RawHarness` (baseline), `ReActHarness`, `FunctionCallHarness`, `DirectHarness` |
| **Environment** | Task environment | `DialogEnvironment` (slot filling), `RAGQAEnvironment` (app-level RAG QA), `WorkspaceEnvironment` (AlphaEval-style task directories), extensible |

`Environment` is the task world, not just a prompt template. For LLM-only
benchmarks it can talk to a harness/LLM; for app-level benchmarks it can call a
`Target` directly. This is how you evaluate projects such as a RAG assistant
without pretending the whole app is an LLM.

For agent/product benchmarks, prefer **self-contained task directories**:

```
tasks/my_suite/my_task/
├─ task.yaml
├─ query.md
├─ files/
└─ .eval/
   └─ rubric.py
```

This mirrors AlphaEval's environment model: the task directory itself carries
the prompt, visible files, hidden evaluation assets, and scoring logic.

**Bring your own Target.** Need to evaluate a CLI tool, a Python library, a
stdio agent, or an MCP server? Subclass `BaseTarget` and register it — the
extension point is ~10 lines:

```python
from src.target import BaseTarget, TargetResponse, register_target

class MyCLITarget(BaseTarget):
    capabilities = ["run"]                           # what operations you handle

    async def invoke(self, operation, payload, *, task=None):
        # call your tool however you want; never raise — wrap failures
        # into TargetResponse(error=...) so the eval pipeline keeps going.
        result = await do_my_thing(**payload)
        return TargetResponse(content=result)

register_target("MyCLITarget", MyCLITarget)
```

After that, any environment can point at it via YAML (`class: MyCLITarget`).
`eval-anything --list-targets` shows everything currently registered. We
deliberately ship only HTTPAppTarget + MockTarget out of the box — every other
target shape needs a paired Environment that knows how to call it, so we let
you write that pair together instead of half-supplying it.

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

For app-level evaluation, define the application in `configs/targets.yaml` and
reference it from an environment:

```yaml
# configs/targets.yaml
targets:
  openfiles_local:
    class: "HTTPAppTarget"
    base_url: "${OPENFILES_BASE_URL:-http://localhost:8000}"
    endpoints:
      chat: "/api/v1/chat"

# configs/environments.yaml
environments:
  openfiles_rag_qa:
    class: "RAGQAEnvironment"
    dataset: "tasks/openfiles_rag_qa/dataset.jsonl"
    target: "openfiles_local"
```

### 7. LLM-as-Judge

Two modes — both wired into the orchestrator. Set `judge` or `judge_panel` on an environment in `configs/environments.yaml` and the orchestrator runs the judge after each task.

**Single judge** (cheaper, biased toward one model's preferences):

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

**Judge panel (PoLL — Panel of LLM Judges)** — *recommended*. N cross-family judges score independently, then aggregate. Eliminates self-preference and cognitive lock-in that a single judge silently introduces. Cross-family is mandatory: three GPT-4 variants voting ≠ a panel.

`configs/judge_profiles.yaml` ships a **15-judge catalog** spanning OpenAI · Anthropic · Qwen · DeepSeek · Zhipu GLM · Moonshot Kimi · Google Gemini · local vLLM. Pick any cross-family triple to compose a panel; or use one of the four built-in presets:

| Preset | Composition | Cost vs default | When |
|---|---|---|---|
| `default_panel` | gpt-4o + claude-sonnet-4 + qwen-max | 1× | Most cases |
| `budget_panel` | gpt-4o-mini + claude-haiku + qwen-plus | ~0.1–0.2× | Bulk runs, CI |
| `frontier_panel` | o3-mini + claude-opus + qwen-max | ~2–3× | Releases, papers |
| `domestic_panel` | qwen-max + glm-4-plus + kimi | ~0.5× | China-only deploy |

```yaml
# configs/environments.yaml — pick any preset
environments:
  my_task:
    class: DialogEnvironment
    dataset: datasets/my_task.jsonl
    judge_panel: default_panel        # or budget_panel / frontier_panel / domestic_panel
```

**Swap judge models without editing YAML.** Every catalog entry uses `${VAR:-default}` so you can hot-swap via env vars:

```bash
# A/B-test gpt-4o-mini vs gpt-4o as the OpenAI judge, no git diff
export OPENAI_JUDGE_MODEL=gpt-4o-mini
export QWEN_JUDGE_MODEL=qwen2.5-72b-instruct
eval-anything --experiment my_exp --config-dir configs
```

Roll your own panel:

```yaml
# configs/judge_panels.yaml
judge_panels:
  my_custom_panel:
    members:                          # references judge_profiles.yaml
      - openai_judge                  # OpenAI family
      - claude_judge                  # Anthropic family
      - deepseek_judge                # DeepSeek family
    aggregation: trimmed_mean         # mean | median | trimmed_mean | majority
    disagreement_threshold: 0.3       # max-min > threshold → auto-label panel_disagree
    require_diverse_families: true    # warns if same family appears ≥ 2 times
    min_label_support: ceil_half      # a label needs ⌈N/2⌉ votes to survive
```

Aggregation rules (built-in, not magic):

| Field | Aggregation |
|---|---|
| `score` | `trimmed_mean` of N member scores (drops one high + one low at N≥3) |
| `passed` | majority vote, tie → `false` (conservative) |
| `labels` | union, filter by `min_label_support` (default ⌈N/2⌉) |
| `evidence` | union with dedup |
| `comment` | concat with `[<member>]` prefix per judge |
| `dimensions` | per-dim trimmed_mean |
| `panel_disagree` | auto-added when `max(scores) - min(scores) > disagreement_threshold` |

Cases tagged `panel_disagree` are the most valuable for human review — they expose rubric ambiguity, edge cases, or one judge being systematically off.

```python
# Library use (skips orchestrator)
from src.core.config import ConfigLoader
from src.metrics import LLMJudgeEvaluator, PanelLLMJudgeEvaluator

loader = ConfigLoader("configs")

# single
judge = LLMJudgeEvaluator.from_profile(loader.get_judge_profile("default_judge"))

# panel
panel = PanelLLMJudgeEvaluator.from_panel_profile(
    loader.get_judge_panel("default_panel"),
    loader.load_judge_profiles(),
)
result = await panel.evaluate_async(prediction, reference, task=task_prompt)
```

Each judge's raw JSON output must contain: `score`, `passed`, `labels`, `comment`, `evidence`, `dimensions`. Panel `result.details["members"]` retains every member's raw verdict so case-study reports can drill in. If a panel member errors out mid-run, the panel **degrades to N-1** instead of failing — survivors aggregate as usual, the case gets a `member_failed` label, and the error is recorded in `details.failed_members`.

**Judge calibration (optional).** How much should you trust the judge at all? Add a human-annotated `calibration_set` (JSONL with `human_score` / `human_passed` / `human_labels`) to any judged environment and the orchestrator measures judge↔human agreement after the main run — Pearson r, pass accuracy, macro-F1 — and shows the verdict as traffic-light cards in the HTML dashboard. Runs once per (env, judge) pair, no matter how many LLM combos share it:

```yaml
environments:
  my_task:
    judge_panel: default_panel
    calibration_set: datasets/calibration/my_cal.jsonl   # ← opt-in, one line
```

**Pairwise mode + Elo ranking (optional).** Absolute scores are rubric-sensitive; "which answer is better" is what humans actually judge. Set `pairwise_judge` at the experiment level (needs ≥ 2 LLM profiles) and every pair of model outputs gets compared head-to-head — with position-swap to cancel order bias — then aggregated into an Elo leaderboard and a win matrix in the report:

```yaml
experiment:
  llm_profiles: [gpt4o, claude_sonnet, qwen_max]
  pairwise_judge: openai_judge          # ← opt-in, one line
```

### 8. Reports

| Report | Format | Content |
|------|------|------|
| Detail | Excel | Per-row results, field-level diff, errors highlighted |
| Summary | Excel | Per-combo success rate and mean score |
| Comparison | Excel | LLM × Harness success-rate heatmap |
| Dashboard | HTML | Heatmap, field analysis, judge dimension **radar charts**, Elo leaderboard + win matrix, calibration cards |
| Machine summary | JSON | `<exp>_summary.json` — single machine-readable artifact for CI / scripting |
| Trajectories | JSONL | Full per-step execution log, **streamed to disk as each task finishes** |
| Case studies | Markdown | Failure clustering + representative cases |

Crash mid-run? Results already on disk. Re-run with `--resume` to skip every task that has a recorded verdict (infra failures — `error` / `timeout` — are retried):

```bash
eval-anything --experiment my_exp --config-dir configs --resume
```

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
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  LLM 层     │   │ Target 层   │   │ Harness 层  │   │Environment层 │
│ (模型后端)   │   │ (应用/API)  │   │ (可替换架构) │   │ (任务世界)   │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       └─────────────────┴──────────┬──────┴─────────────────┘
                                    ▼
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
| **Target** | 被测系统 | `HTTPAppTarget`（RAG 应用/API 等完整系统）、`MockTarget` |
| **Harness** | Agent 架构 | `RawHarness` (baseline)、`ReActHarness`、`FunctionCallHarness`、`DirectHarness` |
| **Environment** | 任务世界 | `DialogEnvironment`（槽位填充）、`RAGQAEnvironment`（应用级 RAG QA）、`WorkspaceEnvironment`（AlphaEval-style 自包含任务目录），可扩展 |

`Environment` 不是单纯 prompt 模板，而是任务世界。LLM benchmark 可以走
Harness + LLM；应用级 benchmark 可以由 Environment 直接调用 `Target`。这样
OpenFiles 这类 RAG 助手可以被当作完整应用评测，而不是被误认为一个裸 LLM。

对 agent / 产品级 benchmark，推荐使用**自包含 task 目录**：

```
tasks/my_suite/my_task/
├─ task.yaml
├─ query.md
├─ files/
└─ .eval/
   └─ rubric.py
```

这和 AlphaEval 的环境理解一致：一个 task 目录本身携带 prompt、可见文件、
隐藏评测资产和评分逻辑。

**自带 Target.** 要评测 CLI 工具、Python 库、stdio agent、MCP 服务器？子类化
`BaseTarget` 再注册一行就行，~10 行代码：

```python
from src.target import BaseTarget, TargetResponse, register_target

class MyCLITarget(BaseTarget):
    capabilities = ["run"]                           # 声明支持哪些 operation

    async def invoke(self, operation, payload, *, task=None):
        # 怎么调你的工具都行；**不要抛异常**——失败包成
        # TargetResponse(error=...) 返回，让评测流水线继续走
        result = await do_my_thing(**payload)
        return TargetResponse(content=result)

register_target("MyCLITarget", MyCLITarget)
```

之后任何 environment 都能在 YAML 里 `class: MyCLITarget` 引用它，`eval-anything
--list-targets` 也会列出来。我们故意只内置 HTTPAppTarget + MockTarget——其他形态
（CLI / Python / stdio / MCP）都需要一个**配套的 Environment** 才能真正跑起来，
所以让你和你的 Env 一起写，比我们给你半套强。

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

评测完整应用时，在 `configs/targets.yaml` 里声明被测系统，并在 environment
里引用：

```yaml
# configs/targets.yaml
targets:
  openfiles_local:
    class: "HTTPAppTarget"
    base_url: "${OPENFILES_BASE_URL:-http://localhost:8000}"
    endpoints:
      chat: "/api/v1/chat"

# configs/environments.yaml
environments:
  openfiles_rag_qa:
    class: "RAGQAEnvironment"
    dataset: "tasks/openfiles_rag_qa/dataset.jsonl"
    target: "openfiles_local"
```

### 7. LLM-as-Judge

两种模式都已接入 orchestrator。在 `configs/environments.yaml` 给某个 env 配 `judge` 或 `judge_panel` 字段，跑完任务后会自动调裁判评分。

**单裁判**（便宜，但带入单家族系统性偏差）：

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

**Judge Panel (PoLL — Panel of LLM Judges)** — **推荐**。N 个跨家族裁判并发独立打分再聚合，抵消单裁判的 self-preference 和 cognitive lock-in。**前提是跨家族**——3 个 GPT-4 变体投票不是 panel，只是浪费 token。

`configs/judge_profiles.yaml` 自带一份 **15 个 judge 的 catalog**，覆盖 OpenAI · Anthropic · Qwen · DeepSeek · 智谱 GLM · 月之暗面 Kimi · Google Gemini · 本地 vLLM。挑任意跨家族三个组成 panel，或直接用内置四个 preset：

| Preset | 组成 | 相对成本 | 用于 |
|---|---|---|---|
| `default_panel` | gpt-4o + claude-sonnet-4 + qwen-max | 1× | 大多数场景 |
| `budget_panel` | gpt-4o-mini + claude-haiku + qwen-plus | ~0.1–0.2× | 大批量跑 / CI |
| `frontier_panel` | o3-mini + claude-opus + qwen-max | ~2–3× | 正式发布、对外报告 |
| `domestic_panel` | qwen-max + glm-4-plus + kimi | ~0.5× | 国产合规 / 不能出海 |

```yaml
# configs/environments.yaml — 挑 preset
environments:
  my_task:
    class: DialogEnvironment
    dataset: datasets/my_task.jsonl
    judge_panel: default_panel        # 或 budget_panel / frontier_panel / domestic_panel
```

**不改 YAML 就换模型。** Catalog 里每个 judge 都用 `${VAR:-default}` 写死，环境变量直接覆盖：

```bash
# 把 OpenAI 裁判从 gpt-4o 临时换成 gpt-4o-mini，git 不动
export OPENAI_JUDGE_MODEL=gpt-4o-mini
export QWEN_JUDGE_MODEL=qwen2.5-72b-instruct
eval-anything --experiment my_exp --config-dir configs
```

自己拼一个 panel：

```yaml
# configs/judge_panels.yaml
judge_panels:
  my_custom_panel:
    members:                          # 引用 judge_profiles.yaml 中的 judge 名字
      - openai_judge                  # OpenAI 家族
      - claude_judge                  # Anthropic 家族
      - deepseek_judge                # DeepSeek 家族
    aggregation: trimmed_mean         # mean | median | trimmed_mean | majority
    disagreement_threshold: 0.3       # max-min > 阈值 → 自动加 panel_disagree 标签
    require_diverse_families: true    # 同家族 ≥ 2 个时 warning
    min_label_support: ceil_half      # label 至少 ⌈N/2⌉ 票才保留
```

聚合规则（内置）：

| 字段 | 聚合 |
|---|---|
| `score` | N 个成员的 `trimmed_mean`（N≥3 时去掉最高、最低各一） |
| `passed` | 多数票，平票 → `false`（保守） |
| `labels` | union，按 `min_label_support`（默认 ⌈N/2⌉）过滤 |
| `evidence` | union 去重 |
| `comment` | 拼接，每条带 `[<成员>]` 前缀，可追溯 |
| `dimensions` | 按维度独立 trimmed_mean |
| `panel_disagree` | `max(scores) - min(scores) > disagreement_threshold` 时自动加 |

带 `panel_disagree` 的 case 是金矿——暴露 rubric 歧义、边界 case，或某个裁判系统性偏，人工 review 价值最大。

```python
# 库级用法（绕过 orchestrator）
from src.core.config import ConfigLoader
from src.metrics import LLMJudgeEvaluator, PanelLLMJudgeEvaluator

loader = ConfigLoader("configs")

# 单裁判
judge = LLMJudgeEvaluator.from_profile(loader.get_judge_profile("default_judge"))

# Panel
panel = PanelLLMJudgeEvaluator.from_panel_profile(
    loader.get_judge_panel("default_panel"),
    loader.load_judge_profiles(),
)
result = await panel.evaluate_async(prediction, reference, task=task_prompt)
```

每个裁判原始 JSON 必须包含：`score`、`passed`、`labels`、`comment`、`evidence`、`dimensions`。Panel 的 `result.details["members"]` 完整保留每个成员的原始判定，case study 报告可下钻每个裁判看了什么。Panel 成员中途挂掉**不会报废整个 panel**——剩余成员降级聚合（N-1），该条加 `member_failed` 标签，错误记录在 `details.failed_members`。

**Judge 校准（可选）。** judge 本身可不可信？给任何挂了 judge 的环境加一份人工标注的 `calibration_set`（JSONL，含 `human_score` / `human_passed` / `human_labels`），主任务跑完后自动测 judge↔人类一致性——Pearson r、pass 准确率、macro-F1——结果在 HTML 仪表盘以红绿灯卡片呈现。按 (env, judge) 只跑一次，多少个 LLM combo 共享都不重复花钱：

```yaml
environments:
  my_task:
    judge_panel: default_panel
    calibration_set: datasets/calibration/my_cal.jsonl   # ← 可选，一行接入
```

**Pairwise 对比 + Elo 排名（可选）。** 绝对分对 rubric 措辞敏感；人类真正擅长的判断是"哪个回答更好"。在 experiment 级配 `pairwise_judge`（要求 ≥ 2 个 LLM profile），所有模型输出两两对比——自动 A/B 换位消除位置偏差——聚合成 Elo 排行榜 + win 矩阵进报告：

```yaml
experiment:
  llm_profiles: [gpt4o, claude_sonnet, qwen_max]
  pairwise_judge: openai_judge          # ← 可选，一行接入
```

### 8. 输出报告

| 报告 | 格式 | 内容 |
|------|------|------|
| 详细结果 | Excel | 逐条结果、字段对比、黄色标错 |
| 统计汇总 | Excel | 每个组合的成功率、平均得分 |
| 模型对比 | Excel | LLM × Harness 成功率热力图 |
| 仪表盘 | HTML | 热力图、字段级分析、judge 维度**雷达图**、Elo 排行榜 + win 矩阵、校准卡片 |
| 机读汇总 | JSON | `<exp>_summary.json` —— CI / 脚本集成的单一机读出口 |
| 轨迹日志 | JSONL | 完整执行步骤记录，**每条任务完成即落盘** |
| 案例研究 | Markdown | 失败分类、代表性案例、分析洞察 |

中途崩溃？已完成的结果都在盘上。加 `--resume` 重跑会跳过所有已有评测结论的任务（`error` / `timeout` 这类基础设施故障会重试）：

```bash
eval-anything --experiment my_exp --config-dir configs --resume
```

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
