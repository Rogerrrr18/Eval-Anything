# 任务类型 → 开源测试集映射

主流程 Step 2 闸门 2 中"选开源数据集"分支用此表给用户推荐候选。每条候选要告诉用户：在哪、多大、什么语言、需不需要适配。

## 通用规则

1. **先问用户语种和领域**——中文客服任务推 C-Eval/CrossWOZ 之类，硬塞英文集是浪费时间
2. **给 2-3 个候选**，不要给 1 个（用户没法对比），也不要 10 个（决策疲劳）
3. **永远附加"None of these → mock 一份"选项**，让用户能回退
4. **明确"是否需要 schema 适配"**——开源集大多不是 `TaskInstance` 格式，必须写转换脚本

## 任务类型 → 候选数据集

### 槽位填充 / 对话式信息抽取（slot filling, NLU）

| 数据集 | 来源 | 语言 | 规模 | 备注 |
|---|---|---|---|---|
| MultiWOZ 2.2 | HuggingFace `multi_woz_v22` | EN | ~10k 对话 | 多域对话状态追踪，需要把 dialogue state 转成槽位字典 |
| CrossWOZ | GitHub `thu-coai/CrossWOZ` | ZH | ~6k 对话 | 中文多域对话，最接近 Eval-Anything 现有 slot_filling_xiu 形态 |
| SNIPS | HuggingFace `snips_built_in_intents` | EN | ~14k utterances | 单轮意图+槽位，简单 |
| RiSAWOZ | HuggingFace `RiSAWOZ` | ZH | ~10k 对话 | 中文，覆盖 12 个域 |

**用现有 `DialogEnvironment` 直接跑**——只需写 schema 转换脚本输出 JSONL。

### 工具调用 / Function calling / Agent benchmark

| 数据集 | 来源 | 语言 | 规模 | 备注 |
|---|---|---|---|---|
| BFCL (Berkeley Function-Calling Leaderboard) | GitHub `ShishirPatil/gorilla` | EN | ~2k 测例 | 工业标准 function-call benchmark，含 multi-turn / parallel / irrelevance |
| ToolBench | GitHub `OpenBMB/ToolBench` | EN | 16k 真实 API | 大规模，但需要联网调真 API |
| API-Bank | HuggingFace `liyucheng/api_bank` | EN | ~2k 对话 | 工具调用 + 多轮规划 |
| τ-bench | GitHub `sierra-research/tau-bench` | EN | ~150 测例 | 现实客服场景，user simulator 参与 |

**`DialogEnvironment` 不够用**——FunctionCall harness 在它面前只能用 `submit_answer` 提交字符串。要真正评 tool use，需要新写一个 `ToolEnvironment`（见 `references/extending.md`）。

### 多步推理 / 数学 / 代码

| 数据集 | 来源 | 语言 | 规模 | 备注 |
|---|---|---|---|---|
| GSM8K | HuggingFace `gsm8k` | EN | 1.3k 测试 | 小学数学，最常用的 reasoning baseline |
| MATH | HuggingFace `hendrycks/competition_math` | EN | 5k 题 | 中学竞赛数学 |
| BBH (Big-Bench Hard) | HuggingFace `lukaemon/bbh` | EN | 27 子任务 | 涵盖逻辑、符号、语义推理 |
| HumanEval | HuggingFace `openai_humaneval` | EN | 164 测例 | 代码生成 baseline，需 sandbox 执行 |
| MBPP | HuggingFace `mbpp` | EN | 974 题 | 代码生成，类似 HumanEval |
| LiveCodeBench | GitHub `LiveCodeBench/LiveCodeBench` | EN | 月度更新 | 防数据污染的代码基准 |

**这些任务需要新 environment 类**：数学/推理类需要数值或文本匹配 env；代码类需要执行型 env（sandbox）。

### 中文通用能力

| 数据集 | 来源 | 语言 | 规模 | 备注 |
|---|---|---|---|---|
| C-Eval | HuggingFace `ceval/ceval-exam` | ZH | 14k 题 | 多学科多项选择，常用主榜 |
| CMMLU | HuggingFace `haonan-li/cmmlu` | ZH | 11k 题 | 多任务中文 MLU |
| AGIEval | GitHub `microsoft/AGIEval` | ZH/EN | 8k 题 | 高考、公务员、SAT 等真题 |
| SuperCLUE | GitHub `CLUEbenchmark/SuperCLUE` | ZH | 多榜单 | 中文综合 |

需要选择题专用 env（输出 A/B/C/D，对比正确选项）。

### 多轮对话能力

| 数据集 | 来源 | 语言 | 规模 | 备注 |
|---|---|---|---|---|
| MT-Bench | GitHub `lm-sys/FastChat` 子目录 | EN | 80 多轮题 | LLM-as-Judge 评分，配 GPT-4 当裁判 |
| AlpacaEval 2 | GitHub `tatsu-lab/alpaca_eval` | EN | 805 题 | 单轮对话，用 LLM-as-Judge |
| MT-Bench-CN | 社区中文版 | ZH | 80 多轮题 | 中文版多轮 |

**这类必须配 `judge_profiles.yaml`**，不能用规则匹配。

### 垂直业务场景（客服 / 报修 / 报装 / ...）

→ **通常没现成开源集**，走 mock 流程或用户自有。这是 Eval-Anything 当前 `slot_filling_xiu/zhuang` 的场景。

## 给用户的展示模板

在闸门 2 里，按这种格式列候选：

```
对于「<用户任务描述>」，我推荐 3 个开源候选：

A. <数据集名> — <来源> — <规模> — <语言>
   优势：xxx
   适配工作量：xxx（需要写 ~N 行 schema 转换脚本）

B. <...>

C. <...>

D. 都不合适 → 走 Mock 合成流程
E. 我自己有数据 → 走自有数据流程
```

让用户选一个或要求看更多。

## 加载到 Eval-Anything 的步骤

无论选哪个开源集，最终都要落到 `datasets/<task>/<source>.jsonl`，单行字段对齐 `references/configs.md` 第 3 节的 JSONL schema。

标准转换脚本骨架：
```python
# scripts/convert_<source>.py
import json
from datasets import load_dataset

ds = load_dataset("<source_name>", split="test")
slot_keys = [...]  # 你的任务 schema

with open("datasets/<task>/<source>.jsonl", "w", encoding="utf-8") as f:
    for i, row in enumerate(ds):
        task = {
            "task_id": f"<source>_{i:05d}",
            "task_type": "<your_type>",
            "prompt": row["<input_field>"],
            "ground_truth": {...},
            "expected_slots": {...},
            "slot_keys": slot_keys,
            "metadata": {"source": "<source_name>", "row_idx": i},
        }
        f.write(json.dumps(task, ensure_ascii=False) + "\n")
```

写完后让用户先 `head -1 datasets/<task>/<source>.jsonl` 检查一条样例再大规模跑。
