"""
WorkspaceEnvironment — AlphaEval-style self-contained task environment.

Each task is a directory:

    task_id/
    ├── task.yaml
    ├── query.md
    ├── files/
    └── .eval/
        └── rubric.py

The environment creates an isolated workspace, copies visible files into
deliverables, writes the agent answer to results/ans.md, then runs the
task-local evaluator defined by task.yaml.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BaseEnvironment, EnvConfig, EnvStepResult, TaskInstance


class WorkspaceEnvironment(BaseEnvironment):
    """Task-directory environment inspired by AlphaEval."""

    def __init__(self, config: EnvConfig):
        super().__init__(config)
        self._workspace_dir: Optional[Path] = None
        self._answer: str = ""
        self._score: float = 0.0
        self._passed: bool = False
        self._eval_details: Dict[str, Any] = {}

    async def reset(self, task: TaskInstance) -> str:
        self.current_task = task
        self.step_count = 0
        self._done = False
        self._answer = ""
        self._score = 0.0
        self._passed = False
        self._eval_details = {}

        self._workspace_dir = self._prepare_workspace(task)
        return task.prompt

    async def step(self, action: Any) -> EnvStepResult:
        self.step_count += 1
        if self.current_task is None or self._workspace_dir is None:
            raise RuntimeError("WorkspaceEnvironment.step() called before reset()")

        self._answer = self._extract_action_text(action)
        results_dir = self._workspace_dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "ans.md").write_text(self._answer, encoding="utf-8")

        self._eval_details = self._evaluate(self.current_task, self._workspace_dir)
        self._score = float(self._eval_details.get("score", 0.0))
        self._passed = bool(self._eval_details.get("passed", self._score >= 1.0))
        self._mark_done(terminated=True)

        return EnvStepResult(
            observation=f"评测完成。得分: {self._score:.2%}",
            reward=self._score,
            terminated=True,
            truncated=False,
            info=self._build_info(),
        )

    def get_reward(self) -> float:
        return self._score

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update(self._build_info())
        return info

    def _prepare_workspace(self, task: TaskInstance) -> Path:
        task_dir = Path(task.metadata.get("task_dir", "")).expanduser()
        if not task_dir.exists():
            raise FileNotFoundError(f"Task directory not found: {task_dir}")

        root = Path(self.config.extra_params.get("workspace_root", "outputs/workspaces"))
        if not root.is_absolute():
            root = Path.cwd() / root
        workspace = root / self.config.name / task.task_id

        if self.config.extra_params.get("clean_workspace", True) and workspace.exists():
            shutil.rmtree(workspace)

        for subdir in ("query", "deliverables", "results", "logs"):
            (workspace / subdir).mkdir(parents=True, exist_ok=True)

        query_path = task_dir / "query.md"
        if query_path.exists():
            shutil.copy2(query_path, workspace / "query" / "task.md")

        files_dir = task_dir / "files"
        if files_dir.exists():
            self._copy_visible_files(files_dir, workspace / "deliverables")

        return workspace

    def _copy_visible_files(self, src: Path, dst: Path) -> None:
        dst.mkdir(parents=True, exist_ok=True)
        for item in src.iterdir():
            target = dst / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)

    def _evaluate(self, task: TaskInstance, workspace: Path) -> Dict[str, Any]:
        task_config = dict(task.metadata.get("task_config", {}) or {})
        evaluation = dict(task.metadata.get("evaluation", {}) or task_config.get("evaluation", {}) or {})
        eval_type = evaluation.get("type", "exact_match")

        if eval_type == "exact_match":
            return self._evaluate_exact_match(evaluation)
        if eval_type == "code_exec":
            return self._evaluate_code_exec(task, workspace, evaluation)

        return {
            "type": eval_type,
            "score": 0.0,
            "passed": False,
            "reasoning": f"Unsupported evaluation type: {eval_type}",
        }

    def _evaluate_exact_match(self, evaluation: Dict[str, Any]) -> Dict[str, Any]:
        expected = str(evaluation.get("expected_answer", ""))
        actual = self._answer
        clean = bool(evaluation.get("ignore_whitespace", True))
        expected_cmp = re.sub(r"\s+", "", expected) if clean else expected
        actual_cmp = re.sub(r"\s+", "", actual) if clean else actual
        passed = expected_cmp == actual_cmp
        return {
            "type": "exact_match",
            "score": 1.0 if passed else 0.0,
            "passed": passed,
            "expected": expected,
            "actual": actual,
            "reasoning": "Exact match" if passed else "Answer does not match expected value",
        }

    def _evaluate_code_exec(
        self,
        task: TaskInstance,
        workspace: Path,
        evaluation: Dict[str, Any],
    ) -> Dict[str, Any]:
        task_dir = Path(task.metadata.get("task_dir", "")).expanduser()
        rubric_script = evaluation.get("rubric_script", ".eval/rubric.py")
        rubric_src = task_dir / rubric_script
        if not rubric_src.exists():
            return {
                "type": "code_exec",
                "score": 0.0,
                "passed": False,
                "reasoning": f"Rubric script not found: {rubric_src}",
            }

        rubric_dir = workspace / "rubric"
        rubric_dir.mkdir(parents=True, exist_ok=True)
        eval_dir = rubric_src.parent
        if eval_dir.exists():
            self._copy_visible_files(eval_dir, rubric_dir)
        rubric_path = rubric_dir / rubric_src.name

        timeout = int(evaluation.get("timeout_seconds", self.config.extra_params.get("rubric_timeout_seconds", 120)))
        try:
            result = subprocess.run(
                [sys.executable, str(rubric_path), "--submission", str(workspace)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(workspace),
            )
        except subprocess.TimeoutExpired:
            return {
                "type": "code_exec",
                "score": 0.0,
                "passed": False,
                "reasoning": f"Rubric execution timed out after {timeout}s",
            }
        except Exception as exc:
            return {
                "type": "code_exec",
                "score": 0.0,
                "passed": False,
                "reasoning": f"Rubric execution error: {exc}",
            }

        output = (result.stdout or "") + (result.stderr or "")
        score = self._extract_score(output)
        threshold = float(evaluation.get("pass_threshold", 1.0))
        passed = score >= threshold
        return {
            "type": "code_exec",
            "score": score,
            "passed": passed,
            "reasoning": f"Score: {score:.2f}",
            "output": output.strip(),
            "exit_code": result.returncode,
            "rubric_script": str(rubric_src),
            "pass_threshold": threshold,
        }

    def _extract_score(self, output: str) -> float:
        match = re.search(r"score=(\d+(?:\.\d+)?)", output)
        if match:
            return max(0.0, min(1.0, float(match.group(1))))

        for line in output.splitlines():
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            try:
                parsed = json.loads(stripped)
                if "score" in parsed:
                    return max(0.0, min(1.0, float(parsed["score"])))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return 0.0

    def _build_info(self) -> Dict[str, Any]:
        return {
            "final_answer": self._answer,
            "prediction": self._answer,
            "reference": self.current_task.ground_truth if self.current_task else None,
            "workspace_dir": str(self._workspace_dir) if self._workspace_dir else "",
            "evaluation": dict(self._eval_details),
            "passed": self._passed,
            "format_ok": True,
        }

    def _extract_action_text(self, action: Any) -> str:
        if hasattr(action, "content"):
            return str(action.content)
        if isinstance(action, str):
            return action
        if isinstance(action, dict):
            return str(action.get("content") or action.get("answer") or "")
        return str(action)
