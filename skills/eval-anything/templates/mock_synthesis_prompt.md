# Mock Synthesis Prompt 模板

由 `workflows/mock-dataset.md` Step 3 渲染后发给 synthesizer LLM。

变量：
- `{TASK_TYPE}`：任务类型，如 `slot_filling`
- `{TASK_DESCRIPTION}`：用户对任务的自然语言描述
- `{SLOT_KEYS}`：JSON list，待抽取字段，如 `["product_name", "phone_number", ...]`
- `{OUTPUT_SCHEMA}`：JSON 字段模板，如 `{"product_name": "", "phone_number": ""}`
- `{DIVERSITY_DIMENSIONS}`：用户选的多样性维度（如 "覆盖不同难度、包含负样本"）
- `{SEED_EXAMPLES}`：可选，1-3 条种子样例（JSON 字符串），用作 few-shot
- `{BATCH_SIZE}`：本批次合成数量，默认 5
- `{BATCH_HINT}`：可选，本批次侧重维度（"这批侧重 hard"、"这批侧重边界"）

---

## SYSTEM PROMPT

```
你是一个高质量评测数据合成器。你的任务是为「{TASK_DESCRIPTION}」生成结构化测试用例，每条用例将被用来评测下游 LLM 的表现。

【合成规范】
任务类型: {TASK_TYPE}
需要抽取的字段: {SLOT_KEYS}
输出 schema: {OUTPUT_SCHEMA}

【多样性要求】
请确保本批次的样例满足：{DIVERSITY_DIMENSIONS}
{BATCH_HINT}

【输出格式】
严格按 JSONL 输出，每行一个合法 JSON 对象，包含以下字段：
- task_id: 字符串，格式 "mock_<6位随机字母数字>"
- task_type: 字符串，固定为 "{TASK_TYPE}"
- prompt: 字符串，模拟用户的真实输入文本（口语、自然、含信息密度）
- ground_truth: 对象，按 schema 填入正确的字段值
- expected_slots: 对象，与 ground_truth 一致
- slot_keys: 数组，固定为 {SLOT_KEYS}
- metadata: 对象，含 "difficulty"（easy/medium/hard）和 "synth_batch"（递增整数）

【硬约束】
1. prompt 必须像真人写的，避免 "请帮我..." 这类机器腔；可用方言、缩写、错别字
2. ground_truth 必须严格能从 prompt 中找到（不要捏造 prompt 没有的信息）
3. 故意制造一些"信息缺失"的样例：有些字段 prompt 里就没说，对应 ground_truth 字段留空字符串
4. 不要在样例之间复制粘贴句式，每条要有显著差异
5. 不输出任何 JSONL 之外的内容（不要解释、不要 markdown 代码块）

【种子样例（如有）】
{SEED_EXAMPLES}

请基于以上规范，生成 {BATCH_SIZE} 条不同的样例。
```

## USER MESSAGE（每批的实际请求）

```
请生成 {BATCH_SIZE} 条新样例。要求：
- 不要重复前面已经生成过的样例
- 至少 1 条 hard 难度（多字段同时出现 + 干扰信息）
- 至少 1 条含信息缺失（某些字段无法从 prompt 中提取）
- 至少 1 条边界情况（超长 / 超短 / 含噪声）

只输出 JSONL，每行一条。
```

---

## 用法

在 `workflows/mock-dataset.md` Step 3 中：

```python
SYNTHESIS_PROMPT = render_template("templates/mock_synthesis_prompt.md", {
    "TASK_TYPE": task_type,
    "TASK_DESCRIPTION": user_task_description,
    "SLOT_KEYS": json.dumps(slot_keys, ensure_ascii=False),
    "OUTPUT_SCHEMA": json.dumps({k: "" for k in slot_keys}, ensure_ascii=False),
    "DIVERSITY_DIMENSIONS": ", ".join(user_selected_dimensions),
    "SEED_EXAMPLES": json.dumps(seed_examples, ensure_ascii=False) if seed_examples else "(无)",
    "BATCH_SIZE": 3,                # 试样阶段用 3，全量阶段用 5
    "BATCH_HINT": "",               # 试样阶段空；全量阶段每批轮换
})
```

试样阶段（Step 4）`BATCH_SIZE=3` 出 3 条审核；全量阶段（Step 5）每批 `BATCH_SIZE=5` 循环直到达到 N。

## 调优建议

- **temperature**：合成时建议 0.7-1.0（评测时是 0.0），增加多样性
- **max_tokens**：每条样例约 200-500 token，每批 5 条留 3000-5000 token 余量
- **失败处理**：如果某批返回的 JSONL 解析失败超过 1/3，提示用户"合成器输出不稳定，建议换更强的合成器或简化 schema"
