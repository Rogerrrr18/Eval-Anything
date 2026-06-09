# CLI 参数手册（`eval-anything` / `eval-agent`）

本文档是 `src/__main__.py` 的事实快照。两个命令（`eval-anything`、`eval-agent`）完全等价，后者只是 Agent CLI 场景的别名。

## 安装

```bash
# 本地源码（开发模式）
pip install -e .

# 从 GitHub
pip install "git+https://github.com/Rogerrrr18/Eval-Anything.git"
```

安装后即可使用 `eval-anything` 或 `eval-agent` 命令；未安装时用 `python -m src`，三者完全等价。

## 参数全集

| 参数 | 简写 | 类型 | 默认 | 说明 |
|---|---|---|---|---|
| `--experiment` | `-e` | str | — | 实验文件名（不含 `.yaml`，位于 `configs/experiments/`） |
| `--config-dir` | `-c` | str | `configs` | 配置目录根，支持相对/绝对路径 |
| `--llm` | — | str | — | LLM profile 名（与 `--harness`/`--env` 三件套使用） |
| `--harness` | — | str | — | Harness profile 名 |
| `--env` | — | str | — | Environment profile 名 |
| `--output-dir` | `-o` | str | — | 覆盖实验配置里的 `output_dir` |
| `--log-level` | — | str | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `--list-profiles` | — | flag | false | 列出所有 LLM / Judge / Harness / Env profile |
| `--generate-sample-data` | — | flag | false | 在 `datasets/slot_filling/` 下生成 `xiu_test.jsonl` 和 `zhuang_test.jsonl` |
| `--no-excel` | — | flag | false | 不生成 Excel 报告 |
| `--no-html` | — | flag | false | 不生成 HTML 仪表盘 |
| `--dry-run` | — | flag | false | 只列出将运行的组合，不执行 |

## 调用模式

### 模式 A：跑预设实验

```bash
eval-agent --experiment slot_filling
```

读取 `configs/experiments/slot_filling.yaml`，按其中的 `llm_profiles × harness_profiles × environments` 跑笛卡尔积。

### 模式 B：临时指定单组合

```bash
eval-agent --llm deepseek_v4_flash --harness raw --env slot_filling_xiu
```

三件套必须全部提供。此时不读 experiment 文件，自动构造一个名为 `custom_<llm>_<harness>_<env>` 的临时实验。

### 模式 C：探索可用配置

```bash
eval-agent --list-profiles
```

输出形如：
```
=== 可用 LLM Profiles ===
  deepseek_v4_flash: DeepSeek-V4-Flash @ http://localhost:10814/v1/chat/completions
=== 可用 Harness Profiles ===
  raw: RawHarness (直接 prompt-in / response-out 基线...)
  react: ReActHarness (ReAct 推理+行动循环...)
  function_call: FunctionCallHarness (基于 LLM 原生 tool/function calling...)
=== 可用 Environments ===
  slot_filling_xiu: DialogEnvironment — 报修预约槽位填充 [datasets/slot_filling/xiu_test.jsonl]
```

**强烈建议在 skill 主流程 Step 2 之前先跑一次 `--list-profiles`**，把现有 profile 真实拉出来给用户看。

### 模式 D：dry-run 看组合数

```bash
eval-agent --experiment slot_filling --dry-run
```

输出形如：
```
=== Dry Run: 将运行 N 个组合 ===
  LLM=deepseek_v4_flash, Harness=raw, Env=slot_filling_xiu
  LLM=deepseek_v4_flash, Harness=react, Env=slot_filling_xiu
  ...
```

**Step 4 闸门 4 必须基于这一步的输出展示给用户**。

### 模式 E：生成示例数据

```bash
eval-agent --generate-sample-data
```

写出两个 JSONL 到 `datasets/slot_filling/`。用于第一次跑通流程时无配置门槛上手。

## 输出目录结构

跑完后会在 `<output_dir>/`（默认来自 experiment 配置的 `output_dir`）下生成：

```
<output_dir>/
├─ reports/
│  ├─ *.xlsx               详细结果 / 统计汇总 / 模型对比
│  └─ *.html               HTML 仪表盘
├─ trajectories/
│  └─ <exp_name>.jsonl     每条任务的完整步骤记录
└─ case_studies/
   └─ <exp_name>.md        失败案例 + 代表性案例（数量由 case_study_count 控制）
```

`--no-excel` / `--no-html` 可分别关掉 Excel / HTML；trajectory JSONL 和 case study Markdown 永远生成。

## 错误退出

- 既不提供 `--experiment` 也不同时提供 `--llm/--harness/--env` 三件套 → 打印错误退出码 0（脚本不抛异常，但不会跑）
- profile 名不存在 → 抛 `KeyError` 并打印可用列表
- 数据集文件不存在 → 警告并使用空测试集（即组合会跑 0 条任务，不会硬错）

## Skill 调用约定

在 skill 流程里调 CLI 的标准做法：

1. **list-profiles 先于一切**：任何对话开始时如果你拿不准当前有哪些 profile，先 `eval-agent --list-profiles --config-dir <path>` 一次。
2. **dry-run 必跑**：在闸门 4 之前一定先 `--dry-run`。
3. **跑实测时显式传 `--output-dir`**：避免覆盖之前的实验。命名规则建议 `outputs/<exp_name>_<YYYYMMDD_HHMM>/`。
4. **小数据集试跑**：第一次跑某个组合时建议把 environment 的 dataset 临时指向只有 5-10 条的小集，跑通后再换全量。
