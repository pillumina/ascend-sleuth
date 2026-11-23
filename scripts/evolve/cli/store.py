"""``store`` 命令组：RSI 统一存储的查询、校验与迁移。"""

import argparse
import json
import sys

from .common import evolve_base


def cmd_store_history(args: argparse.Namespace) -> int:
    from ..store import RSIStore
    try:
        if not args.experiment and not args.proposal:
            raise ValueError("pass --experiment or --proposal")
        rows = RSIStore(evolve_base(args)).history(
            experiment_id=args.experiment, proposal_id=args.proposal)
        if args.kind:
            rows = [row for row in rows if row.get("kind") == args.kind]
        if args.limit:
            rows = rows[-args.limit:]
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def cmd_store_verify(args: argparse.Namespace) -> int:
    from ..store import verify
    try:
        result = verify(evolve_base(args))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"store: {result['store_path']}")
        print("counts: " + " ".join(f"{k}={v}" for k, v in result["counts"].items()))
        print(f"issues: {len(result['issues'])} ok={result['ok']}")
        for issue in result["issues"][:20]:
            print(f"- {issue['severity']} {issue['code']}: {issue['detail']}")
    return 0 if result["ok"] else 1


def cmd_store_migrate(args: argparse.Namespace) -> int:
    from ..migrate import migrate_legacy
    try:
        result = migrate_legacy(evolve_base(args), dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        counts = result["counts"]
        print(f"store: {result['store_path']}")
        print(f"experiments: {counts['experiments']} decisions: {counts['decisions']} "
              f"rollouts: {counts['rollouts']} skipped: {counts['skipped']}")
    return 0


def register(subparsers) -> None:
    store = subparsers.add_parser("store", help="RSI 统一存储")
    store_sub = store.add_subparsers(dest="store_command", required=True)
    store_migrate = store_sub.add_parser("migrate", help="把旧 JSONL 迁移到 rsi-events")
    store_migrate.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    store_migrate.add_argument("--dry-run", action="store_true")
    store_migrate.add_argument("--json", action="store_true")
    store_migrate.set_defaults(func=cmd_store_migrate)

    store_verify = store_sub.add_parser("verify", help="检查 rsi-events 完整性")
    store_verify.add_argument("--root", default=None)
    store_verify.add_argument("--json", action="store_true")
    store_verify.set_defaults(func=cmd_store_verify)

    store_history = store_sub.add_parser("history", help="按 experiment/proposal 查事件历史")
    store_history.add_argument("--root", default=None)
    store_history.add_argument("--experiment", default=None)
    store_history.add_argument("--proposal", default=None)
    store_history.add_argument("--kind", default=None)
    store_history.add_argument("--limit", type=int, default=0)
    store_history.set_defaults(func=cmd_store_history)
