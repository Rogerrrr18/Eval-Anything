# 扩展：新增 LLM / Harness / Environment

每次新增组件涉及**多文件多处改动**，是最容易漏注册的环节。本文档把 4 步流程钉死，供 `workflows/add-llm.md` 和 `workflows/add-harness.md` 引用。

## 1. 新增 LLM 类（罕见）

绝大多数场景下**不需要新增 LLM 类**，因为 `OpenAICompatibleLLM` 覆盖所有 OpenAI API 兼容端点。只有这些情况才真的需要新写：

- 调一个非 OpenAI 协议的 SDK（如 Anthropic、Bedrock 原生协议、自研 RPC）
- 需要自定义请求/响应转换、签名、限速逻辑

### 步骤

1. **在 `src/llm/` 新建 `<your_name>.py`**，继承 `BaseLLM`，实现：
   - `async def chat(messages, temperature=None, max_tokens=None) -> LLMResponse`
   - `async def chat_stream(messages, ...) -> AsyncIterator[str]`
   - `async def chat_with_tools(messages, tools, tool_choice="auto", ...) -> LLMResponse`
   - 可选 `async def close(self)` 清理 client
2. **在 `src/llm/__init__.py` 的 `_LLM_REGISTRY` 注册**：
   ```python
   from .your_module import YourLLM
   _LLM_REGISTRY["YourLLM"] = YourLLM
   ```
3. **在 `configs/llm_profiles.yaml` 加 profile**：
   ```yaml
   llm_profiles:
     your_profile_name:
       class: "YourLLM"
       model_name: "..."
       endpoint_url: "..."
       # ...
   ```
4. **跑一次冒烟测试**：
   ```bash
   eval-agent --llm your_profile_name --harness raw --env slot_filling_xiu --dry-run
   eval-agent --llm your_profile_name --harness raw --env slot_filling_xiu  # 真跑 1-2 条
   ```

## 2. 新增 Harness 类（中频）

写新 agent 架构（如 Plan-and-Execute、自洽 voting、tree search）时用。

### 步骤

1. **在 `src/harness/` 新建 `<your_name>.py`**，继承 `BaseHarness`，实现：
   - `async def initial_action(self, task_prompt: str) -> Action`
   - `async def next_action(self, observation: str) -> Action`
   - `def is_finished(self) -> bool`
2. **善用基类提供的工具**：
   - `self._call_with_retries(lambda: self.llm.chat(...), label="...")` 自带指数退避
   - `self._record_step(...)` 记录 trajectory，会自动累计 tokens / latency
   - `self.history` 是你管理的消息历史（基类不强加结构）
3. **在 `src/core/orchestrator.py` 的 `_HARNESS_REGISTRY` 注册**：
   ```python
   from ..harness.your_module import YourHarness
   _HARNESS_REGISTRY = {
       "RawHarness": RawHarness,
       "ReActHarness": ReActHarness,
       "FunctionCallHarness": FunctionCallHarness,
       "YourHarness": YourHarness,            # ← 加这一行
   }
   ```
4. **在 `configs/harness_profiles.yaml` 加 profile**：
   ```yaml
   harness_profiles:
     your_harness_name:
       class: "YourHarness"
       max_steps: 10
       max_retries: 3
       timeout_per_step: 60
       description: "..."
       extra_params:
         your_custom_param: ...
   ```
5. **冒烟测试**：跟新 LLM 同样的 dry-run + 小数据集流程。

### 设计要点

- `initial_action` 和 `next_action` 都返回 `Action`（dataclass），字段：`action_type / content / tool_name / tool_args / metadata`
- 任务完成时设 `self._finished = True` 并把答案塞 `self._final_answer`
- **每次 LLM 调用后必须调 `self._record_step(...)`**，否则 trajectory 是空的，报告会缺数据
- 如果你需要把 reasoning 留给报告读者看，把 thought 放进 `_record_step(thought=...)` 参数

### 兼容性 checklist

