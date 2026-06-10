"""
CalibrationResult + run_calibration 单元测试。
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.metrics.calibration import (
    CalibrationResult,
    _label_f1,
    _pearson_r,
    run_calibration,
)
from src.metrics.evaluators import EvaluationResult


# ── 统计工具 ─────────────────────────────────────────────────────────────────

def test_pearson_r_perfect_positive():
    xs = [0.0, 0.5, 1.0]
    ys = [0.0, 0.5, 1.0]
    assert abs(_pearson_r(xs, ys) - 1.0) < 1e-6


def test_pearson_r_perfect_negative():
    xs = [0.0, 0.5, 1.0]
    ys = [1.0, 0.5, 0.0]
    assert abs(_pearson_r(xs, ys) - (-1.0)) < 1e-6


def test_pearson_r_too_few_samples():
    assert _pearson_r([0.5], [0.5]) is None
    assert _pearson_r([], []) is None


def test_pearson_r_constant_xs():
    # 方差为 0 → None（除以 0）
    assert _pearson_r([0.5, 0.5, 0.5], [0.0, 0.5, 1.0]) is None


def test_label_f1_perfect():
    true = [["correct"], ["format_error"]]
    pred = [["correct"], ["format_error"]]
    out = _label_f1(true, pred, ["correct", "format_error"])
    assert abs(out["correct"] - 1.0) < 1e-6
    assert abs(out["format_error"] - 1.0) < 1e-6
    assert abs(out["macro"] - 1.0) < 1e-6


def test_label_f1_no_overlap():
    true = [["correct"]]
    pred = [["format_error"]]
    out = _label_f1(true, pred, ["correct", "format_error"])
    assert out["correct"] == 0.0
    assert out["format_error"] == 0.0
    assert out["macro"] == 0.0


def test_label_f1_partial():
    true = [["correct", "incomplete_answer"], ["format_error"]]
    pred = [["correct"], ["format_error", "hallucination"]]
    out = _label_f1(true, pred, ["correct", "incomplete_answer", "format_error", "hallucination"])
    assert out["correct"] > 0.0
    assert out["format_error"] > 0.0


# ── run_calibration 集成测试 ─────────────────────────────────────────────────

def _make_mock_judge(score: float = 0.8, passed: bool = True, labels=None):
    """构造一个总是返回固定结果的 mock judge。"""
    fixed = EvaluationResult(
        score=score,
        passed=passed,
        labels=labels or ["correct"],
    )

    class MockJudge:
        async def evaluate_async(self, prediction, reference=None, *, task=None, metadata=None):
            return fixed

    return MockJudge()


def _write_jsonl(path: Path, rows: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_run_calibration_missing_file():
    judge = _make_mock_judge()
    result = asyncio.run(run_calibration(judge, "/nonexistent/path/cal.jsonl"))
    assert result.n_samples == 0
    assert "不存在" in result.warning


def test_run_calibration_empty_file():
    with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
        tmp = Path(f.name)
    judge = _make_mock_judge()
    result = asyncio.run(run_calibration(judge, tmp))
    assert result.n_samples == 0
    assert result.warning


def test_run_calibration_score_pearson():
    """judge 给 0.8 分，human 也是 0.8 → pearson_r 应该是 1.0（完全一致）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cal_path = Path(tmpdir) / "cal.jsonl"
        rows = [
            {"task_id": f"t{i}", "prediction": f"ans{i}",
             "human_score": 0.8, "human_passed": True, "human_labels": ["correct"]}
            for i in range(5)
        ]
        _write_jsonl(cal_path, rows)

        judge = _make_mock_judge(score=0.8, passed=True, labels=["correct"])
        result = asyncio.run(run_calibration(judge, cal_path))

    assert result.n_samples == 5
    assert result.n_evaluated == 5
    # 所有 judge 分都是 0.8，human 也是 0.8 → 常数序列，pearson = None
    assert result.score_pearson_r is None  # 常数向量方差为 0
    # pass_accuracy: all True vs all True → 1.0
    assert result.pass_accuracy == 1.0
    # label f1: perfect match
    assert result.label_macro_f1 is not None
    assert result.label_macro_f1 > 0.9


def test_run_calibration_varying_scores():
    """human_score 从 0 到 1 线性，judge 分完全一致 → pearson_r=1。"""
    n = 5
    with tempfile.TemporaryDirectory() as tmpdir:
        cal_path = Path(tmpdir) / "cal.jsonl"
        scores = [i / (n - 1) for i in range(n)]
        rows = [
            {"task_id": f"t{i}", "prediction": f"ans{i}", "human_score": s}
            for i, s in enumerate(scores)
        ]
        _write_jsonl(cal_path, rows)

        # judge 返回的分和 human_score 一一对应
        call_idx = [0]

        class VaryingJudge:
            async def evaluate_async(self, prediction, reference=None, *, task=None, metadata=None):
                idx = call_idx[0]
                call_idx[0] += 1
                return EvaluationResult(score=scores[idx], passed=scores[idx] >= 0.5)

        result = asyncio.run(run_calibration(VaryingJudge(), cal_path))

    assert result.n_samples == n
    assert result.score_pearson_r is not None
    assert abs(result.score_pearson_r - 1.0) < 1e-6


def test_run_calibration_no_human_annotations():
    """校准集里没有 human_score 等字段 → 指标全 None，有 warning。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cal_path = Path(tmpdir) / "cal.jsonl"
        rows = [{"task_id": f"t{i}", "prediction": f"ans{i}"} for i in range(3)]
        _write_jsonl(cal_path, rows)

        judge = _make_mock_judge()
        result = asyncio.run(run_calibration(judge, cal_path))

    assert result.n_samples == 3
    assert result.score_pearson_r is None
    assert result.pass_accuracy is None
    assert result.label_macro_f1 is None
    assert result.warning  # 应该有 warning


def test_run_calibration_partial_judge_failure():
    """judge 对部分样本失败 → n_evaluated < n_samples，但不报错。"""
    call_idx = [0]

    class SometimesFailJudge:
        async def evaluate_async(self, prediction, reference=None, *, task=None, metadata=None):
            idx = call_idx[0]
            call_idx[0] += 1
            if idx % 2 == 0:
                raise RuntimeError("simulated failure")
            return EvaluationResult(score=0.8, passed=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        cal_path = Path(tmpdir) / "cal.jsonl"
        rows = [{"task_id": f"t{i}", "prediction": f"ans{i}",
                 "human_score": 0.8} for i in range(4)]
        _write_jsonl(cal_path, rows)

        result = asyncio.run(run_calibration(SometimesFailJudge(), cal_path))

    assert result.n_samples == 4
    assert result.n_evaluated == 2  # 只有奇数 idx 成功
    # 虽然 n_evaluated=2，但 scores 列表长度也只有 2，pearson 样本不足 → None
    # 只要不 raise 即可


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
