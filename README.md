# Agent Eval Pipeline

模块化 Agent 评测管线，支持 **LLM × Harness × Environment** 三维组合评测。

## 一键上手（推荐）

```bash
# 1. 装（pipx 隔离干净；也可以 pip install）
pipx install "git+https://github.com/Rogerrrr18/Eval-Anything.git"

# 2. 跑（首次自动启动配置向导，选 provider + 填 API key）
eval-anything

# 第一次会跳出向导：
#   ⮕ 选 LLM provider (OpenAI / DeepSeek / Qwen / Kimi / GLM / 本地 / 自定义)
#   ⮕ 填 API key (推荐用环境变量)
#   ⮕ 选默认模型
#   配置写到 ~/.config/eval-anything/，之后 `eval-anything` 直接进对话
```

之后日常使用：

```bash
eval-anything                              # 进对话模式（默认 driver）
eval-anything --driver openai_gpt4o_mini   # 临时切换驾驶 LLM
eval-anything --init                       # 重新跑配置向导
eval-anything --where                      # 看当前配置在哪
```

在对话里直接说"帮我跑一个 slot filling 评测"、"对比这几个模型"、"加一个新模型 profile"
之类，驾驶 LLM 会按 skill 内置的流程（5 步 4 闸门）带你走。



## 架构

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  LLM 层     │   │ Harness 层   │   │Environment层 │
│ (可替换后端) │   │ (可替换架构) │   │ (可替换环境) │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       └──────────┬──────┴──────────┬──────┘
                  ▼                 ▼
           ┌──────────┐     ┌──────────────┐
           │Orchestrator│    │ Metrics引擎   │
           │ (核心调度) │    │ (定量+定性)   │
           └──────┬────┘     └──────┬───────┘
                  ▼                 ▼
         ┌──────────────────────────────┐
         │     报告生成                  │
         │ Excel | HTML | JSONL | MD    │
         └──────────────────────────────┘
```

### 三层可替换组件

| 层 | 说明 | 已实现 |
|----|------|--------|
| **LLM** | 大模型后端 | `OpenAICompatibleLLM` (vLLM/SGLang/Ollama)、`MockLLM` |
| **Harness** | Agent 架构 | `RawHarness` (基线)、`ReActHarness`、`FunctionCallHarness` |
| **Environment** | 任务环境 | `DialogEnvironment` (槽位填充)、兼容 Excel/JSONL 数据 |

## 高级用法 / 开发模式

```bash
# 从源码开发
git clone https://github.com/Rogerrrr18/Eval-Anything.git
cd Eval-Anything
pip install -e .

# 生成示例数据
eval-anything --generate-sample-data

# 查看可用配置
eval-anything --list-profiles

# Dry run（不实际执行，查看将运行哪些组合）
eval-anything --experiment slot_filling --dry-run

# 运行评测
eval-anything --experiment slot_filling

# 指定单个组合
eval-anything --llm deepseek_v4_flash --harness raw --env slot_filling_xiu
```

## 配置目录在哪？

按以下优先级解析（高 → 低）：

1. `--config-dir` 显式传入
2. `EVAL_ANYTHING_CONFIG_DIR` 环境变量
3. **`~/.config/eval-anything/`**（pipx 安装后向导写入这里）
4. 当前工作目录下的 `./configs/`（在 repo 里开发时）
5. pip data-files 安装的默认 configs/
6. repo 源码内 `configs/`（fallback）

用 `eval-anything --where` 看当前生效的是哪个。

安装后两个命令等价（`eval-agent` 是别名）：

```bash
eval-anything --list-profiles
eval-agent --experiment slot_filling --dry-run
eval-agent --llm deepseek_v4_flash --harness raw --env slot_filling_xiu
```

## 配置说明

### LLM 配置 (`configs/llm_profiles.yaml`)

每个 profile 定义一个 LLM 端点：

```yaml
llm_profiles:
  my_model:
    class: "OpenAICompatibleLLM"
    model_name: "my-model"
    endpoint_url: "http://your-host:port/v1/chat/completions"
    api_key: "EMPTY"
    temperature: 0.0
    max_tokens: 600
