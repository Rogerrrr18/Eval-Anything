"""
配置管理 — 从 YAML 加载实验配置。
"""
from __future__ import annotations

import os
import re
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ── 配置数据类 ──

@dataclass
class ExecutionConfig:
    max_concurrent_tasks: int = 4
    max_concurrent_combos: int = 2
    task_timeout_seconds: int = 120
    step_timeout_seconds: int = 60
    retry_on_api_error: int = 3
    retry_backoff_base: float = 2.0


@dataclass
class ReportingConfig:
    generate_excel: bool = True
    generate_html_dashboard: bool = True
    generate_trajectory_jsonl: bool = True
    generate_case_studies: bool = True
    generate_charts: bool = True
    case_study_count: int = 10


@dataclass
class ExperimentConfig:
    name: str
    description: str = ""
    seed: int = 42
    output_dir: str = "outputs"
    llm_profiles: List[str] = field(default_factory=list)
    harness_profiles: List[str] = field(default_factory=list)
    environments: List[str] = field(default_factory=list)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    pairwise_judge: Optional[str] = None  # 可选：pairwise 对比用的 judge 名字（来自 judge_profiles.yaml）
    resume: bool = False  # CLI --resume 注入：跳过 stream JSONL 里已完成的任务（error/timeout 会重跑）


# ── Profile 加载 ──

@dataclass
class LLMProfile:
    """一个 LLM 端点的配置。

    api_key 解析顺序:
      1. yaml 里直接写明文 api_key
      2. yaml 里写 api_key_env: SOME_VAR → 从环境变量 SOME_VAR 读
      3. yaml 里写 api_key: "${SOME_VAR}" → 同样从环境变量读（更紧凑）
      4. 都没有 → 默认 "EMPTY"（本地 vLLM 等不校验的端点适用）
    """
    name: str
    class_name: str = "OpenAICompatibleLLM"
    model_name: str = ""
    endpoint_url: str = ""
    api_key: str = "EMPTY"
    api_key_env: Optional[str] = None
    temperature: float = 0.0
    max_tokens: int = 600
    top_p: float = 1.0
    timeout_seconds: int = 30
    enable_thinking: bool = False
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JudgeProfile:
    """一个 LLM-as-Judge 裁判配置。"""
    name: str
    class_name: str = "OpenAICompatibleLLM"
    model_name: str = ""
    endpoint_url: str = ""
    api_key: str = "EMPTY"
    temperature: float = 0.0
    max_tokens: int = 800
    top_p: float = 1.0
    timeout_seconds: int = 60
    enable_thinking: bool = False
    rubric: str = ""
    allowed_labels: List[str] = field(default_factory=list)
    threshold: float = 0.6
    system_prompt: Optional[str] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class JudgePanelProfile:
    """LLM-as-Judge 评审团配置（多个跨家族裁判联合打分）。

    members 引用现有 judge_profiles.yaml 里的 JudgeProfile 名字。
    跨家族（如 OpenAI + Anthropic + Qwen）才能真正抵消单家族的系统性偏差。
    """
    name: str
    members: List[str] = field(default_factory=list)
    aggregation: str = "trimmed_mean"   # mean | median | trimmed_mean | majority
    disagreement_threshold: float = 0.3  # max(scores) - min(scores) > 阈值 → 标 panel_disagree
    require_diverse_families: bool = True  # True 时同家族 ≥ 2 个仅 warning（不阻塞）
    min_label_support: str = "ceil_half"    # ceil_half | majority | all
    description: str = ""


@dataclass
class HarnessProfile:
    """一个 Harness 架构的配置。"""
    name: str
    class_name: str = "RawHarness"
    max_steps: int = 1
    max_retries: int = 3
    timeout_per_step: int = 60
    description: str = ""
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnvironmentProfile:
    """一个环境的配置。"""
    name: str
    class_name: str = "DialogEnvironment"
    dataset: str = ""
    description: str = ""
    max_steps: int = 20
    target: Optional[str] = None       # 引用 TargetProfile，用于评测完整应用/服务
    judge: Optional[str] = None        # 引用单个 JudgeProfile
    judge_panel: Optional[str] = None  # 引用 JudgePanelProfile，与 judge 二选一，panel 优先
    calibration_set: Optional[str] = None  # 可选：校准集路径（JSONL），配置后会在主任务跑完后自动跑 judge 校准
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TargetProfile:
    """一个被测系统配置。可以是 HTTP App、CLI、浏览器应用等。"""
    name: str
    class_name: str = "HTTPAppTarget"
    base_url: str = ""
    endpoints: Dict[str, str] = field(default_factory=dict)
    headers: Dict[str, str] = field(default_factory=dict)
    api_key: str = "EMPTY"
    api_key_env: Optional[str] = None
    timeout_seconds: int = 60
    description: str = ""
    extra_params: Dict[str, Any] = field(default_factory=dict)


