# Workflow: add-harness

新增一个 Harness 类（写新 agent 架构）。

> 这是中频操作。涉及 Python 写代码 + 多文件改动 + 注册。本 workflow 兜底"四步缺一不可"的注册流程，避免 skill 漏掉某一步。

## 触发条件

- 用户说"我想写一个新 agent 架构"、"加一个 Plan-and-Execute harness"、"接入 OpenManus 风格的 react"等
- 用户问"raw/react/function_call 之外还有没有别的 harness"——没有，需要自己写

## Step 0: 确认是否真的需要新写

很多时候用户说"我想试 X 架构"，其实改 `extra_params` 就够了：

| 用户需求 | 是否真要新 harness |
|---|---|
| "我想试不同的 ReAct system prompt" | ❌ 改 react profile 的 `extra_params.system_prompt` |
| "我想限制 ReAct 只能用某些动作" | ❌ 同上 |
| "我想给 FunctionCall 一组自定义 tools" | ❌ 改 function_call profile 的 `extra_params.tools` |
| "我想要 Plan-Then-Execute 两阶段" | ✅ 真需要新类 |
| "我想要 self-consistency voting" | ✅ 真需要新类 |
| "我想要 tree-of-thought" | ✅ 真需要新类 |

先用多选确认询问：

```
question: "在写新代码前先确认：你需要的是<总结需求>。这能否通过改 react/function_call 的 extra_params 实现？"
options:
  - "不能，确实需要新 harness 类（继续）"
  - "可能能，我先试改 extra_params"
```

## Step 1: 设计 harness 接口

按 `references/extending.md` 第 2 节，新类需要实现：
- `async def initial_action(self, task_prompt: str) -> Action`
- `async def next_action(self, observation: str) -> Action`
- `def is_finished(self) -> bool`

先跟用户对齐两个关键设计点：

1. **结束条件**：什么时候 `_finished = True`？常见有：
   - 模型输出特定 token（如 "Finish[...]"、`submit_answer` 工具）
   - 达到 max_steps
   - 拿到符合 schema 的输出
2. **状态管理**：需不需要维护 scratchpad / plan / vote_history 等？

## Step 2: 写代码

在 `src/harness/` 新建 `<your_name>.py`。**强烈建议参考现有三个文件**：
- 最简单：`src/harness/raw.py`（~80 行）
- 中等：`src/harness/react.py`（~130 行）
- 复杂：`src/harness/function_call.py`（~160 行）

骨架：

```python
from __future__ import annotations
import time
from ..llm.base import BaseLLM, LLMResponse
from .base import Action, BaseHarness, HarnessConfig


class YourHarness(BaseHarness):
    """<一句话说明你的架构>"""

    def __init__(self, llm: BaseLLM, config: HarnessConfig):
        super().__init__(llm, config)
        self._step_num: int = 0
        # 你的额外状态...

    async def initial_action(self, task_prompt: str) -> Action:
        # 1. 构造 messages（可读 config.extra_params 拿超参）
        # 2. await self._call_with_retries(lambda: self.llm.chat(messages))
        # 3. 解析响应 → Action
        # 4. self._record_step(...)
        # 5. return action
        ...

    async def next_action(self, observation: str) -> Action:
        self._step_num += 1
        if self._step_num >= self.config.max_steps:
            self._finished = True
            return Action(action_type="text_response", content=self._final_answer)
        # 类似 initial_action 的流程
        ...

    def is_finished(self) -> bool:
        return self._finished
```

**关键规约**（漏掉会让报告缺数据）：
- 每次 LLM 调用后必须调 `self._record_step(...)`，传 input_tokens / output_tokens / latency_ms
- 完成时设 `self._finished = True` **且** `self._final_answer = "..."`
- 用 `self._call_with_retries(...)` 包 LLM 调用，自动指数退避
- 如果你的 harness 维护消息历史，自己管 `self._messages` / `self._scratchpad` 等字段；基类的 `self.history` 是空容器，没强加结构

