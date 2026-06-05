"""
配置管理 — 从 YAML 加载实验配置，Pydantic 校验。
"""
from __future__ import annotations

import os
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


# ── Profile 加载 ──

@dataclass
class LLMProfile:
    """一个 LLM 端点的配置。"""
    name: str
    class_name: str = "OpenAICompatibleLLM"
    model_name: str = ""
    endpoint_url: str = ""
    api_key: str = "EMPTY"
    temperature: float = 0.0
    max_tokens: int = 600
    top_p: float = 1.0
    timeout_seconds: int = 30
    enable_thinking: bool = False
    extra_params: Dict[str, Any] = field(default_factory=dict)


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
    extra_params: Dict[str, Any] = field(default_factory=dict)


# ── 配置加载器 ──

class ConfigLoader:
    """从 YAML 文件加载所有配置。"""

    def __init__(self, config_dir: str = "configs"):
        self.config_dir = Path(config_dir)
        self._llm_profiles: Optional[Dict[str, LLMProfile]] = None
        self._harness_profiles: Optional[Dict[str, HarnessProfile]] = None
        self._env_profiles: Optional[Dict[str, EnvironmentProfile]] = None

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
            profiles[name] = LLMProfile(
                name=name,
                class_name=cfg.get("class", "OpenAICompatibleLLM"),
                model_name=cfg.get("model_name", name),
                endpoint_url=cfg.get("endpoint_url", ""),
                api_key=cfg.get("api_key", "EMPTY"),
                temperature=cfg.get("temperature", 0.0),
                max_tokens=cfg.get("max_tokens", 600),
                top_p=cfg.get("top_p", 1.0),
                timeout_seconds=cfg.get("timeout_seconds", 30),
                enable_thinking=cfg.get("enable_thinking", False),
                extra_params=cfg.get("extra_params", {}),
            )
        self._llm_profiles = profiles
        return profiles

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
                extra_params=cfg.get("extra_params", {}),
            )
        self._env_profiles = profiles
        return profiles

    def get_llm_profile(self, name: str) -> LLMProfile:
        profiles = self.load_llm_profiles()
        if name not in profiles:
            raise KeyError(f"未找到 LLM profile: {name!r}。可用: {list(profiles.keys())}")
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
