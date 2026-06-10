# Eval-Anything

模块化 **Agent 评测管线** + **Agent Skill**，支持 LLM × Harness × Environment 三维组合评测。

两种用法（互不依赖）：
- **作为 Python CLI** — 直接跑评测、出报告
- **作为 Agent Skill** — 把 `skills/eval-anything/` 丢给任意 coding agent（Claude Code / Cursor Agent / ...），让它按 5 步 4 闸门流程驱动你完成完整评测

---

## 1. 装

```bash
# pipx 隔离（推荐）
pipx install "git+https://github.com/Rogerrrr18/Eval-Anything.git"

# 或源码开发模式
git clone https://github.com/Rogerrrr18/Eval-Anything.git
cd Eval-Anything
pip install -e .
```

---

## 2. 用法 A：Python CLI（裸跑评测）

```bash
# 生成示例数据
eval-anything --generate-sample-data

# 列出可用配置
eval-anything --list-profiles --config-dir configs/

# Dry run（不真跑，看将运行哪些组合）
eval-anything --experiment slot_filling --dry-run --config-dir configs/

# 跑预设实验
eval-anything --experiment slot_filling --config-dir configs/

# 指定单一组合
eval-anything --llm deepseek_v4_flash --harness raw --env slot_filling_xiu --config-dir configs/
```

安装后 `eval-anything` 与 `eval-agent` 等价（别名）。

---

## 3. 用法 B：Agent Skill（让任意 coding agent 驱动你跑评测）

`skills/eval-anything/` 是一份自包含的 **agent skill**：决策树、自动选择算法、模板、4 道人工闸门规约全在里面。**不绑定任何具体 agent / LLM**——你用 Claude Code 就 Claude Code，用 Cursor Agent 就 Cursor Agent，agent 用自己原生的 `Read`/`Write`/`Edit`/`Bash` 工具操作仓库即可。

### 喂给 Claude Code

在仓库根目录起一个 Claude Code 会话，告诉它：

> "把 `skills/eval-anything/SKILL.md` 当作 system prompt 读进来。我想跑一个评测/对比这些模型/接入新 LLM/..."

它会按 SKILL.md 里的入口路由分发到对应 workflow，并强制走 4 道闸门让你确认。

### 喂给其他 coding agent

任何能读文件 + 跑 shell 的 agent 都行。告诉它：

> "Read `skills/eval-anything/SKILL.md`，按里面规定的流程帮我设计/运行/解读评测。所有人工确认环节直接向我提问。"

### Skill 内部结构

```
skills/eval-anything/
├─ SKILL.md                          ← 入口路由（决策树 + 闸门规约）
├─ references/                       ← Ground truth，agent 必须 Read 后再下笔
│  ├─ cli.md                         CLI 参数手册
│  ├─ configs.md                     4 类 YAML 的字段 schema
│  ├─ datasets.md                    任务类型 → 开源测试集映射
│  ├─ reports.md                     报告产物解读
│  ├─ extending.md                   新增 LLM / Harness / Env 注册步骤
│  └─ harness-selection.md           Harness 自动选择算法（Step 3 必读）
├─ workflows/                        ← 流程剧本
│  ├─ design-experiment.md           主流程：5 步 4 闸门
│  ├─ add-llm.md
│  ├─ add-harness.md
│  ├─ compare-models.md
│  └─ mock-dataset.md
└─ templates/                        ← Jinja 模板（agent 用 Write 工具落盘）
   ├─ dataset.jsonl.j2
   ├─ environment.yaml.j2
   ├─ experiment.yaml.j2
   └─ mock_synthesis_prompt.md
```

### 主流程：5 步 4 强制闸门

```
Step 1: 任务类型识别        ──► 闸门 1（确认任务类型 + 评测维度）
Step 2: 数据集来源选择      ──► 闸门 2（开源 / Mock / 自有 / 混合）
                              └─ Mock 分支 ──► 闸门 2b（审核 3 条样例）
Step 3: 自动选 harness + 生成配置 YAML
                              ──► 闸门 3（看 diff 后确认写盘）
Step 4: --dry-run 展示组合数 + 预估耗时
                              ──► 闸门 4（开跑确认）
Step 5: 跑完读报告 + 输出洞察小结
```

`workflows/design-experiment.md` 是主入口，**Step 3 的 harness 选择由 agent 按 `references/harness-selection.md` 内嵌算法自动算**，不再单独问用户"你要 raw 还是 react"——只在闸门 3 的 diff 里展示决策依据让用户拍板。

---

## 4. 架构

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│  LLM 层     │   │ Harness 层  │   │Environment层 │
│ (可替换后端) │   │ (可替换架构) │   │ (可替换环境) │
└──────┬──────┘   └──────┬──────┘   └──────┬──────┘
       └──────────┬──────┴──────────┬──────┘
                  ▼                 ▼
           ┌────────────┐    ┌──────────────┐
           │Orchestrator│    │ Metrics 引擎 │
           │ (核心调度) │    │ (定量+定性)  │
           └──────┬─────┘    └──────┬───────┘
                  ▼                 ▼
         ┌──────────────────────────────┐
         │  报告生成                    │
         │  Excel | HTML | JSONL | MD   │
         └──────────────────────────────┘