## Step 3: 在 4 处注册（容易漏！）

按这个顺序检查：

### 3.1 `src/core/orchestrator.py` 的 `_HARNESS_REGISTRY`

```python
from ..harness.your_module import YourHarness  # ← 加 import

_HARNESS_REGISTRY = {
    "RawHarness": RawHarness,
    "ReActHarness": ReActHarness,
    "FunctionCallHarness": FunctionCallHarness,
    "YourHarness": YourHarness,                  # ← 加这一行
}
```

### 3.2 `configs/harness_profiles.yaml` 加 profile

按 `references/configs.md` 第 2 节的 schema。建议至少提供两个 profile：一个"默认调参"、一个"激进调参"，方便用户对比。

### 3.3（可选）`src/harness/__init__.py` 暴露

如果有用户会 `from src.harness import YourHarness` 直接 import，加到 `__init__.py`；否则可不加。

### 3.4 测试用例

在 `tests/` 下加一个 `test_<your_harness>.py`：
```python
import asyncio
from src.llm.mock import MockLLM
from src.llm.base import LLMConfig
from src.harness.your_module import YourHarness
from src.harness.base import HarnessConfig

def test_your_harness_basic():
    llm = MockLLM(LLMConfig(model_name="mock", endpoint_url=""))
    harness = YourHarness(llm, HarnessConfig(name="t", max_steps=3))
    action = asyncio.run(harness.initial_action("test task"))
    assert action.content
    assert harness.is_finished() or harness.get_trajectory()
```

## Step 4: 冒烟测试

```bash
# 4.1 dry-run
eval-agent --llm deepseek_v4_flash --harness <your_harness> --env slot_filling_xiu --dry-run

# 4.2 真跑 1-3 条
eval-agent --llm deepseek_v4_flash --harness <your_harness> --env slot_filling_xiu --output-dir outputs/smoke_<your_harness>

# 4.3 看 trajectory
head -1 outputs/smoke_<your_harness>/trajectories/*.jsonl
```

`steps` 列表非空 + 每步有 thought（如适用）+ `final_answer` 非空 + `total_input_tokens > 0` → 通过。

## Step 5: 跟现有 harness 对比一轮

这是 harness 类的"成人礼"：

```yaml
# configs/experiments/<your_harness>_comparison.yaml
experiment:
  name: "<your_harness>_vs_baselines"
  llm_profiles: [deepseek_v4_flash]   # 单一 LLM，公平对比
  harness_profiles:
    - raw
    - react
    - <your_harness>                   # ← 新 harness 跟两个 baseline 同台
  environments:
    - slot_filling_xiu                # 或更适合你架构的 env
```

跑完后给用户对比表：

```
Harness        Success Rate    Avg Tokens    Avg Latency
raw            X%              Y             Z ms
react          X%              Y             Z ms
<your_harness> X%              Y             Z ms
```

如果新 harness 没显著优于 raw 但 token 显著更高 —— 直接告诉用户"目前看下来这个架构没体现出价值"，不要粉饰。

## 常见坑

| 症状 | 原因 | 对策 |
|---|---|---|
| `ValueError: 未注册的 Harness 类: 'YourHarness'` | 忘了改 `_HARNESS_REGISTRY` | 改 orchestrator.py |
| trajectory 里 steps 为空 | 忘了 `_record_step` | 每次 LLM 调用后必须调 |
| trajectory 里 `total_input_tokens = 0` | LLM 子类没正确填 `LLMResponse.input_tokens` | 不是 harness 问题，检查 LLM 子类 |
| 跑到 max_steps 才结束但其实早该完事 | `is_finished()` 没正确返回 True | 检查 `_finished` 何时设 True |
| 报告里 success 率明显高于人眼判断 | `final_answer` 抓错了内容 | 在 _record_step 之前 print 一下 final_answer 调试 |
