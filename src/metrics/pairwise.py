"""
Pairwise LLM Judge — A vs B 直接对比，替代绝对打分。

与 pointwise 的区别：
  - 不需要校准 rubric 的绝对尺度；只要求"哪个更好"
  - 适用场景：同一批 prompt 跑了多个模型，想知道相对排名
  - 输出：winner(A/B/tie) → 聚合为 Elo 分 + win 矩阵

位置偏差处理（swap_positions=True，默认开启）：
  - 把 A/B 互换重跑一次，两次一致才算定论；否则置 tie
  - 消除"先读到的回答偏高分"的位置偏差

参考：Chatbot Arena (Zheng et al., 2024), arXiv:2306.05685
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..llm.base import BaseLLM
from ..utils.json_utils import robust_json_parse

logger = logging.getLogger(__name__)


@dataclass
class PairwiseResult:
    """一次 A vs B 对比结果。"""
    task_id: str
    model_a: str
    model_b: str
    winner: str          # "A" | "B" | "tie"
    reason: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class PairwiseExperimentResult:
    """pairwise 评测的汇总结果（存入 ExperimentResult.pairwise）。"""
    models: List[str]
    elo_scores: Dict[str, float]
    ranking: List[Tuple[str, float]]               # [(model, elo), ...] 从高到低
    win_matrix: Dict[str, Dict[str, Dict[str, int]]]  # a→b→{wins,losses,ties,total}
    n_comparisons: int
    judge: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "models": self.models,
            "elo_scores": self.elo_scores,
            "ranking": self.ranking,
            "win_matrix": self.win_matrix,
            "n_comparisons": self.n_comparisons,
            "judge": self.judge,
        }


class PairwiseLLMJudgeEvaluator:
    """用 LLM 做 A vs B 对比判断。

    支持 swap_positions（默认开启）：把 A/B 互换后再跑一次，
    两次一致才确认胜者，否则 tie，消除位置偏差。
    """

    name = "pairwise_judge"

    DEFAULT_SYSTEM_PROMPT = (
        "你是一个公正的裁判，需要比较两个模型对同一任务的回答。\n"
        "先独立分析每个回答，再判断哪个更好。\n"
        "只输出合法 JSON：{\"winner\": \"A\" 或 \"B\" 或 \"tie\", \"reason\": \"一句话理由\"}\n"
        "不要输出 Markdown，不要输出任何前后缀文本。"
    )

    def __init__(
        self,
        llm: BaseLLM,
        rubric: str = "",
        system_prompt: Optional[str] = None,
        swap_positions: bool = True,
    ):
        self.llm = llm
        self.rubric = rubric
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self.swap_positions = swap_positions

    @classmethod
    def from_profile(cls, profile: Any) -> "PairwiseLLMJudgeEvaluator":
        """从 JudgeProfile 创建。"""
        from ..llm import create_llm
        from ..llm.base import LLMConfig
        config = LLMConfig(
            model_name=profile.model_name,
            endpoint_url=profile.endpoint_url,
            api_key=profile.api_key,
            temperature=profile.temperature,
            max_tokens=min(profile.max_tokens, 600),
            top_p=profile.top_p,
            timeout_seconds=profile.timeout_seconds,
            enable_thinking=profile.enable_thinking,
            extra_params=profile.extra_params,
        )
        return cls(
            llm=create_llm(config, class_name=profile.class_name),
            rubric=getattr(profile, "rubric", ""),
        )

    async def compare_async(
        self,
        task_id: str,
        model_a: str,
        output_a: str,
        model_b: str,
        output_b: str,
        *,
        task_prompt: str = "",
        reference: Any = None,
    ) -> PairwiseResult:
        """比较 A vs B。swap_positions=True 时自动换位复查。"""
        r_ab = await self._single_compare(output_a, output_b,
                                          task_prompt=task_prompt, reference=reference)

        if not self.swap_positions:
            return PairwiseResult(
                task_id=task_id, model_a=model_a, model_b=model_b,
                winner=r_ab["winner"], reason=r_ab["reason"],
                latency_ms=r_ab["latency_ms"],
                input_tokens=r_ab["input_tokens"],
                output_tokens=r_ab["output_tokens"],
            )

        # 换位复查
        r_ba = await self._single_compare(output_b, output_a,
                                          task_prompt=task_prompt, reference=reference)
        # 把 BA 结果映射回 AB 视角
        flip = {"A": "B", "B": "A", "tie": "tie"}
        w_ab = r_ab["winner"]
        w_ba_as_ab = flip.get(r_ba["winner"], "tie")

        winner = w_ab if w_ab == w_ba_as_ab else "tie"
        return PairwiseResult(
            task_id=task_id, model_a=model_a, model_b=model_b,
            winner=winner,
            reason=f"[AB]{r_ab['reason']} | [BA]{r_ba['reason']}",
            latency_ms=r_ab["latency_ms"] + r_ba["latency_ms"],
            input_tokens=r_ab["input_tokens"] + r_ba["input_tokens"],
            output_tokens=r_ab["output_tokens"] + r_ba["output_tokens"],
        )

    async def _single_compare(
        self,
        output_a: str,
        output_b: str,
        *,
        task_prompt: str,
        reference: Any,
    ) -> Dict[str, Any]:
        payload = {
            "task": task_prompt,
            "reference": reference,
            "rubric": self.rubric,
            "output_A": output_a,
            "output_B": output_b,
            "output_schema": {"winner": "A | B | tie", "reason": "one-sentence explanation"},
        }
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ]
        response = await self.llm.chat(messages)
        parsed = robust_json_parse(response.content)

        winner = "tie"
        reason = ""
        if isinstance(parsed, dict):
            raw = str(parsed.get("winner", "")).strip().upper()
            if raw in ("A", "B"):
                winner = raw
            elif "TIE" in raw:
                winner = "tie"
            reason = str(parsed.get("reason", ""))

        return {
            "winner": winner,
            "reason": reason,
            "latency_ms": getattr(response, "latency_ms", 0.0),
            "input_tokens": getattr(response, "input_tokens", 0),
            "output_tokens": getattr(response, "output_tokens", 0),
        }

    async def close(self) -> None:
        await self.llm.close()


# ── Elo ──────────────────────────────────────────────────────────────────────

class EloRanker:
    """从 pairwise 结果聚合 Elo 排名。

    初始分 1000，K=32（适合 ≤200 对比的实验规模）。
    同一个 model 出现多轮结果时 Elo 会累积更新，体现统计稳健性。
    """

    def __init__(
        self,
        models: Sequence[str],
        initial_elo: float = 1000.0,
        k: float = 32.0,
    ):
        self.scores: Dict[str, float] = {m: initial_elo for m in models}
        self.k = k
        self._initial = initial_elo
        self.wins: Dict[str, int] = {m: 0 for m in models}
        self.losses: Dict[str, int] = {m: 0 for m in models}
        self.ties: Dict[str, int] = {m: 0 for m in models}

    def _ensure(self, model: str) -> None:
        if model not in self.scores:
            self.scores[model] = self._initial
            self.wins[model] = 0
            self.losses[model] = 0
            self.ties[model] = 0

    def update(self, model_a: str, model_b: str, winner: str) -> None:
        """更新 Elo。winner: 'A' | 'B' | 'tie'"""
        self._ensure(model_a)
        self._ensure(model_b)
        ra, rb = self.scores[model_a], self.scores[model_b]
        ea = 1 / (1 + 10 ** ((rb - ra) / 400))

        if winner == "A":
            sa, sb = 1.0, 0.0
            self.wins[model_a] += 1
            self.losses[model_b] += 1
        elif winner == "B":
            sa, sb = 0.0, 1.0
            self.wins[model_b] += 1
            self.losses[model_a] += 1
        else:
            sa, sb = 0.5, 0.5
            self.ties[model_a] += 1
            self.ties[model_b] += 1

        self.scores[model_a] = ra + self.k * (sa - ea)
        self.scores[model_b] = rb + self.k * (sb - (1 - ea))

    def ranking(self) -> List[Tuple[str, float]]:
        """返回 [(model, elo), ...] 从高到低。"""
        return sorted(self.scores.items(), key=lambda x: x[1], reverse=True)

    def win_rate(self, model: str) -> float:
        """胜率（平局算 0.5）。"""
        w = self.wins.get(model, 0)
        t = self.ties.get(model, 0)
        n = w + self.losses.get(model, 0) + t
        return (w + 0.5 * t) / n if n else 0.0
