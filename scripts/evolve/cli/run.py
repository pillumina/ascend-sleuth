"""``run`` 命令组：维护者下一步计划。"""

import argparse
import json
import sys
from pathlib import Path

from ..adapters.metrics import load_metrics
from ..policy import PolicyError
from ..records import RecordError
from ..runner import issue_plan, render_plan
from ..samples import StoreError
from ..trace_attribution import status as trace_status
from .common import evolve_base, policy_for


def cmd_run(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    base = evolve_base(args)
    try:
        policy = policy_for(args)
        trace = trace_status(base / "trace-state.json")
        plan = issue_plan(root, base, policy, metrics=load_metrics(root), trace_state=trace)
    except (PolicyError, StoreError, RecordError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_plan(plan))
    return 0


def register(subparsers) -> None:
    run = subparsers.add_parser("run", help="维护者下一步计划（不跑模型/不写库）")
    run.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    run.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    run.set_defaults(func=cmd_run)
