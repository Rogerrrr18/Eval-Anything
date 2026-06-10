# Harness 自动选择算法

> Skill 在 design-experiment workflow Step 3 必须按本算法**自动计算** harness 集合 + 超参，**不再单独问用户选哪些 harness**。计算结果统一塞进闸门 3 的配置 diff 里，让用户一次性审。
>
> 设计原则：用户已经在闸门 1 给出了"任务类型 + 评测维度"，那么"该用哪些 harness、每个 max_steps 设多少"是**领域工程问题**，应该由 skill 内置专家知识自动决策，而不是把负担抛回给用户。

## 输入

来自闸门 1 与前置准备：
- `task_type` ∈ {slot_filling, tool_use, reasoning, code, dialog_judge, classification, custom}
- `eval_dimensions`：用户在闸门 1 确认的评测维度
- `env_class`：当前是 `DialogEnvironment`，未来可能扩展
- `llm_profiles`：用户要测的 LLM profile name 列表（来自 design-experiment 中跟用户确认的范围）

## 输出

```python
{
  "harness_profiles": ["raw", "react"],          # 自动选出的 harness 名列表
  "harness_overrides": {                          # 每个 harness 的超参（可能改 yaml 现有 profile，也可能新建 profile）
    "raw": {"max_steps": 1},
    "react": {"max_steps": 8, "system_prompt": "..."},
  },
  "filtered_combos": [                            # 自动剔除的 (llm, harness) 不兼容组合 + 理由
    {"llm": "deepseek_v4_flash", "harness": "function_call",
     "reason": "DeepSeek-V4-Flash 未知是否支持 native tools，且任务类型 slot_filling 不需要 function calling"},
  ],
  "reasoning": "为何这样选（一段话）"             # 写进闸门 3 给用户看
}
```

## 算法

### Step 1：按 task_type 决定 harness 集合的种子

| task_type | 默认 harness 集合 | 备注 |
|---|---|---|
| `slot_filling` | `[raw]` | 一步出 JSON 就完事，ReAct/FunctionCall 是浪费 |
| `classification` | `[raw]` | 同上 |
| `tool_use` | `[raw, function_call]` | raw 作 baseline；function_call 是主角 |
| `reasoning` | `[raw, react]` | ReAct 给推理链 |
| `code` | `[raw, react]` | 复杂题 ReAct 拆解；简单题 raw 够 |
| `dialog_judge` | `[raw]` | 多轮裁判靠 env 编排，harness 维度通常无意义 |
| `custom` | `[raw, react]` | 兜底，让用户事后调 |

**永远包含 `raw`**——它是不可省的对照基线。任何 harness 不能比 raw 显著强就没意义。

### Step 2：根据用户在闸门 1 的"评测维度"补充

如果 `eval_dimensions` 含某些信号，追加 harness：

| 维度关键词 | 追加 |
|---|---|
| "对比 harness"、"测 agent 架构" | 把所有 3 个 harness 都加进来（用户明确要横向） |
| "工具调用"、"function call"、"tool use" | 追加 `function_call` |
| "推理链"、"chain of thought"、"reasoning trace" | 追加 `react` |
| "token 效率"、"成本" | 不追加（轻量场景 raw 已够；甚至若集合里有 react/function_call，提醒用户它们 token 更高） |

去重后得到 `harness_set`。

### Step 3：按 (llm, harness) 二元组做兼容性剔除

对每个 (llm, harness) 组合检查：

#### Rule 3.1：FunctionCallHarness 需要 LLM 支持 tools

判定 LLM 是否支持 native function calling 的**名字启发式**（按可靠性降序）：

| 模型名匹配 | 判定 | 信心 |
|---|---|---|
| `gpt-4*`, `gpt-3.5-turbo-{1106,0125,...}` | 支持 | 高 |
| `claude-3*`, `claude-opus*`, `claude-sonnet*`, `claude-haiku*` | 支持 | 高 |
| `deepseek-chat`, `deepseek-v3*`, `deepseek-coder-v2*` | 支持 | 高 |
| `qwen-max`, `qwen2.5-*-instruct`, `qwen3-*-instruct` | 支持 | 高 |
| `glm-4*` | 支持 | 中 |
| `mistral-large`, `mixtral-8x*-instruct` | 支持 | 中 |
| 名字含 `flash`、`mini`、`int4`、`int8`、`gguf` | **未知** | 低 |
| 名字含 `base`、`pretrain` | 不支持 | 高 |
| MockLLM | 不支持（但不报错，用于 smoke test） | 高 |
| 其他 | **未知** | 低 |

**遇到"未知"时的策略**：
- 如果 `harness_set` 里**只有** function_call 一个 harness（说明任务必须用工具调用）→ **不剔除**，但在 `reasoning` 里加一行警告："⚠️ <llm> 未知是否支持 tools，跑出来若全部不合规请考虑换 LLM"。
- 如果 `harness_set` 里**还有别的 harness**（如 raw）→ 仍然保留 function_call 组合，但在 `reasoning` 里写"<llm> 在 function_call 下不确定能否触发 submit_answer，结果以 raw 为准"。

#### Rule 3.2：ReActHarness 对 LLM 没有硬要求

任何 LLM 都能跑 react——它只是文本 in/out，靠正则解析格式。即使解析失败也会 fallback 到 text_response。**不剔除**。

#### Rule 3.3：RawHarness 与所有 LLM 兼容

无剔除。

#### Rule 3.4：Harness × Environment 兼容性

