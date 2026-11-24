"""``stage`` 命令组：test / regression 的通用 runner。"""

import argparse
import json
import sys
from pathlib import Path

from ..policy import PolicyError
from ..stage_runner import (StageError, judge as stage_judge,
                            load_argv as stage_load_argv, plan as stage_plan,
                            report as stage_report, run as stage_run)
from .common import policy_for, where_pairs


def cmd_stage_plan(args: argparse.Namespace) -> int:
    try:
        tasks = stage_plan(
            Path(args.root), args.stage, Path(args.output), policy_for(args),
            limit=args.limit, full=args.full,
            candidate_path=Path(args.candidate) if args.candidate else None,
            baseline_traces=Path(args.baseline_traces) if args.baseline_traces else None,
            where=where_pairs(args.where),
        )
    except (StageError, OSError, ValueError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(tasks, ensure_ascii=False, indent=2))
    return 0


def cmd_stage_run(args: argparse.Namespace) -> int:
    try:
        result = stage_run(Path(args.output), stage_load_argv(args.command),
                           timeout=args.timeout,
                           judge_path=Path(args.judge) if args.judge else None)
    except (StageError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_stage_judge(args: argparse.Namespace) -> int:
    try:
        calibration = None
        if args.calibration:
            calibration = json.loads(Path(args.calibration).read_text(encoding="utf-8"))
        result = stage_judge(Path(args.output), agent=args.agent,
                             timeout=args.timeout, calibration=calibration)
    except (StageError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_stage_report(args: argparse.Namespace) -> int:
    try:
        policy = policy_for(args)
        result = stage_report(Path(args.output), args.stage, Path(args.judge), policy,
                              card=args.card, update_stage=args.update_stage,
                              record=args.record)
    except (StageError, OSError, ValueError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (result.get("passed", True) and
                 (result.get("decision") or {}).get("conclusion", {}).get("decision") != "reject") else 1


def register(subparsers) -> None:
    stage = subparsers.add_parser("stage", help="test / regression 的通用 runner")
    stage_sub = stage.add_subparsers(dest="stage_command", required=True)
    s_plan = stage_sub.add_parser("plan", help="生成 stage 任务")
    s_plan.add_argument("--stage", required=True, choices=("test", "regression"))
    s_plan.add_argument("--root", default=".")
    s_plan.add_argument("--output", required=True)
    s_plan.add_argument("--candidate", default=None)
    s_plan.add_argument("--baseline-traces", default=None)
    s_plan.add_argument("--limit", type=int, default=None)
    s_plan.add_argument("--full", action="store_true")
    s_plan.add_argument("--where", action="append", default=None,
                        help="按 sample.input 的 key=value 选子集，可重复")
    s_plan.add_argument("--policy", default=None)
    s_plan.set_defaults(func=cmd_stage_plan)
    s_run = stage_sub.add_parser("run", help="按外部 command 执行 stage 任务")
    s_run.add_argument("--output", required=True)
    s_run.add_argument("--command", required=True, help='JSON 列表')
    s_run.add_argument("--judge", default=None)
    s_run.add_argument("--timeout", type=float, default=600.0)
    s_run.set_defaults(func=cmd_stage_run)
    s_judge = stage_sub.add_parser("judge", help="按样本/arm 执行外部 judge")
    s_judge.add_argument("--output", required=True)
    s_judge.add_argument("--agent", default="dsh", choices=("dsh", "claude", "echo"))
    s_judge.add_argument("--timeout", type=float, default=300.0)
    s_judge.add_argument("--calibration", default=None,
                         help="judge-calibration --json 的结果；test 必须 passed")
    s_judge.set_defaults(func=cmd_stage_judge)
    s_report = stage_sub.add_parser("report", help="test 走 exact gate；regression 走硬失败")
    s_report.add_argument("--stage", required=True, choices=("test", "regression"))
    s_report.add_argument("--output", required=True)
    s_report.add_argument("--judge", required=True)
    s_report.add_argument("--card", default=None)
    s_report.add_argument("--update-stage", action="store_true",
                          help="test 报告通过后把 test-stage.yaml 标 complete")
    s_report.add_argument("--policy", default=None)
    s_report.add_argument("--record", action="store_true",
                          help="regression 报告后写一条 insufficient 结论，供 readback 回读")
    s_report.set_defaults(func=cmd_stage_report)
