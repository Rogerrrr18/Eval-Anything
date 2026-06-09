# 配置 schema 手册

事实来源：`src/core/config.py` 中的 dataclass 定义 + `configs/` 下的现有 YAML。

## 1. `configs/llm_profiles.yaml`

```yaml
llm_profiles:
  <profile_name>:                    # YAML key 即 profile name
    class: "OpenAICompatibleLLM"     # 注册表中的类名，见下方
    model_name: "DeepSeek-V4-Flash"  # 传给 OpenAI API 的 model 字段
    endpoint_url: "http://localhost:10814/v1/chat/completions"
    api_key: "EMPTY"                 # 或真实 key；建议留 EMPTY / 用环境变量
    temperature: 0.0
    max_tokens: 600
    top_p: 1.0
    timeout_seconds: 30
    enable_thinking: false           # DeepSeek 等模型的 reasoning 开关
    extra_params: {}                 # 透传给 LLM 子类，用得少
```

**LLM 注册表**（`src/llm/__init__.py` 的 `_LLM_REGISTRY`）：

| class 名 | 实现 | 适用场景 |
|---|---|---|
| `OpenAICompatibleLLM` | `src/llm/openai_compatible.py` | 任何 OpenAI API 兼容端点（vLLM、SGLang、Ollama、LMStudio、官方 OpenAI、DeepSeek 平台等） |
| `HttpxLLM` | 复用 `OpenAICompatibleLLM` | 历史别名 |
| `MockLLM` | `src/llm/mock.py` | 离线测试 / pipeline smoke test，不需要真实端点 |

**字段约束**：
- `endpoint_url` 必须包含完整路径 `/v1/chat/completions`（vLLM 兼容规范）
- `api_key` 如果留 `EMPTY`，需要 endpoint 不校验 key（本地 vLLM 默认不校验）
- `enable_thinking` 仅对 DeepSeek-V3.x、Qwen3-Thinking 等显式 reasoning 模型有意义
- 加新 profile 时**永远追加在文件末尾**，不要改动现有条目

## 2. `configs/harness_profiles.yaml`

```yaml
harness_profiles:
  <profile_name>:
    class: "RawHarness"              # 见下方注册表
    max_steps: 1                     # agent loop 最大步数
    max_retries: 3                   # 单步 LLM 调用重试次数
    timeout_per_step: 60             # 单步超时（秒）
    description: "直接 prompt-in / response-out 基线"
    extra_params: {}                 # 各 harness 自有参数，见下
```

**Harness 注册表**（`src/core/orchestrator.py` 的 `_HARNESS_REGISTRY`）：

| class 名 | 文件 | 一句话说明 | 关键 extra_params |
|---|---|---|---|
| `RawHarness` | `src/harness/raw.py` | 单次 LLM 调用，基线 | 无 |
| `ReActHarness` | `src/harness/react.py` | Thought/Action 循环，regex 解析 | `system_prompt`（覆盖默认提示） |
| `FunctionCallHarness` | `src/harness/function_call.py` | LLM 原生 tool calling | `tool_choice`（默认 `auto`）、`tools`（覆盖默认工具集） |

**默认推荐 max_steps**：

| Harness | max_steps |
|---|---|
| raw | **1**（改了无意义） |
| react | 5–10 |
| function_call | 5–15 |

**ReAct 输出格式约定**（写在 system_prompt 里）：
```
Thought: 推理过程
Action: respond[<最终答案>]   # 或 think[<继续思考>] 或 Finish[<最终答案>]
```
`_THOUGHT_RE` / `_ACTION_RE` / `_FINISH_RE` 三个正则解析；不匹配时直接把整段当 text response 提交。

**FunctionCall 默认工具集**（`src/harness/function_call.py` 的 `DEFAULT_TOOLS`）：
- `submit_answer(answer: string)` — 模型用这个提交最终答案
- `request_info(query: string)` — 模型想要更多信息时调用（DialogEnvironment 不响应它，所以会变成空转）

如果你的任务有真实工具，把 `tools` 列表通过 `extra_params.tools` 传进来覆盖默认。

## 3. `configs/environments.yaml`

```yaml
environments:
  <env_name>:
    class: "DialogEnvironment"
    dataset: "datasets/slot_filling/xiu_test.jsonl"   # 相对路径相对项目根；可绝对路径
    description: "报修预约槽位填充"
    max_steps: 1                                       # 环境侧步数上限
    extra_params:
      task_type: "slot_filling"
      intent_filter: "预约维修"      # 仅 Excel 数据源用：按意图过滤行
      slot_keys:                     # 待评测槽位列表（顺序无关）
        - product_name
        - product_brand
        # ...
      system_prompt_file: ""         # 可选：从外部文件读 system prompt
```

**Environment 注册表**（`src/environment/__init__.py` 的 `_ENV_REGISTRY`）：

| class 名 | 文件 | 适用任务 | 输出契约 |
|---|---|---|---|
| `DialogEnvironment` | `src/environment/dialog.py` | 多轮对话 + 槽位抽取 / JSON 信息提取 | agent 必须输出可解析的 JSON 字符串 |

