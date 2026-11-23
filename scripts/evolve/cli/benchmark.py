"""``benchmark`` 命令组：确定性 benchmark。"""

import argparse
import json
import sys
from pathlib import Path

from ..benchmark import BenchmarkError, compare as benchmark_compare, load_argv
from ..policy import PolicyError
from .common import policy_for


def cmd_benchmark(args: argparse.Namespace) -> int:
    try:
        policy = policy_for(args)
        runs = args.runs
        if runs is None:
            runs = int((((policy.get("cost") or {}).get("runs") or {}).get("benchmark_runs") or 3))
        result = benchmark_compare(
            Path(args.baseline_root), Path(args.candidate_root),
            load_argv(args.argv), runs=runs, timeout=args.timeout,
        )
    except (BenchmarkError, OSError, ValueError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"baseline: {result['baseline']['median_ms']} ms ok={result['baseline']['ok']}")
        print(f"candidate: {result['candidate']['median_ms']} ms ok={result['candidate']['ok']}")
        print(f"delta: {result['delta_ms']} ms ratio={result['ratio']}")
    return 0 if result["baseline"]["ok"] and result["candidate"]["ok"] else 1


def register(subparsers) -> None:
    benchmark = subparsers.add_parser("benchmark", help="确定性 benchmark；工具/检索类改动不走诊断")
    benchmark.add_argument("--baseline-root", required=True)
    benchmark.add_argument("--candidate-root", required=True)
    benchmark.add_argument("--argv", required=True, help='JSON 列表，如 ["python3","-c","print(1)"]')
    benchmark.add_argument("--runs", type=int, default=None)
    benchmark.add_argument("--timeout", type=float, default=120.0)
    benchmark.add_argument("--policy", default=None)
    benchmark.add_argument("--json", action="store_true")
    benchmark.set_defaults(func=cmd_benchmark)