# ── 配置加载器 ──

class ConfigLoader:
    """从 YAML 文件加载所有配置。"""

    def __init__(self, config_dir: str = "configs"):
        self.config_dir = self._resolve_config_dir(config_dir)
        self.project_root = self.config_dir.parent
        self._llm_profiles: Optional[Dict[str, LLMProfile]] = None
        self._judge_profiles: Optional[Dict[str, JudgeProfile]] = None
        self._judge_panels: Optional[Dict[str, JudgePanelProfile]] = None
        self._harness_profiles: Optional[Dict[str, HarnessProfile]] = None
        self._env_profiles: Optional[Dict[str, EnvironmentProfile]] = None
        self._target_profiles: Optional[Dict[str, TargetProfile]] = None

    def _resolve_config_dir(self, config_dir: str) -> Path:
        """解析配置目录，兼容源码运行和 pip 安装后的 data-files。"""
        raw_path = Path(config_dir).expanduser()
        candidates = []
        if raw_path.is_absolute():
            candidates.append(raw_path)
        else:
            candidates.extend([
                Path.cwd() / raw_path,
                Path(__file__).resolve().parents[2] / raw_path,
                Path(sysconfig.get_path("data")) / "eval-anything" / raw_path,
            ])

        for candidate in candidates:
            if candidate.exists():
                return candidate.resolve()

        return (Path.cwd() / raw_path).resolve()

    def load_experiment(self, experiment_file: str) -> ExperimentConfig:
        """加载实验配置。"""
        path = self.config_dir / "experiments" / experiment_file
        if not path.exists():
            path = Path(experiment_file)
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        exp = raw.get("experiment", raw)
        execution_raw = exp.get("execution", {})
        reporting_raw = exp.get("reporting", {})

        return ExperimentConfig(
            name=exp.get("name", "unnamed"),
            description=exp.get("description", ""),
            seed=exp.get("seed", 42),
            output_dir=exp.get("output_dir", "outputs"),
            llm_profiles=exp.get("llm_profiles", []),
            harness_profiles=exp.get("harness_profiles", []),
            environments=exp.get("environments", []),
            execution=ExecutionConfig(**execution_raw) if execution_raw else ExecutionConfig(),
            reporting=ReportingConfig(**reporting_raw) if reporting_raw else ReportingConfig(),
            pairwise_judge=exp.get("pairwise_judge"),
        )

    def load_llm_profiles(self) -> Dict[str, LLMProfile]:
        """加载所有 LLM profile。"""
        if self._llm_profiles is not None:
            return self._llm_profiles

        path = self.config_dir / "llm_profiles.yaml"
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        profiles = {}
        for name, cfg in raw.get("llm_profiles", {}).items():
            api_key = self._resolve_api_key(
                raw_key=cfg.get("api_key", "EMPTY"),
                key_env=cfg.get("api_key_env"),
            )
            profiles[name] = LLMProfile(
                name=name,
                class_name=cfg.get("class", "OpenAICompatibleLLM"),
                model_name=self._resolve_env_value(cfg.get("model_name", name)),
                endpoint_url=self._resolve_env_value(cfg.get("endpoint_url", "")),
                api_key=api_key,
                api_key_env=cfg.get("api_key_env"),
                temperature=cfg.get("temperature", 0.0),
                max_tokens=cfg.get("max_tokens", 600),
                top_p=cfg.get("top_p", 1.0),
                timeout_seconds=cfg.get("timeout_seconds", 30),
                enable_thinking=cfg.get("enable_thinking", False),
                extra_params=cfg.get("extra_params", {}),
            )
        self._llm_profiles = profiles
        return profiles

    @staticmethod
    def _resolve_env_value(raw: Any) -> Any:
        """通用 ${VAR} / ${VAR:-default} 环境变量插值。

        支持三种形态：
          1. 不含 ${...} → 原样返回（数值 / bool / list 等也走这里直接返回）
          2. "${VAR}" → 读 VAR；未设则保留原 placeholder（让下游报错，避免静默用空串）
          3. "${VAR:-default}" → 读 VAR；未设则用 default

        允许字符串里嵌入多个 ${...}，每个独立解析。
        """
        if not isinstance(raw, str) or "${" not in raw:
            return raw

        pattern = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

        def _sub(match: "re.Match[str]") -> str:
            var = match.group(1)
            default = match.group(2)
            val = os.getenv(var)
            if val is not None and val != "":
                return val
            if default is not None:
                return default
            # 没设 + 没 default → 保留原 placeholder，让用户在第一次调用时看见
            return match.group(0)

        return pattern.sub(_sub, raw)

    @classmethod
    def _resolve_api_key(cls, raw_key: str, key_env: Optional[str]) -> str:
        """解析 api_key。

        优先级:
          1. api_key_env 显式指定的环境变量
          2. raw_key 中的 ${VAR} / ${VAR:-default} 替换
          3. raw_key 本身（明文，或 "EMPTY"）
        """
        if key_env:
            val = os.getenv(key_env)
            if val:
                return val
            # 落到 raw_key 兜底（可能也是 EMPTY）
        return cls._resolve_env_value(raw_key)

    def load_judge_profiles(self) -> Dict[str, JudgeProfile]:
        """加载所有 LLM Judge profile。不存在配置文件时返回空字典。"""
        if self._judge_profiles is not None:
            return self._judge_profiles

        path = self.config_dir / "judge_profiles.yaml"
        if not path.exists():
            self._judge_profiles = {}
            return self._judge_profiles

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        profiles = {}
        for name, cfg in raw.get("judge_profiles", {}).items():
            api_key = cfg.get("api_key", "EMPTY")
            api_key_env = cfg.get("api_key_env")
            if api_key_env and os.getenv(api_key_env):
                api_key = os.getenv(api_key_env, api_key)

            profiles[name] = JudgeProfile(
                name=name,
                class_name=cfg.get("class", "OpenAICompatibleLLM"),
                model_name=self._resolve_env_value(cfg.get("model_name", name)),
                endpoint_url=self._resolve_env_value(cfg.get("endpoint_url", "")),
                api_key=api_key,
                temperature=cfg.get("temperature", 0.0),
                max_tokens=cfg.get("max_tokens", 800),
                top_p=cfg.get("top_p", 1.0),
                timeout_seconds=cfg.get("timeout_seconds", 60),
                enable_thinking=cfg.get("enable_thinking", False),
                rubric=cfg.get("rubric", ""),
                allowed_labels=cfg.get("allowed_labels", []),
                threshold=cfg.get("threshold", 0.6),
                system_prompt=cfg.get("system_prompt"),
                extra_params=cfg.get("extra_params", {}),
            )
        self._judge_profiles = profiles
        return profiles

    def load_judge_panels(self) -> Dict[str, JudgePanelProfile]:
        """加载所有 Judge Panel profile。不存在配置文件时返回空字典。"""
        if self._judge_panels is not None:
            return self._judge_panels

        path = self.config_dir / "judge_panels.yaml"
        if not path.exists():
            self._judge_panels = {}
            return self._judge_panels

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        panels = {}
        for name, cfg in raw.get("judge_panels", {}).items():
            panels[name] = JudgePanelProfile(
                name=name,
                members=list(cfg.get("members", [])),
                aggregation=cfg.get("aggregation", "trimmed_mean"),
                disagreement_threshold=float(cfg.get("disagreement_threshold", 0.3)),
                require_diverse_families=bool(cfg.get("require_diverse_families", True)),
                min_label_support=cfg.get("min_label_support", "ceil_half"),
                description=cfg.get("description", ""),
            )
        self._judge_panels = panels
        return panels

    def get_judge_panel(self, name: str) -> JudgePanelProfile:
        panels = self.load_judge_panels()
        if name not in panels:
            raise KeyError(f"未找到 Judge Panel: {name!r}。可用: {list(panels.keys())}")
        return panels[name]

    def load_harness_profiles(self) -> Dict[str, HarnessProfile]:
        """加载所有 Harness profile。"""
        if self._harness_profiles is not None:
            return self._harness_profiles

        path = self.config_dir / "harness_profiles.yaml"
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        profiles = {}
        for name, cfg in raw.get("harness_profiles", {}).items():
            profiles[name] = HarnessProfile(
                name=name,
                class_name=cfg.get("class", "RawHarness"),
                max_steps=cfg.get("max_steps", 10),
                max_retries=cfg.get("max_retries", 3),
                timeout_per_step=cfg.get("timeout_per_step", 60),
                description=cfg.get("description", ""),
                extra_params=cfg.get("extra_params", {}),
            )
        self._harness_profiles = profiles
        return profiles

    def load_env_profiles(self) -> Dict[str, EnvironmentProfile]:
        """加载所有 Environment profile。"""
        if self._env_profiles is not None:
            return self._env_profiles

        path = self.config_dir / "environments.yaml"
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        profiles = {}
        for name, cfg in raw.get("environments", {}).items():
            profiles[name] = EnvironmentProfile(
                name=name,
                class_name=cfg.get("class", "DialogEnvironment"),
                dataset=cfg.get("dataset", ""),
                description=cfg.get("description", ""),
                max_steps=cfg.get("max_steps", 20),
                target=cfg.get("target"),
                judge=cfg.get("judge"),
                judge_panel=cfg.get("judge_panel"),
                calibration_set=cfg.get("calibration_set"),
                extra_params=cfg.get("extra_params", {}),
            )
        self._env_profiles = profiles
        return profiles

    def load_target_profiles(self) -> Dict[str, TargetProfile]:
        """加载所有 Target profile。不存在配置文件时返回空字典。"""
        if self._target_profiles is not None:
            return self._target_profiles

        path = self.config_dir / "targets.yaml"
        if not path.exists():
            self._target_profiles = {}
            return self._target_profiles

        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        profiles = {}
        for name, cfg in raw.get("targets", {}).items():
            api_key = self._resolve_api_key(
                raw_key=cfg.get("api_key", "EMPTY"),
                key_env=cfg.get("api_key_env"),
            )
            profiles[name] = TargetProfile(
                name=name,
                class_name=cfg.get("class", "HTTPAppTarget"),
                base_url=self._resolve_env_value(cfg.get("base_url", "")),
                endpoints=dict(cfg.get("endpoints", {})),
                headers=dict(cfg.get("headers", {})),
                api_key=api_key,
                api_key_env=cfg.get("api_key_env"),
                timeout_seconds=cfg.get("timeout_seconds", 60),
                description=cfg.get("description", ""),
                extra_params=cfg.get("extra_params", {}),
            )
        self._target_profiles = profiles
        return profiles

    def get_llm_profile(self, name: str) -> LLMProfile:
        profiles = self.load_llm_profiles()
        if name not in profiles:
            raise KeyError(f"未找到 LLM profile: {name!r}。可用: {list(profiles.keys())}")
        return profiles[name]

    def get_judge_profile(self, name: str) -> JudgeProfile:
        profiles = self.load_judge_profiles()
        if name not in profiles:
            raise KeyError(f"未找到 Judge profile: {name!r}。可用: {list(profiles.keys())}")
        return profiles[name]

    def get_harness_profile(self, name: str) -> HarnessProfile:
        profiles = self.load_harness_profiles()
        if name not in profiles:
            raise KeyError(f"未找到 Harness profile: {name!r}。可用: {list(profiles.keys())}")
        return profiles[name]

    def get_env_profile(self, name: str) -> EnvironmentProfile:
        profiles = self.load_env_profiles()
        if name not in profiles:
            raise KeyError(f"未找到 Environment profile: {name!r}。可用: {list(profiles.keys())}")
        return profiles[name]

    def get_target_profile(self, name: str) -> TargetProfile:
        profiles = self.load_target_profiles()
        if name not in profiles:
            raise KeyError(f"未找到 Target profile: {name!r}。可用: {list(profiles.keys())}")
        return profiles[name]
