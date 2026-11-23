"""``policy`` 命令组：校验、展示与自动档位解析。"""

import argparse
import sys
from pathlib import Path

import yaml

from ..policy import (PolicyError, load_config_policy, policy_hash,
                      resolve_autonomy)
from .common import policy_for


def cmd_policy_autonomy(args: argparse.Namespace) -> int:
    try:
        policy = policy_for(args)
        level = resolve_autonomy(policy, args.component)
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"component: {args.component}")
    print(f"autonomy: {level}")
    return 0


def cmd_policy_check(args: argparse.Namespace) -> int:
    try:
        import sleuth_config as SC
        root = Path(getattr(args, "root", None) or Path.cwd())
        cfg = SC.load_config(root)
        policy = load_config_policy(cfg, getattr(args, "profile", None))
    except (PolicyError, SC.ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("policy: ok")
    print(f"policy_hash: {policy_hash(policy)}")
    print(f"target: {(policy.get('experiment') or {}).get('target', 'skill')}")
    return 0


def cmd_policy_show(args: argparse.Namespace) -> int:
    try:
        policy = policy_for(args)
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = yaml.safe_dump(policy, sort_keys=False, allow_unicode=True)
    print(text, end="" if text.endswith("\n") else "\n")
    print(f"# policy_hash: {policy_hash(policy)}")
    return 0


def register(subparsers) -> None:
    policy = subparsers.add_parser("policy", help="策略文件检查/展示")
    policy_sub = policy.add_subparsers(dest="policy_command", required=True)
    check = policy_sub.add_parser("check", help="校验 sleuth.config.yaml 的 evolution.policy")
    check.add_argument("--root", default=".", help="检出根目录（默认 .）")
    check.set_defaults(func=cmd_policy_check)
    show = policy_sub.add_parser("show", help="打印合并默认值后的策略")
    show.add_argument("--root", default=".", help="检出根目录（默认 .）")
    show.set_defaults(func=cmd_policy_show)
    autonomy = policy_sub.add_parser("autonomy", help="按 target_component 解析自动档位")
    autonomy.add_argument("--root", default=".", help="检出根目录（默认 .）")
    autonomy.add_argument("--component", required=True)
    autonomy.add_argument("--policy", default=None, help="策略文件路径（默认 sleuth.config.yaml 的 evolution.policy）")
    autonomy.set_defaults(func=cmd_policy_autonomy)