```

### 三层可替换组件

| 层 | 说明 | 已实现 |
|----|------|--------|
| **LLM** | 大模型后端 | `OpenAICompatibleLLM` (vLLM/SGLang/Ollama/任何 OpenAI 兼容 API)、`MockLLM` |
| **Harness** | Agent 架构 | `RawHarness` (baseline)、`ReActHarness`、`FunctionCallHarness` |
| **Environment** | 任务环境 | `DialogEnvironment` (槽位填充 / JSONL 数据集)，可扩展 |

---

## 5. 配置说明

所有配置都在 `--config-dir` 指定的目录里（默认 `./configs/`）。

### LLM 配置 (`configs/llm_profiles.yaml`)

```yaml
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

兼容所有 OpenAI API 兼容的推理服务（vLLM / SGLang / LMStudio / Ollama / DeepSeek / Qwen / Kimi / GLM 等）。**绝不要把真实 key 写进 yaml**——用 `api_key_env` 或 `${VAR}` 占位。

### Harness 配置 (`configs/harness_profiles.yaml`)

```yaml
harness_profiles:
  raw:
    class: "RawHarness"
    max_steps: 1
    description: "直接 prompt-in / response-out 基线"
```

### Environment 配置 (`configs/environments.yaml`)

```yaml
environments:
  my_task:
    class: "DialogEnvironment"
    dataset: "datasets/my_task.jsonl"
    extra_params:
      slot_keys: [field1, field2, ...]
```

支持 `.jsonl`、`.json`、`.xlsx` 三种数据格式。

### 实验配置 (`configs/experiments/*.yaml`)

```yaml
experiment:
  name: "my_eval"
  llm_profiles: [model_a, model_b]
  harness_profiles: [raw, react]
  environments: [task_a, task_b]
```

---

## 6. 数据格式

### JSONL（推荐）

```json
{
  "task_id": "repair_001",
  "task_type": "slot_filling",
  "prompt": "用户输入文本...",
  "expected_slots": {"product_name": "空调", ...},
  "slot_keys": ["product_name", "product_brand", ...]
}
```

### Excel

`.xlsx` 文件，需包含 `conversation_id`、`dialogue_count`、`query` 等列以及各槽位列。自动解析多轮对话。

---

## 7. 输出报告

| 报告 | 格式 | 内容 |
|------|------|------|
| 详细结果 | Excel | 逐条结果、字段对比、黄色标错 |
| 统计汇总 | Excel | 每个组合的成功率、平均得分 |
| 模型对比 | Excel | LLM × Harness 成功率热力图 |
| 仪表盘 | HTML | 可视化看板（热力图、字段级分析） |
| 轨迹日志 | JSONL | 完整执行步骤记录 |
| 案例研究 | Markdown | 失败分类、代表性案例、分析洞察 |

---

## 8. 扩展

### 添加新 LLM

1. 在 `src/llm/` 下创建新类，继承 `BaseLLM`
2. 实现 `chat()` / `chat_stream()` / `chat_with_tools()`
3. 在 `configs/llm_profiles.yaml` 中添加 profile

### 添加新 Harness

1. 在 `src/harness/` 下创建新类，继承 `BaseHarness`
2. 实现 `initial_action()` / `next_action()` / `is_finished()`
3. 在 `src/core/orchestrator.py` 的 `_HARNESS_REGISTRY` 注册
4. 在 `configs/harness_profiles.yaml` 中添加 profile

### 添加新 Environment

1. 在 `src/environment/` 下创建新类，继承 `BaseEnvironment`
2. 实现 `reset()` / `step()` / `get_reward()`
3. 在 `src/environment/__init__.py` 的 `_ENV_REGISTRY` 注册
4. 在 `configs/environments.yaml` 中添加 profile

详见 `skills/eval-anything/references/extending.md`。

---

## 9. 评测指标

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

Judge 需返回 JSON：`score`、`passed`、`labels`、`comment`、`evidence`、`dimensions`。

---

## 10. Star 监控面板

仓库自带一个零依赖的 **GitHub Star 监控仪表盘**（纯静态 HTML，无需后端、无需 token）：

```bash
# macOS
open tools/star_dashboard.html

# Linux
xdg-open tools/star_dashboard.html

# Windows
start tools/star_dashboard.html
```

页面会调 GitHub 公开 API 拉本仓库的 stargazers 数据，画出：

- 当前总 star 数 + 与上周对比
- 累计 star 曲线（按真实 starred_at 时间戳）
- 最近 30 天每日新增
- 最近 stargazers 列表（头像 + 时间）

默认监控 `Rogerrrr18/Eval-Anything`。**改顶部 `REPO` 常量**可以盯任意公开仓库。未鉴权请求每小时 60 次配额（足够日常刷新）；如果想长期跑，给 URL 加 `?token=ghp_xxx` 提升到 5000/h。
