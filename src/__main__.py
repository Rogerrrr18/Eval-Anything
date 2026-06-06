"""
Agent Eval Pipeline — CLI 入口。

用法:
    # 运行预设实验
    python -m src --experiment slot_filling --config-dir configs/

    # 指定单个 LLM + Harness + 环境
    python -m src --llm deepseek_v4_flash --harness raw --env slot_filling_xiu

    # 列出可用配置
    python -m src --list-profiles

    # 生成示例数据集
    python -m src --generate-sample-data
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import os
from pathlib import Path

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import ConfigLoader, ExperimentConfig
from src.core.orchestrator import Orchestrator
from src.core.trajectory import ExperimentResult
from src.reporting.excel_writer import ExcelWriter
from src.reporting.html_dashboard import HTMLDashboard
from src.reporting.trajectory_logger import TrajectoryLogger
from src.reporting.case_study import CaseStudyWriter
from src.utils.json_utils import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Agent Eval Pipeline — 模块化 Agent 评测管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 运行预设实验
  python -m src --experiment slot_filling

  # 指定组件组合
  python -m src --llm deepseek_v4_flash --harness raw --env slot_filling_xiu

  # 列出可用配置
  python -m src --list-profiles

  # 生成示例数据
  python -m src --generate-sample-data
        """,
    )

    # 实验配置
    parser.add_argument(
        "--experiment", "-e",
        type=str,
        help="实验配置文件名（在 configs/experiments/ 目录下，不含 .yaml 后缀）",
    )
    parser.add_argument(
        "--config-dir", "-c",
        type=str,
        default="configs",
        help="配置文件根目录（默认: configs/）",
    )

    # 直接指定组件
    parser.add_argument("--llm", type=str, help="LLM profile 名称")
    parser.add_argument("--harness", type=str, help="Harness profile 名称")
    parser.add_argument("--env", type=str, help="Environment profile 名称")

    # 输出控制
    parser.add_argument("--output-dir", "-o", type=str, help="输出目录（覆盖配置）")
    parser.add_argument("--log-level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    # 功能开关
    parser.add_argument("--list-profiles", action="store_true", help="列出所有可用配置")
    parser.add_argument("--generate-sample-data", action="store_true", help="生成示例测试数据")
    parser.add_argument("--no-excel", action="store_true", help="跳过 Excel 报告")
    parser.add_argument("--no-html", action="store_true", help="跳过 HTML 仪表盘")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要运行的组合，不实际执行")

    return parser.parse_args()


def list_profiles(config_loader: ConfigLoader) -> None:
    """列出所有可用配置。"""
    print("\n=== 可用 LLM Profiles ===")
    for name, profile in config_loader.load_llm_profiles().items():
        print(f"  {name}: {profile.model_name} @ {profile.endpoint_url}")

    judges = config_loader.load_judge_profiles()
    if judges:
        print("\n=== 可用 Judge Profiles ===")
        for name, profile in judges.items():
            print(f"  {name}: {profile.model_name} @ {profile.endpoint_url} (threshold={profile.threshold})")

    print("\n=== 可用 Harness Profiles ===")
    for name, profile in config_loader.load_harness_profiles().items():
        print(f"  {name}: {profile.class_name} ({profile.description})")

    print("\n=== 可用 Environments ===")
    for name, profile in config_loader.load_env_profiles().items():
        print(f"  {name}: {profile.class_name} — {profile.description} [{profile.dataset}]")


def generate_sample_data(output_dir: str = "datasets/slot_filling") -> None:
    """生成示例测试数据。"""
    os.makedirs(output_dir, exist_ok=True)

    # 示例报修数据
    sample_tasks = [
        {
            "task_id": "repair_001",
            "task_type": "slot_filling",
            "prompt": "我家空调不制冷了，想约个师傅上门看看。地址是广东省广州市天河区天河路太阳新天地小区，电话13800138000，明天上午方便",
            "ground_truth": {
                "product_name": "空调",
                "product_brand": "",
                "fault_info_desc": "不制冷",
                "product_num": "1",
                "province": "广东省",
                "city": "广州市",
                "county": "天河区",
                "subdistrict": "天河路",
                "community": "太阳新天地小区",
                "book_desc": "明天上午",
                "phone_number": "13800138000",
            },
            "expected_slots": {
                "product_name": "空调",
                "product_brand": "",
                "fault_info_desc": "不制冷",
                "product_num": "1",
                "province": "广东省",
                "city": "广州市",
                "county": "天河区",
                "subdistrict": "天河路",
                "community": "太阳新天地小区",
                "book_desc": "明天上午",
                "phone_number": "13800138000",
            },
            "slot_keys": [
                "product_name", "product_brand", "fault_info_desc", "product_num",
                "province", "city", "county", "subdistrict", "community",
                "book_desc", "phone_number",
            ],
        },
        {
            "task_id": "repair_002",
            "task_type": "slot_filling",
            "prompt": "我要报修洗衣机，海尔牌的，脱水的时候噪音特别大。我家住浙江省杭州市西湖区文三路嘉绿苑小区，电话是13912345678，后天下午吧",
            "ground_truth": {
                "product_name": "洗衣机",
                "product_brand": "海尔",
                "fault_info_desc": "脱水噪音大",
                "product_num": "1",
                "province": "浙江省",
                "city": "杭州市",
                "county": "西湖区",
                "subdistrict": "文三路",
                "community": "嘉绿苑小区",
                "book_desc": "后天下午",
                "phone_number": "13912345678",
            },
            "expected_slots": {
                "product_name": "洗衣机",
                "product_brand": "海尔",
                "fault_info_desc": "脱水噪音大",
                "product_num": "1",
                "province": "浙江省",
                "city": "杭州市",
                "county": "西湖区",
                "subdistrict": "文三路",
                "community": "嘉绿苑小区",
                "book_desc": "后天下午",
                "phone_number": "13912345678",
            },
            "slot_keys": [
                "product_name", "product_brand", "fault_info_desc", "product_num",
                "province", "city", "county", "subdistrict", "community",
                "book_desc", "phone_number",
            ],
        },
    ]

    filepath = os.path.join(output_dir, "xiu_test.jsonl")
    with open(filepath, "w", encoding="utf-8") as f:
        for task in sample_tasks:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")
    print(f"示例数据已生成: {filepath} ({len(sample_tasks)} 条)")

    # 示例报装数据
    install_tasks = [
        {
            "task_id": "install_001",
            "task_type": "slot_filling",
            "prompt": "我买了一台格力中央空调，需要安装，壁挂式安装。地址在北京市朝阳区望京街道望京SOHO小区，电话15011112222，下周一来装",
            "ground_truth": {
                "product_name": "中央空调",
                "product_brand": "格力",
                "product_install_mode": "壁挂式安装",
                "product_num": "1",
                "province": "北京市",
                "city": "北京市",
                "county": "朝阳区",
                "subdistrict": "望京街道",
                "community": "望京SOHO小区",
                "book_desc": "下周一",
                "phone_number": "15011112222",
            },
            "expected_slots": {
                "product_name": "中央空调",
                "product_brand": "格力",
                "product_install_mode": "壁挂式安装",
                "product_num": "1",
                "province": "北京市",
                "city": "北京市",
                "county": "朝阳区",
                "subdistrict": "望京街道",
                "community": "望京SOHO小区",
                "book_desc": "下周一",
                "phone_number": "15011112222",
            },
            "slot_keys": [
                "product_name", "product_brand", "product_install_mode", "product_num",
                "province", "city", "county", "subdistrict", "community",
                "book_desc", "phone_number",
            ],
        },
    ]

    filepath2 = os.path.join(output_dir, "zhuang_test.jsonl")
    with open(filepath2, "w", encoding="utf-8") as f:
        for task in install_tasks:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")
    print(f"示例数据已生成: {filepath2} ({len(install_tasks)} 条)")


async def run_pipeline(args: argparse.Namespace) -> None:
    """运行评测管线。"""
    logger = setup_logging(args.log_level)
    config_loader = ConfigLoader(config_dir=args.config_dir)

    # 加载实验配置
    if args.experiment:
        exp_config = config_loader.load_experiment(f"{args.experiment}.yaml")
    elif args.llm and args.harness and args.env:
        # 从命令行参数构建配置
        exp_config = ExperimentConfig(
            name=f"custom_{args.llm}_{args.harness}_{args.env}",
            llm_profiles=[args.llm],
            harness_profiles=[args.harness],
            environments=[args.env],
        )
    else:
        print("错误: 请指定 --experiment 或 --llm + --harness + --env")
        print("使用 --help 查看帮助")
        return

    # 覆盖输出目录
    if args.output_dir:
        exp_config.output_dir = args.output_dir

    # Dry run
    if args.dry_run:
        import itertools
        combos = list(itertools.product(
            exp_config.llm_profiles,
            exp_config.harness_profiles,
            exp_config.environments,
        ))
        print(f"\n=== Dry Run: 将运行 {len(combos)} 个组合 ===\n")
        for llm, harness, env in combos:
            print(f"  LLM={llm}, Harness={harness}, Env={env}")
        print()
        return

    # 运行评测
    orchestrator = Orchestrator(config_loader)
    result = await orchestrator.run_experiment(exp_config)

    # 生成报告
    output_dir = os.path.join(exp_config.output_dir, "reports")
    all_trajs = result.get_all_trajectories()

    if not args.no_excel:
        writer = ExcelWriter(output_dir)
        writer.write(result)

    if not args.no_html:
        dashboard = HTMLDashboard(output_dir)
        dashboard.write(result)

    # 轨迹日志
    traj_dir = os.path.join(exp_config.output_dir, "trajectories")
    logger_obj = TrajectoryLogger(traj_dir)
    logger_obj.write_all(all_trajs, exp_config.name)

    # 案例研究
    case_dir = os.path.join(exp_config.output_dir, "case_studies")
    case_writer = CaseStudyWriter(case_dir)
    case_writer.write(all_trajs, exp_config.name, case_count=exp_config.reporting.case_study_count)

    print(f"\n✅ 所有报告已生成，保存在: {exp_config.output_dir}")


def main() -> None:
    args = parse_args()

    if args.list_profiles:
        config_loader = ConfigLoader(config_dir=args.config_dir)
        list_profiles(config_loader)
        return

    if args.generate_sample_data:
        generate_sample_data()
        return

    asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    main()
