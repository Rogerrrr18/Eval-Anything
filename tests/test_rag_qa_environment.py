"""
RAGQAEnvironment tests.

These tests verify the new Target-backed path without making network calls.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import ConfigLoader
from src.core.orchestrator import Orchestrator
from src.environment.base import EnvConfig, TaskInstance
from src.environment.rag_qa import RAGQAEnvironment
from src.harness.base import Action


def test_rag_qa_environment_with_mock_target():
    task = TaskInstance(
        task_id="rag_001",
        task_type="rag_qa",
        prompt="Q4 营收同比增长多少？",
        ground_truth="同比增长 23%",
        metadata={
            "files": ["q4_strategy.pdf"],
            "reference_answer": "同比增长 23%",
            "expected_citations": ["q4_strategy.pdf"],
        },
    )
    env = RAGQAEnvironment(
        EnvConfig(
            name="rag_test",
            target="mock_rag",
            target_config={
                "name": "mock_rag",
                "class_name": "MockTarget",
                "endpoints": {"chat": "mock://chat"},
                "extra_params": {
                    "responses": [
                        {
                            "answer": "Q4 营收同比增长 23%，依据 q4_strategy.pdf。",
                            "citations": ["q4_strategy.pdf"],
                        }
                    ]
                },
            },
            extra_params={
                "metrics": ["answer_correctness", "citation_accuracy", "target_success"],
            },
        )
    )

    async def _run():
        observation = await env.reset(task)
        assert observation == task.prompt
        result = await env.step(Action(action_type="direct_input", content=observation))
        assert result.terminated is True
        assert result.reward == 1.0
        assert result.info["final_answer"].startswith("Q4 营收同比增长 23%")
        assert result.info["citations"] == ["q4_strategy.pdf"]
        await env.close()

    asyncio.run(_run())


def test_orchestrator_rag_qa_mock_config_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config_dir = root / "configs"
        data_dir = root / "datasets"
        (config_dir / "experiments").mkdir(parents=True)
        data_dir.mkdir()

        task = {
            "task_id": "rag_orch_001",
            "task_type": "rag_qa",
            "question": "Q4 营收同比增长多少？",
            "files": ["q4_strategy.pdf"],
            "reference_answer": "同比增长 23%",
            "expected_citations": ["q4_strategy.pdf"],
        }
        (data_dir / "rag.jsonl").write_text(json.dumps(task, ensure_ascii=False) + "\n", encoding="utf-8")

        (config_dir / "llm_profiles.yaml").write_text(
            """
llm_profiles:
  mock_passthrough:
    class: "MockLLM"
    model_name: "mock"
    endpoint_url: ""
""",
            encoding="utf-8",
        )
        (config_dir / "harness_profiles.yaml").write_text(
            """
harness_profiles:
  direct:
    class: "DirectHarness"
    max_steps: 1
""",
            encoding="utf-8",
        )
        (config_dir / "targets.yaml").write_text(
            """
targets:
  mock_rag:
    class: "MockTarget"
    endpoints:
      chat: "mock://chat"
    extra_params:
      responses:
        - answer: "Q4 营收同比增长 23%，依据 q4_strategy.pdf。"
          citations: ["q4_strategy.pdf"]
""",
            encoding="utf-8",
        )
        (config_dir / "environments.yaml").write_text(
            """
environments:
  rag:
    class: "RAGQAEnvironment"
    dataset: "datasets/rag.jsonl"
    target: "mock_rag"
    max_steps: 1
    extra_params:
      metrics: [answer_correctness, citation_accuracy, target_success]
""",
            encoding="utf-8",
        )
        (config_dir / "experiments" / "rag.yaml").write_text(
            """
experiment:
  name: "rag_eval"
  llm_profiles: [mock_passthrough]
  harness_profiles: [direct]
  environments: [rag]
  execution:
    max_concurrent_tasks: 1
    max_concurrent_combos: 1
    task_timeout_seconds: 30
    step_timeout_seconds: 30
    retry_on_api_error: 1
    retry_backoff_base: 1
""",
            encoding="utf-8",
        )

        loader = ConfigLoader(str(config_dir))
        result = asyncio.run(Orchestrator(loader).run_experiment(loader.load_experiment("rag.yaml")))

    combo = result.combo_results[0]
    traj = combo.task_results[0]
    assert combo.summary["success_rate"] == 1.0
    assert traj.final_answer.startswith("Q4 营收同比增长 23%")
    assert traj.scores["answer_correctness"] == 1.0
    assert traj.metadata["env_info"]["citations"] == ["q4_strategy.pdf"]


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