```

兼容所有 OpenAI API 兼容的推理服务（vLLM / SGLang / LMStudio / Ollama 等）。

### Harness 配置 (`configs/harness_profiles.yaml`)

```yaml
harness_profiles:
  raw:
    class: "RawHarness"
    max_steps: 1
    description: "直接 prompt-in / response-out 基线"
```

### Environment 配置 (`configs/environments.yaml`)

支持 `.jsonl`、`.json`、`.xlsx` 三种数据格式：

```yaml
environments:
  my_task:
    class: "DialogEnvironment"
    dataset: "datasets/my_task.jsonl"  # 或 .xlsx 绝对路径
    extra_params:
      slot_keys: [field1, field2, ...]
```

### 实验配置 (`configs/experiments/*.yaml`)

指定要测试的 LLM × Harness × Environment 组合矩阵：

```yaml
experiment:
  name: "my_eval"
  llm_profiles: [model_a, model_b]
  harness_profiles: [raw, react]
  environments: [task_a, task_b]
```

## 数据格式

### JSONL 格式（推荐）

每行一个测试用例：

```json
{
  "task_id": "repair_001",
  "task_type": "slot_filling",
  "prompt": "用户输入文本...",
  "expected_slots": {"product_name": "空调", ...},
  "slot_keys": ["product_name", "product_brand", ...]
}
```

### Excel 格式（兼容现有 evalv3）

直接使用 `.xlsx` 文件，需要包含 `conversation_id`、`dialogue_count`、`query` 等列以及各槽位列。自动解析多轮对话。

## 输出报告

| 报告 | 格式 | 内容 |
|------|------|------|
| 详细结果 | Excel | 逐条结果、字段对比、黄色标错 |
| 统计汇总 | Excel | 每个组合的成功率、平均得分 |
| 模型对比 | Excel | LLM × Harness 成功率热力图 |
| 仪表盘 | HTML | 可视化看板（热力图、字段级分析） |
| 轨迹日志 | JSONL | 完整执行步骤记录 |
| 案例研究 | Markdown | 失败分类、代表性案例、分析洞察 |

## 扩展

### 添加新 LLM

1. 在 `src/llm/` 下创建新类，继承 `BaseLLM`
2. 实现 `chat()` / `chat_stream()` / `chat_with_tools()`
3. 在 `configs/llm_profiles.yaml` 中添加配置

### 添加新 Harness

1. 在 `src/harness/` 下创建新类，继承 `BaseHarness`
2. 实现 `initial_action()` / `next_action()` / `is_finished()`
3. 在 `src/core/orchestrator.py` 的 `_HARNESS_REGISTRY` 注册
4. 在 `configs/harness_profiles.yaml` 中添加配置

### 添加新 Environment

1. 在 `src/environment/` 下创建新类，继承 `BaseEnvironment`
2. 实现 `reset()` / `step()` / `get_reward()`
3. 在 `src/environment/__init__.py` 的 `_ENV_REGISTRY` 注册
4. 在 `configs/environments.yaml` 中添加配置

## 评测指标

### 定量指标
- 任务完成率（全对比例）
- 字段级准确率
- JSON 格式合规率
- Token 使用效率
- 平均完成步数
- 错误恢复率

### 定性分析
- 失败模式自动分类
- 成功模式统计
- 接近成功案例（Near Misses）
- LLM × Harness 对比洞察

### LLM-as-Judge

在 `configs/judge_profiles.yaml` 中配置裁判模型：

```yaml
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

代码中使用：

```python
from src.core.config import ConfigLoader
from src.metrics import LLMJudgeEvaluator

loader = ConfigLoader("configs")
profile = loader.get_judge_profile("default_judge")
judge = LLMJudgeEvaluator.from_profile(profile)
result = await judge.evaluate_async(prediction, reference, task=task_prompt)
```

Judge 需要返回 JSON：`score`、`passed`、`labels`、`comment`、`evidence`、`dimensions`。
