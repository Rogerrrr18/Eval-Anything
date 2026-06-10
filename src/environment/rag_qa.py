"""
RAGQAEnvironment — end-to-end evaluation for retrieval QA applications.

The environment prepares a question from the dataset, invokes a configured
Target through the "chat" operation, and scores answer correctness plus
citation grounding with lightweight rule metrics. LLM-as-Judge can still be
attached at the environment profile level for semantic scoring.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .base import BaseEnvironment, EnvConfig, EnvStepResult, TaskInstance
from ..target import create_target
from ..target.base import TargetConfig, TargetResponse


def _norm_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip().lower()


class RAGQAEnvironment(BaseEnvironment):
    """Task environment for evaluating RAG-style question answering apps."""

    def __init__(self, config: EnvConfig):
        super().__init__(config)
        self._target = None
        self._answer: str = ""
        self._target_response: Optional[TargetResponse] = None
        self._scores: Dict[str, float] = {}
        self._citations: List[str] = []

    async def reset(self, task: TaskInstance) -> str:
        self.current_task = task
        self.step_count = 0
        self._done = False
        self._answer = ""
        self._target_response = None
        self._scores = {}
        self._citations = []

        if self._target is None:
            self._target = self._create_target()
        await self._target.setup(task)
        return self._get_question(task)

    async def step(self, action: Any) -> EnvStepResult:
        self.step_count += 1
        if self.current_task is None:
            raise RuntimeError("RAGQAEnvironment.step() called before reset()")
        if self._target is None:
            self._target = self._create_target()

        question = self._extract_action_text(action) or self._get_question(self.current_task)
        payload = self._build_payload(self.current_task, question)
        response = await self._target.invoke("chat", payload, task=self.current_task)
        self._target_response = response

        self._answer = self._extract_answer(response.content)
        self._citations = self._extract_citations(response.content)
        self._scores = self._score_response(response)
        reward = self.get_reward()
        self._mark_done(terminated=True)

        return EnvStepResult(
            observation=f"评测完成。回答得分: {reward:.2%}",
            reward=reward,
            terminated=True,
            truncated=False,
            info={
                "final_answer": self._answer,
                "prediction": self._answer,
                "reference": self._get_reference(self.current_task),
                "citations": self._citations,
                "target_ok": response.ok,
                "target_status_code": response.status_code,
                "target_latency_ms": response.latency_ms,
                "target_error": response.error,
                "target_response": response.raw_response,
                "format_ok": response.ok,
                "rag_scores": dict(self._scores),
            },
        )

    def get_reward(self) -> float:
        if not self._scores:
            return 0.0
        metric_names = self.config.extra_params.get("metrics") or list(self._scores.keys())
        values = [self._scores[name] for name in metric_names if name in self._scores]
        return sum(values) / len(values) if values else 0.0

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({
            "final_answer": self._answer,
            "prediction": self._answer,
            "citations": list(self._citations),
            "rag_scores": dict(self._scores),
            "target_status_code": self._target_response.status_code if self._target_response else None,
            "target_latency_ms": self._target_response.latency_ms if self._target_response else 0.0,
            "target_error": self._target_response.error if self._target_response else None,
            "target_response": self._target_response.raw_response if self._target_response else None,
            "format_ok": self._target_response.ok if self._target_response else False,
        })
        return info

    async def close(self) -> None:
        if self._target is not None:
            await self._target.teardown(self.current_task)
            await self._target.close()

    def _create_target(self):
        raw = self.config.target_config
        if not raw:
            raise ValueError(
                f"Environment {self.config.name!r} requires a target profile. "
                "Set target: <target_name> in configs/environments.yaml."
            )
        target_config = TargetConfig(
            name=raw.get("name", self.config.target or "target"),
            class_name=raw.get("class", raw.get("class_name", "HTTPAppTarget")),
            base_url=raw.get("base_url", ""),
            endpoints=dict(raw.get("endpoints", {})),
            headers=dict(raw.get("headers", {})),
            api_key=raw.get("api_key", "EMPTY"),
            api_key_env=raw.get("api_key_env"),
            timeout_seconds=raw.get("timeout_seconds", 60),
            extra_params=dict(raw.get("extra_params", {})),
        )
        return create_target(target_config, class_name=target_config.class_name)

    def _build_payload(self, task: TaskInstance, question: str) -> Dict[str, Any]:
        metadata = task.metadata or {}
        request_template = self.config.extra_params.get("request_template")
        base = {
            "question": question,
            "query": question,
            "message": question,
            "files": metadata.get("files", []),
            "metadata": metadata,
        }
        if not isinstance(request_template, dict):
            return base

        payload = {}
        for key, value in request_template.items():
            if value == "$question":
                payload[key] = question
            elif value == "$files":
                payload[key] = metadata.get("files", [])
            elif value == "$metadata":
                payload[key] = metadata
            else:
                payload[key] = value
        return payload

    def _score_response(self, response: TargetResponse) -> Dict[str, float]:
        if not response.ok:
            return {
                "answer_correctness": 0.0,
                "citation_accuracy": 0.0,
                "target_success": 0.0,
            }

        reference = _norm_text(self._get_reference(self.current_task))
        answer = _norm_text(self._answer)
        if not reference:
            correctness = 1.0 if answer else 0.0
        else:
            correctness = 1.0 if reference in answer or answer in reference else 0.0

        expected_citations = [
            _norm_text(item)
            for item in (self.current_task.metadata or {}).get("expected_citations", [])
            if _norm_text(item)
        ]
        actual_citations = [_norm_text(item) for item in self._citations if _norm_text(item)]
        if not expected_citations:
            citation_accuracy = 1.0
        else:
            matched = 0
            answer_blob = " ".join([answer, *actual_citations])
            for expected in expected_citations:
                if expected in answer_blob:
                    matched += 1
            citation_accuracy = matched / len(expected_citations)

        return {
            "answer_correctness": correctness,
            "citation_accuracy": citation_accuracy,
            "target_success": 1.0,
        }

    def _get_question(self, task: TaskInstance) -> str:
        return str((task.metadata or {}).get("question") or task.prompt or "")

    def _get_reference(self, task: Optional[TaskInstance]) -> Any:
        if task is None:
            return None
        return (task.metadata or {}).get("reference_answer", task.ground_truth)

    def _extract_action_text(self, action: Any) -> str:
        if hasattr(action, "content"):
            return str(action.content)
        if isinstance(action, str):
            return action
        if isinstance(action, dict):
            return str(action.get("content") or action.get("question") or "")
        return str(action)

    def _extract_answer(self, content: Any) -> str:
        answer_fields = self.config.extra_params.get(
            "answer_fields",
            ["answer", "response", "content", "message", "text"],
        )
        if isinstance(content, dict):
            for field in answer_fields:
                value = content.get(field)
                if isinstance(value, str):
                    return value
                if isinstance(value, dict):
                    nested = self._extract_answer(value)
                    if nested:
                        return nested
            return json.dumps(content, ensure_ascii=False)
        return "" if content is None else str(content)

    def _extract_citations(self, content: Any) -> List[str]:
        citation_fields = self.config.extra_params.get(
            "citation_fields",
            ["citations", "sources", "source_documents", "references"],
        )
        values: List[str] = []
        if isinstance(content, dict):
            for field in citation_fields:
                raw = content.get(field)
                values.extend(self._coerce_citation_values(raw))
        return values

    def _coerce_citation_values(self, raw: Any) -> List[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, dict):
            for key in ("file", "filename", "source", "title", "path", "id"):
                if raw.get(key):
                    return [str(raw[key])]
            return [json.dumps(raw, ensure_ascii=False)]
        if isinstance(raw, list):
            out: List[str] = []
            for item in raw:
                out.extend(self._coerce_citation_values(item))
            return out
        return [str(raw)]
