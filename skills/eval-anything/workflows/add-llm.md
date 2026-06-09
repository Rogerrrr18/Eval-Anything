# Workflow: add-llm

接入一个新 LLM profile（不需要写新类，只是新建配置）。

> 这是高频操作。绝大多数情况下用户说"加个 GPT-4"、"接入 DeepSeek 平台"、"我的 vLLM 起了个新模型"时走这里，**不需要碰 `src/llm/` 代码**。

## 触发条件

- 用户说"加一个 LLM profile"、"接入 X 模型"、"我刚部署了一个新端点"
- 在 design-experiment workflow 的 Step 3 中用户需要新 LLM

## 前置检查

```bash
eval-agent --list-profiles --config-dir <repo>/configs
```

看现有有哪些，避免重复名字。

## Step 1: 收集端点信息

问用户（用多选确认或自由对话，看复杂度）：

| 字段 | 必填 | 例子 |
|---|---|---|
| profile 名 | 是 | `gpt4o_mini`、`deepseek_v3_chat`、`qwen3_4b_local` |
| `model_name`（API 那一侧的 model id） | 是 | `gpt-4o-mini`、`deepseek-chat`、`Qwen3-4B-Instruct` |
| `endpoint_url` | 是 | `https://api.openai.com/v1/chat/completions` |
| `api_key` 或 `api_key_env` | 视端点而定 | `sk-...`（不推荐明文） / 留 `EMPTY` |
| 是否支持 function calling | 是 | 用于决定能不能跟 `function_call` harness 配 |
| 是否要 reasoning（enable_thinking） | 否 | DeepSeek-V3.x、Qwen3-Thinking 才用得到 |

## Step 2: 写入 `configs/llm_profiles.yaml`

**追加在文件末尾**，不要改现有条目。用 `templates/llm_profile.yaml.j2` 的格式（如果没有该模板，按 `references/configs.md` 第 1 节的 schema 手写）。

```yaml
# 在文件末尾追加：
  <profile_name>:
    class: "OpenAICompatibleLLM"
    model_name: "<api_model_id>"
    endpoint_url: "<full_url_with_chat_completions>"
    api_key: "EMPTY"        # ← 留 EMPTY 或 ${OPENAI_API_KEY}；不要写真 key 到 repo
    temperature: 0.0
    max_tokens: 600
    top_p: 1.0
    timeout_seconds: 30
    enable_thinking: false
    extra_params: {}
```

**安全护栏**：
- 如果用户给你真实 api key，**不要**直接写进 YAML。提示用户 `export OPENAI_API_KEY=sk-...` 然后改 YAML 为 `api_key: "${OPENAI_API_KEY}"` 或留 `EMPTY` 由 client 库自动从环境变量取。
- 如果是公司内网端点（含 `localhost`、`10.x`、`192.168.x`），加一行注释 `# 内网端点，请勿提交到公开仓库`。

## Step 3: 冒烟测试

### 3.1 看 list 能不能识别

```bash
eval-agent --list-profiles --config-dir <repo>/configs
```

新 profile 应该出现在 LLM 列表里，`endpoint_url` 正确。

### 3.2 跑一条最简组合

挑一个最便宜最快的 (harness, env) 组合验通：

```bash
eval-agent --llm <new_profile> --harness raw --env slot_filling_xiu --config-dir <repo>/configs --dry-run
```

dry-run 通过后：

```bash
# 临时把 environment 的 dataset 指向一个只有 1-3 条的小集，或：
eval-agent --llm <new_profile> --harness raw --env slot_filling_xiu --config-dir <repo>/configs --output-dir outputs/smoke_<profile>
```

跑通后看一眼 trajectory：
```bash
head -1 outputs/smoke_<profile>/trajectories/*.jsonl
```

`final_answer` 字段非空 + `total_input_tokens > 0` 就算成功。

## Step 4: 写一个"特征卡"返回给用户

跑通后告诉用户：

```
✅ 已接入 <profile_name>

▸ Endpoint: <url>
▸ Function calling: 支持 / 不支持
▸ 冒烟测试: 1 条任务，<status>，<n> tokens，<ms>ms

可以用法:
  eval-agent --llm <profile_name> --harness raw --env <any_env>
  eval-agent --llm <profile_name> --harness function_call --env <tool_env>   # ← 仅当支持 fc
  在 experiment YAML 的 llm_profiles 列表里加上 "<profile_name>"
```

## 常见坑

| 症状 | 原因 | 对策 |
|---|---|---|
| HTTP 401 / 403 | api_key 错或 endpoint 校验 | 检查 key、检查 `endpoint_url` 是否带 `/v1/chat/completions` |
| HTTP 404 | URL 路径不对 | OpenAI 兼容必须是 `/v1/chat/completions`，不是 `/v1/completions` |
| 响应 200 但 content 为空 | 模型名错或 vLLM 没起这个模型 | 跟运维确认 `model_name` 跟 vLLM 启动参数一致 |
| function_call harness 跑通但 `submit_answer` 从来不触发 | 模型不支持 tools | 换 harness 或换 LLM |
| 偶发 timeout | 端点慢或网络抖动 | 调高 `timeout_seconds`、降并发 |
