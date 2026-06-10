"""
EloRanker + PairwiseLLMJudgeEvaluator 单元测试。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.metrics.pairwise import EloRanker, PairwiseLLMJudgeEvaluator, PairwiseResult


# ── EloRanker 测试 ───────────────────────────────────────────────────────────

def test_elo_initial_scores():
    elo = EloRanker(["A", "B", "C"])
    assert elo.scores["A"] == 1000.0
    assert elo.scores["B"] == 1000.0
    assert elo.scores["C"] == 1000.0


def test_elo_winner_gains_points():
    elo = EloRanker(["A", "B"])
    elo.update("A", "B", "A")
    assert elo.scores["A"] > 1000.0
    assert elo.scores["B"] < 1000.0
    # 总分守恒
    assert abs(elo.scores["A"] + elo.scores["B"] - 2000.0) < 1e-6


def test_elo_tie_keeps_equal_scores():
    elo = EloRanker(["A", "B"])
    elo.update("A", "B", "tie")
    assert abs(elo.scores["A"] - elo.scores["B"]) < 1e-6


def test_elo_ranking_order():
    # Use distinct names so they don't clash with positional winner codes "A"/"B"
    elo = EloRanker(["m1", "m2", "m3"])
    for _ in range(5):
        elo.update("m1", "m2", "A")  # m1 beats m2
        elo.update("m1", "m3", "A")  # m1 beats m3
        elo.update("m2", "m3", "A")  # m2 beats m3
    ranking = elo.ranking()
    models = [m for m, _ in ranking]
    assert models[0] == "m1"
    assert models[-1] == "m3"


def test_elo_win_loss_counters():
    elo = EloRanker(["A", "B"])
    elo.update("A", "B", "A")
    elo.update("A", "B", "B")
    assert elo.wins["A"] == 1
    assert elo.losses["A"] == 1
    assert elo.wins["B"] == 1
    assert elo.losses["B"] == 1


def test_elo_tie_counters():
    elo = EloRanker(["A", "B"])
    elo.update("A", "B", "tie")
    assert elo.ties["A"] == 1
    assert elo.ties["B"] == 1


def test_elo_win_rate():
    elo = EloRanker(["A", "B"])
    elo.update("A", "B", "A")  # A wins
    elo.update("A", "B", "A")  # A wins
    elo.update("A", "B", "tie")  # tie
    # win_rate = (2 wins + 0.5 * 1 tie) / 3 total = 2.5/3
    assert abs(elo.win_rate("A") - 2.5 / 3) < 1e-6


def test_elo_dynamic_model_registration():
    elo = EloRanker([])
    elo.update("X", "Y", "A")  # "A" = first positional arg wins = "X" wins
    assert "X" in elo.scores
    assert "Y" in elo.scores
    assert elo.scores["X"] > elo.scores["Y"]


# ── PairwiseLLMJudgeEvaluator 测试 ──────────────────────────────────────────

def _make_pairwise_judge(winner: str, reason: str = "ok") -> PairwiseLLMJudgeEvaluator:
    """返回一个 mock judge，compare 总是返回固定 winner。"""
    import json

    mock_response = MagicMock()
    mock_response.content = json.dumps({"winner": winner, "reason": reason})
    mock_response.latency_ms = 100.0
    mock_response.input_tokens = 50
    mock_response.output_tokens = 20

    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value=mock_response)
    mock_llm.close = AsyncMock()

    judge = PairwiseLLMJudgeEvaluator(llm=mock_llm, swap_positions=False)
    return judge


def test_pairwise_no_swap_winner_a():
    judge = _make_pairwise_judge("A")
    result = asyncio.run(judge.compare_async(
        task_id="t1", model_a="gpt4", output_a="ans A",
        model_b="claude", output_b="ans B",
    ))
    assert result.winner == "A"
    assert result.model_a == "gpt4"
    assert result.model_b == "claude"


def test_pairwise_no_swap_winner_b():
    judge = _make_pairwise_judge("B")
    result = asyncio.run(judge.compare_async(
        task_id="t1", model_a="gpt4", output_a="ans A",
        model_b="claude", output_b="ans B",
    ))
    assert result.winner == "B"


def test_pairwise_no_swap_tie():
    judge = _make_pairwise_judge("tie")
    result = asyncio.run(judge.compare_async(
        task_id="t1", model_a="gpt4", output_a="ans A",
        model_b="claude", output_b="ans B",
    ))
    assert result.winner == "tie"


def test_pairwise_with_swap_consistent_winner():
    """两次调用都说 A 赢 → swap_positions 下应得 A。"""
    import json

    call_count = [0]

    async def mock_chat(messages):
        r = MagicMock()
        r.content = json.dumps({"winner": "A", "reason": "A is better"})
        r.latency_ms = 50.0
        r.input_tokens = 20
        r.output_tokens = 10
        call_count[0] += 1
        return r

    mock_llm = MagicMock()
    mock_llm.chat = mock_chat
    mock_llm.close = AsyncMock()

    judge = PairwiseLLMJudgeEvaluator(llm=mock_llm, swap_positions=True)
    result = asyncio.run(judge.compare_async(
        task_id="t1", model_a="M1", output_a="X",
        model_b="M2", output_b="Y",
    ))
    # 第一次: A wins (M1 wins), 第二次 swap: A wins → 映射回来是 B wins → 不一致 → tie
    assert result.winner == "tie"
    assert call_count[0] == 2


def test_pairwise_with_swap_inconsistent_becomes_tie():
    """两次调用不一致时，应输出 tie。"""
    import json

    responses = [
        {"winner": "A", "reason": "first call"},
        {"winner": "A", "reason": "second call (B-A order, A=original-B wins)"},
    ]
    idx = [0]

    async def mock_chat(messages):
        r = MagicMock()
        r.content = json.dumps(responses[idx[0] % 2])
        r.latency_ms = 50.0
        r.input_tokens = 20
        r.output_tokens = 10
        idx[0] += 1
        return r

    mock_llm = MagicMock()
    mock_llm.chat = mock_chat
    mock_llm.close = AsyncMock()

    judge = PairwiseLLMJudgeEvaluator(llm=mock_llm, swap_positions=True)
    result = asyncio.run(judge.compare_async(
        task_id="t1", model_a="M1", output_a="X",
        model_b="M2", output_b="Y",
    ))
    assert result.winner == "tie"


def test_pairwise_invalid_json_falls_back_to_tie():
    """judge 输出不合法 JSON → winner=tie。"""
    mock_response = MagicMock()
    mock_response.content = "I think A is better!"  # not JSON
    mock_response.latency_ms = 50.0
    mock_response.input_tokens = 10
    mock_response.output_tokens = 10

    mock_llm = MagicMock()
    mock_llm.chat = AsyncMock(return_value=mock_response)
    mock_llm.close = AsyncMock()

    judge = PairwiseLLMJudgeEvaluator(llm=mock_llm, swap_positions=False)
    result = asyncio.run(judge.compare_async(
        task_id="t1", model_a="M1", output_a="X",
        model_b="M2", output_b="Y",
    ))
    assert result.winner == "tie"


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
