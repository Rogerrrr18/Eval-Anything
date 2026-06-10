"""
通用评测器。

这些 evaluator 面向跨领域任务的基础评分能力：
  - ExactMatch: 标准答案完全匹配
  - F1Match: 字符/词级 F1
  - FieldMatch: 结构化字段匹配
  - LLMJudge: 模型裁判打分、打标签、给评语
  - Composite: 多指标加权组合
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

from ..llm import create_llm
from ..llm.base import BaseLLM, LLMConfig
from ..utils.json_utils import robust_json_parse

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """单次评分结果。"""
    score: float
    passed: bool
    details: Dict[str, Any] = field(default_factory=dict)
    labels: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    comment: str = ""


class Evaluator(Protocol):
    """评测器协议。"""

    name: str

    def evaluate(self, prediction: Any, reference: Any) -> EvaluationResult:
        ...


def _normalize_text(value: Any, *, ignore_case: bool = True) -> str:
    text = "" if value is None else str(value)
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text.lower() if ignore_case else text


def _tokenize(text: str) -> List[str]:
    """英文按词切分，中文/无空格文本按字符切分。"""
    text = _normalize_text(text)
    if not text:
        return []
    if " " in text:
        return text.split()
    return list(text)


def _flatten_json(obj: Any) -> Dict[str, str]:
    flat: Dict[str, str] = {}
    if not isinstance(obj, dict):
        return flat
    for key, value in obj.items():
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                flat[child_key] = "" if child_value is None else str(child_value).strip()
        else:
            flat[key] = "" if value is None else str(value).strip()
    return flat


class ExactMatchEvaluator:
    """文本完全匹配评测器。"""

    name = "exact_match"

    def __init__(self, ignore_case: bool = True):
        self.ignore_case = ignore_case

    def evaluate(self, prediction: Any, reference: Any) -> EvaluationResult:
        pred = _normalize_text(prediction, ignore_case=self.ignore_case)
        ref = _normalize_text(reference, ignore_case=self.ignore_case)
        passed = pred == ref
        return EvaluationResult(
            score=1.0 if passed else 0.0,
            passed=passed,
            details={"prediction": pred, "reference": ref},
        )


class F1MatchEvaluator:
    """词/字符级 F1 评测器。"""

    name = "f1_match"

    def evaluate(self, prediction: Any, reference: Any) -> EvaluationResult:
        pred_tokens = _tokenize("" if prediction is None else str(prediction))
        ref_tokens = _tokenize("" if reference is None else str(reference))
        if not pred_tokens and not ref_tokens:
            return EvaluationResult(score=1.0, passed=True, details={"precision": 1.0, "recall": 1.0})
        if not pred_tokens or not ref_tokens:
            return EvaluationResult(score=0.0, passed=False, details={"precision": 0.0, "recall": 0.0})

        ref_counts: Dict[str, int] = {}
        for token in ref_tokens:
            ref_counts[token] = ref_counts.get(token, 0) + 1

        overlap = 0
        for token in pred_tokens:
            if ref_counts.get(token, 0) > 0:
                overlap += 1
                ref_counts[token] -= 1

        precision = overlap / len(pred_tokens)
        recall = overlap / len(ref_tokens)
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        return EvaluationResult(
            score=f1,
            passed=f1 >= 1.0,
            details={"precision": precision, "recall": recall, "overlap": overlap},
        )


class FieldMatchEvaluator:
    """结构化字段级匹配评测器。"""

    name = "field_match"

    def __init__(self, field_keys: Optional[Sequence[str]] = None):
        self.field_keys = list(field_keys) if field_keys else None

    def evaluate(self, prediction: Any, reference: Any) -> EvaluationResult:
        pred_obj = robust_json_parse(prediction) if isinstance(prediction, str) else prediction
        ref_obj = robust_json_parse(reference) if isinstance(reference, str) else reference
        pred_fields = _flatten_json(pred_obj)
        ref_fields = _flatten_json(ref_obj)

        keys = self.field_keys or sorted(set(ref_fields.keys()) | set(pred_fields.keys()))
        if not keys:
            return EvaluationResult(score=0.0, passed=False, details={"field_results": {}})

        field_results = {}
        for key in keys:
            pred_val = _normalize_text(pred_fields.get(key, ""))
            ref_val = _normalize_text(ref_fields.get(key, ""))
            field_results[key] = pred_val == ref_val

        correct = sum(1 for passed in field_results.values() if passed)
        score = correct / len(keys)
        return EvaluationResult(
            score=score,
            passed=score >= 1.0,
            details={
                "field_results": field_results,
                "correct": correct,
                "total": len(keys),
            },
        )


class LLMJudgeEvaluator:
    """基于 LLM-as-Judge 的评测器。

    Judge 模型需要输出 JSON：
    {
      "score": 0.0-1.0,
      "passed": true/false,
      "labels": ["..."],
      "comment": "...",
      "evidence": ["..."],
      "dimensions": {"correctness": 0.8}
    }
    """

    name = "llm_judge"

    DEFAULT_SYSTEM_PROMPT = """你是一个严格、公正的评测裁判。
