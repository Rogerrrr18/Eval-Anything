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
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

from ..llm import create_llm
from ..llm.base import BaseLLM, LLMConfig
from ..utils.json_utils import robust_json_parse


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
