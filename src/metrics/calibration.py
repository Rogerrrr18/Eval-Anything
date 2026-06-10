"""
Judge Calibration — 衡量 LLM Judge 与人工标注的一致性。

完全可选：在 environments.yaml 的某个 env 下加 calibration_set 字段才触发。
主流程不依赖它，失败也不影响主流程结果。

校准集 JSONL schema（每行一条，字段均为可选）：
  task_id:      标识
  prompt:       任务输入（让 judge 看上下文用）
  prediction:   待评分的模型输出
  reference:    参考答案
  human_score:  人工分（0-1）
  human_passed: 人工是否通过（bool）
  human_labels: 人工标签列表

输出指标：
  score_pearson_r  : judge_score ↔ human_score 的 Pearson 相关系数
  pass_accuracy    : judge_passed ↔ human_passed 的一致率
  label_macro_f1   : judge_labels ↔ human_labels 的 macro-F1

解读建议（rough rule of thumb）：
  pearson_r ≥ 0.7  → 与人类评分高度线性相关，可信赖
  pass_accuracy ≥ 0.8  → pass/fail 判断与人类大体一致
  label_macro_f1 ≥ 0.5  → label 多分类表现合格
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Judge 校准结果，全部字段均可为 None（对应数据不可用）。"""
    n_samples: int = 0
    n_evaluated: int = 0                         # judge 成功评估的样本数
    score_pearson_r: Optional[float] = None
    pass_accuracy: Optional[float] = None
    label_macro_f1: Optional[float] = None
    per_label_f1: Dict[str, float] = field(default_factory=dict)
    warning: str = ""


# ── 统计工具（纯计算，无副作用）─────────────────────────────────────────────

def _pearson_r(xs: List[float], ys: List[float]) -> Optional[float]:
    """Pearson 相关系数，样本数 < 2 时返回 None。"""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denom_sq = sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)
    if denom_sq <= 0:
        return None
    return num / denom_sq ** 0.5


def _label_f1(
    true_labels_list: List[List[str]],
    pred_labels_list: List[List[str]],
    all_labels: List[str],
) -> Dict[str, float]:
    """per-label F1 + macro 平均（返回 dict，包含 "macro" 键）。"""
    per: Dict[str, float] = {}
    for label in all_labels:
        tp = sum(1 for t, p in zip(true_labels_list, pred_labels_list)
                 if label in t and label in p)
        fp = sum(1 for t, p in zip(true_labels_list, pred_labels_list)
                 if label not in t and label in p)
        fn = sum(1 for t, p in zip(true_labels_list, pred_labels_list)
                 if label in t and label not in p)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        per[label] = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    if per:
        per["macro"] = sum(per.values()) / len(per)
    return per


def _load_calibration_jsonl(path: Path) -> List[Dict[str, Any]]:
    samples: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError as e:
                logger.warning(f"calibration JSONL 第 {line_no} 行解析失败: {e}")
    return samples


# ── 主入口 ───────────────────────────────────────────────────────────────────

async def run_calibration(
    judge: Any,
    calibration_path: Union[str, Path],
    *,
    project_root: Optional[Path] = None,
    max_concurrency: int = 4,
) -> CalibrationResult:
    """对 judge 跑校准集，返回 CalibrationResult。

    judge 须实现 evaluate_async(prediction, reference, *, task, metadata) → EvaluationResult。
    失败时返回带 warning 的空结果，不抛异常。
    """
    path = Path(calibration_path)
    if not path.is_absolute() and project_root:
        path = project_root / path

    if not path.exists():
        return CalibrationResult(warning=f"校准集文件不存在: {path}")

    try:
        samples = _load_calibration_jsonl(path)
    except Exception as e:
        return CalibrationResult(warning=f"读取校准集失败: {e}")

    if not samples:
        return CalibrationResult(warning="校准集为空")

    # 并发调用 judge（受 semaphore 限速）
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _eval_one(sample: Dict[str, Any]):
        async with semaphore:
            try:
                return await judge.evaluate_async(
                    prediction=sample.get("prediction", ""),
                    reference=sample.get("reference"),
                    task=sample.get("task_id", ""),
                    metadata={"source": "calibration", "prompt": sample.get("prompt", "")},
                )
            except Exception as e:
                logger.warning(f"calibration eval 失败 {sample.get('task_id')}: {e}")
                return None

    judge_results = await asyncio.gather(*[_eval_one(s) for s in samples])

    # 收集对比数据
    human_scores: List[float] = []
    judge_scores: List[float] = []
    human_passed: List[bool] = []
    judge_passed_list: List[bool] = []
    human_labels_list: List[List[str]] = []
    judge_labels_list: List[List[str]] = []
    n_evaluated = sum(1 for r in judge_results if r is not None)

    for sample, jr in zip(samples, judge_results):
        if jr is None:
            continue
        # score
        hs = sample.get("human_score")
        if hs is not None:
            try:
                human_scores.append(float(hs))
                judge_scores.append(jr.score)
            except (TypeError, ValueError):
                pass
        # passed
        hp = sample.get("human_passed")
        if hp is not None:
            human_passed.append(bool(hp))
            judge_passed_list.append(jr.passed)
        # labels
        hl = sample.get("human_labels")
        if hl is not None:
            human_labels_list.append(
                [str(x) for x in hl] if isinstance(hl, list) else [str(hl)]
            )
            judge_labels_list.append(jr.labels)

    # 计算指标
    pearson = _pearson_r(human_scores, judge_scores) if len(human_scores) >= 2 else None
    pass_acc = (
        sum(1 for h, j in zip(human_passed, judge_passed_list) if h == j) / len(human_passed)
        if human_passed else None
    )
    per_label: Dict[str, float] = {}
    macro: Optional[float] = None
    if human_labels_list:
        all_labels = sorted({
            lbl
            for ll in human_labels_list + judge_labels_list
            for lbl in ll
        })
        scores_map = _label_f1(human_labels_list, judge_labels_list, all_labels)
        macro = scores_map.pop("macro", None)
        per_label = scores_map

    warnings = []
    if n_evaluated < len(samples):
        warnings.append(f"{len(samples) - n_evaluated}/{len(samples)} 条样本 judge 评估失败")
    if pearson is None and pass_acc is None and macro is None:
        warnings.append("校准集缺少 human_score / human_passed / human_labels 字段，无法计算指标")

    return CalibrationResult(
        n_samples=len(samples),
        n_evaluated=n_evaluated,
        score_pearson_r=pearson,
        pass_accuracy=pass_acc,
        label_macro_f1=macro,
        per_label_f1=per_label,
        warning="; ".join(warnings),
    )
