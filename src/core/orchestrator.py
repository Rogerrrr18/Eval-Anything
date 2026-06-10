"""
Orchestrator — 核心调度器。

驱动整个评测流程：
  1. 加载配置 → 创建组件
  2. 对每个 (LLM × Harness × Environment) 组合运行评测
  3. 收集轨迹 → 计算指标 → 生成报告
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from ..llm.base import BaseLLM, LLMConfig
from ..llm import create_llm
from ..harness.base import BaseHarness
from ..harness.raw import RawHarness
from ..harness.react import ReActHarness
from ..harness.function_call import FunctionCallHarness
from ..harness.direct import DirectHarness
from ..environment.base import BaseEnvironment, TaskInstance
from ..environment import create_environment
from .config import (
    ConfigLoader, EnvironmentProfile, ExperimentConfig,
    HarnessProfile, LLMProfile,
)
from ..harness.base import HarnessConfig
from ..metrics.evaluators import (
    EvaluationResult,
    LLMJudgeEvaluator,
    PanelLLMJudgeEvaluator,
)
from .trajectory import Trajectory, ComboResult, ExperimentResult

# ── Harness 注册表 ──
_HARNESS_REGISTRY = {
    "RawHarness": RawHarness,
    "ReActHarness": ReActHarness,
    "FunctionCallHarness": FunctionCallHarness,
    "DirectHarness": DirectHarness,
}


def _create_llm_from_profile(profile: LLMProfile) -> BaseLLM:
    """从 profile 创建 LLM 实例。"""
    config = LLMConfig(
        model_name=profile.model_name,
        endpoint_url=profile.endpoint_url,
        api_key=profile.api_key,
        temperature=profile.temperature,
        max_tokens=profile.max_tokens,
        top_p=profile.top_p,
        timeout_seconds=profile.timeout_seconds,
        enable_thinking=profile.enable_thinking,
        extra_params=profile.extra_params,
    )
    return create_llm(config, class_name=profile.class_name)


def _create_harness_from_profile(
    profile: HarnessProfile, llm: BaseLLM
) -> BaseHarness:
    """从 profile 创建 Harness 实例。"""
    cls = _HARNESS_REGISTRY.get(profile.class_name)
    if cls is None:
        raise ValueError(f"未注册的 Harness 类: {profile.class_name!r}")
    config = HarnessConfig(
        name=profile.name,
        max_steps=profile.max_steps,
        max_retries=profile.max_retries,
        timeout_per_step=profile.timeout_per_step,
        description=profile.description,
        extra_params=profile.extra_params,
    )
    return cls(llm, config)


def _create_env_from_profile(
    profile: EnvironmentProfile,
    config_loader: Optional[ConfigLoader] = None,
) -> BaseEnvironment:
    """从 profile 创建 Environment 实例。"""
    from ..environment.base import EnvConfig
    target_config: Dict[str, Any] = {}
    if profile.target:
        if config_loader is None:
            raise ValueError(f"环境 {profile.name!r} 引用了 target，但没有传入 ConfigLoader")
        target_config = asdict(config_loader.get_target_profile(profile.target))
    config = EnvConfig(
        name=profile.name,
        dataset=profile.dataset,
        description=profile.description,
        max_steps=profile.max_steps,
        target=profile.target,
        target_config=target_config,
        extra_params=profile.extra_params,
    )
    return create_environment(config, class_name=profile.class_name)


def _trajectory_from_dict(data: Dict[str, Any]) -> Trajectory:
    """从 stream JSONL 行重建 Trajectory（--resume 用）。"""
    from ..harness.base import Action, StepRecord

    steps: List[StepRecord] = []
    for s in data.get("steps", []) or []:
        raw_action = s.get("action") or {}
        action = Action(
            action_type=raw_action.get("action_type", "text_response"),
            content=raw_action.get("content", ""),
            tool_name=raw_action.get("tool_name"),
            tool_args=raw_action.get("tool_args"),
            metadata=raw_action.get("metadata", {}) or {},
        )
        steps.append(StepRecord(
            step_number=s.get("step_number", 0),
            observation=s.get("observation", ""),
            thought=s.get("thought"),
            action=action,
            action_result=s.get("action_result", ""),
            latency_ms=s.get("latency_ms", 0.0),
            input_tokens=s.get("input_tokens", 0),
            output_tokens=s.get("output_tokens", 0),
            error=s.get("error"),
        ))

    return Trajectory(
        experiment_name=data.get("experiment_name", ""),
        task_id=data.get("task_id", ""),
        llm_name=data.get("llm_name", ""),
        harness_name=data.get("harness_name", ""),
        env_name=data.get("env_name", ""),
        steps=steps,
        final_answer=data.get("final_answer", ""),
        ground_truth=data.get("ground_truth"),
        scores=data.get("scores", {}) or {},
        total_input_tokens=data.get("total_input_tokens", 0),
        total_output_tokens=data.get("total_output_tokens", 0),
        total_latency_ms=data.get("total_latency_ms", 0.0),
        status=data.get("status", "error"),
        error_message=data.get("error_message"),
        metadata=data.get("metadata", {}) or {},
    )


# resume 时这些状态视为"已有评测结论"，跳过；error/timeout 是基础设施故障，重跑
_RESUMABLE_DONE_STATUSES = ("success", "partial", "failure")


def _build_judge_for_env(
    env_profile: EnvironmentProfile,
    config_loader: ConfigLoader,
):
    """根据 env_profile 的 judge_panel / judge 字段构造一个 LLM 裁判。

    判定优先级：judge_panel > judge > None。没配就返回 None，跳过 LLM 裁判评分。
    返回的对象同时支持 `evaluate_async` 和 `close`，调用方按一个接口走。
    """
    if env_profile.judge_panel:
        panel_profile = config_loader.get_judge_panel(env_profile.judge_panel)
        judge_profiles = config_loader.load_judge_profiles()
        return PanelLLMJudgeEvaluator.from_panel_profile(panel_profile, judge_profiles)
    if env_profile.judge:
        judge_profile = config_loader.get_judge_profile(env_profile.judge)
        return LLMJudgeEvaluator.from_profile(judge_profile)
    return None


class Orchestrator:
    """核心评测调度器。"""

    def __init__(self, config_loader: ConfigLoader):
        self.config_loader = config_loader
        self.logger = logging.getLogger("agent-eval")
        # calibration 衡量 judge↔人类一致性，与被测 LLM 无关——
        # 同一 (env, judge) 在多个 combo 间复用结果，避免重复花 judge token
        self._calibration_cache: Dict[str, Dict[str, Any]] = {}
        self._calibration_locks: Dict[str, asyncio.Lock] = {}

    async def run_experiment(self, experiment_config: ExperimentConfig) -> ExperimentResult:
        """运行完整实验。

        对每个 (LLM × Harness × Environment) 组合：
          1. 初始化组件
          2. 加载测试集
          3. 逐任务运行 agent loop
          4. 收集轨迹和分数
          5. 汇总结果
        """
        print(f"\n{'='*60}")
        print(f"实验: {experiment_config.name}")
        print(f"描述: {experiment_config.description}")
        print(f"{'='*60}\n")

        # 生成所有组合
        combos = list(itertools.product(
            experiment_config.llm_profiles,
            experiment_config.harness_profiles,
            experiment_config.environments,
        ))
        print(f"共 {len(combos)} 个评测组合\n")

        # 按配置并发运行组合。
        semaphore = asyncio.Semaphore(experiment_config.execution.max_concurrent_combos)

        async def _run_indexed_combo(
            idx: int, combo: Tuple[str, str, str]
        ) -> ComboResult:
            llm_name, harness_name, env_name = combo
            async with semaphore:
                print(f"\n[{idx}/{len(combos)}] 运行: LLM={llm_name}, Harness={harness_name}, Env={env_name}")
                result = await self._run_combo(
                    llm_name, harness_name, env_name, experiment_config
                )
                self._print_combo_summary(result)
                return result

        combo_results = await asyncio.gather(*[
            _run_indexed_combo(idx, combo)
            for idx, combo in enumerate(combos, 1)
        ])

        # 可选：pairwise 对比（所有 combo 跑完后执行）
        pairwise_data: Optional[Dict[str, Any]] = None
        if experiment_config.pairwise_judge:
            pairwise_data = await self._run_pairwise(experiment_config, list(combo_results))

        # 汇总
        exp_result = ExperimentResult(
            experiment_name=experiment_config.name,
            combo_results=combo_results,
            config_snapshot={
                "llm_profiles": experiment_config.llm_profiles,
                "harness_profiles": experiment_config.harness_profiles,
                "environments": experiment_config.environments,
                "seed": experiment_config.seed,
            },
            pairwise=pairwise_data,
        )

        print(f"\n{'='*60}")
        print(f"实验完成！共 {len(combo_results)} 个组合，"
              f"{sum(len(cr.task_results) for cr in combo_results)} 条轨迹")
        print(f"{'='*60}\n")

        return exp_result

    async def _run_combo(
        self,
        llm_name: str,
        harness_name: str,
        env_name: str,
        exp_config: ExperimentConfig,
    ) -> ComboResult:
        """运行单个 (LLM × Harness × Env) 组合。"""
        # 创建组件
        llm_profile = self.config_loader.get_llm_profile(llm_name)
        harness_profile = self.config_loader.get_harness_profile(harness_name)
        env_profile = self.config_loader.get_env_profile(env_name)

        llm = _create_llm_from_profile(llm_profile)

        # 可选：LLM 裁判（单裁判或 panel）。env_profile 配了才构造。
        judge = _build_judge_for_env(env_profile, self.config_loader)
        if judge is not None:
            judge_kind = "panel" if isinstance(judge, PanelLLMJudgeEvaluator) else "single"
            judge_name = getattr(judge, "panel_name", None) or env_profile.judge or "judge"
            print(f"  LLM 裁判: {judge_kind} ({judge_name})")

        # 加载测试集
        tasks = self._load_tasks(env_profile)
        print(f"  加载 {len(tasks)} 条测试用例")

        # 流式落盘：每条任务完成立刻 append 到 stream JSONL。
        # 进程中途崩溃时已完成的结果不丢，--resume 可以从这里续跑。
        stream_path = (
            Path(exp_config.output_dir) / "trajectories" / "stream"
            / f"{llm_name}__{harness_name}__{env_name}.jsonl"
        )
        stream_path.parent.mkdir(parents=True, exist_ok=True)

        resumed: Dict[str, Trajectory] = {}
        if exp_config.resume and stream_path.exists():
            with open(stream_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if data.get("status") in _RESUMABLE_DONE_STATUSES:
                        resumed[data.get("task_id", "")] = _trajectory_from_dict(data)
            if resumed:
                print(f"  断点续跑: 跳过 {len(resumed)} 条已完成任务")
        elif not exp_config.resume and stream_path.exists():
            stream_path.unlink()  # 全新运行，清掉旧 stream 避免和本次结果混淆

        pending_tasks = [t for t in tasks if t.task_id not in resumed]

        # 按配置并发运行任务。Harness/Environment 都是有状态对象，
        # 所以每个任务创建独立实例，LLM client 共享。
        task_semaphore = asyncio.Semaphore(exp_config.execution.max_concurrent_tasks)

        async def _run_task(task_idx: int, task: TaskInstance) -> Trajectory:
            async with task_semaphore:
                harness = _create_harness_from_profile(harness_profile, llm)
                env = _create_env_from_profile(env_profile, self.config_loader)
                try:
                    traj = await self._run_single_task(
                        harness, env, task, exp_config, task_idx, len(pending_tasks),
                        llm_name, harness_name, env_name,
                        judge=judge,
                    )
                finally:
                    await env.close()
                # 单事件循环内整行一次写入，无交错风险
                with open(stream_path, "a", encoding="utf-8") as f:
                    f.write(traj.to_jsonl() + "\n")
                return traj

        calibration_data: Optional[Dict[str, Any]] = None
        try:
            new_trajectories = await asyncio.gather(*[
                _run_task(task_idx, task)
                for task_idx, task in enumerate(pending_tasks)
            ])
            # 按数据集原始顺序合并 resumed + 新跑的
            traj_by_id = {t.task_id: t for t in new_trajectories}
            traj_by_id.update({tid: t for tid, t in resumed.items()})
            trajectories = [
                traj_by_id[t.task_id] for t in tasks if t.task_id in traj_by_id
            ]

            # 可选：judge 校准（主任务跑完后，关闭 judge 之前执行）。
            # 结果按 (env, judge) 缓存——多个 LLM×Harness combo 共享同一 judge 时只跑一次。
            if env_profile.calibration_set and judge is not None:
                cal_key = f"{env_name}::{env_profile.judge_panel or env_profile.judge}"
                lock = self._calibration_locks.setdefault(cal_key, asyncio.Lock())
                async with lock:
                    if cal_key in self._calibration_cache:
                        calibration_data = self._calibration_cache[cal_key]
                    else:
                        print(f"  Judge 校准中: {env_profile.calibration_set}")
                        from ..metrics.calibration import run_calibration
                        try:
                            cal = await run_calibration(
                                judge,
                                env_profile.calibration_set,
                                project_root=self.config_loader.project_root,
                            )
                            calibration_data = {
                                "n_samples": cal.n_samples,
                                "n_evaluated": cal.n_evaluated,
                                "score_pearson_r": cal.score_pearson_r,
                                "pass_accuracy": cal.pass_accuracy,
                                "label_macro_f1": cal.label_macro_f1,
                                "per_label_f1": cal.per_label_f1,
                                "warning": cal.warning,
                            }
                            self._calibration_cache[cal_key] = calibration_data
                            r_str = f"{cal.score_pearson_r:.3f}" if cal.score_pearson_r is not None else "N/A"
                            print(f"  校准完成: n={cal.n_samples}, pearson_r={r_str}")
                        except Exception as exc:
                            self.logger.warning(f"judge 校准失败: {exc}")
        finally:
            await llm.close()
            if judge is not None:
                try:
                    await judge.close()
                except Exception as exc:  # 关闭失败不影响主流程
                    self.logger.warning(f"关闭 judge 失败: {exc}")

        # 汇总
        combo = ComboResult(
            llm_name=llm_name,
            harness_name=harness_name,
            env_name=env_name,
            task_results=trajectories,
        )
        combo.compute_summary()
        if calibration_data:
            combo.summary["calibration"] = calibration_data
        return combo

    async def _run_pairwise(
        self,
        exp_config: ExperimentConfig,
        combo_results: List[ComboResult],
    ) -> Optional[Dict[str, Any]]:
        """跨 LLM pairwise 对比。

        对每个 task_id，收集所有 LLM 的输出，两两调用 PairwiseLLMJudgeEvaluator 比较。
        聚合为 Elo 分 + win 矩阵，用于识别哪个模型总体更好。

        只有 experiment.yaml 里配了 pairwise_judge 才会执行。
        """
        from ..metrics.pairwise import PairwiseLLMJudgeEvaluator, EloRanker

        # 参赛单位是 (LLM, Harness) 组合——多 harness 实验里同一 LLM 的不同
        # harness 输出是不同的"选手"，不能互相覆盖。单 harness 时显示名退化为 LLM 名。
        harness_names = {cr.harness_name for cr in combo_results}

        def _competitor(cr: ComboResult) -> str:
            if len(harness_names) == 1:
                return cr.llm_name
            return f"{cr.llm_name}+{cr.harness_name}"

        all_models: List[str] = list(dict.fromkeys(_competitor(cr) for cr in combo_results))
        if len(all_models) < 2:
            self.logger.warning("pairwise: 参赛组合不足 2 个，跳过")
            return None

        judge_profile = self.config_loader.get_judge_profile(exp_config.pairwise_judge)
        pairwise_judge = PairwiseLLMJudgeEvaluator.from_profile(judge_profile)

        try:
            # task_id → {competitor: final_answer}
            task_outputs: Dict[str, Dict[str, str]] = {}
            for cr in combo_results:
                comp = _competitor(cr)
                for traj in cr.task_results:
                    if traj.status not in ("error", "timeout"):
                        task_outputs.setdefault(traj.task_id, {})[comp] = traj.final_answer

            n_tasks = len(task_outputs)
            n_pairs = len(all_models) * (len(all_models) - 1) // 2
            print(f"\n  Pairwise: {n_tasks} tasks × {n_pairs} model pairs "
                  f"({n_tasks * n_pairs * 2} judge calls with swap)")

            elo = EloRanker(all_models)
            win_matrix: Dict[str, Dict[str, Dict[str, int]]] = {
                a: {b: {"wins": 0, "losses": 0, "ties": 0, "total": 0}
                    for b in all_models if b != a}
                for a in all_models
            }
            pw_results = []

            # 并发控制
            semaphore = asyncio.Semaphore(3)  # 避免 pairwise judge API 过载

            async def _cmp(task_id: str, model_a: str, output_a: str,
                           model_b: str, output_b: str):
                async with semaphore:
                    try:
                        return await pairwise_judge.compare_async(
                            task_id=task_id,
                            model_a=model_a, output_a=output_a,
                            model_b=model_b, output_b=output_b,
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"pairwise {model_a} vs {model_b} on {task_id}: {e}")
                        return None

            tasks_all = []
            for tid, model_map in task_outputs.items():
                model_list = [(m, model_map[m]) for m in all_models if m in model_map]
                for i in range(len(model_list)):
                    for j in range(i + 1, len(model_list)):
                        ma, oa = model_list[i]
                        mb, ob = model_list[j]
                        tasks_all.append(_cmp(tid, ma, oa, mb, ob))

            raw_results = await asyncio.gather(*tasks_all)

            for pw in raw_results:
                if pw is None:
                    continue
                pw_results.append(pw)
                elo.update(pw.model_a, pw.model_b, pw.winner)
                ma, mb = pw.model_a, pw.model_b
                if ma in win_matrix and mb in win_matrix[ma]:
                    win_matrix[ma][mb]["total"] += 1
                    win_matrix[mb][ma]["total"] += 1
                    if pw.winner == "A":
                        win_matrix[ma][mb]["wins"] += 1
                        win_matrix[mb][ma]["losses"] += 1
                    elif pw.winner == "B":
                        win_matrix[ma][mb]["losses"] += 1
                        win_matrix[mb][ma]["wins"] += 1
                    else:
                        win_matrix[ma][mb]["ties"] += 1
                        win_matrix[mb][ma]["ties"] += 1

            ranking = elo.ranking()
            print(f"  Pairwise 完成: {len(pw_results)} 次对比")
            print("  Elo 排名: " + " > ".join(
                f"{m}({s:.0f})" for m, s in ranking
            ))

            return {
                "models": all_models,
                "elo_scores": elo.scores,
                "ranking": [(m, round(s, 1)) for m, s in ranking],
                "win_matrix": win_matrix,
                "n_comparisons": len(pw_results),
                "judge": exp_config.pairwise_judge,
            }
        finally:
            await pairwise_judge.close()

    async def _run_single_task(
        self,
        harness: BaseHarness,
        env: BaseEnvironment,
        task: TaskInstance,
        exp_config: ExperimentConfig,
        task_idx: int,
        total_tasks: int,
        llm_name: str,
        harness_name: str,
        env_name: str,
        judge: Optional[Any] = None,
    ) -> Trajectory:
        """运行单个任务。"""
        harness.reset()

        try:
            # 重置环境
            observation = await asyncio.wait_for(
                env.reset(task),
                timeout=exp_config.execution.task_timeout_seconds,
            )

            # Agent 产生第一个动作
            action = await self._with_retries(
                lambda: asyncio.wait_for(
                    harness.initial_action(observation),
                    timeout=exp_config.execution.step_timeout_seconds,
                ),
                retries=exp_config.execution.retry_on_api_error,
                backoff_base=exp_config.execution.retry_backoff_base,
            )

            # Agent loop
            step_count = 0
            max_steps = min(harness.config.max_steps, env.config.max_steps)
            last_step_info: Dict[str, Any] = {}
            while not harness.is_finished() and not env.is_done():
                if step_count >= max_steps:
                    break
                step_count += 1

                result = await asyncio.wait_for(
                    env.step(action),
                    timeout=exp_config.execution.step_timeout_seconds,
                )
                last_step_info = result.info

                if result.terminated or result.truncated:
                    break

                action = await self._with_retries(
                    lambda: asyncio.wait_for(
                        harness.next_action(result.observation),
                        timeout=exp_config.execution.step_timeout_seconds,
                    ),
                    retries=exp_config.execution.retry_on_api_error,
                    backoff_base=exp_config.execution.retry_backoff_base,
                )

            # 最后一步如果环境还没 done，提交最终动作
            if not env.is_done() and action:
                result = await asyncio.wait_for(
                    env.step(action),
                    timeout=exp_config.execution.step_timeout_seconds,
                )
                last_step_info = result.info

        except asyncio.TimeoutError:
            print(f"  [{task_idx+1}/{total_tasks}] 超时: {task.task_id}")
            return Trajectory(
                experiment_name=exp_config.name,
                task_id=task.task_id,
                llm_name=llm_name,
                harness_name=harness_name,
                env_name=env_name,
                steps=harness.get_trajectory(),
                final_answer=harness.get_final_answer(),
                ground_truth=task.ground_truth,
                scores={},
                total_input_tokens=harness._total_input_tokens,
                total_output_tokens=harness._total_output_tokens,
                total_latency_ms=harness.get_total_latency(),
                status="timeout",
                error_message="任务执行超时",
            )
        except Exception as e:
            print(f"  [{task_idx+1}/{total_tasks}] 错误: {task.task_id}: {e}")
            return Trajectory(
                experiment_name=exp_config.name,
                task_id=task.task_id,
                llm_name=llm_name,
                harness_name=harness_name,
                env_name=env_name,
                steps=harness.get_trajectory(),
                final_answer=harness.get_final_answer(),
                ground_truth=task.ground_truth,
                scores={},
                total_input_tokens=harness._total_input_tokens,
                total_output_tokens=harness._total_output_tokens,
                total_latency_ms=harness.get_total_latency(),
                status="error",
                error_message=str(e),
            )

        # 计算分数
        reward = env.get_reward()
        # 从环境获取详细信息
        env_info = env.get_info()
        env_info.update(last_step_info)
        final_answer = (
            env_info.get("final_answer")
            or env_info.get("prediction")
            or harness.get_final_answer()
        )
        field_results = env_info.get("field_results", {})
        format_ok = env_info.get("format_ok", False)
        target_latency_ms = float(env_info.get("target_latency_ms") or 0.0)
        passed_flag = env_info.get("passed")

        # 确定状态
        if passed_flag is True:
            status = "success"
        elif passed_flag is False and reward <= 0.0:
            status = "failure"
        elif reward >= 1.0:
            status = "success"
        elif reward > 0.0:
            status = "partial"
        else:
            status = "failure"

        scores = {
            "partial_completion": reward,
            "format_compliance": 1.0 if format_ok else 0.0,
            "task_completion": 1.0 if status == "success" else 0.0,
        }

        # 加入字段级分数
        if field_results:
            for key, passed in field_results.items():
                scores[f"field_{key}"] = 1.0 if passed else 0.0
        for key, value in env_info.get("rag_scores", {}).items():
            try:
                scores[key] = float(value)
            except (TypeError, ValueError):
                continue
        if "evaluation" in env_info and isinstance(env_info["evaluation"], dict):
            try:
                scores["evaluation_score"] = float(env_info["evaluation"].get("score", reward))
            except (TypeError, ValueError):
                pass

        # 可选：LLM 裁判评分。失败不阻塞主流程，记到 metadata。
        judge_metadata: Dict[str, Any] = {}
        if judge is not None:
            try:
                judge_result: EvaluationResult = await judge.evaluate_async(
                    prediction=final_answer,
                    reference=env_info.get("reference", task.ground_truth),
                    task=task.task_id,
                    metadata={
                        "llm_name": llm_name,
                        "harness_name": harness_name,
                        "env_name": env_name,
                    },
                )
                scores["judge_score"] = judge_result.score
                scores["judge_passed"] = 1.0 if judge_result.passed else 0.0
                judge_metadata = {
                    "labels": judge_result.labels,
                    "evidence": judge_result.evidence,
                    "comment": judge_result.comment,
                    "details": judge_result.details,
                }
            except Exception as exc:
                self.logger.warning(f"judge 评分失败 task={task.task_id}: {exc}")
                judge_metadata = {"error": str(exc)}

        print(f"  [{task_idx+1}/{total_tasks}] {task.task_id}: {status} ({reward:.1%})")

        return Trajectory(
            experiment_name=exp_config.name,
            task_id=task.task_id,
            llm_name=llm_name,
            harness_name=harness_name,
            env_name=env_name,
            steps=harness.get_trajectory(),
            final_answer=final_answer,
            ground_truth=task.ground_truth,
            scores=scores,
            total_input_tokens=harness._total_input_tokens,
            total_output_tokens=harness._total_output_tokens,
            total_latency_ms=harness.get_total_latency() + target_latency_ms,
            status=status,
            metadata={
                "field_results": field_results,
                "format_ok": format_ok,
                "env_info": env_info,
                **({"judge": judge_metadata} if judge_metadata else {}),
            },
        )

    async def _with_retries(
        self,
        func,
        retries: int,
        backoff_base: float,
    ) -> Any:
        """对单步 LLM 调用做指数退避重试。"""
        attempts = max(1, retries)
        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                return await func()
            except Exception as e:
                last_error = e
                if attempt >= attempts:
                    raise
                delay = backoff_base ** (attempt - 1)
                self.logger.warning(
                    "LLM step failed on attempt %s/%s: %s; retrying in %.1fs",
                    attempt, attempts, e, delay,
                )
                await asyncio.sleep(delay)
        raise last_error or RuntimeError("retry failed without an exception")

    def _load_tasks(self, env_profile: EnvironmentProfile) -> List[TaskInstance]:
        """根据环境 profile 加载测试集。

        支持多种数据源：
          1. JSONL 文件（推荐）
          2. Excel 文件（兼容现有 evalv3 数据）
          3. AlphaEval-style task directory（task.yaml + query.md + files + .eval）
        """
        dataset_path = env_profile.dataset
        if not dataset_path:
            print(f"  警告: 环境 {env_profile.name} 未配置 dataset，使用空测试集")
            return []

        path = Path(dataset_path).expanduser()
        if not path.is_absolute():
            path = self.config_loader.project_root / path
        if not path.exists():
            print(f"  警告: 数据集文件不存在: {path}")
            return []

        if path.is_dir():
            return self._load_task_directory(path, env_profile)
        if path.suffix == ".jsonl":
            return self._load_jsonl(path, env_profile)
        elif path.suffix in (".xlsx", ".xls"):
            return self._load_excel(path, env_profile)
        elif path.suffix == ".json":
            return self._load_json(path, env_profile)
        else:
            print(f"  警告: 不支持的数据集格式: {path.suffix}")
            return []

    def _load_task_directory(self, path: Path, env_profile: EnvironmentProfile) -> List[TaskInstance]:
        """加载 AlphaEval-style task directory。

        支持两种形式：
          - dataset 指向单个 task 目录（含 task.yaml）
          - dataset 指向 task suite 目录，下面每个子目录是一个 task
        """
        task_dirs = [path] if (path / "task.yaml").exists() else [
            child for child in sorted(path.iterdir())
            if child.is_dir() and (child / "task.yaml").exists()
        ]
        tasks: List[TaskInstance] = []
        for task_dir in task_dirs:
            task_yaml = task_dir / "task.yaml"
            query_path = task_dir / "query.md"
            try:
                with open(task_yaml, "r", encoding="utf-8") as f:
                    task_config = yaml.safe_load(f) or {}
            except Exception as exc:
                print(f"  警告: task.yaml 读取失败 {task_yaml}: {exc}")
                continue

            query = query_path.read_text(encoding="utf-8") if query_path.exists() else task_config.get("description", "")
            evaluation = task_config.get("evaluation", {}) or {}
            reference = (
                evaluation.get("expected_answer")
                or evaluation.get("reference_answer")
                or task_config.get("ground_truth")
            )
            metadata = {
                "task_dir": str(task_dir.resolve()),
                "query_path": str(query_path.resolve()) if query_path.exists() else "",
                "files_dir": str((task_dir / "files").resolve()),
                "eval_dir": str((task_dir / ".eval").resolve()),
                "task_config": task_config,
                "evaluation": evaluation,
                "category": task_config.get("category"),
                "difficulty": task_config.get("difficulty"),
                "tags": task_config.get("tags", []),
            }
            tasks.append(TaskInstance(
                task_id=task_config.get("id", task_dir.name),
                task_type=evaluation.get("type", "workspace"),
                prompt=query,
                ground_truth=reference,
                metadata=metadata,
            ))
        return tasks

    def _load_jsonl(self, path: Path, env_profile: EnvironmentProfile) -> List[TaskInstance]:
        """从 JSONL 文件加载测试集。"""
        tasks = []
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    tasks.append(TaskInstance(
                        task_id=obj.get("task_id", f"task_{line_no}"),
                        task_type=obj.get("task_type", "slot_filling"),
                        prompt=obj.get("prompt") or obj.get("question", ""),
                        ground_truth=obj.get("ground_truth", obj.get("reference_answer")),
                        metadata=self._extract_task_metadata(obj),
                        conversation_history=obj.get("conversation_history"),
                        expected_slots=obj.get("expected_slots"),
                        slot_keys=obj.get("slot_keys"),
                    ))
                except json.JSONDecodeError as e:
                    print(f"  警告: JSONL 第 {line_no} 行解析失败: {e}")
        return tasks

    def _load_json(self, path: Path, env_profile: EnvironmentProfile) -> List[TaskInstance]:
        """从 JSON 文件加载测试集。"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("tasks", [])
        tasks = []
        for i, obj in enumerate(items):
            tasks.append(TaskInstance(
                task_id=obj.get("task_id", f"task_{i}"),
                task_type=obj.get("task_type", "slot_filling"),
                prompt=obj.get("prompt") or obj.get("question", ""),
                ground_truth=obj.get("ground_truth", obj.get("reference_answer")),
                metadata=self._extract_task_metadata(obj),
                conversation_history=obj.get("conversation_history"),
                expected_slots=obj.get("expected_slots"),
                slot_keys=obj.get("slot_keys"),
            ))
        return tasks

    def _extract_task_metadata(self, obj: Dict[str, Any]) -> Dict[str, Any]:
        """保留通用任务字段，方便非槽位环境读取。"""
        metadata = dict(obj.get("metadata", {}) or {})
        for key in (
            "files",
            "question",
            "reference_answer",
            "expected_citations",
            "rubric",
            "tags",
        ):
            if key in obj and key not in metadata:
                metadata[key] = obj[key]
        return metadata

    def _load_excel(self, path: Path, env_profile: EnvironmentProfile) -> List[TaskInstance]:
        """从 Excel 文件加载测试集（兼容 evalv3 数据格式）。"""
        import pandas as pd

        df = pd.read_excel(path, dtype={"phone_number": str})
        df = df.fillna("")

        slot_keys = env_profile.extra_params.get("slot_keys", [])
        system_prompt_file = env_profile.extra_params.get("system_prompt_file", "")

        tasks = []
        grouped = df.groupby("conversation_id") if "conversation_id" in df.columns else [(None, df)]

        for conv_id, group in grouped:
            if isinstance(group, pd.DataFrame):
                group = group.sort_values("dialogue_count") if "dialogue_count" in group.columns else group

            for idx, row in group.iterrows():
                # 构造期望槽位
                expected = {}
                for key in slot_keys:
                    val = row.get(key, "")
                    # 特殊处理数值字段
                    if key == "phone_number" and isinstance(val, str) and val.endswith(".0"):
                        val = val[:-2]
                    elif key in ("product_num",) and val != "":
                        try:
                            val = str(int(float(val)))
                        except (ValueError, TypeError):
                            pass
                    expected[key] = val

                # 构造多轮对话历史
                history = []
                if "dialogue_count" in df.columns:
                    hist_rows = group[group["dialogue_count"] < row.get("dialogue_count", 0)]
                    for _, hr in hist_rows.iterrows():
                        history.append({"role": "user", "content": str(hr.get("query", ""))})
                        ans = hr.get("answer", "")
                        if ans and str(ans) != "nan":
                            history.append({"role": "assistant", "content": str(ans)})

                # 构造 prompt
                query = str(row.get("query", ""))
                intent = row.get("INTENTION", "")
                if intent and str(intent) == "预约维修" and env_profile.extra_params.get("intent_filter") == "预约维修":
                    pass  # 保留
                elif intent and env_profile.extra_params.get("intent_filter") and str(intent) != str(env_profile.extra_params.get("intent_filter")):
                    continue  # 跳过非目标意图

                prompt = query  # 简单 prompt = 用户输入

                task_id = f"{conv_id}_{row.get('dialogue_count', idx)}" if conv_id else f"task_{idx}"

                tasks.append(TaskInstance(
                    task_id=task_id,
                    task_type="slot_filling",
                    prompt=prompt,
                    ground_truth=expected,
                    metadata={"conversation_id": str(conv_id), "query": query},
                    conversation_history=history,
                    expected_slots=expected,
                    slot_keys=slot_keys,
                ))

        return tasks

    def _print_combo_summary(self, combo: ComboResult) -> None:
        """打印组合结果摘要。"""
        s = combo.summary
        if not s:
            return
        print(f"  结果: 成功率={s.get('success_rate', 0):.1%}, "
              f"平均得分={s.get('avg_score', 0):.1%}, "
              f"平均延迟={s.get('avg_latency_ms', 0):.0f}ms, "
              f"平均token={s.get('avg_tokens', 0):.0f}")
