"""``traces`` 命令组：本地 trace 归因状态。"""

import argparse
import json
import sys
from pathlib import Path

from ..trace_attribution import status as trace_status, sync as trace_sync
from .common import evolve_base


def cmd_traces_sync(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    state = Path(args.state) if args.state else evolve_base(args) / "trace-state.json"
    try:
        stats = trace_sync(root, state, source_id=args.source_id)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({k: v for k, v in stats.items() if k != "attributions"},
                         ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"traces: {stats['traces']} new={stats['new']} changed={stats['changed']} reused={stats['reused']}")
        print(f"events: {stats['events']}")
        for region in stats.get("regions") or []:
            print(f"region: {region['region']} hard={region['hard']} events={region['events']}")
        if stats.get("experiment"):
            spec = stats["experiment"]
            print(f"experiment: target={spec['target_skill']} region={spec['mutable_region']}")
        print(f"snapshot_id: {stats['snapshot_id']}")
        print(f"state: {stats['state_path']}")
    return 0


def cmd_traces_status(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    state = Path(args.state) if args.state else evolve_base(args) / "trace-state.json"
    try:
        payload = trace_status(state)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def register(subparsers) -> None:
    traces = subparsers.add_parser("traces", help="本地 trace 归因状态")
    traces_sub = traces.add_subparsers(dest="traces_command", required=True)
    traces_sync = traces_sub.add_parser("sync", help="增量归因本地 traces")
    traces_sync.add_argument("--root", default=None)
    traces_sync.add_argument("--state", default=None)
    traces_sync.add_argument("--source-id", default="local")
    traces_sync.add_argument("--json", action="store_true")
    traces_sync.set_defaults(func=cmd_traces_sync)
    traces_status = traces_sub.add_parser("status", help="查看 trace 状态/快照")
    traces_status.add_argument("--root", default=None)
    traces_status.add_argument("--state", default=None)
    traces_status.set_defaults(func=cmd_traces_status)
