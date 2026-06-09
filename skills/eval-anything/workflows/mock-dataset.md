# Workflow: mock-dataset

合成评测数据子流程。被 `design-experiment.md` 在 Step 2 分支 B 调用。

> 核心约定：**合成器（synthesizer）必须从用户已配置的 `llm_profiles` 里选一个，不要默认、不要硬编码**。合成后必须先抽样 3 条让用户审核，通过才全量生成。

## 何时调用

- 用户的任务是垂直业务场景，开源集都不合适
- 用户明说"帮我 mock 一份"、"合成一些测试数据"
- design-experiment Step 2 闸门 2 选了"B. Mock"或"D. 混合"

## Step 1: 选合成器 LLM

⛔ 多选确认（必须从已有 profile 里选）：

```bash
# 先拉 profile 列表
eval-agent --list-profiles --config-dir <repo>/configs
```

按拉到的 LLM profile 列表生成选项：

```
question: "用哪个 LLM 来合成数据？（建议选你信得过的'最强'模型，因为它是 ground truth 的代笔）"
options:
  - "<llm_profile_1>: <model_name> @ <endpoint>"
  - "<llm_profile_2>: <model_name> @ <endpoint>"
  - "..."
```

**不要**默认选第一个。**不要**让 MockLLM 当合成器（它不会真生成内容）。

如果用户的 llm_profiles 都不合适（比如全是被测模型，要避免自考自），提示用户：
> "你目前配置的 LLM 都是被评测对象。要不要先用 `workflows/add-llm.md` 接入一个高质量的合成专用模型（如 GPT-4o、Claude Opus、DeepSeek-V3）？"

## Step 2: 收集合成参数

⛔ 多选确认（多问题）：

```
question 1: "合成多少条？"
options:
  - "10 条（快速试跑）"
  - "30 条（默认规模）"
  - "100 条（小规模评测）"
  - "自定义"

question 2: "数据多样性维度（多选）："
multiSelect: true
options:
  - "覆盖不同难度（easy / medium / hard）"
  - "覆盖边界情况（空字段、超长输入、噪声）"
  - "覆盖多种表达风格（口语、书面、方言/缩写）"
  - "包含负样本（信息不全、需要追问）"

question 3: "任务输入的来源："
options:
  - "完全合成（synthesizer 自己造场景）"
  - "基于已有几条样例扩写（你给 1-3 条种子，我让 synthesizer 类比）"
```

种子样例分支：如果用户选了"基于样例扩写"，让用户先粘 1-3 条样例，作为 synthesis prompt 的 few-shot。

## Step 3: 构造 synthesis prompt

读 `templates/mock_synthesis_prompt.md`，按用户选的参数填充：
- 任务类型（来自 design-experiment Step 1）
- slot_keys / 输出 schema（来自 design-experiment Step 1）
- 多样性维度
- 种子样例（如有）

合成 prompt 必须明确要求合成器输出**严格的 JSONL**（每行一个 task），方便直接落盘。

## Step 4: 先合成 3 条试样

**不要直接跑全量**。先用合成 prompt 让 synthesizer 出 3 条：

```python
# 伪代码：通过现有 ConfigLoader + LLM 调用
from src.core.config import ConfigLoader
from src.llm import create_llm
from src.llm.base import LLMConfig

loader = ConfigLoader("configs")
profile = loader.get_llm_profile("<chosen_synthesizer>")
llm = create_llm(LLMConfig(
    model_name=profile.model_name,
    endpoint_url=profile.endpoint_url,
    api_key=profile.api_key,
    temperature=0.7,  # 合成时用更高 temperature 增加多样性
    max_tokens=2000,
), class_name=profile.class_name)

response = await llm.chat([
    {"role": "system", "content": SYNTHESIS_PROMPT},
    {"role": "user", "content": "请合成 3 条样例，JSONL 格式。"}
])
```

把合成出的 3 条**完整展示**给用户。

## ⛔ Step 4b: 闸门 2b（强制多选确认）

```
question: "这是合成器产出的 3 条样例。质量怎么样？"
options:
  - "质量 OK，继续合成全量 <N> 条"
  - "字段缺失/格式错，回到 Step 3 改 prompt"
  - "内容太单一，要改多样性维度"
  - "太假/不真实，换个合成器（回 Step 1）"
```

**绝不**绕过这一道闸门。Mock 数据质量直接决定评测信号是否可信，省这一步会让整个评测白做。

## Step 5: 合成全量并落盘

通过审核后：

```python
all_tasks = []
batch_size = 5  # 一次合成 5 条，循环到达到 N
while len(all_tasks) < N:
    response = await llm.chat([
        {"role": "system", "content": SYNTHESIS_PROMPT},
        {"role": "user", "content": f"继续合成 {batch_size} 条，跟之前不重复。"}
    ])
    new_tasks = parse_jsonl(response.content)
    all_tasks.extend(new_tasks)

# 落盘
with open(f"datasets/<task>/mock_<source>.jsonl", "w") as f:
    for t in all_tasks[:N]:
        f.write(json.dumps(t, ensure_ascii=False) + "\n")
```

**注意**：
- 合成时建议 `temperature` 调到 0.7-1.0，比评测时高
- 每批 N=5 而不是一次让模型出 100 条，模型一次性出多了容易塌缩到同模板
- 如果用户选了多样性维度，每批轮换提示词（"这批侧重 hard"、"这批侧重边界"）

## Step 6: 抽样复查

合成完后再抽 5 条让用户扫一眼：

```
合成完成，共 <N> 条 → datasets/<task>/mock_<source>.jsonl

随机抽样 5 条让你扫一眼：
1. <task_id_x>: ...
2. <task_id_y>: ...
...

OK 吗？OK 的话回到 design-experiment Step 3。
```

如果用户说不 OK，回到 Step 4 调整合成 prompt 重做。

## 给用户的注意事项

跑完 mock 流程一定要告诉用户：

```
⚠️ 关于 mock 数据的免责声明：
- 这份数据由 <synthesizer_name> 合成，不代表真实分布
- 评测结果只能作为「相对对比」参考，不能直接外推到生产
- 强烈建议：跑通流程后逐步用真实数据替换 mock 数据
- 不要拿 mock 数据训练模型 — 会污染 / 偏离真实分布
```

把这段话明确写出来，不要藏在角落。
