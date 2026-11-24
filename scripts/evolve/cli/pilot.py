"""``pilot`` 命令组：真实 baseline/candidate pilot 编排。"""

import argparse
import json
import sys
from pathlib import Path

from ..pilot import (PilotError, checkpoint as pilot_checkpoint,
                     collect as pilot_collect, decide as pilot_decide,
                     prepare as pilot_prepare)
from ..policy import PolicyError
from .common import policy_for


def cmd_pilot_prepare(args: argparse.Namespace) -> int:
    try:
        result = pilot_prepare(Path(args.root), Path(args.candidate), args.samples,
                               Path(args.output), policy=policy_for(args),
                               baseline_traces=(Path(args.baseline_traces)
                                                if args.baseline_traces else None))
    except (OSError, ValueError, PilotError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_pilot_collect(args: argparse.Namespace) -> int:
    try:
        result = pilot_collect(Path(args.output), judge=Path(args.judge) if args.judge else None)
    except (OSError, ValueError, PilotError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_pilot_checkpoint(args: argparse.Namespace) -> int:
    try:
        policy = policy_for(args)
        result = pilot_checkpoint(Path(args.output), Path(args.judge), policy,
                                  reuse_index=args.reuse_index)
    except (OSError, ValueError, PilotError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["stop"] else 0


def cmd_pilot_decide(args: argparse.Namespace) -> int:
    try:
        policy = policy_for(args)
        result = pilot_decide(Path(args.output), Path(args.judge), policy,
                              reuse_index=args.reuse_index, pool=args.pool,
                              card=args.card)
    except (OSError, ValueError, PilotError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def register(subparsers) -> None:
    pilot = subparsers.add_parser("pilot", help="真实 baseline/candidate pilot 编排")
    pilot_sub = pilot.add_subparsers(dest="pilot_command", required=True)
    p_prepare = pilot_sub.add_parser("prepare")
    p_prepare.add_argument("--root", required=True)
    p_prepare.add_argument("--candidate", required=True)
    p_prepare.add_argument("--samples", nargs="+", required=True)
    p_prepare.add_argument("--output", required=True)
    p_prepare.add_argument("--baseline-traces", default=None,
                           help="复用已有 baseline traces/out 的目录；只跑 candidate")
    p_prepare.set_defaults(func=cmd_pilot_prepare)
    p_collect = pilot_sub.add_parser("collect")
    p_collect.add_argument("--output", required=True)
    p_collect.add_argument("--judge", default=None, help="可选 judge JSON，用于给 source_ok 赋值")
    p_collect.set_defaults(func=cmd_pilot_collect)
    p_check = pilot_sub.add_parser("checkpoint", help="按预算与 futility 判断是否继续跑")
    p_check.add_argument("--output", required=True)
    p_check.add_argument("--judge", required=True)
    p_check.add_argument("--policy", default=None)
    p_check.add_argument("--reuse-index", type=int, default=0)
    p_check.set_defaults(func=cmd_pilot_checkpoint)

    p_decide = pilot_sub.add_parser("decide", help="配对判定并写 Run/Conclusion 记录")
    p_decide.add_argument("--output", required=True)
    p_decide.add_argument("--judge", required=True)
    p_decide.add_argument("--policy", default=None)
    p_decide.add_argument("--reuse-index", type=int, default=None)
    p_decide.add_argument("--pool", default="pilot")
    p_decide.add_argument("--card", default=None, help="写进结论的 EV 卡号")
    p_decide.set_defaults(func=cmd_pilot_decide)
