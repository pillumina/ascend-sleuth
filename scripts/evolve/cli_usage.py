"""用量维度的子命令：三个维度由 ``usage_dimensions`` 表生成。

``from-trace`` / ``evaluate`` / ``compare`` 三组命令的差别只在维度记录里
（参数、解析函数、人读输出）；这里不写任何维度名。
"""

import argparse
import json
import sys
from functools import partial
from pathlib import Path

import yaml

from .inputs import read_json
from .usage_dimensions import DIMENSIONS, UsageDimension


def _error(message: object) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 2


def _from_trace(dimension: UsageDimension, args: argparse.Namespace) -> int:
    try:
        document = yaml.safe_load(Path(args.trace).read_text(encoding="utf-8"))
        options = {
            option.dest: option.convert(getattr(args, option.dest, None))
            for option in dimension.trace_options
        }
        result = dimension.from_trace(document, **options)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return _error(exc)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for line in dimension.trace_lines(result):
            print(line)
    return 0


def _evaluate(dimension: UsageDimension, args: argparse.Namespace) -> int:
    try:
        result = dimension.evaluate(read_json(args.file))
    except (OSError, ValueError) as exc:
        return _error(exc)
    if args.json or not dimension.human_evaluate:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for line in dimension.evaluate_lines(result):
            print(line)
    return 0


def _compare(dimension: UsageDimension, args: argparse.Namespace) -> int:
    try:
        result = dimension.compare(read_json(args.baseline), read_json(args.candidate))
    except (OSError, ValueError) as exc:
        return _error(exc)
    if args.json or not dimension.human_compare:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for line in dimension.compare_lines(result):
            print(line)
    return 0


def register(subparsers) -> None:
    for dimension in DIMENSIONS:
        group = subparsers.add_parser(dimension.label, help=dimension.help)
        commands = group.add_subparsers(dest=f"{dimension.name}_command", required=True)

        trace = commands.add_parser("from-trace", help=dimension.trace_help)
        trace.add_argument("--trace", required=True)
        for option in dimension.trace_options:
            if option.choices:
                trace.add_argument(option.flag, choices=option.choices, default=None)
            else:
                trace.add_argument(option.flag, default=None)
        trace.add_argument("--json", action="store_true")
        trace.set_defaults(func=partial(_from_trace, dimension))

        evaluate = commands.add_parser("evaluate", help=dimension.evaluate_help)
        evaluate.add_argument("--file", required=True)
        evaluate.add_argument("--json", action="store_true")
        evaluate.set_defaults(func=partial(_evaluate, dimension))

        compare = commands.add_parser("compare", help=dimension.compare_help)
        compare.add_argument("--baseline", required=True)
        compare.add_argument("--candidate", required=True)
        compare.add_argument("--json", action="store_true")
        compare.set_defaults(func=partial(_compare, dimension))
