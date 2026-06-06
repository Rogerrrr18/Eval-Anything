"""
端到端验证测试 — 使用 MockLLM 验证管线完整性。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.base import LLMConfig
from src.llm.mock import MockLLM
from src.harness.raw import RawHarness
from src.harness.base import HarnessConfig
from src.environment.base import TaskInstance, EnvConfig
from src.environment.dialog import DialogEnvironment
from src.core.config import ConfigLoader
from src.core.orchestrator import Orchestrator
from src.core.trajectory import Trajectory, ComboResult
from src.metrics.quantitative import QuantitativeMetrics
from src.metrics.qualitative import QualitativeAnalyzer
from src.metrics.evaluators import (
    CompositeEvaluator,
    ExactMatchEvaluator,
    F1MatchEvaluator,
    FieldMatchEvaluator,
    LLMJudgeEvaluator,
)
from src.reporting.excel_writer import ExcelWriter
from src.reporting.html_dashboard import HTMLDashboard
from src.reporting.trajectory_logger import TrajectoryLogger
from src.reporting.case_study import CaseStudyWriter


def create_sample_tasks() -> list:
    """创建测试用 TaskInstance。"""
    return [
        TaskInstance(
            task_id="test_001",
            task_type="slot_filling",
            prompt="我家空调不制冷了，地址广东省广州市天河区天河路太阳新天地，电话13800138000",
            ground_truth={
                "product_name": "空调",
                "product_brand": "",
                "fault_info_desc": "不制冷",
                "product_num": "1",
                "province": "广东省",
                "city": "广州市",
                "county": "天河区",
                "subdistrict": "天河路",
                "community": "太阳新天地",
                "book_desc": "",
                "phone_number": "13800138000",
            },
            expected_slots={
                "product_name": "空调",
                "product_brand": "",
                "fault_info_desc": "不制冷",
                "product_num": "1",
                "province": "广东省",
                "city": "广州市",
                "county": "天河区",
                "subdistrict": "天河路",
                "community": "太阳新天地",
                "book_desc": "",
                "phone_number": "13800138000",
            },
            slot_keys=[
                "product_name", "product_brand", "fault_info_desc", "product_num",
                "province", "city", "county", "subdistrict", "community",
                "book_desc", "phone_number",
            ],
        ),
        TaskInstance(
            task_id="test_002",
            task_type="slot_filling",
            prompt="洗衣机报修，海尔牌，脱水噪音大",
            ground_truth={
                "product_name": "洗衣机",
                "product_brand": "海尔",
                "fault_info_desc": "脱水噪音大",
                "product_num": "1",
                "province": "",
                "city": "",
                "county": "",
                "subdistrict": "",
                "community": "",
                "book_desc": "",
                "phone_number": "",
            },
            expected_slots={
                "product_name": "洗衣机",
                "product_brand": "海尔",
                "fault_info_desc": "脱水噪音大",
                "product_num": "1",
                "province": "",
                "city": "",
                "county": "",
                "subdistrict": "",
                "community": "",
                "book_desc": "",
                "phone_number": "",
            },
            slot_keys=[
                "product_name", "product_brand", "fault_info_desc", "product_num",
                "province", "city", "county", "subdistrict", "community",
                "book_desc", "phone_number",
            ],
        ),
    ]


def test_llm_layer():
    """测试 LLM 层。"""
    print("测试 LLM 层...")
    config = LLMConfig(model_name="mock", endpoint_url="http://localhost:8000/v1")
    llm = MockLLM(config)

    llm.set_response("你好，我是助手")
    messages = [{"role": "user", "content": "hello"}]

    result = asyncio.run(llm.chat(messages))
    assert result.content == "你好，我是助手", f"期望 '你好，我是助手'，实际 '{result.content}'"
    assert len(llm.call_log) == 1

    msgs = llm.format_messages([], "test input", system_prompt="You are helpful")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["content"] == "test input"

    print("  ✅ LLM 层测试通过")


def test_environment_layer():
    """测试 Environment 层。"""
    print("测试 Environment 层...")
    config = EnvConfig(name="test_dialog")
    tasks = create_sample_tasks()

    # 正确 JSON
    correct_output = json.dumps({
        "product_info": {"product_name": "空调", "product_brand": "", "fault_info_desc": "不制冷", "product_num": "1"},
        "address_info": {"province": "广东省", "city": "广州市", "county": "天河区", "subdistrict": "天河路", "community": "太阳新天地"},
        "date_info": {"book_desc": ""},
        "number_info": {"phone_number": "13800138000"},
    }, ensure_ascii=False)

    async def _test_correct():
        from src.harness.base import Action
        env = DialogEnvironment(config)
        obs = await env.reset(tasks[0])
        assert "空调" in obs

        action = Action(action_type="text_response", content=correct_output)
        result = await env.step(action)

        assert result.terminated, "应该 terminated"
        assert result.reward == 1.0, f"全对应得到 1.0，实际 {result.reward}"
        assert env.get_all_correct(), "应该全部正确"

    asyncio.run(_test_correct())

    # 部分正确
    partial_output = json.dumps({
        "product_info": {"product_name": "洗衣机", "product_brand": "海尔", "fault_info_desc": "脱水噪音大", "product_num": "1"},
        "address_info": {"province": "错误省", "city": "", "county": "", "subdistrict": "", "community": ""},
        "date_info": {"book_desc": ""},
        "number_info": {"phone_number": ""},
    }, ensure_ascii=False)

    async def _test_partial():
        from src.harness.base import Action
        env = DialogEnvironment(config)
        obs = await env.reset(tasks[1])
        action = Action(action_type="text_response", content=partial_output)
        result = await env.step(action)
        assert result.reward < 1.0, f"部分正确应该 < 1.0，实际 {result.reward}"
        field_results = env.get_field_results()
        assert field_results["product_name"] == True, "product_name 应该正确"
        assert field_results["province"] == False, "province 应该错误"

    asyncio.run(_test_partial())

    # 格式错误
    async def _test_format():
        from src.harness.base import Action
        env = DialogEnvironment(config)
        await env.reset(tasks[0])
        action = Action(action_type="text_response", content="这不是JSON")
        result = await env.step(action)
        assert not env.get_format_ok(), "格式应该不合规"
        assert result.reward == 0.0, f"格式错误得分应为 0，实际 {result.reward}"

    asyncio.run(_test_format())

    print("  ✅ Environment 层测试通过")


def test_harness_layer():
    """测试 Harness 层。"""
    print("测试 Harness 层...")
    config = LLMConfig(model_name="mock", endpoint_url="")
    llm = MockLLM(config)

    correct_json = json.dumps({
        "product_info": {"product_name": "空调", "product_brand": "", "fault_info_desc": "不制冷", "product_num": "1"},
        "address_info": {"province": "广东省", "city": "广州市", "county": "天河区", "subdistrict": "天河路", "community": "太阳新天地"},
        "date_info": {"book_desc": ""},
        "number_info": {"phone_number": "13800138000"},
    }, ensure_ascii=False)
    llm.set_response(correct_json)

    harness_config = HarnessConfig(name="raw_test", max_steps=1)
    harness = RawHarness(llm, harness_config)
    tasks = create_sample_tasks()

    async def _test():
        action = await harness.initial_action(tasks[0].prompt)
        assert harness.is_finished(), "RawHarness 应该一步完成"
        assert json.loads(harness.get_final_answer()), "输出应该是有效 JSON"
        assert len(harness.get_trajectory()) == 1, "应该有 1 步记录"

    asyncio.run(_test())
    print("  ✅ Harness 层测试通过")


def test_evaluators():
    """测试通用 evaluator。"""
    print("测试通用评测器...")

    exact = ExactMatchEvaluator()
    assert exact.evaluate(" Hello ", "hello").score == 1.0

    f1 = F1MatchEvaluator()
    f1_result = f1.evaluate("空调不制冷", "空调制冷")
    assert 0.0 < f1_result.score < 1.0

    field = FieldMatchEvaluator(field_keys=["product_name", "city"])
    field_result = field.evaluate(
        {"product_name": "空调", "city": "广州市"},
        {"product_name": "空调", "city": "深圳市"},
    )
    assert field_result.score == 0.5
    assert field_result.details["field_results"]["product_name"] is True
    assert field_result.details["field_results"]["city"] is False

    composite = CompositeEvaluator([(exact, 0.4), (field, 0.6)])
    composite_result = composite.evaluate(
        {"product_name": "空调", "city": "广州市"},
        {"product_name": "空调", "city": "深圳市"},
    )
    assert 0.0 <= composite_result.score <= 1.0

    async def _test_llm_judge():
        judge_llm = MockLLM(LLMConfig(model_name="mock_judge", endpoint_url=""))
        judge_llm.set_json_response({
            "score": 0.82,
            "passed": True,
            "labels": ["correct"],
            "comment": "答案基本满足要求。",
            "evidence": ["字段 product_name 正确"],
            "dimensions": {"correctness": 0.82},
        })
        judge = LLMJudgeEvaluator(
            llm=judge_llm,
            rubric="判断 prediction 是否满足 reference。",
            allowed_labels=["correct", "missing_requirement"],
        )
        judge_result = await judge.evaluate_async(
            prediction={"product_name": "空调"},
            reference={"product_name": "空调"},
            task="槽位抽取",
        )
        assert judge_result.score == 0.82
        assert judge_result.passed is True
        assert judge_result.labels == ["correct"]
        assert judge_result.evidence == ["字段 product_name 正确"]

    asyncio.run(_test_llm_judge())

    print("  ✅ 通用评测器测试通过")


def test_judge_profile_loading():
    """测试 LLM Judge 配置加载。"""
    print("测试 Judge 配置加载...")

    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "configs"
        config_dir.mkdir()
        (config_dir / "llm_profiles.yaml").write_text("llm_profiles: {}\n", encoding="utf-8")
        (config_dir / "harness_profiles.yaml").write_text("harness_profiles: {}\n", encoding="utf-8")
        (config_dir / "environments.yaml").write_text("environments: {}\n", encoding="utf-8")
        (config_dir / "judge_profiles.yaml").write_text(
            """
