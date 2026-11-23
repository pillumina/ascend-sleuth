"""``judge`` 命令组：二元配对判定、stats 配对与校准。"""

import argparse
import json
import sys
from pathlib import Path

from ..adapters import AdapterError
from ..adapters.arena import counts_from_files
from ..calibration import CalibrationError, calibrate
from ..policy import PolicyError
from .common import CliError, decide_from_args, finish_judge


def cmd_judge(args: argparse.Namespace) -> int:
    if args.record and not args.versions:
        print("error: --versions is required with --record", file=sys.stderr)
        return 2
    try:
        result = decide_from_args(args, args.b, args.c, args.n)
    except (PolicyError, CliError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return finish_judge(args, result)


def cmd_judge_calibration(args: argparse.Namespace) -> int:
    try:
        result = calibrate(Path(args.a), Path(args.b),
                           min_raw=args.min_raw, min_kappa=args.min_kappa)
    except CalibrationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        print(f"n: {result['n']}")
        print(f"agree: {result['agree']} ({result['raw']:.4f})")
        print(f"kappa: {result['kappa']:.4f}")
        print(f"passed: {str(result['passed']).lower()} "
              f"(min_raw={result['min_raw']}, min_kappa={result['min_kappa']})")
    return 0 if result["passed"] else 1


def cmd_judge_stats(args: argparse.Namespace) -> int:
    """读两份 stats，按配对读数判定；账本只写结论记录，不碰 arena 影响账本。"""
    if args.record and not args.versions:
        print("error: --versions is required with --record", file=sys.stderr)
        return 2
    try:
        counts = counts_from_files(args.baseline, args.candidate)
    except AdapterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"paired: b={counts['b']} c={counts['c']} n={counts['n']}")
    try:
        result = decide_from_args(args, counts["b"], counts["c"], counts["n"])
    except (PolicyError, CliError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return finish_judge(args, result)


def register(subparsers) -> None:
    judge = subparsers.add_parser("judge", help="二元配对判定（b/c/n + 可选成本）")
    judge.add_argument("--b", type=int, required=True, help="候选独家命中数")
    judge.add_argument("--c", type=int, required=True, help="基线独家命中数")
    judge.add_argument("--n", type=int, required=True, help="配对样本总数")
    judge.add_argument("--cost-b", type=float, default=None)
    judge.add_argument("--cost-c", type=float, default=None)
    judge.add_argument("--policy", default=None, help="策略文件路径（默认 sleuth.config.yaml 的 evolution.policy）")
    judge.add_argument("--k", type=int, default=0, help="同一评估池复用序号")
    judge.add_argument("--root", default=None, help="结论记录本地根（默认锚主检出）")
    judge.add_argument("--record", action="store_true",
                       help="把结论追加到 .s2-replay/evolve/conclusions.jsonl")
    judge.add_argument("--versions", default=None,
                       help="结论版本 YAML/JSON（protocol/policy/base_kb/candidate_kb/candidate/model）")
    judge.add_argument("--pool-hash", default=None, help="写进结论的池内容哈希")
    judge.add_argument("--metrics-json", default=None, help="JSON 对象，写进结论 metrics")
    judge.add_argument("--cost-json", default=None, help="JSON 对象，写进结论 cost")
    judge.add_argument("--sample", default=None, help="写进结论的样本 id")
    judge.add_argument("--card", default=None, help="写进结论的 EV 卡号")
    judge.add_argument("--pool", default=None, help="写进结论的评估池名")
    judge.set_defaults(func=cmd_judge)

    judge_stats = subparsers.add_parser(
        "judge-stats", help="从两份 arena stats 的 issues 配对 b/c/n 并判定"
    )
    judge_stats.add_argument("--baseline", required=True, help="基线 stats YAML")
    judge_stats.add_argument("--candidate", required=True, help="候选 stats YAML")
    judge_stats.add_argument("--cost-b", type=float, default=None)
    judge_stats.add_argument("--cost-c", type=float, default=None)
    judge_stats.add_argument("--policy", default=None, help="策略文件路径（默认 sleuth.config.yaml 的 evolution.policy）")
    judge_stats.add_argument("--k", type=int, default=0, help="同一评估池复用序号")
    judge_stats.add_argument("--root", default=None, help="结论记录本地根（默认锚主检出）")
    judge_stats.add_argument("--record", action="store_true",
                             help="把结论追加到 .s2-replay/evolve/conclusions.jsonl")
    judge_stats.add_argument("--versions", default=None,
                             help="结论版本 YAML/JSON（protocol/policy/base_kb/"
                                  "candidate_kb/candidate/model）")
    judge_stats.add_argument("--pool-hash", default=None, help="写进结论的池内容哈希")
    judge_stats.add_argument("--metrics-json", default=None, help="JSON 对象，写进结论 metrics")
    judge_stats.add_argument("--cost-json", default=None, help="JSON 对象，写进结论 cost")
    judge_stats.add_argument("--sample", default=None, help="写进结论的样本 id")
    judge_stats.add_argument("--card", default=None, help="写进结论的 EV 卡号")
    judge_stats.add_argument("--pool", default=None, help="写进结论的评估池名")
    judge_stats.set_defaults(func=cmd_judge_stats)

    calibration = subparsers.add_parser(
        "judge-calibration", help="两份 0/1 标签的一致率与 kappa 门槛")
    calibration.add_argument("--a", required=True, help="评分员 A 的 JSON 标签")
    calibration.add_argument("--b", required=True, help="评分员 B 的 JSON 标签")
    calibration.add_argument("--min-raw", type=float, default=0.8)
    calibration.add_argument("--min-kappa", type=float, default=0.6)
    calibration.add_argument("--json", action="store_true")
    calibration.set_defaults(func=cmd_judge_calibration)
