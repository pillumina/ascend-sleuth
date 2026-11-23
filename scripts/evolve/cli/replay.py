"""``replay`` 命令组：S2 replay 输入准备与评分收集。"""

import argparse
import sys
from pathlib import Path

from ..adapters import AdapterError
from ..adapters.replay import collect as replay_collect
from ..adapters.replay import prepare as replay_prepare


def cmd_replay_prepare(args: argparse.Namespace) -> int:
    try:
        replay_prepare(Path(args.root))
    except (AdapterError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_replay_collect(args: argparse.Namespace) -> int:
    try:
        replay_collect(Path(args.root), Path(args.report))
    except (AdapterError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def register(subparsers) -> None:
    replay = subparsers.add_parser("replay", help="S2 replay 输入准备与评分收集")
    replay_sub = replay.add_subparsers(dest="replay_command", required=True)
    replay_prepare_cmd = replay_sub.add_parser("prepare", help="产 replay 输入清单")
    replay_prepare_cmd.add_argument("--root", default=".", help="检出根目录（默认 .）")
    replay_prepare_cmd.set_defaults(func=cmd_replay_prepare)
    replay_collect_cmd = replay_sub.add_parser("collect", help="读 result 并写评分报告")
    replay_collect_cmd.add_argument("--root", default=".", help="检出根目录（默认 .）")
    replay_collect_cmd.add_argument("--report", required=True, help="评分报告输出路径")
    replay_collect_cmd.set_defaults(func=cmd_replay_collect)
