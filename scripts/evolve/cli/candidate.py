"""``candidate`` 命令组：candidate Patch 校验、隔离 apply 与 rollback。"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ..candidate import (CandidateError, create_workspace, diff_workspace,
                         rollback_workspace, validate_candidate)
from .common import read_json_value


def cmd_candidate_validate(args: argparse.Namespace) -> int:
    try:
        candidate = validate_candidate(read_json_value(args.file))
    except (OSError, ValueError, CandidateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(candidate, ensure_ascii=False, indent=2))
    return 0


def cmd_candidate_apply(args: argparse.Namespace) -> int:
    try:
        candidate = validate_candidate(read_json_value(args.candidate))
        result = create_workspace(Path(args.root), candidate, Path(args.workspace))
    except (OSError, ValueError, subprocess.CalledProcessError, CandidateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_candidate_rollback(args: argparse.Namespace) -> int:
    try:
        rollback_workspace(Path(args.root), Path(args.workspace))
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"removed: {args.workspace}")
    return 0


def cmd_candidate_diff(args: argparse.Namespace) -> int:
    try:
        print(diff_workspace(Path(args.workspace)))
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def register(subparsers) -> None:
    candidate = subparsers.add_parser("candidate", help="candidate Patch 校验/隔离 apply/rollback")
    candidate_sub = candidate.add_subparsers(dest="candidate_command", required=True)
    cand_validate = candidate_sub.add_parser("validate")
    cand_validate.add_argument("--file", required=True)
    cand_validate.set_defaults(func=cmd_candidate_validate)
    cand_apply = candidate_sub.add_parser("apply")
    cand_apply.add_argument("--root", required=True)
    cand_apply.add_argument("--candidate", required=True)
    cand_apply.add_argument("--workspace", required=True)
    cand_apply.set_defaults(func=cmd_candidate_apply)
    cand_rollback = candidate_sub.add_parser("rollback")
    cand_rollback.add_argument("--root", required=True)
    cand_rollback.add_argument("--workspace", required=True)
    cand_rollback.set_defaults(func=cmd_candidate_rollback)
    cand_diff = candidate_sub.add_parser("diff")
    cand_diff.add_argument("--workspace", required=True)
    cand_diff.set_defaults(func=cmd_candidate_diff)