你会根据 rubric 对 prediction 进行评分，并只输出合法 JSON。
不要输出 Markdown，不要输出解释性前后缀。"""

    def __init__(
        self,
        llm: BaseLLM,
        rubric: str,
        allowed_labels: Optional[Sequence[str]] = None,
        threshold: float = 0.6,
        system_prompt: Optional[str] = None,
    ):
        self.llm = llm
        self.rubric = rubric
        self.allowed_labels = list(allowed_labels or [])
        self.threshold = threshold
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT

    @classmethod
    def from_llm_config(
        cls,
        config: LLMConfig,
        rubric: str,
        class_name: str = "OpenAICompatibleLLM",
        allowed_labels: Optional[Sequence[str]] = None,
        threshold: float = 0.6,
        system_prompt: Optional[str] = None,
    ) -> "LLMJudgeEvaluator":
        """从 LLMConfig 创建 judge。"""
        return cls(
            llm=create_llm(config, class_name=class_name),
            rubric=rubric,
            allowed_labels=allowed_labels,
            threshold=threshold,
            system_prompt=system_prompt,
        )

    @classmethod
    def from_profile(cls, profile: Any) -> "LLMJudgeEvaluator":
        """从 ConfigLoader 加载的 JudgeProfile 创建 judge。"""
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
        return cls.from_llm_config(
            config=config,
            class_name=profile.class_name,
            rubric=profile.rubric,
            allowed_labels=profile.allowed_labels,
            threshold=profile.threshold,
            system_prompt=profile.system_prompt,
        )

    async def evaluate_async(
        self,
        prediction: Any,
        reference: Any = None,
        *,
        task: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """异步执行 LLM Judge。"""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self._build_prompt(prediction, reference, task, metadata or {})},
        ]
        response = await self.llm.chat(messages)
        parsed = robust_json_parse(response.content)
        if not isinstance(parsed, dict):
            return EvaluationResult(
                score=0.0,
                passed=False,
                labels=["judge_parse_error"],
                comment="Judge output was not valid JSON.",
                details={
                    "raw_judge_output": response.content,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "latency_ms": response.latency_ms,
                },
            )

        score = self._coerce_score(parsed.get("score", 0.0))
        passed = bool(parsed.get("passed", score >= self.threshold))
        labels = self._coerce_str_list(parsed.get("labels", []))
        evidence = self._coerce_str_list(parsed.get("evidence", []))
        comment = str(parsed.get("comment", ""))

        return EvaluationResult(
            score=score,
            passed=passed,
            labels=labels,
            evidence=evidence,
            comment=comment,
            details={
                "dimensions": parsed.get("dimensions", {}),
                "raw_judge_output": response.content,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "latency_ms": response.latency_ms,
            },
        )

    def evaluate(self, prediction: Any, reference: Any = None) -> EvaluationResult:
        """同步便捷入口。异步上下文中请使用 evaluate_async。"""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.evaluate_async(prediction, reference))
        raise RuntimeError("LLMJudgeEvaluator.evaluate() cannot run inside an active event loop; use evaluate_async().")

    async def close(self) -> None:
        """关闭底层 LLM client。"""
        await self.llm.close()

    def _build_prompt(
        self,
        prediction: Any,
        reference: Any,
        task: Any,
        metadata: Dict[str, Any],
    ) -> str:
        payload = {
            "rubric": self.rubric,
            "allowed_labels": self.allowed_labels,
            "task": task,
            "reference": reference,
            "prediction": prediction,
            "metadata": metadata,
            "output_schema": {
                "score": "float between 0 and 1",
                "passed": "boolean",
                "labels": "list of short snake_case labels",
                "comment": "short Chinese or English explanation",
                "evidence": "list of concrete evidence strings",
                "dimensions": "object of optional dimension scores",
            },
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    def _coerce_score(self, value: Any) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = 0.0
        return max(0.0, min(1.0, score))

    def _coerce_str_list(self, value: Any) -> List[str]:
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, list):
            items = value
        else:
            items = []
        return [str(item).strip() for item in items if str(item).strip()]


# ── PoLL: Panel of LLM Judges ─────────────────────────────────────────────
#
# 单裁判一次打分的两大问题：
#   1) 自我偏好（self-preference）：裁判偏爱"长得像自己输出"的回答
#   2) 锁定错路（cognitive lock-in）：裁判一旦看错某个事实就整路错下去
# Panel 用 N 个跨家族裁判并发独立打分，再聚合（trimmed_mean + 多数票）抵消。
# 关键前提是成员**跨家族**——3 个 GPT-4 变体投票没有意义。
#
# 参考：Cohere 2024, "Replacing Judges with Juries" (arXiv:2404.18796)
# ---------------------------------------------------------------------------

# 模型名前缀 → 家族（用于多样性检测；按可靠的命名约定做启发式）
_FAMILY_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("openai",     re.compile(r"^(gpt|o[134]|chatgpt|text-davinci|text-embedding|whisper)", re.I)),
    ("anthropic",  re.compile(r"^claude", re.I)),
    ("google",     re.compile(r"^(gemini|palm|bard)", re.I)),
    ("meta",       re.compile(r"^(llama|codellama)", re.I)),
    ("mistral",    re.compile(r"^(mistral|mixtral|codestral)", re.I)),
    ("deepseek",   re.compile(r"^deepseek", re.I)),
    ("qwen",       re.compile(r"^qwen", re.I)),
    ("zhipu",      re.compile(r"^(glm|chatglm)", re.I)),
    ("moonshot",   re.compile(r"^(kimi|moonshot)", re.I)),
    ("baichuan",   re.compile(r"^baichuan", re.I)),
    ("yi",         re.compile(r"^yi[- ]?", re.I)),
    ("xai",        re.compile(r"^grok", re.I)),
    ("cohere",     re.compile(r"^(command|cohere)", re.I)),
]


def detect_family(model_name: str) -> str:
    """从模型名启发式识别家族。识别不出时返回 'unknown'。"""
    if not model_name:
        return "unknown"
    for family, pattern in _FAMILY_PATTERNS:
        if pattern.search(model_name):
            return family
    return "unknown"


def _trimmed_mean(values: List[float]) -> float:
    """N≥3 时去掉最高、最低各一个再平均；N<3 取算术平均。"""
    if not values:
        return 0.0
    if len(values) < 3:
        return sum(values) / len(values)
    trimmed = sorted(values)[1:-1]
    return sum(trimmed) / len(trimmed)


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _aggregate_score(values: List[float], method: str) -> float:
    if method == "mean":
        return sum(values) / len(values) if values else 0.0
    if method == "median":
        return _median(values)
    if method == "majority":
        # 用 0.5 阈值二分后多数票，再回拟合到 0/1（少见用法）
        return 1.0 if sum(1 for v in values if v >= 0.5) > len(values) / 2 else 0.0
    # 默认 trimmed_mean
    return _trimmed_mean(values)


def _min_support_count(n_members: int, mode: str) -> int:
    if mode == "all":
        return n_members
    if mode == "majority":
        return n_members // 2 + 1
    # ceil_half 默认
    return (n_members + 1) // 2


class PanelLLMJudgeEvaluator:
    """N 个裁判并发独立打分 + 聚合。

    设计目标：抵消单裁判的 self-preference 和 cognitive lock-in。
    前提：成员必须跨模型家族（构造时校验，default warn 不 raise）。
    """

    name = "panel_judge"

    def __init__(
        self,
        members: Sequence["LLMJudgeEvaluator"],
        member_names: Optional[Sequence[str]] = None,
        member_families: Optional[Sequence[str]] = None,
        aggregation: str = "trimmed_mean",
        disagreement_threshold: float = 0.3,
        require_diverse_families: bool = True,
        min_label_support: str = "ceil_half",
        panel_name: str = "panel",
    ):
        if not members:
            raise ValueError("PanelLLMJudgeEvaluator requires at least one member")
        self.members = list(members)
        self.member_names = list(member_names) if member_names else [f"judge_{i}" for i in range(len(members))]
        self.member_families = list(member_families) if member_families else [
            detect_family(m.llm.config.model_name) for m in self.members
        ]
        self.aggregation = aggregation
        self.disagreement_threshold = disagreement_threshold
        self.require_diverse_families = require_diverse_families
        self.min_label_support_mode = min_label_support
        self.panel_name = panel_name

        self._check_family_diversity()

    def _check_family_diversity(self) -> None:
        family_counts = Counter(self.member_families)
        repeated = {fam: cnt for fam, cnt in family_counts.items() if cnt >= 2 and fam != "unknown"}
        if not repeated:
            return
        msg = (
            f"PanelLLMJudgeEvaluator '{self.panel_name}': 同家族成员重复 "
            f"{repeated} (members={list(zip(self.member_names, self.member_families))})。"
            " 同家族裁判共享 self-preference，panel 抵消偏差的效果会显著下降。"
        )
        if self.require_diverse_families:
            logger.warning(msg)
        else:
            logger.info(msg)

    @classmethod
    def from_panel_profile(
        cls,
        panel_profile: Any,
        judge_profiles: Dict[str, Any],
    ) -> "PanelLLMJudgeEvaluator":
        """从 JudgePanelProfile + judge_profiles 注册表构造。"""
        members: List[LLMJudgeEvaluator] = []
        member_names: List[str] = []
        member_families: List[str] = []
        for member_name in panel_profile.members:
            if member_name not in judge_profiles:
                raise KeyError(
                    f"Panel {panel_profile.name!r} 引用了未知 judge_profile: {member_name!r}。"
                    f" 可用: {list(judge_profiles.keys())}"
                )
            judge_profile = judge_profiles[member_name]
            members.append(LLMJudgeEvaluator.from_profile(judge_profile))
            member_names.append(member_name)
            member_families.append(detect_family(judge_profile.model_name))
        return cls(
            members=members,
            member_names=member_names,
            member_families=member_families,
            aggregation=panel_profile.aggregation,
            disagreement_threshold=panel_profile.disagreement_threshold,
            require_diverse_families=panel_profile.require_diverse_families,
            min_label_support=panel_profile.min_label_support,
            panel_name=panel_profile.name,
        )

    async def evaluate_async(
        self,
        prediction: Any,
        reference: Any = None,
        *,
        task: Any = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        # 并发跑所有成员，asyncio.gather 让总延迟 ≈ max(per-judge)。
        # return_exceptions=True：单个成员失败不报废整个 panel，
        # 剩余成员降级聚合（这正是 panel 冗余的意义）。
        raw_results = await asyncio.gather(
            *[
                m.evaluate_async(prediction, reference, task=task, metadata=metadata)
                for m in self.members
            ],
            return_exceptions=True,
        )

        ok_results: List[EvaluationResult] = []
        ok_names: List[str] = []
        ok_families: List[str] = []
        failed_members: List[Dict[str, str]] = []
        for name, family, r in zip(self.member_names, self.member_families, raw_results):
            if isinstance(r, BaseException):
                logger.warning(f"Panel '{self.panel_name}' 成员 {name} 评分失败: {r}")
                failed_members.append({"name": name, "family": family, "error": str(r)})
            else:
                ok_results.append(r)
                ok_names.append(name)
                ok_families.append(family)

        if not ok_results:
            return EvaluationResult(
                score=0.0,
                passed=False,
                labels=["panel_all_failed"],
                comment=f"Panel '{self.panel_name}' 所有成员评分均失败。",
                details={
                    "panel_name": self.panel_name,
                    "failed_members": failed_members,
                },
            )

        result = self._aggregate(ok_results, ok_names, ok_families)
        if failed_members:
            result.labels.append("member_failed")
            result.details["failed_members"] = failed_members
        return result

    def evaluate(self, prediction: Any, reference: Any = None) -> EvaluationResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.evaluate_async(prediction, reference))
        raise RuntimeError(
            "PanelLLMJudgeEvaluator.evaluate() cannot run inside an active event loop; use evaluate_async()."
        )

    async def close(self) -> None:
        await asyncio.gather(*[m.close() for m in self.members])

    # ── 聚合 ────────────────────────────────────────────────────────────
    def _aggregate(
        self,
        results: List[EvaluationResult],
        member_names: Optional[Sequence[str]] = None,
        member_families: Optional[Sequence[str]] = None,
    ) -> EvaluationResult:
        # 成员失败被剔除后，names/families 必须和 results 对齐传入；
        # 不传则默认全员都在（向后兼容）。
        names = list(member_names) if member_names is not None else self.member_names
        families = list(member_families) if member_families is not None else self.member_families
        n = len(results)
        scores = [r.score for r in results]
        agg_score = _aggregate_score(scores, self.aggregation)

        # 多数票决定 passed；平票时取保守值 False
        pass_votes = sum(1 for r in results if r.passed)
        passed = pass_votes > n / 2

        # label support 过滤：只保留至少 K 个成员同意的 label
        min_support = _min_support_count(n, self.min_label_support_mode)
        label_counter = Counter(label for r in results for label in r.labels)
        consensus_labels = sorted([
            label for label, cnt in label_counter.items() if cnt >= min_support
        ])

        # 分歧度自动标记
        score_range = max(scores) - min(scores) if scores else 0.0
        disagree = score_range > self.disagreement_threshold
        if disagree and "panel_disagree" not in consensus_labels:
            consensus_labels.append("panel_disagree")

        # evidence: union 去重保留顺序
        seen: set = set()
        merged_evidence: List[str] = []
        for r in results:
            for ev in r.evidence:
                key = ev.strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    merged_evidence.append(ev.strip())

        # comment 拼接，带成员前缀，方便报告里追溯
        comment_chunks = []
        for name, r in zip(names, results):
            if r.comment:
                comment_chunks.append(f"[{name}] {r.comment}")
        merged_comment = "\n".join(comment_chunks)

        # dimensions 按维度独立 trimmed_mean
        dim_collector: Dict[str, List[float]] = {}
        for r in results:
            for dim_name, dim_score in (r.details.get("dimensions") or {}).items():
                try:
                    dim_collector.setdefault(dim_name, []).append(float(dim_score))
                except (TypeError, ValueError):
                    continue
        merged_dimensions = {
            dim: _aggregate_score(vals, self.aggregation)
            for dim, vals in dim_collector.items()
        }

        # member_details 完整保留，让 case study 能下钻
        member_details = []
        for name, family, r in zip(names, families, results):
            member_details.append({
                "name": name,
                "family": family,
                "score": r.score,
                "passed": r.passed,
                "labels": r.labels,
                "evidence": r.evidence,
                "comment": r.comment,
                "raw_judge_output": r.details.get("raw_judge_output"),
                "input_tokens": r.details.get("input_tokens"),
                "output_tokens": r.details.get("output_tokens"),
                "latency_ms": r.details.get("latency_ms"),
            })

        # 一致性诊断指标
        agreement_stats = {
            "score_range": score_range,
            "pass_vote_ratio": pass_votes / n,
            "panel_disagree": disagree,
            "n_members": n,
        }

        return EvaluationResult(
            score=agg_score,
            passed=passed,
            labels=consensus_labels,
            evidence=merged_evidence,
            comment=merged_comment,
            details={
                "panel_name": self.panel_name,
                "aggregation": self.aggregation,
                "dimensions": merged_dimensions,
                "agreement": agreement_stats,
                "members": member_details,
            },
        )


class CompositeEvaluator:
    """多评测器加权组合。"""

    name = "composite"

    def __init__(self, evaluators: Iterable[Tuple[Evaluator, float]]):
        self.evaluators = list(evaluators)
        total_weight = sum(weight for _, weight in self.evaluators)
        if total_weight <= 0:
            raise ValueError("CompositeEvaluator requires positive weights")

    def evaluate(self, prediction: Any, reference: Any) -> EvaluationResult:
        weighted_score = 0.0
        total_weight = 0.0
        details: Dict[str, Any] = {}
        for evaluator, weight in self.evaluators:
            result = evaluator.evaluate(prediction, reference)
            weighted_score += result.score * weight
            total_weight += weight
            details[evaluator.name] = {
                "score": result.score,
                "passed": result.passed,
                "details": result.details,
            }

        score = weighted_score / total_weight
        return EvaluationResult(
            score=score,
            passed=score >= 1.0,
            details=details,
        )