当前 codebase 唯一的 `DialogEnvironment` 期望**合法 JSON 字符串**作为 `action.content`：

| Harness | DialogEnvironment 兼容性 | 注意 |
|---|---|---|
| raw | ✅ 直接出 JSON 字符串 | system_prompt 已含 schema 约束 |
| react | ✅ 通过 `Action: respond[<json>]` 输出 | 必须在 react 的 system_prompt 里强调 respond 内容要是 JSON |
| function_call | ✅ 通过 `submit_answer(answer="<json>")` 输出 | env 会把 answer 当字符串解析 |

未来若新增非 JSON 输出的 env（如 `MathEnvironment` 要数值），需要在本表追加。

### Step 4：超参自动调

按 task_type × harness 二维矩阵设 `max_steps`：

| task_type | raw | react | function_call |
|---|---|---|---|
| slot_filling | 1 | 3 | 3 |
| classification | 1 | 3 | 3 |
| tool_use | 1 | 8 | 10 |
| reasoning | 1 | 8 | — |
| code | 1 | 6 | 8 |
| dialog_judge | 1 | 5 | — |
| custom | 1 | 5 | 5 |

**额外规则**：
- 用户在闸门 1 明说"复杂多步"、"链路长" → 把 react/function_call 的 max_steps × 1.5（向上取整）
- 用户明说"快"、"省 token" → 把 react/function_call 的 max_steps × 0.5（最小 2）

### Step 5：决定是新建 profile 还是复用现有

读 `configs/harness_profiles.yaml`，对每个要用的 harness：

| 情况 | 处置 |
|---|---|
| 现有 profile `<name>` 的 max_steps 跟算法推荐一致 | 直接复用，不动文件 |
| 不一致但差距 < 30% | 复用现有，不动文件，在 reasoning 里说明"已用现有 react profile（max_steps=10），算法推荐 8，偏差小直接复用" |
| 不一致且差距大 | 在 yaml 里新增一个 profile，命名 `<harness>_<task_type>`，如 `react_tool_use`，max_steps 用推荐值 |
| harness_set 含的 harness 在 yaml 中根本没有对应 profile | 必须新建 profile |

**绝不修改现有 profile 的字段**。永远追加新 profile，避免破坏其他实验。

### Step 6：组装 reasoning 文本给用户看

写一段说明，进闸门 3 的配置 diff：

```
我自动选了 harness = [<list>]，理由：
- <task_type> 任务通常 <一句话>
- raw 作为不可省的基线（不带就无法判断其他 harness 的增益）
- <如果加了 react> react 在 <X> 维度可能有增益，max_steps 设 <N>（按任务复杂度估算）
- <如果加了 function_call> function_call 用于 <Y>，max_steps 设 <M>
- <如果剔除了某组合> 自动剔除 (<llm>, function_call) — <LLM 名> 未知是否支持 tools

如需横向对比所有 harness 或锁死单一 harness，告诉我即可调整。
```

## 不在算法里的事

- **不预测哪个 harness 会赢**——这是评测要回答的问题
- **不主动加 function_call 给纯文本任务**——没意义
- **不剔除"用户明确要求保留"的组合**——用户优先级最高
- **不自动改 system_prompt 内容**——只动 max_steps；改 prompt 是 harness profile 维护者的事

## 给 skill 实现者的伪代码

```python
def auto_select(task_type, eval_dims, env_class, llm_profiles, existing_harnesses):
    # Step 1
    harness_set = {
        "slot_filling": ["raw"],
        "classification": ["raw"],
        "tool_use": ["raw", "function_call"],
        "reasoning": ["raw", "react"],
        "code": ["raw", "react"],
        "dialog_judge": ["raw"],
        "custom": ["raw", "react"],
    }[task_type]
    harness_set = set(harness_set)

    # Step 2
    if any(k in eval_dims.lower() for k in ["对比 harness", "测 agent 架构", "compare harness"]):
        harness_set.update(["raw", "react", "function_call"])
    if any(k in eval_dims.lower() for k in ["工具", "function call", "tool"]):
        harness_set.add("function_call")
    if any(k in eval_dims.lower() for k in ["推理链", "cot", "reasoning trace"]):
        harness_set.add("react")

    # Step 3
    filtered = []
    for llm in llm_profiles:
        for h in list(harness_set):
            if h == "function_call":
                support = guess_tool_support(llm.model_name)
                if support == "no":
                    filtered.append((llm.name, h, "模型不支持原生 function calling"))
                # "unknown" 或 "yes" 都保留

    # Step 4
    max_steps_table = { ... }  # 见上表
    overrides = {h: {"max_steps": max_steps_table[task_type][h]} for h in harness_set}
    # 复杂度调整
    if "复杂" in eval_dims or "多步" in eval_dims:
        for h in ["react", "function_call"]:
            if h in overrides:
                overrides[h]["max_steps"] = math.ceil(overrides[h]["max_steps"] * 1.5)

    # Step 5
    # 对比 existing_harnesses 决定复用 / 新建

    # Step 6
    reasoning = render_reasoning(...)

    return {
        "harness_profiles": sorted(harness_set, key=lambda h: ["raw","react","function_call"].index(h) if h in ["raw","react","function_call"] else 99),
        "harness_overrides": overrides,
        "filtered_combos": filtered,
        "reasoning": reasoning,
    }
```

skill 在 agent 这一侧不需要真跑 Python——agent 按本文档的规则**心算**出结果即可。把这份规则当成 skill 的"内嵌专家"。