judge_profiles:
  mock_judge:
    class: "MockLLM"
    model_name: "mock"
    endpoint_url: ""
    threshold: 0.7
    allowed_labels: [correct, missing_requirement]
    rubric: "检查输出是否满足要求。"
    extra_params:
      responses:
        - '{"score": 0.75, "passed": true, "labels": ["correct"], "comment": "ok", "evidence": ["matched"]}'
""",
            encoding="utf-8",
        )

        loader = ConfigLoader(str(config_dir))
        profile = loader.get_judge_profile("mock_judge")
        assert profile.threshold == 0.7
        assert profile.allowed_labels == ["correct", "missing_requirement"]

        judge = LLMJudgeEvaluator.from_profile(profile)
        result = asyncio.run(judge.evaluate_async("answer", "answer"))
        assert result.score == 0.75
        assert result.labels == ["correct"]

    print("  ✅ Judge 配置加载测试通过")


def test_orchestrator_with_mock_config():
    """测试配置驱动的 Orchestrator 完整链路。"""
    print("测试 Orchestrator 配置链路...")

    expected = {
        "product_name": "空调",
        "product_brand": "",
        "fault_info_desc": "不制冷",
        "product_num": "1",
        "province": "广东省",
        "city": "广州市",
        "county": "天河区",
        "subdistrict": "天河路",
        "community": "太阳新天地",
        "book_desc": "",
        "phone_number": "13800138000",
    }
    slot_keys = list(expected.keys())

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config_dir = root / "configs"
        data_dir = root / "datasets"
        (config_dir / "experiments").mkdir(parents=True)
        data_dir.mkdir()

        task = {
            "task_id": "orchestrator_001",
            "task_type": "slot_filling",
            "prompt": "空调不制冷，广东省广州市天河区天河路太阳新天地，电话13800138000",
            "ground_truth": expected,
            "expected_slots": expected,
            "slot_keys": slot_keys,
        }
        with open(data_dir / "tasks.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")

        response = json.dumps(expected, ensure_ascii=False).replace('"', '\\"')
        (config_dir / "llm_profiles.yaml").write_text(
            f"""
