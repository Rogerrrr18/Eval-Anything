"""
断点续跑（--resume）+ 轨迹流式落盘测试。
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
from src.core.orchestrator import Orchestrator, _trajectory_from_dict
from src.core.trajectory import Trajectory
from src.harness.base import Action, StepRecord


# ── _trajectory_from_dict 往返 ───────────────────────────────────────────────

def test_trajectory_dict_roundtrip():
    traj = Trajectory(
        experiment_name="exp",
        task_id="t1",
        llm_name="m",
        harness_name="raw",
        env_name="dialog",
        steps=[StepRecord(
            step_number=1,
            observation="obs",
            thought="think",
            action=Action(action_type="text_response", content="hi"),
            action_result="ok",
            latency_ms=12.5,
            input_tokens=10,
            output_tokens=5,
        )],
        final_answer="hi",
        ground_truth={"k": "v"},
        scores={"partial_completion": 1.0},
        total_input_tokens=10,
        total_output_tokens=5,
        total_latency_ms=12.5,
        status="success",
        metadata={"format_ok": True},
    )
    restored = _trajectory_from_dict(json.loads(traj.to_jsonl()))
    assert restored.task_id == "t1"
    assert restored.status == "success"
    assert restored.final_answer == "hi"
    assert restored.scores == {"partial_completion": 1.0}
    assert len(restored.steps) == 1
    assert restored.steps[0].action.content == "hi"
    assert restored.steps[0].thought == "think"
    assert restored.metadata == {"format_ok": True}


# ── 完整 resume 链路 ─────────────────────────────────────────────────────────

_EXPECTED = {"product_name": "空调", "city": "广州市"}
_SLOT_KEYS = list(_EXPECTED.keys())


def _build_config_dir(root: Path) -> Path:
    config_dir = root / "configs"
    (config_dir / "experiments").mkdir(parents=True)
    data_dir = root / "datasets"
    data_dir.mkdir()

    tasks = [
        {"task_id": f"task_{i}", "task_type": "slot_filling",
         "prompt": f"prompt {i}", "ground_truth": _EXPECTED,
         "expected_slots": _EXPECTED, "slot_keys": _SLOT_KEYS}
        for i in (1, 2)
    ]
    with open(data_dir / "tasks.jsonl", "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    # MockLLM 的 responses 是弹出队列（不循环），两个任务给两份相同响应
    response = json.dumps(_EXPECTED, ensure_ascii=False).replace('"', '\\"')
    (config_dir / "llm_profiles.yaml").write_text(f"""
llm_profiles:
  mock:
    class: "MockLLM"
    model_name: "mock"
    endpoint_url: ""
    extra_params:
      responses:
        - "{response}"
        - "{response}"
""", encoding="utf-8")
    (config_dir / "harness_profiles.yaml").write_text("""
harness_profiles:
  raw:
    class: "RawHarness"
    max_steps: 1
""", encoding="utf-8")
    (config_dir / "environments.yaml").write_text("""
environments:
  test_dialog:
    class: "DialogEnvironment"
    dataset: "datasets/tasks.jsonl"
    max_steps: 1
""", encoding="utf-8")
    (config_dir / "experiments" / "mock.yaml").write_text(f"""
experiment:
  name: "resume_eval"
  output_dir: "{(root / 'outputs').as_posix()}"
  llm_profiles: [mock]
  harness_profiles: [raw]
  environments: [test_dialog]
""", encoding="utf-8")
    return config_dir


def _seed_stream(root: Path, task_id: str, status: str, marker: str) -> Path:
    """预埋一条 stream 记录，模拟上次中断前已完成的任务。"""
    stream_path = root / "outputs" / "trajectories" / "stream" / "mock__raw__test_dialog.jsonl"
    stream_path.parent.mkdir(parents=True, exist_ok=True)
    traj = Trajectory(
        experiment_name="resume_eval", task_id=task_id,
        llm_name="mock", harness_name="raw", env_name="test_dialog",
        steps=[], final_answer=marker, ground_truth=_EXPECTED,
        scores={"partial_completion": 1.0}, total_input_tokens=1,
        total_output_tokens=1, total_latency_ms=1.0, status=status,
    )
    with open(stream_path, "a", encoding="utf-8") as f:
        f.write(traj.to_jsonl() + "\n")
    return stream_path


def test_resume_skips_completed_tasks():
    """task_1 已在 stream 里 success → resume 只跑 task_2，且保留 task_1 旧结果。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config_dir = _build_config_dir(root)
        _seed_stream(root, "task_1", "success", "RESUMED_MARKER")

        loader = ConfigLoader(str(config_dir))
        exp_config = loader.load_experiment("mock.yaml")
        exp_config.resume = True
        result = asyncio.run(Orchestrator(loader).run_experiment(exp_config))

        combo = result.combo_results[0]
        by_id = {t.task_id: t for t in combo.task_results}
        assert set(by_id) == {"task_1", "task_2"}
        # task_1 没有重跑：final_answer 还是预埋的 marker
        assert by_id["task_1"].final_answer == "RESUMED_MARKER"
        # task_2 是新跑的：mock 输出 expected JSON
        assert by_id["task_2"].final_answer != "RESUMED_MARKER"
        assert by_id["task_2"].status == "success"


def test_resume_retries_error_status():
    """stream 里 status=error 的任务视为基础设施故障，resume 时重跑。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config_dir = _build_config_dir(root)
        _seed_stream(root, "task_1", "error", "STALE_ERROR")

        loader = ConfigLoader(str(config_dir))
        exp_config = loader.load_experiment("mock.yaml")
        exp_config.resume = True
        result = asyncio.run(Orchestrator(loader).run_experiment(exp_config))

        combo = result.combo_results[0]
        by_id = {t.task_id: t for t in combo.task_results}
        # error 状态被重跑，旧 marker 被覆盖
        assert by_id["task_1"].final_answer != "STALE_ERROR"
        assert by_id["task_1"].status == "success"


def test_fresh_run_clears_old_stream():
    """非 resume 运行会清掉旧 stream 文件，避免新旧混淆。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config_dir = _build_config_dir(root)
        stream_path = _seed_stream(root, "task_1", "success", "OLD_RUN")

        loader = ConfigLoader(str(config_dir))
        exp_config = loader.load_experiment("mock.yaml")  # resume 默认 False
        result = asyncio.run(Orchestrator(loader).run_experiment(exp_config))

        combo = result.combo_results[0]
        assert len(combo.task_results) == 2
        # 全部重跑，旧 marker 不存在
        assert all(t.final_answer != "OLD_RUN" for t in combo.task_results)
        # stream 重写为本次的 2 条
        lines = [l for l in stream_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2


def test_streaming_writes_during_run():
    """每条任务完成即落盘——正常跑完后 stream 文件有 N 行。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config_dir = _build_config_dir(root)

        loader = ConfigLoader(str(config_dir))
        exp_config = loader.load_experiment("mock.yaml")
        asyncio.run(Orchestrator(loader).run_experiment(exp_config))

        stream_path = root / "outputs" / "trajectories" / "stream" / "mock__raw__test_dialog.jsonl"
        assert stream_path.exists()
        lines = [l for l in stream_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert data["status"] == "success"


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