- 你的 harness 产出的 `Action.content` 是不是会被现有 env 正确解析？`DialogEnvironment.step` 用 `action.content` 当 raw_output，然后用 `robust_json_parse` 解析。
- 如果你的 harness 依赖 `chat_with_tools`，记得在 skill 引导用户时提醒"所选 LLM 必须支持 function calling"。
- max_steps 跟 environment 的 max_steps 取 `min`（见 orchestrator `_run_single_task`）。

## 3. 新增 Environment 类（高频）

当前 codebase **只有 `DialogEnvironment`**。任何不是"输出 JSON 槽位"形态的任务都需要新 env。

### 常见 env 类型

| 任务类型 | 建议 env 名 | 输出契约 | 评分规则 |
|---|---|---|---|
| 单选 / 多选题 | `MultipleChoiceEnvironment` | "A" / "B" / "C" / "D" | 选项匹配 |
| 数学 / 推理 | `MathEnvironment` | 数值或表达式 | `sympy` 等价 / 数值容差 |
| 代码生成 | `CodeEnvironment` | 函数体 / 完整文件 | 跑 sandbox + 测试用例 |
| 工具调用 | `ToolEnvironment` | 一系列 `tool_call` Action | 调用图匹配 + 最终答案 |
| 自由文本（裁判打分） | `JudgeEnvironment` | 任意文本 | 调 `judge_profile` 打分 |

### 步骤

1. **在 `src/environment/` 新建 `<your_name>.py`**，继承 `BaseEnvironment`，实现：
   - `async def reset(self, task: TaskInstance) -> str` — 返回给 agent 的初始 observation
   - `async def step(self, action: Any) -> EnvStepResult` — 处理 action，返回 (observation, reward, terminated, truncated, info)
   - `def get_reward(self) -> float` — 最终分数 ∈ [0, 1]
2. **在 `src/environment/__init__.py` 的 `_ENV_REGISTRY` 注册**：
   ```python
   from .your_module import YourEnvironment
   _ENV_REGISTRY["YourEnvironment"] = YourEnvironment
   ```
3. **在 `configs/environments.yaml` 加 profile**：
   ```yaml
   environments:
     your_env_name:
       class: "YourEnvironment"
       dataset: "datasets/your_task/test.jsonl"
       description: "..."
       max_steps: 20
       extra_params:
         your_custom_param: ...
   ```
4. **准备数据集**：每行一个 `TaskInstance` JSON，字段含 task_id / prompt / ground_truth / metadata，以及你 env 需要的额外字段。
5. **冒烟测试**：同上。

### 设计要点

- `reset` 必须重置内部状态（清空累积分数、解析结果等）并把 `current_task` 存好
- `step` 通过 `action.content` 拿 agent 输出文本（或 `action.tool_args`），不要假定 action 类型
- `_mark_done(terminated=True)` 在评分完成后调，会让 `is_done()` 返回 True
- `get_info()` 返回的 dict 会被 orchestrator 写进 trajectory 的 `metadata.field_results / format_ok`，**报告依赖这两个 key**——如果你想让报告里显示字段级正确率，把 `field_results: {key: bool, ...}` 放进 `info`
- `EnvStepResult.info` 是单步的，`get_info()` 是任务级的，两者会被 orchestrator 合并

### Reward 设计建议

- 严格"全对/全错"任务（选择题、代码通过 vs 不通过）：reward ∈ {0, 1}
- 字段级任务：reward = 正确字段数 / 总字段数（`DialogEnvironment` 就是这样）
- 裁判型任务：reward = judge score（0-1）
- **强烈避免 reward 在 (0, 1) 区间但语义不清**——会让 case study 分类混乱

## 4. 验证 checklist

无论新增哪一层，提交前过一遍：

- [ ] `eval-agent --list-profiles` 能看到新 profile
- [ ] `eval-agent --<new-component> --dry-run` 不报错
- [ ] 小数据集（3-5 条）跑通，trajectory JSONL 非空、字段对齐
- [ ] 报告 HTML 能正常打开，新组合出现在矩阵里
- [ ] 在 `tests/` 下加一个单元测试（参考 `tests/test_e2e.py`）

## 5. 提交 PR 时

在 PR 描述里贴 dry-run 输出 + 一条任务的 trajectory JSON，方便 reviewer 复核接口契约。
