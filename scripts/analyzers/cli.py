#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内置分析器统一 CLI。

用法：
  python3 scripts/analyzers/cli.py status [--json]
  python3 scripts/analyzers/cli.py list
  python3 scripts/analyzers/cli.py enable
  python3 scripts/analyzers/cli.py disable
  python3 scripts/analyzers/cli.py run <name> --inputs <路径...> [--out-dir <目录>] [--session-id <ID>]

分析器默认关闭。enable / disable 保存本机设置，环境变量 SLEUTH_ANALYZERS 可覆盖该设置。
每个分析器也可以直接跑自己的适配器：python3 scripts/analyzers/<name>/run.py --help
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _lib import (  # noqa: E402
    ENABLE_COMMAND,
    UPSTREAM_COMMIT,
    analyzer_state,
    force_utf8,
    save_analyzer_preference,
)
from registry import ANALYZERS, find  # noqa: E402


def _installed(item: dict) -> bool:
    return (HERE / item["adapter"]).is_file() and (HERE / item["name"] / item["entry"]).is_file()


def _status_payload() -> dict:
    enabled, source = analyzer_state()
    return {
        "schema_version": 1,
        "enabled": enabled,
        "source": source,
        "enable_command": ENABLE_COMMAND,
        "upstream_commit": UPSTREAM_COMMIT,
        "python": sys.executable,
        "analyzers": [
            {
                "name": item["name"],
                "installed": _installed(item),
                "adapter": str(HERE / item["adapter"]),
                "entry": str(HERE / item["name"] / item["entry"]),
                "inputs": item["inputs"],
                "purpose": item["purpose"],
            }
            for item in ANALYZERS
        ],
    }


def cmd_status(args: argparse.Namespace) -> int:
    payload = _status_payload()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        state = "enabled" if payload["enabled"] else "disabled"
        print(f"analyzers: {state}")
        print(f"source: {payload['source']}")
        print(f"python: {payload['python']}")
        print(f"upstream: {payload['upstream_commit']}")
        for item in payload["analyzers"]:
            mark = "installed" if item["installed"] else "MISSING"
            print(f"  {item['name']:<22} {mark}")
        if not payload["enabled"]:
            print(f"\n本机启用：{payload['enable_command']}")
    return 0


def cmd_set_enabled(args: argparse.Namespace) -> int:
    try:
        path = save_analyzer_preference(args.enabled)
    except OSError as exc:
        print(f"保存分析器设置失败（{exc}）", file=sys.stderr)
        return 1
    preference = "开启" if args.enabled else "关闭"
    print(f"已保存本机设置（{preference}） {path}")
    enabled, source = analyzer_state()
    if enabled != args.enabled:
        state = "开启" if enabled else "关闭"
        print(f"当前仍为{state}（{source}）")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    if getattr(args, "json", False):
        print(json.dumps(
            [
                {"name": item["name"], "inputs": item["inputs"], "purpose": item["purpose"]}
                for item in ANALYZERS
            ],
            ensure_ascii=False,
            indent=2,
        ))
        return 0
    print("name                     inputs")
    for item in ANALYZERS:
        print(f"{item['name']:<24} {item['inputs']}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    item = find(args.name)
    if item is None:
        print(f"未知分析器：{args.name}；可用：{', '.join(x['name'] for x in ANALYZERS)}", file=sys.stderr)
        return 2
    enabled, source = analyzer_state()
    if not enabled:
        print(
            f"分析器已关闭（{source}）。本机启用命令：{ENABLE_COMMAND}",
            file=sys.stderr,
        )
        return 3
    adapter = HERE / item["adapter"]
    if not adapter.is_file():
        print(f"分析器适配器缺失：{adapter}", file=sys.stderr)
        return 4
    cmd = [sys.executable, str(adapter), *args.rest]
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    force_utf8()
    parser = argparse.ArgumentParser(description="ascend-sleuth 内置分析器 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="查看开关与分析器安装状态")
    status.add_argument("--json", action="store_true", help="输出 JSON")
    status.set_defaults(func=cmd_status)

    enable = sub.add_parser("enable", help="在本机开启分析器")
    enable.set_defaults(func=cmd_set_enabled, enabled=True)
    disable = sub.add_parser("disable", help="在本机关闭分析器")
    disable.set_defaults(func=cmd_set_enabled, enabled=False)

    listing = sub.add_parser("list", help="列出分析器与输入形态")
    listing.add_argument("--json", action="store_true", help="输出 JSON")
    listing.set_defaults(func=cmd_list)

    run = sub.add_parser("run", help="运行一个分析器（参数透传给适配器）")
    run.add_argument("name", help="分析器名")
    run.add_argument("rest", nargs=argparse.REMAINDER, help="--inputs / --out-dir / --session-id / --ab / --purpose / --timeout")
    run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
