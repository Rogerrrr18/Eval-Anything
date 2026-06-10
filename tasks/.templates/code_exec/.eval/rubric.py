#!/usr/bin/env python3
"""Example task-local rubric.

Rubrics receive --submission pointing at the task workspace. The agent answer is
available at <workspace>/results/ans.md, and visible task files are under
<workspace>/deliverables/.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True)
    args = parser.parse_args()

    workspace = Path(args.submission)
    answer_path = workspace / "results" / "ans.md"
    answer = answer_path.read_text(encoding="utf-8") if answer_path.exists() else ""

    score = 1.0 if "expected keyword" in answer.lower() else 0.0
    print(f"score={score:.2f}")
    print("result=PASSED" if score >= 0.6 else "result=FAILED")


if __name__ == "__main__":
    main()