llm_profiles:
  mock:
    class: "MockLLM"
    model_name: "mock"
    endpoint_url: ""
    extra_params:
      responses:
        - "{response}"
""",
            encoding="utf-8",
        )
        (config_dir / "harness_profiles.yaml").write_text(
            """
harness_profiles:
  raw:
    class: "RawHarness"
    max_steps: 1
    max_retries: 2
""",
            encoding="utf-8",
        )
        (config_dir / "environments.yaml").write_text(
            """
environments:
  test_dialog:
    class: "DialogEnvironment"
    dataset: "datasets/tasks.jsonl"
    max_steps: 1
""",
            encoding="utf-8",
        )
        (config_dir / "experiments" / "mock.yaml").write_text(
            """
experiment:
  name: "mock_eval"
  llm_profiles: [mock]
  harness_profiles: [raw]
  environments: [test_dialog]
  execution:
    max_concurrent_tasks: 2
    max_concurrent_combos: 1
    task_timeout_seconds: 30
    step_timeout_seconds: 30
    retry_on_api_error: 2
    retry_backoff_base: 1
""",
            encoding="utf-8",
        )

        loader = ConfigLoader(str(config_dir))
        exp_config = loader.load_experiment("mock.yaml")
        result = asyncio.run(Orchestrator(loader).run_experiment(exp_config))

    combo = result.combo_results[0]
    assert combo.summary["success_rate"] == 1.0
    assert combo.summary["format_compliance_rate"] == 1.0
    assert combo.task_results[0].metadata["field_results"]["product_name"] is True
    print("  ✅ Orchestrator 配置链路测试通过")


def test_full_pipeline():
    """端到端测试：MockLLM → RawHarness → DialogEnvironment → 报告生成。"""
    print("测试完整管线...")

    tasks = create_sample_tasks()
    llm_config = LLMConfig(model_name="mock_llm", endpoint_url="")
    harness_config = HarnessConfig(name="raw", max_steps=1)
    env_config = EnvConfig(name="test_dialog")

    responses = [
        json.dumps({
            "product_info": {"product_name": "空调", "product_brand": "", "fault_info_desc": "不制冷", "product_num": "1"},
            "address_info": {"province": "广东省", "city": "广州市", "county": "天河区", "subdistrict": "天河路", "community": "太阳新天地"},
            "date_info": {"book_desc": ""},
            "number_info": {"phone_number": "13800138000"},
        }, ensure_ascii=False),
        json.dumps({
            "product_info": {"product_name": "洗衣机", "product_brand": "海尔", "fault_info_desc": "脱水噪音大", "product_num": "1"},
            "address_info": {"province": "错误省", "city": "", "county": "", "subdistrict": "", "community": ""},
            "date_info": {"book_desc": ""},
            "number_info": {"phone_number": ""},
        }, ensure_ascii=False),
    ]

    trajectories = []

    async def _run():
        for i, task in enumerate(tasks):
            llm = MockLLM(llm_config)
            llm.set_response(responses[i])

            harness = RawHarness(llm, harness_config)
            env = DialogEnvironment(env_config)

            obs = await env.reset(task)
            action = await harness.initial_action(task.prompt)

            if not env.is_done():
                await env.step(action)

            reward = env.get_reward()
            field_results = env.get_field_results()
            format_ok = env.get_format_ok()
            status = "success" if reward >= 1.0 else ("partial" if reward > 0 else "failure")

            scores = {"partial_completion": reward, "format_compliance": 1.0 if format_ok else 0.0, "task_completion": 1.0 if status == "success" else 0.0}
            for k, v in field_results.items():
                scores[f"field_{k}"] = 1.0 if v else 0.0

            traj = Trajectory(
                experiment_name="test",
                task_id=task.task_id,
                llm_name="mock_llm",
                harness_name="raw",
                env_name="test_dialog",
                steps=harness.get_trajectory(),
                final_answer=harness.get_final_answer(),
                ground_truth=task.ground_truth,
                scores=scores,
                total_input_tokens=harness._total_input_tokens,
                total_output_tokens=harness._total_output_tokens,
                total_latency_ms=harness.get_total_latency(),
                status=status,
                metadata={"field_results": field_results, "format_ok": format_ok},
            )
            trajectories.append(traj)
            print(f"    任务 {task.task_id}: {status} (reward={reward:.1%})")

    asyncio.run(_run())

    assert len(trajectories) == 2
    assert trajectories[0].status == "success", f"第一个应该成功，实际 {trajectories[0].status}"
    assert trajectories[1].status == "partial", f"第二个应该部分成功，实际 {trajectories[1].status}"

    print("  计算指标...")
    metrics = QuantitativeMetrics()
    results = metrics.compute_all(trajectories)
    assert results["task_completion_rate"].value == 0.5, f"完成率应为 0.5，实际 {results['task_completion_rate'].value}"
    print(f"    任务完成率: {results['task_completion_rate'].value:.1%}")
    print(f"    字段平均准确率: {results['partial_completion_score'].value:.1%}")
    print(f"    格式合规率: {results['format_compliance_rate'].value:.1%}")

    with tempfile.TemporaryDirectory() as tmpdir:
        print("  生成报告...")
        combo = ComboResult(
            llm_name="mock_llm",
            harness_name="raw",
            env_name="test_dialog",
            task_results=trajectories,
        )
        combo.compute_summary()
        assert combo.summary["format_compliance_rate"] == 1.0

        from src.core.trajectory import ExperimentResult
        exp_result = ExperimentResult(
            experiment_name="test",
            combo_results=[combo],
        )

        writer = ExcelWriter(tmpdir)
        path = writer.write(exp_result)
        assert os.path.exists(path), "Excel 文件应该存在"

        dashboard = HTMLDashboard(tmpdir)
        path = dashboard.write(exp_result)
        assert os.path.exists(path), "HTML 文件应该存在"

        logger = TrajectoryLogger(tmpdir)
        path = logger.write_all(trajectories, "test")
        assert os.path.exists(path), "JSONL 文件应该存在"

        case_writer = CaseStudyWriter(tmpdir)
        path = case_writer.write(trajectories, "test")
        assert os.path.exists(path), "Case study 文件应该存在"

    print("  ✅ 完整管线测试通过")


if __name__ == "__main__":
    print("=" * 50)
    print("Agent Eval Pipeline — 端到端验证测试")
    print("=" * 50 + "\n")

    try:
        test_llm_layer()
        test_environment_layer()
        test_harness_layer()
        test_evaluators()
        test_judge_profile_loading()
        test_orchestrator_with_mock_config()
        test_full_pipeline()
        print("\n" + "=" * 50)
        print("✅ 所有测试通过！管线可以正常工作。")
        print("=" * 50)
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 运行错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
