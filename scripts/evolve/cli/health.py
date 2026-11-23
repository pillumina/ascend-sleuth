"""``health`` 命令组：metrics 体检只读摘要。"""

import argparse
import json
from pathlib import Path

from ..adapters.health import metrics as health_metrics


def cmd_health(args: argparse.Namespace) -> int:
    payload = health_metrics(Path(args.root) if args.root else Path.cwd())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        if not payload.get("available"):
            print(f"metrics_health: unavailable ({payload.get('error', 'unknown')})")
        else:
            print(f"metrics_health: {payload.get('check_verdict', 'unknown')}")
            print(f"fail_count: {payload.get('fail_count', 0)}")
            for finding in (payload.get("findings") or [])[:5]:
                print(f"- {finding.get('face', '')}: {finding.get('text', '')}")
            for item in payload.get("broken") or []:
                print(f"- broken: {item}")
    if not payload.get("available"):
        return 1
    if args.check:
        if payload.get("broken"):
            return 2
        if int(payload.get("fail_count") or 0) > 0:
            return 1
    return 0


def register(subparsers) -> None:
    health = subparsers.add_parser("health", help="metrics 体检只读摘要")
    health.add_argument("--root", default=None)
    health.add_argument("--json", action="store_true")
    health.add_argument("--check", action="store_true", help="有 fail 时退出 1")
    health.set_defaults(func=cmd_health)