**当前 codebase 只有 1 个 env 类**。需要新任务类型（代码生成、推理、工具调用 with 真实工具等）时必须先新增 env 类，见 `references/extending.md`。

**数据集文件支持的格式**（`Orchestrator._load_tasks`）：
- `.jsonl` — 每行一个 `TaskInstance` 的 JSON 字典，**推荐**
- `.json` — 顶层是 list 或 `{"tasks": [...]}` 包裹的 list
- `.xlsx` / `.xls` — 兼容历史 evalv3 格式，按 `conversation_id` 分组、按 `dialogue_count` 排序

**JSONL 单行 schema**（`TaskInstance` 字段）：
```json
{
  "task_id": "repair_001",
  "task_type": "slot_filling",
  "prompt": "用户输入文本...",
  "ground_truth": {"product_name": "空调", "...": "..."},
  "expected_slots": {"product_name": "空调", "...": "..."},
  "slot_keys": ["product_name", "product_brand", "..."],
  "conversation_history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "metadata": {"any": "thing"}
}
```

- 槽位填充任务里 `ground_truth` 和 `expected_slots` 通常一致；`expected_slots` 是 `DialogEnvironment._compare_fields` 真正用到的字段
- `slot_keys` 必填，决定评测的字段集合；缺则从 `expected_slots` 的 key 推断
- `conversation_history` 可选；存在时 env 会拼到 prompt 里

**特殊字段处理**（`DialogEnvironment._compare_fields`）：
- `fault_info_desc`：空对空、非空对非空都算对（语义模糊，不做精确匹配）
- `product_name`：`"空气能"` 归一化为 `"中央空调"`
- 其他字段做严格 `str.strip()` 后相等比较

## 4. `configs/experiments/<name>.yaml`

```yaml
experiment:
  name: "slot_filling_eval"
  description: "..."
  seed: 42
  output_dir: "outputs/slot_filling_eval"

  llm_profiles:                     # 取 llm_profiles.yaml 的 key
    - deepseek_v4_flash
  harness_profiles:                 # 取 harness_profiles.yaml 的 key
    - raw
  environments:                     # 取 environments.yaml 的 key
    - slot_filling_xiu

  execution:
    max_concurrent_tasks: 4         # 单组合内并行任务数
    max_concurrent_combos: 1        # 同时跑几个组合（看 GPU 显存）
    task_timeout_seconds: 120
    step_timeout_seconds: 60
    retry_on_api_error: 3
    retry_backoff_base: 2

  reporting:
    generate_excel: true
    generate_html_dashboard: true
    generate_trajectory_jsonl: true
    generate_case_studies: true
    generate_charts: true
    case_study_count: 10
```

跑的时候是三轴**笛卡尔积**：`|llm| × |harness| × |env|` 个组合。设计 experiment 时务必先在脑子里乘一下，再让用户确认。

**并发参数怎么调**：
- 远程 API（OpenAI 兼容公有云）：`max_concurrent_tasks=8-16`，`max_concurrent_combos=2-4`，限速由 API 端处理
- 本地 vLLM：取决于 GPU 显存和 batch size，通常 `max_concurrent_tasks=4-8`，`max_concurrent_combos=1`
- MockLLM：随便填，反正不真调

## 5. `configs/judge_profiles.yaml`（可选，LLM-as-Judge）

```yaml
judge_profiles:
  <judge_name>:
    class: "OpenAICompatibleLLM"
    model_name: "your-judge-model"
    endpoint_url: "https://your-judge-endpoint/v1/chat/completions"
    api_key_env: "JUDGE_API_KEY"     # 从环境变量读，比明文 api_key 安全
    temperature: 0.0
    max_tokens: 800
    threshold: 0.6                   # passed 与否的阈值
    allowed_labels:                  # 限制 judge 输出的标签集合
      - correct
      - format_error
      - missing_requirement
      - hallucination
      - incomplete_answer
      - weak_reasoning
    rubric: |
      请根据任务、参考答案和模型输出进行评审。
      评分范围 0-1，必须输出合法 JSON，字段含 score、passed、labels、comment、evidence、dimensions。
```

**强烈建议 judge 用独立模型**，不要让被评测模型给自己打分。在代码里用法见 README §LLM-as-Judge，目前 judge 不是主流程自动调用——是用户在自己代码里显式调 `LLMJudgeEvaluator`。

## 字段命名约定

- profile 名：`<provider>_<model>_<variant>`，如 `deepseek_v4_flash`、`qwen3_4b`、`gpt4o_mini`
- environment 名：`<task_type>_<scenario>`，如 `slot_filling_xiu`、`tool_use_weather`
- experiment 文件名：`<focus>.yaml`，如 `slot_filling.yaml`、`harness_comparison.yaml`
- output_dir：`outputs/<exp_name>` 或 `outputs/<exp_name>_<YYYYMMDD>`
