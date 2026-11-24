"""``readback`` 命令组：按 EV 卡回读最新 Conclusion。"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

from ..readback import (ReadbackError, latest_by_proposal, latest_conclusion,
                        summary as readback_summary)
from ..store import RSIStore
from .common import evolve_base


def _card_rollback(root: Path, card: str):
    for path in sorted((root / "proposals" / "ideas").glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(doc, dict) and doc.get("id") == card:
            return (doc.get("validation") or {}).get("rollback")
    return None


def cmd_readback(args: argparse.Namespace) -> int:
    if bool(args.card) == bool(args.proposal):
        print("error: pass exactly one of --card or --proposal", file=sys.stderr)
        return 2
    try:
        base = evolve_base(args)
        if args.proposal:
            record = latest_by_proposal(args.proposal, base)
            if record is None:
                from ..store import RSIStore
                for event in reversed(RSIStore(base).history(proposal_id=args.proposal)):
                    data = event.get("data") or {}
                    if event.get("kind") == "decision":
                        record = data.get("conclusion")
                    elif event.get("kind") == "experiment":
                        record = data.get("conclusion")
                    if record:
                        break
        else:
            record = latest_conclusion(args.card, base)
    except ReadbackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if record is None:
        label = args.card or args.proposal
        print(f"error: no conclusion bound to {label}", file=sys.stderr)
        return 1
    data = readback_summary(record)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"card: {data['card'] or ''}")
        print(f"proposal: {data['proposal'] or ''}")
        print(f"decision: {data['decision']}")
        print(f"b/c/n: {data['b']}/{data['c']}/{data['n']} p={data['p_value']} alpha_eff={data['alpha_eff']}")
        print(f"model: {data['model'] or 'unknown'}")
        print(f"cost: {data['cost'] or 'unavailable'} paired={data['cost_paired']} missing={data['cost_missing']}")
        print(f"at: {data['at']}")
    if args.measure and not data.get("card"):
        print("error: --measure requires a card-bound conclusion", file=sys.stderr)
        return 2
    if args.measure:
        root = Path(args.root or ".")
        proc = subprocess.run(
            [sys.executable, str(root / "scripts" / "ev_measure.py"), data["card"],
             "--run", "--timeout", str(args.measure_timeout)],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
        )
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        if proc.returncode != 0:
            rollback = _card_rollback(root, args.card)
            print("rollback: " + (rollback or "measure 失败；见卡 validation.rollback"))
        return proc.returncode
    return 0


def register(subparsers) -> None:
    readback = subparsers.add_parser("readback", help="按 EV 卡回读最新 Conclusion")
    readback.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    readback.add_argument("--card", default=None)
    readback.add_argument("--proposal", default=None)
    readback.add_argument("--measure", action="store_true", help="再跑 EV 卡的 predicted_effect.measure")
    readback.add_argument("--measure-timeout", type=int, default=120)
    readback.add_argument("--json", action="store_true")
    readback.set_defaults(func=cmd_readback)
