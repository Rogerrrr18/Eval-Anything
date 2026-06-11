<div align="center">

# Eval-Anything

---

### The Agent-Driven Evaluation Engine<br/>**LLM** × **Harness** × **Environment** matrix benchmarking, with cross-family judge panels.

<p>

![version](https://img.shields.io/badge/version-0.1.0-2188ff?style=for-the-badge)
![python](https://img.shields.io/badge/python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![license](https://img.shields.io/github/license/Rogerrrr18/Eval-Anything?style=for-the-badge&color=informational)
![driven by](https://img.shields.io/badge/driven_by-any_coding_agent-7e57c2?style=for-the-badge)
![stars](https://img.shields.io/github/stars/Rogerrrr18/Eval-Anything?style=for-the-badge&logo=github&color=yellow)

</p>

### Repo: **[github.com/Rogerrrr18/Eval-Anything](https://github.com/Rogerrrr18/Eval-Anything)**

[English](#english) · [中文](#中文) · [Star History](#star-history) · [Skill](skills/eval-anything/SKILL.md)

<sub>One pipeline. Any coding agent drives it — Claude Code · Cursor · Codex · Gemini CLI · …<br/>Plug in any OpenAI-compatible endpoint — vLLM · SGLang · Ollama · DeepSeek · Qwen · Kimi · GLM.</sub>

</div>

---

## English

`skills/eval-anything/` is a self-contained agent skill — decision trees,
auto-selection algorithms, templates, and a 4-gate human-in-the-loop
protocol. Drop it into any coding agent (Claude Code · Cursor · Codex · …)
and the agent drives a full evaluation end-to-end through its native
`Read` / `Write` / `Edit` / `Bash` tools.

### 1. Install

```bash
# pipx (isolated, recommended)
pipx install "git+https://github.com/Rogerrrr18/Eval-Anything.git"

# or from source, for development
git clone https://github.com/Rogerrrr18/Eval-Anything.git
cd Eval-Anything
pip install -e .
```

### 2. Drive it with a coding agent

**Claude Code** — open a session at the repo root and say:

> "Read `skills/eval-anything/SKILL.md` as your system prompt.
> I want to run an eval / compare these models / add a new LLM / ..."

**Any other coding agent** — anything that can read files and run a shell:

> "Read `skills/eval-anything/SKILL.md` and follow its workflow to
> design / run / interpret an evaluation. Ask me at every human-confirmation gate."

The agent routes your request into a matching workflow under
`skills/eval-anything/workflows/` and stops at 4 confirmation gates along the way.

### 3. The skill, at a glance

```
skills/eval-anything/
├─ SKILL.md                       ← Entry point: routing + gate protocol
│
├─ references/                    ← Ground truth — the agent MUST Read these
│  ├─ cli.md                      CLI flag reference
│  ├─ configs.md                  Schema for the 4 kinds of YAML config
│  ├─ datasets.md                 Task type → open-source dataset map
│  ├─ reports.md                  How to read the generated outputs
│  ├─ extending.md                Registering a new LLM / Harness / Env
│  └─ harness-selection.md        Harness auto-selection algorithm
│
├─ workflows/                     ← Step-by-step playbooks
│  ├─ design-experiment.md        Main flow: 5 steps × 4 gates
│  ├─ add-llm.md
│  ├─ add-harness.md
│  ├─ compare-models.md
│  └─ mock-dataset.md
│
└─ templates/                     ← Jinja templates, filled in via Write
   ├─ dataset.jsonl.j2
   ├─ environment.yaml.j2
   ├─ experiment.yaml.j2
   └─ mock_synthesis_prompt.md
```

### 4. Main flow: 5 steps × 4 mandatory gates

```
  ①  Identify task type        ──▶  Gate 1   confirm type + eval dimensions
  ②  Pick dataset source       ──▶  Gate 2   open-source · mock · yours · mix
       └─ if Mock branch       ──▶  Gate 2b  review 3 generated samples
  ③  Auto-select harness       ──▶  Gate 3   review YAML diff, then write
       + generate config YAML
  ④  Dry-run shows combos      ──▶  Gate 4   confirm to start the full run
       + ETA estimate
  ⑤  Run · read report · write insight summary
```

The agent never asks *"raw or react?"* — Step 3 runs the algorithm in
`references/harness-selection.md` automatically and surfaces its reasoning
at Gate 3 for you to approve.

### 5. Architecture

```
   ╭─────────────╮  ╭─────────────╮  ╭─────────────╮  ╭─────────────╮
   │     LLM     │  │   Target    │  │   Harness   │  │ Environment │
   │   backend   │  │   app/API   │  │ agent arch  │  │ task world  │
   ╰──────┬──────╯  ╰──────┬──────╯  ╰──────┬──────╯  ╰──────┬──────╯
          └────────────────┴────────┬───────┴────────────────┘
                                    ▼
                       ╭─────────────────────╮
                       │    Orchestrator     │
                       │  ◆ Metrics  ◆ Judge │
                       ╰──────────┬──────────╯
                                  ▼
            ╭───────────────────────────────────────────╮
            │  📊 Reports                               │
            │  Excel · HTML · JSONL · Markdown · JSON   │
            ╰───────────────────────────────────────────╯
```

| Layer | Role | Built-in |
|----|------|--------|
| **LLM** | Model backend | `OpenAICompatibleLLM` (any OpenAI-compatible API: vLLM · SGLang · Ollama · DeepSeek · Qwen · Kimi · GLM …) · `MockLLM` |
| **Target** | System under evaluation | `HTTPAppTarget` (REST / RAG apps) · `MockTarget` |
| **Harness** | Agent strategy | `RawHarness` · `ReActHarness` · `FunctionCallHarness` · `DirectHarness` |
| **Environment** | Task world | `DialogEnvironment` (slot filling) · `RAGQAEnvironment` (app-level QA) · `WorkspaceEnvironment` (self-contained task dirs), extensible |

`Environment` is the task world, not just a prompt template. For LLM-only
benchmarks it talks to a harness + LLM; for app-level benchmarks it can
call a `Target` directly — so a RAG assistant gets evaluated as a whole
application, not as if it were a bare LLM.

For agent and product benchmarks, prefer **self-contained task directories**:

```
tasks/my_suite/my_task/         ← one self-contained task
├─ task.yaml                    ← type · evaluation kind · metadata
├─ query.md                     ← prompt visible to the agent
├─ files/                       ← input files the agent can see
└─ .eval/                       ← hidden evaluation assets
   └─ rubric.py                 ← scoring script
```

**Bring your own Target.** Evaluating a CLI tool, a Python library, a
stdio agent, or an MCP server? Subclass `BaseTarget` and register it —
the extension point is ~10 lines:

```python
from src.target import BaseTarget, TargetResponse, register_target

class MyCLITarget(BaseTarget):
    capabilities = ["run"]                           # operations you support

    async def invoke(self, operation, payload, *, task=None):
        # Call your tool however you like; never raise — wrap failures
        # as TargetResponse(error=...) so the pipeline keeps going.
        result = await do_my_thing(**payload)
        return TargetResponse(content=result)

register_target("MyCLITarget", MyCLITarget)
```

Any environment can then reference it from YAML (`class: MyCLITarget`),
and `eval-anything --list-targets` will show it. We ship only
`HTTPAppTarget` + `MockTarget` out of the box on purpose — every other
target shape needs a paired Environment to drive it, so you write the
pair together rather than receive half a feature.

### 6. Config reference

All config lives under `--config-dir` (default `./configs/`). The agent
reads and writes these for you — full schemas in
`skills/eval-anything/references/configs.md`.

```yaml
# configs/llm_profiles.yaml
llm_profiles:
  my_model:
    class: "OpenAICompatibleLLM"
    model_name: "my-model"
    endpoint_url: "http://your-host:port/v1/chat/completions"
    api_key_env: "MY_MODEL_API_KEY"          # read from env var
    # or:  api_key: "${MY_MODEL_API_KEY}"    # inline placeholder
    temperature: 0.0
    max_tokens: 600
```

> ⚠️ **Never** put real API keys in YAML. Use `api_key_env` or `${VAR}`.

For app-level evaluation, declare the system under test in
`configs/targets.yaml` and reference it from an environment:

```yaml
# configs/targets.yaml
targets:
  my_rag_app:
    class: "HTTPAppTarget"
    base_url: "${RAG_BASE_URL:-http://localhost:8000}"
    endpoints:
      chat: "/api/v1/chat"

# configs/environments.yaml
environments:
  my_rag_qa:
    class: "RAGQAEnvironment"
    dataset: "tasks/my_rag_qa/dataset.jsonl"
    target: "my_rag_app"
```

### 7. LLM-as-Judge

Two modes, both wired into the orchestrator — set `judge` or `judge_panel`
on an environment and the judge runs automatically after each task.

**Single judge** — cheap, but biased toward one model's preferences:

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

**Judge Panel (PoLL — Panel of LLM Judges)** — *recommended.* N cross-family
judges score independently in parallel, then aggregate. Cancels the
self-preference and cognitive lock-in a single judge silently introduces.
Cross-family is **mandatory** — three GPT-4 variants voting is not a panel,
just a louder echo chamber.

`configs/judge_profiles.yaml` ships a **15-judge catalog** spanning
OpenAI · Anthropic · Qwen · DeepSeek · Zhipu GLM · Moonshot Kimi ·
Google Gemini · local vLLM. Pick any cross-family triple, or use one of
four built-in presets:

| Preset | Composition | Cost vs default | When to use |
|---|---|---|---|
| `default_panel`  | gpt-4o + claude-sonnet-4 + qwen-max     | 1×        | Most cases |
| `budget_panel`   | gpt-4o-mini + claude-haiku + qwen-plus  | ~0.1–0.2× | Bulk runs, CI |
| `frontier_panel` | o3-mini + claude-opus + qwen-max        | ~2–3×     | Releases, papers |
| `domestic_panel` | qwen-max + glm-4-plus + kimi            | ~0.5×     | China-only deploy |

```yaml
# configs/environments.yaml — one line to enable
environments:
  my_task:
    class: DialogEnvironment
    dataset: datasets/my_task.jsonl
    judge_panel: default_panel    # or budget_panel / frontier_panel / domestic_panel
```

**Swap judge models without touching YAML.** Every catalog entry uses
`${VAR:-default}` so you can hot-swap via env vars:

```bash
# A/B-test gpt-4o-mini vs gpt-4o as the OpenAI judge — no git diff
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

Aggregation rules — no magic, all explicit:

| Field | Aggregation |
|---|---|
| `score`         | `trimmed_mean` of N member scores (drops one high + one low at N≥3) |
| `passed`        | majority vote; tie → `false` (conservative) |
| `labels`        | union, then filtered by `min_label_support` (default ⌈N/2⌉) |
| `evidence`      | union, deduplicated |
| `comment`       | concatenated, each prefixed with `[<member>]` |
| `dimensions`    | per-dimension `trimmed_mean` |
| `panel_disagree`| auto-added when `max − min > disagreement_threshold` |

Cases tagged `panel_disagree` are gold for human review — they surface
rubric ambiguity, edge cases, or a judge that's systematically off.

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

Each judge's raw JSON must contain `score`, `passed`, `labels`, `comment`,
`evidence`, `dimensions`. The panel's `result.details["members"]` keeps
every member's raw verdict so case-study reports can drill in. If one
member errors out mid-run the panel **degrades to N-1** instead of
failing — survivors aggregate as usual, the case gets a `member_failed`
label, and the error lands in `details.failed_members`.

**Judge calibration** *(optional).* How much should you actually trust
the judge? Attach a human-annotated `calibration_set` (JSONL with
`human_score` / `human_passed` / `human_labels`) and the orchestrator
measures judge↔human agreement after the main run — Pearson r, pass
accuracy, macro-F1 — surfaced as traffic-light cards in the HTML
dashboard. Cached per `(env, judge)` so it runs only once across all
sharing combos:

```yaml
environments:
  my_task:
    judge_panel: default_panel
    calibration_set: datasets/calibration/my_cal.jsonl   # one line, opt-in
```

**Pairwise + Elo** *(optional).* Absolute scores are rubric-sensitive;
"which answer is better" is what humans actually judge. Set
`pairwise_judge` at the experiment level (≥ 2 LLM profiles required) and
every pair of outputs is compared head-to-head — with position-swap to
cancel order bias — then aggregated into an Elo leaderboard and a win
matrix:

```yaml
experiment:
  llm_profiles: [gpt4o, claude_sonnet, qwen_max]
  pairwise_judge: openai_judge          # one line, opt-in
```

### 8. Reports

| Report | Format | What's inside |
|------|------|------|
| **Detail**          | Excel    | Per-row results, field-level diff, errors highlighted |
| **Summary**         | Excel    | Per-combo success rate, mean score |
| **Comparison**      | Excel    | LLM × Harness success-rate heatmap |
| **Dashboard**       | HTML     | Heatmap, field analysis, judge dimension radar, Elo leaderboard + win matrix, calibration cards |
| **Machine summary** | JSON     | `<exp>_summary.json` — single artifact for CI / scripting |
| **Trajectories**    | JSONL    | Full per-step log, streamed to disk as each task finishes |
| **Case studies**    | Markdown | Failure clusters + representative cases |

Crashed mid-run? Results are already on disk. Re-run with `--resume` to
skip every task with a recorded verdict (infra failures — `error` /
`timeout` — are retried):

```bash
eval-anything --experiment my_exp --config-dir configs --resume
```

### 9. Extending

- **New LLM**         — subclass `BaseLLM` in `src/llm/`, add a profile in `configs/llm_profiles.yaml`
- **New Harness**     — subclass `BaseHarness` in `src/harness/`, register in `_HARNESS_REGISTRY`, add a profile
- **New Environment** — subclass `BaseEnvironment` in `src/environment/`, register in `_ENV_REGISTRY`, add a profile
- **New Target**      — subclass `BaseTarget` in `src/target/`, call `register_target(name, cls)`

Full walkthrough in `skills/eval-anything/references/extending.md`.

---

## 中文

`skills/eval-anything/` 是一份**自包含的 agent skill** —— 决策树、自动选择
算法、模板、4 道人工闸门规约一应俱全。把它喂给任意 coding agent
（Claude Code · Cursor · Codex · …），agent 用自己原生的
`Read` / `Write` / `Edit` / `Bash` 工具就能端到端驱动一整轮评测。

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

**Claude Code** —— 在仓库根目录起会话，告诉它：

> "把 `skills/eval-anything/SKILL.md` 当作 system prompt 读进来。
> 我想跑一个评测 / 对比这些模型 / 接入新 LLM / …"

**其他 coding agent** —— 任何能读文件 + 跑 shell 的都行：

> "Read `skills/eval-anything/SKILL.md`，按里面规定的流程帮我设计 / 运行 / 解读评测。
> 所有人工确认环节直接向我提问。"

Agent 会自动按 SKILL.md 入口路由分发到对应 workflow，并在 4 道闸门处停下来让你拍板。

### 3. Skill 内部结构

```
skills/eval-anything/
├─ SKILL.md                       ← 入口路由：决策树 + 闸门规约
│
├─ references/                    ← Ground truth，agent 下笔前必须 Read
│  ├─ cli.md                      CLI 参数手册
│  ├─ configs.md                  4 类 YAML 的字段 schema
│  ├─ datasets.md                 任务类型 → 开源测试集映射
│  ├─ reports.md                  报告产物解读
│  ├─ extending.md                新增 LLM / Harness / Env 注册步骤
│  └─ harness-selection.md        Harness 自动选择算法
│
├─ workflows/                     ← 流程剧本
│  ├─ design-experiment.md        主流程：5 步 4 闸门
│  ├─ add-llm.md
│  ├─ add-harness.md
│  ├─ compare-models.md
│  └─ mock-dataset.md
│
└─ templates/                     ← Jinja 模板，agent 用 Write 工具落盘
   ├─ dataset.jsonl.j2
   ├─ environment.yaml.j2
   ├─ experiment.yaml.j2
   └─ mock_synthesis_prompt.md
```

### 4. 主流程：5 步 × 4 道强制闸门

```
  ①  任务类型识别              ──▶  闸门 1   确认任务类型 + 评测维度
  ②  数据集来源选择            ──▶  闸门 2   开源 · Mock · 自有 · 混合
       └─ 走 Mock 分支         ──▶  闸门 2b  审核 3 条生成样例
  ③  自动选 harness            ──▶  闸门 3   看 YAML diff 后确认写盘
       + 生成 配置 YAML
  ④  --dry-run 展示组合数      ──▶  闸门 4   确认开跑
       + 预估耗时
  ⑤  跑完 · 读报告 · 输出洞察小结
```

Step 3 **绝不会**问"你要 raw 还是 react"—— agent 直接按
`references/harness-selection.md` 内嵌算法自动算，在闸门 3 把决策依据
摆给你看再拍板。

### 5. 架构

```
   ╭─────────────╮  ╭─────────────╮  ╭─────────────╮  ╭─────────────╮
   │    LLM      │  │   Target    │  │   Harness   │  │ Environment │
   │  模型后端   │  │  应用 / API │  │  Agent 架构 │  │  任务世界   │
   ╰──────┬──────╯  ╰──────┬──────╯  ╰──────┬──────╯  ╰──────┬──────╯
          └────────────────┴────────┬───────┴────────────────┘
                                    ▼
                       ╭─────────────────────╮
                       │     Orchestrator    │
                       │  ◆ Metrics  ◆ Judge │
                       ╰──────────┬──────────╯
                                  ▼
            ╭───────────────────────────────────────────╮
            │  📊 报告产物                              │
            │  Excel · HTML · JSONL · Markdown · JSON   │
            ╰───────────────────────────────────────────╯
```

| 层 | 角色 | 已实现 |
|----|------|--------|
| **LLM**         | 模型后端     | `OpenAICompatibleLLM`（任何 OpenAI 兼容 API：vLLM · SGLang · Ollama · DeepSeek · Qwen · Kimi · GLM …）· `MockLLM` |
| **Target**      | 被测系统     | `HTTPAppTarget`（REST / RAG 应用）· `MockTarget` |
| **Harness**     | Agent 架构   | `RawHarness` · `ReActHarness` · `FunctionCallHarness` · `DirectHarness` |
| **Environment** | 任务世界     | `DialogEnvironment`（槽位填充）· `RAGQAEnvironment`（应用级 RAG QA）· `WorkspaceEnvironment`（自包含任务目录），可扩展 |

`Environment` 不是 prompt 模板，而是**任务世界**。LLM benchmark 走
Harness + LLM；应用级 benchmark 让 Environment 直接调 `Target` —— 你的
RAG 助手就被当作"完整应用"来评测，而不是误当成一个裸 LLM。

Agent / 产品级 benchmark 建议用**自包含任务目录**：

```
tasks/my_suite/my_task/         ← 一个自包含任务
├─ task.yaml                    ← 任务类型 · 评测方式 · 元数据
├─ query.md                     ← agent 可见的 prompt
├─ files/                       ← agent 可读的输入文件
└─ .eval/                       ← 隐藏评测资产
   └─ rubric.py                 ← 评分脚本
```

**自带 Target.** 要评测 CLI 工具、Python 库、stdio agent、MCP 服务器？
子类化 `BaseTarget` 再注册一行就行 —— 大约 10 行代码：

```python
from src.target import BaseTarget, TargetResponse, register_target

class MyCLITarget(BaseTarget):
    capabilities = ["run"]                           # 声明支持哪些 operation

    async def invoke(self, operation, payload, *, task=None):
        # 怎么调你的工具都行；**绝不要抛异常** —— 失败包成
        # TargetResponse(error=...) 返回，让流水线继续走
        result = await do_my_thing(**payload)
        return TargetResponse(content=result)

register_target("MyCLITarget", MyCLITarget)
```

之后任何 environment 都能在 YAML 里 `class: MyCLITarget` 引用，
`eval-anything --list-targets` 也会自动列出。我们刻意只内置
`HTTPAppTarget` + `MockTarget` —— 其他形态（CLI / Python / stdio / MCP）
都需要一个**配套的 Environment** 才能真正跑起来，所以让你和 env 一起写，
比我们塞半套给你强。

### 6. 配置说明

所有配置都在 `--config-dir` 目录下（默认 `./configs/`），agent 会替你读写。
完整 schema 见 `skills/eval-anything/references/configs.md`。

```yaml
# configs/llm_profiles.yaml
llm_profiles:
  my_model:
    class: "OpenAICompatibleLLM"
    model_name: "my-model"
    endpoint_url: "http://your-host:port/v1/chat/completions"
    api_key_env: "MY_MODEL_API_KEY"          # 推荐：从环境变量读
    # 或：api_key: "${MY_MODEL_API_KEY}"     # 也支持 ${VAR} 内联占位
    temperature: 0.0
    max_tokens: 600
```

> ⚠️ **绝不要**把真实 key 写进 YAML。用 `api_key_env` 或 `${VAR}` 占位。

评测完整应用时，在 `configs/targets.yaml` 里声明被测系统，environment
引用它即可：

```yaml
# configs/targets.yaml
targets:
  my_rag_app:
    class: "HTTPAppTarget"
    base_url: "${RAG_BASE_URL:-http://localhost:8000}"
    endpoints:
      chat: "/api/v1/chat"

# configs/environments.yaml
environments:
  my_rag_qa:
    class: "RAGQAEnvironment"
    dataset: "tasks/my_rag_qa/dataset.jsonl"
    target: "my_rag_app"
```

### 7. LLM-as-Judge

两种模式都已接入 orchestrator —— 给 environment 配 `judge` 或
`judge_panel` 字段，跑完任务后自动调裁判评分。

**单裁判** —— 便宜，但会带入单家族系统性偏差：

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

**Judge Panel (PoLL — Panel of LLM Judges)** —— **推荐**。N 个跨家族裁判
并发独立打分再聚合，抵消单裁判的 self-preference 与 cognitive lock-in。
**前提是跨家族** —— 3 个 GPT-4 变体投票不是 panel，只是更大声的回音壁。

`configs/judge_profiles.yaml` 自带一份 **15 个 judge 的 catalog**，覆盖
OpenAI · Anthropic · Qwen · DeepSeek · 智谱 GLM · 月之暗面 Kimi ·
Google Gemini · 本地 vLLM。挑任意跨家族 3 个组 panel，或直接用 4 个内置 preset：

| Preset | 组成 | 相对成本 | 用于 |
|---|---|---|---|
| `default_panel`  | gpt-4o + claude-sonnet-4 + qwen-max     | 1×        | 大多数场景 |
| `budget_panel`   | gpt-4o-mini + claude-haiku + qwen-plus  | ~0.1–0.2× | 大批量 / CI |
| `frontier_panel` | o3-mini + claude-opus + qwen-max        | ~2–3×     | 正式发布、对外报告 |
| `domestic_panel` | qwen-max + glm-4-plus + kimi            | ~0.5×     | 国产合规 / 不出境 |

```yaml
# configs/environments.yaml —— 一行启用
environments:
  my_task:
    class: DialogEnvironment
    dataset: datasets/my_task.jsonl
    judge_panel: default_panel    # 或 budget_panel / frontier_panel / domestic_panel
```

**不改 YAML 就换裁判模型。** Catalog 里每条都用 `${VAR:-default}`，
环境变量直接覆盖：

```bash
# 把 OpenAI 裁判临时降档到 gpt-4o-mini，git 完全不动
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

聚合规则 —— 全部明示，没有魔法：

| 字段 | 聚合 |
|---|---|
| `score`         | N 个成员的 `trimmed_mean`（N≥3 时去掉最高、最低各一）|
| `passed`        | 多数票；平票 → `false`（保守） |
| `labels`        | union，按 `min_label_support`（默认 ⌈N/2⌉）过滤 |
| `evidence`      | union 去重 |
| `comment`       | 拼接，每条带 `[<成员>]` 前缀，可追溯 |
| `dimensions`    | 按维度独立 `trimmed_mean` |
| `panel_disagree`| `max − min > disagreement_threshold` 时自动加 |

带 `panel_disagree` 的 case 是金矿 —— 暴露 rubric 歧义、边界 case，
或某个裁判系统性偏离，人工 review 价值最大。

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

每个裁判原始 JSON 必须包含 `score` · `passed` · `labels` · `comment` ·
`evidence` · `dimensions`。Panel 的 `result.details["members"]` 完整保留
每个成员的原始判定，case study 报告可逐裁判下钻。Panel 成员中途挂掉
**不会报废整盘** —— 剩余成员降级聚合（N-1），该条加 `member_failed` 标签，
错误记录在 `details.failed_members`。

**Judge 校准** *(可选)*。Judge 本身可不可信？给任何挂了 judge 的环境
加一份人工标注的 `calibration_set`（JSONL，含 `human_score` /
`human_passed` / `human_labels`），主任务跑完后自动测 judge↔人类一致性 ——
Pearson r、pass 准确率、macro-F1 —— 结果在 HTML 仪表盘以红绿灯卡片呈现。
按 `(env, judge)` 缓存，多少 combo 共享都只跑一次：

```yaml
environments:
  my_task:
    judge_panel: default_panel
    calibration_set: datasets/calibration/my_cal.jsonl   # 一行接入，可选
```

**Pairwise + Elo** *(可选)*。绝对分对 rubric 措辞敏感；人类真正擅长
判断的是"哪个回答更好"。在 experiment 级配 `pairwise_judge`（要求 ≥ 2 个
LLM profile），所有模型输出两两对比 —— 自动 A/B 换位消除位置偏差 ——
聚合成 Elo 排行榜 + win 矩阵进报告：

```yaml
experiment:
  llm_profiles: [gpt4o, claude_sonnet, qwen_max]
  pairwise_judge: openai_judge          # 一行接入，可选
```

### 8. 输出报告

| 报告 | 格式 | 内容 |
|------|------|------|
| **详细结果**   | Excel    | 逐条结果、字段对比、黄色标错 |
| **统计汇总**   | Excel    | 每个组合的成功率、平均得分 |
| **模型对比**   | Excel    | LLM × Harness 成功率热力图 |
| **仪表盘**     | HTML     | 热力图、字段级分析、judge 维度雷达图、Elo 排行 + win 矩阵、校准卡片 |
| **机读汇总**   | JSON     | `<exp>_summary.json` —— CI / 脚本集成的单一机读出口 |
| **轨迹日志**   | JSONL    | 完整执行步骤记录，每条任务完成即落盘 |
| **案例研究**   | Markdown | 失败分类、代表性案例、分析洞察 |

中途崩溃？已完成的结果都在盘上。加 `--resume` 重跑会跳过所有已有结论
的任务（`error` / `timeout` 这类基础设施故障会重试）：

```bash
eval-anything --experiment my_exp --config-dir configs --resume
```

### 9. 扩展

- **新 LLM**         —— `src/llm/` 下继承 `BaseLLM`，到 `configs/llm_profiles.yaml` 加 profile
- **新 Harness**     —— `src/harness/` 下继承 `BaseHarness`，注册到 `_HARNESS_REGISTRY`，加 profile
- **新 Environment** —— `src/environment/` 下继承 `BaseEnvironment`，注册到 `_ENV_REGISTRY`，加 profile
- **新 Target**      —— `src/target/` 下继承 `BaseTarget`，调 `register_target(name, cls)`

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
