"""
PoLL (Panel of LLM Judges) 单元测试。

覆盖：
- 家族识别启发式
- trimmed_mean / median / aggregate_score / min_support_count
- PanelLLMJudgeEvaluator 聚合行为：
  * 多数票 passed
  * label 支持度过滤
  * panel_disagree 自动标记
  * dimensions 按维度独立聚合
  * member_details 完整保留
- 跨家族 warning（同家族重复 → log.warning）
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.base import LLMConfig
from src.llm.mock import MockLLM
from src.metrics.evaluators import (
    LLMJudgeEvaluator,
    PanelLLMJudgeEvaluator,
    detect_family,
    _trimmed_mean,
    _median,
    _aggregate_score,
    _min_support_count,
)


# ── 家族识别 ─────────────────────────────────────────────────────────────

def test_detect_family_well_known():
    assert detect_family("gpt-4o") == "openai"
    assert detect_family("gpt-3.5-turbo") == "openai"
    assert detect_family("o3-mini") == "openai"
    assert detect_family("claude-sonnet-4") == "anthropic"
    assert detect_family("claude-3-opus-20240229") == "anthropic"
    assert detect_family("qwen-max") == "qwen"
    assert detect_family("qwen2.5-72b-instruct") == "qwen"
    assert detect_family("deepseek-v3") == "deepseek"
    assert detect_family("glm-4-plus") == "zhipu"
    assert detect_family("kimi-k1") == "moonshot"
    assert detect_family("llama-3.1-70b") == "meta"
    assert detect_family("mixtral-8x22b-instruct") == "mistral"
    assert detect_family("gemini-2.0-flash") == "google"
    assert detect_family("grok-2") == "xai"


def test_detect_family_unknown():
    assert detect_family("") == "unknown"
    assert detect_family("my-internal-vllm-deploy-2024") == "unknown"


# ── 聚合 helper ─────────────────────────────────────────────────────────

def test_trimmed_mean_drops_extremes_when_n_ge_3():
    # 5 个值，去掉 0.2 和 0.9 → (0.5+0.6+0.7)/3 = 0.6
    assert abs(_trimmed_mean([0.2, 0.5, 0.6, 0.7, 0.9]) - 0.6) < 1e-9


def test_trimmed_mean_falls_back_to_mean_when_n_lt_3():
    assert _trimmed_mean([0.3, 0.7]) == 0.5
    assert _trimmed_mean([0.42]) == 0.42
    assert _trimmed_mean([]) == 0.0


def test_median_even_and_odd():
    assert _median([0.2, 0.5, 0.9]) == 0.5
    assert _median([0.2, 0.5, 0.7, 0.9]) == 0.6


def test_aggregate_score_dispatches():
    vals = [0.2, 0.5, 0.8]
    assert _aggregate_score(vals, "mean") == 0.5
    assert _aggregate_score(vals, "median") == 0.5
    # trimmed_mean with n=3 → trim both ends, left with [0.5], mean=0.5
    assert _aggregate_score(vals, "trimmed_mean") == 0.5
    # majority: 2 of 3 ≥ 0.5 → 1.0
    assert _aggregate_score(vals, "majority") == 1.0


def test_min_support_count_modes():
    assert _min_support_count(3, "ceil_half") == 2
    assert _min_support_count(4, "ceil_half") == 2  # ceil(4/2)=2
    assert _min_support_count(5, "ceil_half") == 3
    assert _min_support_count(3, "majority") == 2
    assert _min_support_count(4, "majority") == 3
    assert _min_support_count(3, "all") == 3


# ── Panel 聚合行为 ─────────────────────────────────────────────────────────

def _make_judge(name: str, model_name: str, response: dict) -> LLMJudgeEvaluator:
    """构造一个会返回固定 JSON 的 mock judge。"""
    llm = MockLLM(LLMConfig(model_name=model_name, endpoint_url=""))
    llm.set_json_response(response)
    return LLMJudgeEvaluator(llm=llm, rubric="dummy rubric", threshold=0.6)


def test_panel_majority_vote_passed():
    """3 成员里 2 个 passed → 整体 passed=True。"""
    judges = [
        _make_judge("j1", "gpt-4o", {"score": 0.8, "passed": True, "labels": ["correct"]}),
        _make_judge("j2", "claude-sonnet-4", {"score": 0.7, "passed": True, "labels": ["correct"]}),
        _make_judge("j3", "qwen-max", {"score": 0.4, "passed": False, "labels": ["incomplete_answer"]}),
    ]
    panel = PanelLLMJudgeEvaluator(
        members=judges,
        member_names=["j1", "j2", "j3"],
        member_families=["openai", "anthropic", "qwen"],
        disagreement_threshold=0.5,  # 0.8-0.4=0.4 < 0.5 → 不算 disagree
    )
    result = asyncio.run(panel.evaluate_async("pred", "ref"))
    assert result.passed is True
    # trimmed_mean of [0.4, 0.7, 0.8] → drop 0.4 + 0.8 → [0.7] → 0.7
    assert abs(result.score - 0.7) < 1e-9


def test_panel_majority_vote_failed_at_tie():
    """2 vs 2 平票时 passed=False（保守）。"""
    judges = [
        _make_judge("j1", "gpt-4o", {"score": 0.7, "passed": True, "labels": []}),
        _make_judge("j2", "claude-sonnet-4", {"score": 0.7, "passed": True, "labels": []}),
        _make_judge("j3", "qwen-max", {"score": 0.3, "passed": False, "labels": []}),
        _make_judge("j4", "deepseek-v3", {"score": 0.3, "passed": False, "labels": []}),
    ]
    panel = PanelLLMJudgeEvaluator(
        members=judges,
        member_names=["j1", "j2", "j3", "j4"],
        member_families=["openai", "anthropic", "qwen", "deepseek"],
        disagreement_threshold=0.5,
    )
    result = asyncio.run(panel.evaluate_async("pred", "ref"))
    assert result.passed is False  # 2/4 不严格大于 4/2，按保守 False


def test_panel_label_support_filtering():
    """label 必须 ≥ ceil(N/2) 个成员同意才进 consensus_labels。"""
    judges = [
        _make_judge("j1", "gpt-4o", {"score": 0.8, "passed": True, "labels": ["a", "b"]}),
        _make_judge("j2", "claude-sonnet-4", {"score": 0.8, "passed": True, "labels": ["a", "c"]}),
        _make_judge("j3", "qwen-max", {"score": 0.8, "passed": True, "labels": ["a"]}),
    ]
    panel = PanelLLMJudgeEvaluator(
        members=judges,
        member_names=["j1", "j2", "j3"],
        member_families=["openai", "anthropic", "qwen"],
        min_label_support="ceil_half",  # ⌈3/2⌉ = 2
    )
    result = asyncio.run(panel.evaluate_async("pred", "ref"))
    # a: 3 票（保留）；b: 1 票（淘汰）；c: 1 票（淘汰）
    assert result.labels == ["a"]


def test_panel_disagree_auto_flag():
    """max - min > threshold → 自动加 panel_disagree label。"""
    judges = [
        _make_judge("j1", "gpt-4o", {"score": 0.9, "passed": True, "labels": []}),
        _make_judge("j2", "claude-sonnet-4", {"score": 0.6, "passed": True, "labels": []}),
        _make_judge("j3", "qwen-max", {"score": 0.1, "passed": False, "labels": []}),
    ]
    panel = PanelLLMJudgeEvaluator(
        members=judges,
        member_names=["j1", "j2", "j3"],
        member_families=["openai", "anthropic", "qwen"],
        disagreement_threshold=0.3,  # 0.9 - 0.1 = 0.8 > 0.3
    )
    result = asyncio.run(panel.evaluate_async("pred", "ref"))
    assert "panel_disagree" in result.labels
    assert result.details["agreement"]["panel_disagree"] is True
    assert abs(result.details["agreement"]["score_range"] - 0.8) < 1e-9


def test_panel_dimensions_aggregated_per_dim():
    """dimensions 按维度独立聚合。"""
    judges = [
        _make_judge("j1", "gpt-4o", {
            "score": 0.8, "passed": True, "labels": [],
            "dimensions": {"correctness": 0.9, "safety": 0.7},
        }),
        _make_judge("j2", "claude-sonnet-4", {
            "score": 0.6, "passed": True, "labels": [],
            "dimensions": {"correctness": 0.6, "safety": 0.5},
        }),
        _make_judge("j3", "qwen-max", {
            "score": 0.7, "passed": True, "labels": [],
            "dimensions": {"correctness": 0.7, "safety": 0.6},
        }),
    ]
    panel = PanelLLMJudgeEvaluator(
        members=judges,
        member_names=["j1", "j2", "j3"],
        member_families=["openai", "anthropic", "qwen"],
    )
    result = asyncio.run(panel.evaluate_async("pred", "ref"))
    dims = result.details["dimensions"]
    # trimmed_mean of [0.6, 0.7, 0.9] = drop 0.6+0.9 → [0.7] → 0.7
    assert abs(dims["correctness"] - 0.7) < 1e-9
    # trimmed_mean of [0.5, 0.6, 0.7] = drop 0.5+0.7 → [0.6] → 0.6
    assert abs(dims["safety"] - 0.6) < 1e-9


def test_panel_member_details_preserved():
    """每个成员的原始判定都进 details.members，便于报告下钻。"""
    judges = [
        _make_judge("j1", "gpt-4o", {"score": 0.8, "passed": True, "labels": ["correct"],
                                      "comment": "looks good"}),
        _make_judge("j2", "claude-sonnet-4", {"score": 0.4, "passed": False, "labels": ["weak_reasoning"],
                                                "comment": "missed a step"}),
        _make_judge("j3", "qwen-max", {"score": 0.7, "passed": True, "labels": ["correct"],
                                        "comment": "ok"}),
    ]
    panel = PanelLLMJudgeEvaluator(
        members=judges,
        member_names=["openai_judge", "claude_judge", "qwen_judge"],
        member_families=["openai", "anthropic", "qwen"],
    )
    result = asyncio.run(panel.evaluate_async("pred", "ref"))
    members = result.details["members"]
    assert len(members) == 3
    names = [m["name"] for m in members]
    assert names == ["openai_judge", "claude_judge", "qwen_judge"]
    assert members[0]["family"] == "openai"
    assert members[1]["family"] == "anthropic"
    assert members[2]["family"] == "qwen"
    assert members[1]["comment"] == "missed a step"
    # comment 拼接保留追溯
    assert "[openai_judge]" in result.comment
    assert "[claude_judge]" in result.comment


def test_panel_warns_on_repeated_family(caplog):
    """同家族 ≥ 2 个 + require_diverse_families=True → log.warning。"""
    judges = [
        _make_judge("j1", "gpt-4o",     {"score": 0.8, "passed": True, "labels": []}),
        _make_judge("j2", "gpt-4-turbo", {"score": 0.7, "passed": True, "labels": []}),
        _make_judge("j3", "qwen-max",    {"score": 0.6, "passed": True, "labels": []}),
    ]
    with caplog.at_level(logging.WARNING, logger="src.metrics.evaluators"):
        PanelLLMJudgeEvaluator(
            members=judges,
            member_names=["j1", "j2", "j3"],
            member_families=["openai", "openai", "qwen"],
            require_diverse_families=True,
            panel_name="bad_panel",
        )
    # 应有一条 warning 提到 openai 家族重复
    msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("openai" in m and "bad_panel" in m for m in msgs)


def test_panel_does_not_warn_when_diverse():
    """所有家族唯一 → 不产生 warning。"""
    judges = [
        _make_judge("j1", "gpt-4o", {"score": 0.8, "passed": True, "labels": []}),
        _make_judge("j2", "claude-sonnet-4", {"score": 0.7, "passed": True, "labels": []}),
        _make_judge("j3", "qwen-max", {"score": 0.6, "passed": True, "labels": []}),
    ]
    import logging as _logging
    from logging.handlers import MemoryHandler
    caplog_handler = MemoryHandler(capacity=1024)
    logger = _logging.getLogger("src.metrics.evaluators")
    logger.addHandler(caplog_handler)
    try:
        PanelLLMJudgeEvaluator(
            members=judges,
            member_names=["j1", "j2", "j3"],
            member_families=["openai", "anthropic", "qwen"],
            require_diverse_families=True,
        )
    finally:
        logger.removeHandler(caplog_handler)
    warnings = [r for r in caplog_handler.buffer if r.levelno >= _logging.WARNING]
    assert warnings == []


def test_panel_close_calls_all_members():
    judges = [
        _make_judge("j1", "gpt-4o", {"score": 0.8, "passed": True, "labels": []}),
        _make_judge("j2", "claude-sonnet-4", {"score": 0.7, "passed": True, "labels": []}),
        _make_judge("j3", "qwen-max", {"score": 0.6, "passed": True, "labels": []}),
    ]
    panel = PanelLLMJudgeEvaluator(
        members=judges,
        member_names=["j1", "j2", "j3"],
        member_families=["openai", "anthropic", "qwen"],
    )
    # 不应抛异常
    asyncio.run(panel.close())


if __name__ == "__main__":
    # 简易运行：python tests/test_panel_judge.py
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            sig = t.__code__.co_varnames[:t.__code__.co_argcount]
            if "caplog" in sig:
                # 这条用例需要 pytest 才能跑，跳过
                print(f"SKIP  {t.__name__} (requires pytest)")
                continue
            t()
            print(f"PASS  {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed - 1} passed, {failed} failed, 1 skipped")
    sys.exit(1 if failed else 0)
