"""``rsi`` 命令组：多源归因、实验计划与写回。"""

import argparse
import json
import sys
from pathlib import Path

from ..adapters.metrics import load_metrics
from ..holdout_guard import issue_numbers
from ..rsi import apply_attribution, apply_selection, build_plan, save_plan
from .common import evolve_base, load_plan, policy_for, yaml_or_json_object


def cmd_rsi_plan(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    try:
        metrics = load_metrics(root)
        policy = policy_for(args)
        plan = build_plan(
            root,
            trace_state=Path(args.trace_state) if args.trace_state else (evolve_base(args) / "trace-state.json"),
            replay=Path(args.replay) if args.replay else None,
            metrics=metrics,
            holdout_numbers=issue_numbers(root),
            stages_config=(policy.get("experiment") or {}).get("stages"),
        )
        state = Path(args.state) if args.state else evolve_base(args) / "rsi-plan.json"
        save_plan(plan, state)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"rsi_status: {plan['status']}")
        print(f"snapshot_id: {plan['snapshot_id']}")
        for name, source in plan["sources"].items():
            print(f"source {name}: available={source.get('available')} snapshot={source.get('snapshot_id')}")
        for region in plan.get("regions") or []:
            print(f"region: {region['region']} hard={region['hard']} events={region['events']}")
        if plan.get("experiment"):
            spec = plan["experiment"]
            print(f"experiment: target={spec['target_skill']} region={spec['mutable_region']}")
        print(f"stages: {plan['stages']}")
    return 0


def cmd_rsi_attribute(args: argparse.Namespace) -> int:
    try:
        path = Path(args.state)
        plan = load_plan(path)
        payload = yaml_or_json_object(args.file, "--file")
        plan = apply_attribution(plan, payload)
        save_plan(plan, path)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"updated: {path}")
    print("stage: attribute.agent")
    return 0


def cmd_rsi_select(args: argparse.Namespace) -> int:
    try:
        path = Path(args.state)
        plan = load_plan(path)
        payload = yaml_or_json_object(args.file, "--file")
        plan = apply_selection(plan, payload)
        save_plan(plan, path)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"updated: {path}")
    print("stage: select.region_agent")
    return 0


def cmd_rsi_status(args: argparse.Namespace) -> int:
    path = Path(args.state)
    try:
        print(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def register(subparsers) -> None:
    rsi = subparsers.add_parser("rsi", help="RSI 多源归因与实验计划")
    rsi_sub = rsi.add_subparsers(dest="rsi_command", required=True)
    rsi_plan = rsi_sub.add_parser("plan", help="trace/metrics/replay -> 实验计划")
    rsi_plan.add_argument("--root", default=None)
    rsi_plan.add_argument("--trace-state", default=None)
    rsi_plan.add_argument("--replay", default=None)
    rsi_plan.add_argument("--state", default=None)
    rsi_plan.add_argument("--json", action="store_true")
    rsi_plan.set_defaults(func=cmd_rsi_plan)
    rsi_attr = rsi_sub.add_parser("attribute", help="写回 agent 归因证据")
    rsi_attr.add_argument("--state", required=True)
    rsi_attr.add_argument("--file", required=True)
    rsi_attr.set_defaults(func=cmd_rsi_attribute)
    rsi_select = rsi_sub.add_parser("select", help="写回 agent 选点")
    rsi_select.add_argument("--state", required=True)
    rsi_select.add_argument("--file", required=True)
    rsi_select.set_defaults(func=cmd_rsi_select)
    rsi_status = rsi_sub.add_parser("status", help="读取已保存的 RSI 计划")
    rsi_status.add_argument("--state", required=True)
    rsi_status.set_defaults(func=cmd_rsi_status)
