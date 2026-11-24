"""CLI 各组共用的路径、读写、策略与判定收尾 helper。

组模块只从这里取共用件；``evolve.cli`` 再把它们以原私有名字 re-export，
外部看到的 ``evolve.cli._json_object`` 等名字不变。这里不放任何 argparse
注册代码。
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from ..contracts import Conclusion, ContractError, Version, now_iso
from ..decision import Decision, DecisionResult, decide
from ..errors import EvolveError
from ..holdout_guard import is_holdout_source, issue_numbers
from ..inputs import json_object, read_json
from ..policy import PolicyError, load_config_policy, load_policy
from ..records import ConclusionStore, RecordError
from ..samples import SampleStore

from exec_log_path import resolve_checkout_dir

PROG = "evolve.py"

JUDGE_METHODS = ("paired_binary", "cost_primary")


class CliError(EvolveError, ValueError):
    """命令行输入错误。"""


def json_object_arg(text: Optional[str], name: str) -> Optional[Dict[str, Any]]:
    return json_object(text, name, CliError)


def yaml_or_json_object(text: Optional[str], name: str) -> Optional[Dict[str, Any]]:
    """接受内联 YAML/JSON 或文件路径；用于 --versions。"""
    if text is None:
        return None
    candidate = Path(text)
    try:
        raw_text = candidate.read_text(encoding="utf-8") if candidate.is_file() else text
        value = yaml.safe_load(raw_text)
    except (OSError, UnicodeDecodeError) as exc:
        raise CliError(f"cannot read {name}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise CliError(f"{name} is not valid YAML/JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CliError(f"{name} must be an object")
    return value


def root_of(args: argparse.Namespace) -> Path:
    """策略文件的检出根；默认当前目录（策略是 tracked 文件，不该锚主检出）。"""
    return Path(getattr(args, "root", None) or ".")


def evolve_base(args: argparse.Namespace) -> Path:
    """样本/结论/执行记录的 base（``.s2-replay/evolve``）。

    未显式给 ``--root`` 时锚到同一克隆的主检出（与 traces/exec-log 同一条语义），
    避免 worktree 清理时静默丢掉候选队列与结论；给了 ``--root`` 就落在该检出内，
    测试与临时隔离用这条。
    """
    explicit = getattr(args, "root", None)
    if explicit:
        return Path(explicit) / ".s2-replay" / "evolve"
    path, _where, _rel = resolve_checkout_dir("evolve", Path.cwd())
    if path is None:
        return Path.cwd() / ".s2-replay" / "evolve"
    return path


def sample_store(args: argparse.Namespace) -> SampleStore:
    return SampleStore(base=evolve_base(args))


def guard_holdout(args: argparse.Namespace, source: str) -> None:
    numbers = issue_numbers(Path(args.root) if getattr(args, "root", None) else Path.cwd())
    if numbers and is_holdout_source(source, numbers):
        raise CliError(f"source {source!r} is in holdout; do not ingest it as an eval sample")


def judge_policy(path: Optional[str]) -> Dict[str, Any]:
    if path:
        return load_policy(Path(path))
    return load_policy(None)


def policy_for(args: argparse.Namespace) -> Dict[str, Any]:
    """策略读取顺序：显式 ``--policy`` → ``<root>/sleuth.config.yaml`` 的 evolution.policy。"""
    explicit = getattr(args, "policy", None)
    if explicit:
        return judge_policy(explicit)
    import sleuth_config as SC
    root = Path(getattr(args, "root", None) or Path.cwd())
    try:
        config = SC.load_config(root)
        return load_config_policy(config, getattr(args, "profile", None),
                                  getattr(args, "pipeline", None))
    except SC.ConfigError as exc:
        raise PolicyError(str(exc)) from exc


def decide_from_args(args: argparse.Namespace, b: int, c: int,
                     n: int) -> DecisionResult:
    """按 ``policy.decision`` 与 ``policy.cost`` 做一次二元配对判定。"""
    policy = policy_for(args)
    method = policy["decision"]["method"]
    if method not in JUDGE_METHODS:
        raise CliError(
            f"judge supports {list(JUDGE_METHODS)}, policy selects {method!r}"
        )
    cost = policy["cost"]
    return decide(
        method,
        b=b,
        c=c,
        n=n,
        alpha=policy["decision"]["alpha"],
        k=args.k,
        cost_b=args.cost_b,
        cost_c=args.cost_c,
        budget=cost["B"],
        epsilon=cost["epsilon"],
        delta=cost["delta"],
    )


def record_conclusion(args: argparse.Namespace, result: DecisionResult) -> Path:
    """把判定结果追加到结论记录；版本、指标与成本沿用 judge 的参数。"""
    versions = Version.from_dict(
        yaml_or_json_object(args.versions, "--versions") or {}
    )
    metrics = json_object_arg(args.metrics_json, "--metrics-json") or {}
    cost = json_object_arg(args.cost_json, "--cost-json")
    conclusion = Conclusion(
        decision=result.decision.value,
        metrics=metrics,
        cost=cost,
        reason=result.reason,
        versions=versions,
        pool_hash=args.pool_hash,
        reuse_index=args.k,
        alpha_eff=result.alpha_eff,
        b=result.b,
        c=result.c,
        n=result.n,
        p_value=result.p_value,
        delta_q=result.delta_q,
        cost_ratio=result.cost_ratio,
        sample=args.sample,
        card=getattr(args, "card", None),
        pool=args.pool,
        at=now_iso(),
    )
    conclusion.validate()
    store = ConclusionStore.for_base(evolve_base(args))
    store.append(conclusion.to_dict())
    return store.path


def print_decision(result: DecisionResult) -> None:
    data = result.to_dict()
    print(f"decision: {data['decision']}")
    print(f"reason: {data['reason']}")
    for key in ("method", "b", "c", "n", "p_value", "alpha_eff",
                "delta_q", "cost_ratio", "cost_ok", "cost_path"):
        if key in data:
            print(f"{key}: {data[key]}")
    if result.decision in (Decision.ACCEPT, Decision.INSUFFICIENT, Decision.REJECT):
        print("outcome: decided")
    else:
        print("outcome: unknown")


def finish_judge(args: argparse.Namespace, result: DecisionResult) -> int:
    print_decision(result)
    if not args.record:
        return 0
    try:
        path = record_conclusion(args, result)
    except (ContractError, CliError, ValueError) as exc:
        print(f"error: cannot record conclusion: {exc}", file=sys.stderr)
        return 2
    except (RecordError, OSError) as exc:
        print(f"error: cannot append conclusion: {exc}", file=sys.stderr)
        return 1
    print(f"recorded: {path}")
    return 0


def read_json_value(path: str) -> Any:
    return read_json(path)


def load_plan(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def where_pairs(values):
    pairs = {}
    for raw in values or []:
        if "=" not in raw:
            raise ValueError(f"--where expects key=value, got {raw!r}")
        key, value = raw.split("=", 1)
        if not key:
            raise ValueError(f"--where expects key=value, got {raw!r}")
        pairs[key] = value
    return pairs
