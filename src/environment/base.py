"""
Environment 抽象层 — Gym 风格的任务环境接口。

所有任务环境继承 BaseEnvironment，实现 reset / step / get_reward。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EnvConfig:
    """环境配置，从 YAML environments 加载。"""
    name: str
    dataset: str = ""
    description: str = ""
    max_steps: int = 20
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnvStepResult:
    """Gym 风格的 step 返回值。"""
    observation: str
    reward: float
    terminated: bool          # 任务自然结束（成功或失败）
    truncated: bool           # 达到步数 / 时间上限
    info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskInstance:
    """单个测试用例定义，从数据集加载。"""
    task_id: str
    task_type: str
    prompt: str               # 初始任务描述
    ground_truth: Any         # 期望输出（用于评分）
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ── 槽位填充专用字段 ──
    conversation_history: Optional[List[Dict[str, str]]] = None   # 多轮对话历史
    expected_slots: Optional[Dict[str, Any]] = None              # 期望槽位值
    slot_keys: Optional[List[str]] = None                        # 槽位键名列表


class BaseEnvironment(ABC):
    """任务环境抽象基类。

    Gym 风格接口: reset(task) -> initial_observation, step(action) -> EnvStepResult。
    每个环境封装了任务逻辑、ground truth 和评分规则。
    """

    def __init__(self, config: EnvConfig):
        self.config = config
        self.current_task: Optional[TaskInstance] = None
        self.step_count: int = 0
        self._done: bool = False

    @abstractmethod
    async def reset(self, task: TaskInstance) -> str:
        """初始化环境，加载一个任务实例。

        Returns:
            初始观察（任务描述 + 起始状态）。
        """
        ...

    @abstractmethod
    async def step(self, action: Any) -> EnvStepResult:
        """处理 harness 发来的 action。

        Returns:
            EnvStepResult: (observation, reward, terminated, truncated, info)
        """
        ...

    @abstractmethod
    def get_reward(self) -> float:
        """在任务结束后计算最终分数。返回 [0.0, 1.0]。"""
        ...

    def is_done(self) -> bool:
        """任务是否已结束。"""
        return self._done

    def get_info(self) -> Dict[str, Any]:
        """返回任务执行的补充信息。"""
        return {
            "task_id": self.current_task.task_id if self.current_task else None,
            "steps_taken": self.step_count,
            "env_name": self.config.name,
        }

    def _mark_done(self, terminated: bool = False, truncated: bool = False) -> None:
        """标记任务结束。"""
        self._done = terminated or truncated
