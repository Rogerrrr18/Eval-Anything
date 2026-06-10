"""
AlphaEval-style workspace task tests.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import ConfigLoader
from src.core.orchestrator import Orchestrator


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")


def test_workspace_environment_exact_match_orchestrator():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config_dir = root / "configs"
        task_dir = root / "tasks" / "suite" / "exact_001"
        (config_dir / "experiments").mkdir(parents=True)

        _write(task_dir / "task.yaml", """
        name: "Exact task"
        evaluation:
          type: exact_match
          expected_answer: "42"
        """)
        _write(task_dir / "query.md", "What is 6 * 7? Answer only the number.")

        _write(config_dir / "llm_profiles.yaml", """
        llm_profiles:
          mock:
            class: "MockLLM"
            model_name: "mock"
            endpoint_url: ""
            extra_params:
              responses:
                - "42"
        """)
        _write(config_dir / "harness_profiles.yaml", """
        harness_profiles:
          raw:
            class: "RawHarness"
            max_steps: 1
        """)
        _write(config_dir / "environments.yaml", f"""
        environments:
          workspace:
            class: "WorkspaceEnvironment"
            dataset: "{(root / 'tasks' / 'suite').as_posix()}"
            max_steps: 1
            extra_params:
              workspace_root: "{(root / 'workspaces').as_posix()}"
        """)
        _write(config_dir / "experiments" / "workspace.yaml", """
        experiment:
          name: "workspace_eval"
          llm_profiles: [mock]
          harness_profiles: [raw]
          environments: [workspace]
          execution:
            max_concurrent_tasks: 1
            max_concurrent_combos: 1
        """)

        loader = ConfigLoader(str(config_dir))
        result = asyncio.run(Orchestrator(loader).run_experiment(loader.load_experiment("workspace.yaml")))

    traj = result.combo_results[0].task_results[0]
    assert traj.status == "success"
    assert traj.final_answer == "42"
    assert traj.scores["evaluation_score"] == 1.0
    assert traj.metadata["env_info"]["evaluation"]["type"] == "exact_match"


def test_workspace_environment_code_exec_orchestrator():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config_dir = root / "configs"
        task_dir = root / "tasks" / "suite" / "code_001"
        (config_dir / "experiments").mkdir(parents=True)

        _write(task_dir / "task.yaml", """
        name: "Code exec task"
        evaluation:
          type: code_exec
          rubric_script: .eval/rubric.py
          pass_threshold: 0.6
        """)
        _write(task_dir / "query.md", "Return a sentence containing the expected keyword.")
        _write(task_dir / ".eval" / "rubric.py", """
        import argparse
        from pathlib import Path

        parser = argparse.ArgumentParser()
        parser.add_argument("--submission", required=True)
        args = parser.parse_args()

        ans = Path(args.submission, "results", "ans.md").read_text(encoding="utf-8")
        score = 0.75 if "expected keyword" in ans.lower() else 0.0
        print(f"score={score:.2f}")
        print("result=PASSED" if score >= 0.6 else "result=FAILED")
        """)

        _write(config_dir / "llm_profiles.yaml", """
        llm_profiles:
          mock:
            class: "MockLLM"
            model_name: "mock"
            endpoint_url: ""
            extra_params:
              responses:
                - "This answer contains the expected keyword."
        """)
        _write(config_dir / "harness_profiles.yaml", """
        harness_profiles:
          raw:
            class: "RawHarness"
            max_steps: 1
        """)
        _write(config_dir / "environments.yaml", f"""
        environments:
          workspace:
            class: "WorkspaceEnvironment"
            dataset: "{(root / 'tasks' / 'suite').as_posix()}"
            max_steps: 1
            extra_params:
              workspace_root: "{(root / 'workspaces').as_posix()}"
        """)
        _write(config_dir / "experiments" / "workspace.yaml", """
        experiment:
          name: "workspace_eval"
          llm_profiles: [mock]
          harness_profiles: [raw]
          environments: [workspace]
          execution:
            max_concurrent_tasks: 1
            max_concurrent_combos: 1
        """)

        loader = ConfigLoader(str(config_dir))
        result = asyncio.run(Orchestrator(loader).run_experiment(loader.load_experiment("workspace.yaml")))

    traj = result.combo_results[0].task_results[0]
    assert traj.status == "success"
    assert traj.scores["evaluation_score"] == 0.75
    assert traj.metadata["env_info"]["evaluation"]["passed"] is True
    assert "workspace_dir" in traj.metadata["env_info"]


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {test.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
