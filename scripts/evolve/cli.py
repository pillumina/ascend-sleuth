"""evolve 命令行：策略、样本队列、判定与周读数。

编排在这里，规则在核心模块。核心模块不打印、不读文件；CLI 负责路径、
终端输出与退出码：

- ``0``：命令成功（判定结果本身是数据，accept/insufficient/reject/unknown 都算成功）
- ``1``：样本/策略校验不过、状态转换非法、文件格式错
- ``2``：命令行输入错误（judge 的 b/c/n 非法、缺文件等）
"""

import argparse
import json
import subprocess
from dataclasses import asdict
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import yaml

from .calibration import CalibrationError, calibrate
from .benchmark import BenchmarkError, compare as benchmark_compare, load_argv
from .candidate import CandidateError, create_workspace, diff_workspace, rollback_workspace, validate_candidate
from .contracts import (
    OBJECT_TYPE_VALUES,
    ORIGINS,
    PURPOSES,
    STATUSES,
    Conclusion,
    ContractError,
    Patch,
    Version,
    now_iso,
)
from .adapters import AdapterError
from .adapters.arena import counts_from_files
from .adapters.metrics import load_metrics
from .algorithms.registry import algorithm_ids, get_algorithm
from .targets.registry import get_target, resolve_evaluator, resolve_optimizer, target_ids
from .rsi import apply_attribution, apply_selection, build_plan, save_plan
from .trace_attribution import status as trace_status, sync as trace_sync
from .adapters.replay import collect as replay_collect
from .adapters.replay import prepare as replay_prepare
from .adapters.health import metrics as health_metrics
from .adapters.issues import ingest_issues
from .adapters.ixn import import_ixn
from .adapters.s2 import import_s2_samples
from .decision import Decision, DecisionResult, decide
from .experiments import ExperimentError, validate_experiment
from .holdout_guard import is_holdout_source, issue_numbers
from .knowledge_usage import UsageError, compare as compare_usage, evaluate as evaluate_usage, from_trace
from .flow import FlowError, run_proposal
from .proposal_engine import (BestPolicy, GepaPolicy, ParetoPolicy, ProposalArchive,
                              ProposalEngine)
from .proposals import ProposalError, request as proposal_request, validate_draft
from .pilot import (PilotError, checkpoint as pilot_checkpoint, collect as pilot_collect,
                    decide as pilot_decide, prepare as pilot_prepare)
from .stage import (StageError, judge as stage_judge, load_argv as stage_load_argv,
                    plan as stage_plan, report as stage_report, run as stage_run)
from .source_usage import SourceUsageError, compare as compare_source_usage, evaluate as evaluate_source_usage, from_trace as source_from_trace
from .tool_usage import ToolUsageError, compare as compare_tool_usage, evaluate as evaluate_tool_usage, from_trace as tool_from_trace
from .quality import QualityError, load_quality
from .policy import PolicyError, load_config_policy, load_policy, policy_hash, resolve_autonomy
from .intake import IntakeError, completeness, extract_case, extract_trace, make_sample
from .samples import import_pilot
from .readback import (ReadbackError, latest_by_proposal, latest_conclusion,
                       summary as readback_summary)
from .rsi_store import RSIStore
from .records import ConclusionStore, ExperimentStore, RecordError
from .runner import issue_plan, render_plan
from .scoring import RubricError, score_rubric
from .samples import SampleStore, StoreError
from .sources.registry import get_source

from exec_log_path import resolve_checkout_dir

PROG = "evolve.py"

JUDGE_METHODS = ("paired_binary", "cost_primary")


class CliError(ValueError):
    """命令行输入错误。"""


def _json_object(text: Optional[str], name: str) -> Optional[Dict[str, Any]]:
    if text is None:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(f"{name} is not valid JSON: {exc}") from exc
    if value is not None and not isinstance(value, dict):
        raise CliError(f"{name} must be a JSON object")
    return value


def _yaml_or_json_object(text: Optional[str], name: str) -> Optional[Dict[str, Any]]:
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


def _root(args: argparse.Namespace) -> Path:
    """策略文件的检出根；默认当前目录（策略是 tracked 文件，不该锚主检出）。"""
    return Path(getattr(args, "root", None) or ".")


def _evolve_base(args: argparse.Namespace) -> Path:
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


def _store(args: argparse.Namespace) -> SampleStore:
    return SampleStore(base=_evolve_base(args))


# ---------------------------------------------------------------- policy
def cmd_policy_autonomy(args: argparse.Namespace) -> int:
    try:
        policy = _policy_for(args)
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
        policy = _policy_for(args)
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = yaml.safe_dump(policy, sort_keys=False, allow_unicode=True)
    print(text, end="" if text.endswith("\n") else "\n")
    print(f"# policy_hash: {policy_hash(policy)}")
    return 0


# ---------------------------------------------------------------- sample
def _guard_holdout(args: argparse.Namespace, source: str) -> None:
    numbers = issue_numbers(Path(args.root) if getattr(args, "root", None) else Path.cwd())
    if numbers and is_holdout_source(source, numbers):
        raise CliError(f"source {source!r} is in holdout; do not ingest it as an eval sample")


def cmd_sample_new(args: argparse.Namespace) -> int:
    if getattr(args, "from_source", None):
        store = _store(args)
        root = Path(args.root) if args.root else store.root
        try:
            if args.from_source == "trace":
                if not args.trace:
                    raise CliError("--trace is required with --from trace")
                payload = extract_trace(Path(args.trace), root)
            else:
                if not args.case:
                    raise CliError("--case is required with --from postmortem")
                payload = extract_case(Path(args.case), root)
            _guard_holdout(args, payload["source"])
            sample = make_sample(payload).validate()
            result = completeness(sample, store=store, root=root)
        except (CliError, OSError, ValueError, IntakeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.dry_run:
            if args.json:
                print(json.dumps({"sample": payload, "completeness": result},
                                 ensure_ascii=False, indent=2))
            else:
                print(f"would create: {payload['id']}")
                print(f"state: {result['state']}")
                print(f"reasons: {', '.join(result['reasons']) or 'none'}")
                print(f"duplicates: {', '.join(result['duplicates']) or 'none'}")
            return 0
        try:
            created = store.new(**payload)
        except (StoreError, ContractError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"created: {created.id}")
        print(f"state: {result['state']}")
        print(f"path: {store.path_for(created.id)}")
        return 0
    if not args.id or not args.object_type or not args.source:
        print("error: manual mode requires --id, --object-type and --source", file=sys.stderr)
        return 2
    try:
        _guard_holdout(args, args.source)
    except (CliError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    expected = _json_object(args.expected, "--expected")
    rubric = _json_object(args.rubric, "--rubric")
    payload = _json_object(args.input, "--input")
    proposed = _json_object(args.proposed, "--proposed")
    try:
        sample = _store(args).new(
            id=args.id,
            object_type=args.object_type,
            origin=args.origin,
            purpose=args.purpose,
            source=args.source,
            expected=expected,
            rubric=rubric,
            input=payload,
            expected_kind=args.expected_kind,
            proposed=proposed,
            notes=args.notes,
        )
    except (StoreError, ContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created: {sample.id}")
    print(f"status: {sample.status}")
    print(f"path: {_store(args).path_for(sample.id)}")
    return 0


def cmd_sample_status(args: argparse.Namespace) -> int:
    try:
        store = _store(args)
        sample = store.require(args.id)
        root = Path(args.root) if args.root else store.root
        result = completeness(sample, store=store, root=root)
    except (StoreError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"state: {result['state']}")
        print(f"reasons: {', '.join(result['reasons']) or 'none'}")
        print(f"duplicates: {', '.join(result['duplicates']) or 'none'}")
    return 0


def cmd_sample_export_core(args: argparse.Namespace) -> int:
    try:
        path = _store(args).export_core(args.id)
    except (StoreError, ContractError, CliError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"exported: {path}")
    return 0


def cmd_sample_import_pilot(args: argparse.Namespace) -> int:
    try:
        result = import_pilot(_store(args), Path(args.tasks))
    except (OSError, ValueError, StoreError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created: {len(result['created'])}")
    print(f"skipped: {len(result['skipped'])}")
    return 0


def cmd_sample_set_answer(args: argparse.Namespace) -> int:
    expected = _json_object(args.expected, "--expected")
    rubric = _json_object(args.rubric, "--rubric")
    if args.resolution:
        expected = dict(expected or {})
        expected["resolution"] = args.resolution
    provenance = {}
    if args.confidence:
        provenance["confidence"] = args.confidence
    if args.sanitized is not None:
        provenance["sanitized"] = args.sanitized == "true"
    if args.redaction:
        provenance["redactions"] = list(args.redaction)
    try:
        sample = _store(args).set_answer(
            args.id,
            expected=expected,
            rubric=rubric,
            expected_kind=args.expected_kind,
            provenance=provenance or None,
            actor=args.actor,
            reason=args.reason or "",
        )
    except (StoreError, ContractError, CliError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"updated: {sample.id}")
    print(f"path: {_store(args).path_for(sample.id)}")
    return 0


def cmd_sample_ingest_issues(args: argparse.Namespace) -> int:
    base = _evolve_base(args)
    # 样本总在主检出（或显式 --root 的本地运行件）；ingest-state.json 是 tracked 文件，
    # 默认跟随当前检出，worktree 里跑完能提交，不会写到主检出却看不见。
    root = Path(args.root) if args.root else Path.cwd()
    try:
        source = get_source(args.source, repo=args.repo, cache=args.cache)
        quality = load_quality(Path(args.quality_file)) if args.quality_file else None
        stats = ingest_issues(
            root,
            args.repo,
            labels=args.labels,
            since=args.since,
            min_comments=args.min_comments,
            limit=args.limit,
            state_path=args.state,
            store=SampleStore(base=base),
            dry_run=args.dry_run,
            source=source,
            state_key=f"{source.source_id}/evaluation",
            holdout_numbers=issue_numbers(root),
            quality=quality,
        )
    except (AdapterError, QualityError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (StoreError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created: {stats['created']}")
    for sample_id, path in zip(stats["created_ids"], stats["created_paths"]):
        print(f"candidate: {sample_id}\t{path}")
    for sample_id in stats["would_create"]:
        print(f"would create: {sample_id}")
    print(
        "skipped: "
        f"pr={stats['skipped_pr']} "
        f"processed={stats['skipped_processed']} "
        f"label={stats['skipped_no_label']} "
        f"comments={stats['skipped_low_comments']} "
        f"title={stats['skipped_title']} "
        f"empty_body={stats['skipped_empty_body']} "
        f"short_body={stats['skipped_short_body']} "
        f"feature_title={stats['skipped_feature_title']} "
        f"duplicate_source={stats['skipped_duplicate_source']} "
        f"duplicate_id={stats['skipped_duplicate_id']}"
    )
    if stats["limit_reached"]:
        print(f"limit reached: {args.limit}")
    if args.dry_run:
        print("dry-run: no samples written, state unchanged")
    elif stats["state_updated"]:
        print(f"state: {stats['state_path']}")
    return 0


def cmd_sample_import_s2(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    try:
        stats = import_s2_samples(
            root, args.source, _store(args), limit=args.limit,
            holdout_numbers=issue_numbers(root),
        )
    except AdapterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (StoreError, ContractError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created: {stats['created']}")
    print(
        "skipped: "
        f"non_diagnostic={stats['skipped_non_diagnostic']} "
        f"no_symptoms={stats['skipped_no_symptoms']} "
        f"no_answer={stats.get('skipped_no_answer', 0)} "
        f"split={stats.get('skipped_split', 0)} "
        f"missing_issue={stats['skipped_missing_issue']} "
        f"duplicate_source={stats['skipped_duplicate_source']} "
        f"duplicate_id={stats['skipped_duplicate_id']}"
    )
    if stats["limit_reached"]:
        print(f"limit reached: {args.limit}")
    print(f"source: {stats['source']}")
    return 0


def cmd_sample_import_ixn(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    try:
        stats = import_ixn(
            _store(args), root, root / args.source, limit=args.limit,
            holdout_numbers=issue_numbers(root),
        )
    except (AdapterError, StoreError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created: {stats['created']}")
    print(f"skipped: held_out={stats['skipped_held_out']} duplicate={stats['skipped_duplicate']} missing={stats['skipped_missing']}")
    return 0


def cmd_sample_list(args: argparse.Namespace) -> int:
    try:
        samples = _store(args).list(status=args.status, origin=args.origin)
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not samples:
        print("no samples")
        return 0
    for sample in samples:
        print("\t".join([
            sample.id,
            sample.status,
            sample.origin,
            sample.purpose,
            sample.object_type,
        ]))
    print(f"total: {len(samples)}")
    return 0


def cmd_sample_check(args: argparse.Namespace) -> int:
    errors = _store(args).check(args.id)
    if errors:
        print(f"invalid: {args.id}", file=sys.stderr)
        for message in errors:
            print(f"  - {message}", file=sys.stderr)
        return 1
    print(f"ok: {args.id}")
    return 0


def cmd_sample_review(args: argparse.Namespace) -> int:
    approve = args.approve
    if approve is None:
        print("error: one of --approve/--reject is required", file=sys.stderr)
        return 2
    try:
        sample = _store(args).require(args.id)
        _guard_holdout(args, sample.source)
        sample = _store(args).review(
            args.id, approve=approve, actor=args.actor, reason=args.reason or "",
        )
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "id": sample.id, "status": sample.status},
                         ensure_ascii=False))
    else:
        print(f"{sample.id}: {sample.status}")
    return 0


def cmd_sample_promote(args: argparse.Namespace) -> int:
    try:
        current = _store(args).require(args.id)
        _guard_holdout(args, current.source)
        sample = _store(args).promote(
            args.id, to=args.to, actor=args.actor, reason=args.reason or "",
        )
        exported = None
        if args.export:
            if sample.purpose not in ("test", "regression"):
                raise StoreError("--export requires purpose=test or regression")
            exported = str(_store(args).export_core(sample.id))
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "id": sample.id, "status": sample.status,
                          "origin": sample.origin, "purpose": sample.purpose,
                          "exported": exported},
                         ensure_ascii=False))
    else:
        print(f"{sample.id}: {sample.status} ({sample.origin})")
    return 0


def cmd_sample_retire(args: argparse.Namespace) -> int:
    try:
        sample = _store(args).retire(
            args.id, actor=args.actor, reason=args.reason or "",
        )
    except (StoreError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{sample.id}: {sample.status}")
    return 0


def cmd_sample_set_purpose(args: argparse.Namespace) -> int:
    try:
        sample = _store(args).set_purpose(
            args.id, args.purpose, actor=args.actor, reason=args.reason or "",
        )
    except (StoreError, ContractError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{sample.id}: {sample.purpose}")
    return 0


def cmd_sample_absorb(args: argparse.Namespace) -> int:
    try:
        sample = _store(args).absorb(
            args.id, actor=args.actor, reason=args.reason or "",
        )
    except StoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{sample.id}: {sample.status} ({sample.purpose})")
    return 0


def cmd_sample_draw_test(args: argparse.Namespace) -> int:
    try:
        policy = _policy_for(args)
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    size = args.size if args.size is not None else policy["samples"]["test"]
    method = policy["samples"]["split"]
    try:
        samples = _store(args).draw_test(
            size=size, method=method, strata=policy["samples"].get("strata") or {},
            actor=args.actor, reason=args.reason or "",
        )
    except (StoreError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"drawn: {len(samples)}")
    print(f"size: {size} ({'policy' if args.size is None else 'explicit'})")
    print(f"split: {method} (policy)")
    strata = policy["samples"].get("strata") or {}
    if strata:
        print("strata: " + " ".join(f"{key}={value}" for key, value in sorted(strata.items())))
    for sample in samples:
        print(f"{sample.id}\t{sample.status}\t{sample.origin}\t{sample.purpose}")
    return 0


# ---------------------------------------------------------------- replay
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


# ---------------------------------------------------------------- judge
def _judge_policy(path: Optional[str]) -> Dict[str, Any]:
    if path:
        return load_policy(Path(path))
    return load_policy(None)


def _policy_for(args: argparse.Namespace) -> Dict[str, Any]:
    """策略读取顺序：显式 ``--policy`` → ``<root>/sleuth.config.yaml`` 的 evolution.policy。"""
    explicit = getattr(args, "policy", None)
    if explicit:
        return _judge_policy(explicit)
    import sleuth_config as SC
    root = Path(getattr(args, "root", None) or Path.cwd())
    try:
        config = SC.load_config(root)
        return load_config_policy(config, getattr(args, "profile", None))
    except SC.ConfigError as exc:
        raise PolicyError(str(exc)) from exc


def _decide_from_args(args: argparse.Namespace, b: int, c: int,
                      n: int) -> DecisionResult:
    """按 ``policy.decision`` 与 ``policy.cost`` 做一次二元配对判定。"""
    policy = _policy_for(args)
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


def _record_conclusion(args: argparse.Namespace, result: DecisionResult) -> Path:
    """把判定结果追加到结论记录；版本、指标与成本沿用 judge 的参数。"""
    versions = Version.from_dict(
        _yaml_or_json_object(args.versions, "--versions") or {}
    )
    metrics = _json_object(args.metrics_json, "--metrics-json") or {}
    cost = _json_object(args.cost_json, "--cost-json")
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
    store = ConclusionStore.for_base(_evolve_base(args))
    store.append(conclusion.to_dict())
    return store.path


def _finish_judge(args: argparse.Namespace, result: DecisionResult) -> int:
    _print_decision(result)
    if not args.record:
        return 0
    try:
        path = _record_conclusion(args, result)
    except (ContractError, CliError, ValueError) as exc:
        print(f"error: cannot record conclusion: {exc}", file=sys.stderr)
        return 2
    except (RecordError, OSError) as exc:
        print(f"error: cannot append conclusion: {exc}", file=sys.stderr)
        return 1
    print(f"recorded: {path}")
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    if args.record and not args.versions:
        print("error: --versions is required with --record", file=sys.stderr)
        return 2
    try:
        result = _decide_from_args(args, args.b, args.c, args.n)
    except (PolicyError, CliError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return _finish_judge(args, result)


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
        result = _decide_from_args(args, counts["b"], counts["c"], counts["n"])
    except (PolicyError, CliError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return _finish_judge(args, result)


def _print_decision(result: DecisionResult) -> None:
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


# ---------------------------------------------------------------- experiment
def cmd_store_history(args: argparse.Namespace) -> int:
    from .rsi_store import RSIStore
    try:
        if not args.experiment and not args.proposal:
            raise ValueError("pass --experiment or --proposal")
        rows = RSIStore(_evolve_base(args)).history(
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
    from .store import verify
    try:
        result = verify(_evolve_base(args))
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
    from .migrate import migrate_legacy
    try:
        result = migrate_legacy(_evolve_base(args), dry_run=args.dry_run)
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


def cmd_experiment_list(args: argparse.Namespace) -> int:
    try:
        policy = _policy_for(args)
    except PolicyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    experiment = policy.get("experiment") or {}
    configured_target = experiment.get("target", "skill")
    configured = experiment.get("algorithm", "baseline")
    print(f"configured_target: {configured_target}")
    for tid in target_ids():
        spec = get_target(tid)
        profile = resolve_evaluator(tid)[1]
        marker = "*" if tid == configured_target else " "
        print(
            f"{marker} target {tid}\t{spec.eval_profile_id}\t"
            f"eval_ready={profile.implemented}\t{spec.authority}\t{spec.allowed_algorithms}"
        )
    for name in algorithm_ids():
        algorithm = get_algorithm(name)
        marker = "*" if name == configured else " "
        print(f"{marker} {name}\t{getattr(algorithm, 'version', '')}\t{getattr(algorithm, 'scope', '')}")
    return 0


def _agent_draft_patch(path: str, target_override=None, component_override=None,
                       summary_override=None, seed: int = 0) -> "Patch":
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ProposalError("draft must be an object")
    if component_override:
        data["target_component"] = component_override
    if summary_override:
        data["summary"] = summary_override
    patch = validate_draft(data, target_override=target_override)
    patch.seed = seed
    return patch


def cmd_experiment_flow(args: argparse.Namespace) -> int:
    try:
        policy = _policy_for(args)
        draft = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
        archive_path = Path(args.archive) if args.archive else _evolve_base(args) / "proposals.jsonl"
        archive = ProposalArchive(archive_path)
        engine = ProposalEngine(archive)
        proposal = engine.add(draft)
        if proposal.status == "invalid":
            raise FlowError("; ".join(proposal.errors))
        if not args.dry_run and not args.judge:
            raise FlowError("--judge is required unless --dry-run")
        command = stage_load_argv(args.runner_command) if args.runner_command else None
        result = run_proposal(
            Path(args.root), proposal, args.samples, Path(args.output), policy,
            Path(args.judge) if args.judge else None, archive,
            runner=(lambda tasks: stage_run(Path(args.output), command))
            if command else None,
            baseline_traces=Path(args.baseline_traces) if args.baseline_traces else None,
            reuse_index=args.reuse_index,
            exploratory=args.exploratory,
            card=args.card,
            dry_run=args.dry_run,
        )
    except (FlowError, ProposalError, OSError, ValueError, PolicyError, PilotError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "proposal": proposal.id,
        "decision": result["decision"],
        "conclusion": result["conclusion"],
        "archive": str(archive_path),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_experiment_search(args: argparse.Namespace) -> int:
    try:
        scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
        if not isinstance(scenario, dict):
            raise ProposalError("scenario must be an object")
        target = str(scenario.get("target_kind") or "")
        component = str(scenario.get("target_component") or "")
        samples = scenario.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ProposalError("scenario.samples must be a non-empty list")
        candidates = scenario.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProposalError("scenario.candidates must be a non-empty list")
        policy = {"best": BestPolicy, "pareto": ParetoPolicy, "gepa": GepaPolicy}[args.policy]()
        archive = ProposalArchive(Path(args.archive) if args.archive
                                  else _evolve_base(args) / "proposals.jsonl")
        engine = ProposalEngine(archive)
        for item in candidates:
            draft = item.get("draft") if isinstance(item, dict) else None
            if not isinstance(draft, dict):
                raise ProposalError("candidate.draft is required")
            if draft.get("target_kind") and draft["target_kind"] != target:
                raise ProposalError("draft target_kind does not match scenario")
            draft.setdefault("target_kind", target)
            draft.setdefault("target_component", component)
            proposal = engine.add(draft)
            if proposal.status != "invalid" and isinstance(item.get("scores"), dict):
                engine.evaluate(proposal, item["scores"], item.get("feedback"))
        selected = policy.choose(engine.proposals, list(samples), [])
    except (ProposalError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "policy": policy.id,
        "proposals": [p.to_dict() for p in engine.proposals],
        "selected": selected.to_dict() if selected else None,
        "archive": str(archive.path),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_experiment_request(args: argparse.Namespace) -> int:
    try:
        policy = _policy_for(args)
        target = args.target or ((policy.get("experiment") or {}).get("target") or "skill")
        evidence = None
        if args.evidence:
            evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
        constraints = _json_object(args.constraints, "constraints") or {}
        result = proposal_request(target, args.component, evidence=evidence,
                                  constraints=constraints)
    except (ProposalError, OSError, ValueError, json.JSONDecodeError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_experiment_propose(args: argparse.Namespace) -> int:
    try:
        policy = _policy_for(args)
        experiment = policy.get("experiment") or {}
        target = args.target or experiment.get("target", "skill")
        algorithm = args.algorithm or experiment.get("algorithm", "baseline")
        budget = _json_object(args.budget, "budget")
        if budget is None:
            budget = experiment.get("budget") or {}
        seed = args.seed if args.seed is not None else experiment.get("seed", 0)
        if args.draft:
            patch = _agent_draft_patch(args.draft, target_override=args.target,
                                       component_override=args.component,
                                       summary_override=args.summary, seed=seed)
            patch.validate()
            execution = "subagent"
        else:
            spec, optimizer = resolve_optimizer(target, algorithm)
            patch = optimizer.propose(target, [], None, budget)
            if args.component:
                patch.target_component = args.component
            if args.summary:
                patch.summary = args.summary
            patch.seed = seed
            patch.validate()
            execution = getattr(optimizer, "execution", "manual")
        profile = resolve_evaluator(patch.target_kind)[1]
        record = asdict(patch)
        record["execution"] = execution
        record["source"] = "agent_draft" if args.draft else "algorithm"
        record["eval_profile_id"] = profile.id
        record["eval_gate"] = profile.gate
        record["eval_ready"] = profile.implemented
        record["autonomy"] = resolve_autonomy(policy, patch.target_component)
        record["at"] = now_iso()
        ExperimentStore.for_base(_evolve_base(args)).append(record)
    except (PolicyError, AdapterError, StoreError, RecordError, ContractError, ValueError, TypeError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: cannot write experiment record: {exc}", file=sys.stderr)
        return 1
    print(f"target: {patch.target_kind}")
    print(f"component: {patch.target_component}")
    print(f"autonomy: {record['autonomy']}")
    print(f"algorithm: {patch.algorithm}")
    print(f"summary: {patch.summary}")
    eval_ready = resolve_evaluator(patch.target_kind)[1].implemented
    print(f"eval_profile_id: {resolve_evaluator(target)[1].id}")
    print(f"eval_ready: {eval_ready}")
    if not eval_ready:
        print(
            "warning: target evaluator is not implemented; Patch recorded but not gate-ready",
            file=sys.stderr,
        )
    print(f"recorded: {ExperimentStore.for_base(_evolve_base(args)).path}")
    return 0


def cmd_experiment_record(args: argparse.Namespace) -> int:
    try:
        raw = _yaml_or_json_object(args.file, "--file")
        if raw is None:
            raise ExperimentError("--file is required")
        record = validate_experiment(raw)
        record["at"] = now_iso()
        ExperimentStore.for_base(_evolve_base(args)).append(record)
    except (ExperimentError, PolicyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (RecordError, OSError) as exc:
        print(f"error: cannot write experiment record: {exc}", file=sys.stderr)
        return 1
    print(f"recorded: {record['target_kind']} {record['target_component']}")
    print(f"decision: {record['decision']}")
    print(f"baseline: {record['baseline']['score']:.4f}")
    print(f"candidate: {record['candidate']['score']:.4f}")
    return 0


def cmd_experiment_show(args: argparse.Namespace) -> int:
    try:
        base = _evolve_base(args)
        rows = [row for row in ExperimentStore.for_base(base).read()
                if row.get("proposal") == args.proposal]
        events = RSIStore(base).history(proposal_id=args.proposal)
        proposal = ProposalArchive(base / "proposals.jsonl").latest(args.proposal)
        conclusion = latest_by_proposal(args.proposal, base)
        if proposal is None:
            for event in events:
                if event.get("kind") == "proposal":
                    proposal = (event.get("data") or {}).get("proposal")
                    break
                if event.get("kind") == "experiment":
                    proposal = (event.get("data") or {}).get("proposal")
                    if proposal:
                        break
        if conclusion is None:
            for event in events:
                if event.get("kind") == "decision":
                    conclusion = (event.get("data") or {}).get("conclusion")
                    break
                if event.get("kind") == "experiment":
                    conclusion = (event.get("data") or {}).get("conclusion")
                    if conclusion:
                        break
        if not rows:
            rows = [(event.get("data") or {}).get("experiment") for event in events
                    if event.get("kind") == "experiment"]
            rows = [row for row in rows if row]
        if proposal is None:
            print(f"error: no proposal {args.proposal}", file=sys.stderr)
            return 1
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "proposal": proposal,
        "conclusion": conclusion,
        "experiments": rows,
        "history": events,
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_experiment_records(args: argparse.Namespace) -> int:
    try:
        records = ExperimentStore.for_base(_evolve_base(args)).read()
    except RecordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    limit = args.limit if args.limit and args.limit > 0 else 10
    print(f"experiments: {len(records)}")
    for record in records[-limit:]:
        scores = ""
        if isinstance(record.get("baseline"), dict) and isinstance(record.get("candidate"), dict):
            scores = (
                f" baseline={record['baseline'].get('score')} "
                f"candidate={record['candidate'].get('score')} "
                f"decision={record.get('decision')}"
            )
        print(
            f"{record.get('at', '')} {record.get('target_kind', '')} "
            f"{record.get('target_component', '')} {record.get('algorithm', '')} "
            f"execution={record.get('execution')} "
            f"eval_ready={record.get('eval_ready')} "
            f"profile={record.get('eval_profile_id')} "
            f"proposal={record.get('proposal') or ''}{scores}"
        )
    return 0


def cmd_experiment_gate(args: argparse.Namespace) -> int:
    try:
        spec, profile = resolve_evaluator(args.target)
        if not profile.implemented:
            raise ValueError(
                f"target {args.target!r} has no implemented evaluator ({profile.id})"
            )
        if profile.id == "arena":
            if not args.baseline or not args.candidate or not args.component:
                raise ValueError("arena gate requires --baseline, --candidate and --component")
            command = [sys.executable, str(Path(args.root or ".") / "scripts" / "eval_arena.py"),
                       "--gate", "--baseline", args.baseline, "--candidate", args.candidate,
                       "--component", args.component, "--alpha", str(args.alpha),
                       "--root", str(Path(args.root or "."))]
            if args.candidate_ref:
                command += ["--candidate-ref", args.candidate_ref]
            if args.note:
                command += ["--note", args.note]
            return subprocess.run(command, cwd=str(Path(args.root or "."))).returncode
        if profile.id == "replay_trace":
            if not args.baseline or not args.candidate:
                raise ValueError("replay_trace gate requires --baseline and --candidate")
            result = compare_tool_usage(_read_json(args.baseline), _read_json(args.candidate))
            print(f"target: {spec.id}")
            print(f"eval_profile: {profile.id}")
            print(f"decision: {result['decision']}")
            print(f"reasons: {', '.join(result['reasons']) or 'none'}")
            print(json.dumps(result["deltas"], ensure_ascii=False, sort_keys=True))
            return 0 if result["decision"] == "accept" else 1
        if profile.id != "rubric":
            raise ValueError(
                f"target {args.target!r} uses {profile.id}; no gate wired for it"
            )
        if not args.sample or not args.scores:
            raise ValueError("rubric gate requires --sample and --scores")
        sample = _store(args).require(args.sample)
        if sample.object_type not in profile.object_types:
            raise ValueError(
                f"sample {sample.id!r} object_type {sample.object_type!r} is not "
                f"in target {args.target!r} ({', '.join(profile.object_types)})"
            )
        if sample.rubric is None:
            raise ValueError(f"sample {sample.id!r} has no rubric")
        policy = _policy_for(args)
        threshold = (policy.get("rubrics") or {}).get("threshold")
        scores = _json_object(args.scores, "--scores")
        result = score_rubric(sample.rubric, scores, threshold=threshold)
    except (ValueError, RubricError, CliError, StoreError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"target: {spec.id}")
    print(f"eval_profile: {profile.id}")
    print(f"passed: {str(result.passed).lower()}")
    print(f"score: {result.score:.4f}" if result.score is not None else "score: unavailable")
    print(f"threshold: {result.threshold:.4f}")
    if result.failed_dimensions:
        print("failed_dimensions: " + ", ".join(result.failed_dimensions))
    if result.missing:
        print("missing: " + ", ".join(result.missing))
    return 0 if result.passed else 1


def cmd_experiment_resolve(args: argparse.Namespace) -> int:
    try:
        spec, optimizer = resolve_optimizer(args.target, args.algorithm)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"target: {spec.id}")
    print(f"algorithm: {getattr(optimizer, 'id', args.algorithm or spec.default_algorithm)}")
    print(f"version: {getattr(optimizer, 'version', '')}")
    print(f"scope: {getattr(optimizer, 'scope', '')}")
    profile = resolve_evaluator(spec.id)[1]
    print(f"eval_profile: {spec.eval_profile}")
    print(f"eval_profile_id: {profile.id}")
    print(f"eval_label: {profile.label}")
    print(f"eval_gate: {profile.gate}")
    print(f"eval_object_types: {', '.join(profile.object_types)}")
    print(f"eval_ready: {profile.implemented}")
    print(f"authority: {spec.authority}")
    return 0


# ---------------------------------------------------------------- run
def cmd_run(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    base = _evolve_base(args)
    try:
        policy = _policy_for(args)
        trace = trace_status(base / "trace-state.json")
        plan = issue_plan(root, base, policy, metrics=load_metrics(root), trace_state=trace)
    except (PolicyError, StoreError, RecordError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_plan(plan))
    return 0


# ---------------------------------------------------------------- rsi
def cmd_rsi_plan(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    try:
        metrics = load_metrics(root)
        policy = _policy_for(args)
        plan = build_plan(
            root,
            trace_state=Path(args.trace_state) if args.trace_state else (_evolve_base(args) / "trace-state.json"),
            replay=Path(args.replay) if args.replay else None,
            metrics=metrics,
            holdout_numbers=issue_numbers(root),
            stages_config=(policy.get("experiment") or {}).get("stages"),
        )
        state = Path(args.state) if args.state else _evolve_base(args) / "rsi-plan.json"
        save_plan(plan, state)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"rsi_status: {plan['status']}")
        print(f"snapshot_id: {plan['snapshot_id']}")
        for name, source in plan["sources"].items():
            print(f"source {name}: available={source.get('available')} snapshot={source.get('snapshot_id')}")
        for region in plan.get("regions") or []:
            print(f"region: {region['region']} hard={region['hard']} events={region['events']}")
        if plan.get("experiment"):
            spec = plan["experiment"]
            print(f"experiment: target={spec['target_skill']} region={spec['mutable_region']}")
        print(f"stages: {plan['stages']}")
    return 0


def _load_plan(path: Path) -> dict:
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_rsi_attribute(args: argparse.Namespace) -> int:
    try:
        path = Path(args.state)
        plan = _load_plan(path)
        payload = _yaml_or_json_object(args.file, "--file")
        plan = apply_attribution(plan, payload)
        save_plan(plan, path)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"updated: {path}")
    print("stage: attribute.agent")
    return 0


def cmd_rsi_select(args: argparse.Namespace) -> int:
    try:
        path = Path(args.state)
        plan = _load_plan(path)
        payload = _yaml_or_json_object(args.file, "--file")
        plan = apply_selection(plan, payload)
        save_plan(plan, path)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"updated: {path}")
    print("stage: select.region_agent")
    return 0


def _read_json(path: str) -> Any:
    import json
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_knowledge_usage_evaluate(args: argparse.Namespace) -> int:
    try:
        result = evaluate_usage(_read_json(args.file))
    except (OSError, ValueError, UsageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"samples: {result['n']}")
        print(f"hit_rate: {result['hit_rate']:.3f}")
        print(f"wrong_cases: {result['wrong_cases']}")
    return 0


def _where_pairs(values):
    pairs = {}
    for raw in values or []:
        if "=" not in raw:
            raise ValueError(f"--where expects key=value, got {raw!r}")
        key, value = raw.split("=", 1)
        if not key:
            raise ValueError(f"--where expects key=value, got {raw!r}")
        pairs[key] = value
    return pairs


def cmd_stage_plan(args: argparse.Namespace) -> int:
    try:
        tasks = stage_plan(
            Path(args.root), args.stage, Path(args.output), _policy_for(args),
            limit=args.limit, full=args.full,
            candidate_path=Path(args.candidate) if args.candidate else None,
            baseline_traces=Path(args.baseline_traces) if args.baseline_traces else None,
            where=_where_pairs(args.where),
        )
    except (StageError, OSError, ValueError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(tasks, ensure_ascii=False, indent=2))
    return 0


def cmd_stage_run(args: argparse.Namespace) -> int:
    try:
        result = stage_run(Path(args.output), stage_load_argv(args.command),
                           timeout=args.timeout,
                           judge_path=Path(args.judge) if args.judge else None)
    except (StageError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_stage_judge(args: argparse.Namespace) -> int:
    try:
        calibration = None
        if args.calibration:
            calibration = json.loads(Path(args.calibration).read_text(encoding="utf-8"))
        result = stage_judge(Path(args.output), agent=args.agent,
                             timeout=args.timeout, calibration=calibration)
    except (StageError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_stage_report(args: argparse.Namespace) -> int:
    try:
        policy = _policy_for(args)
        result = stage_report(Path(args.output), args.stage, Path(args.judge), policy,
                              card=args.card, update_stage=args.update_stage)
    except (StageError, OSError, ValueError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if (result.get("passed", True) and
                 (result.get("decision") or {}).get("conclusion", {}).get("decision") != "reject") else 1


def cmd_benchmark(args: argparse.Namespace) -> int:
    try:
        policy = _policy_for(args)
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


def cmd_pilot_prepare(args: argparse.Namespace) -> int:
    try:
        result = pilot_prepare(Path(args.root), Path(args.candidate), args.samples,
                               Path(args.output), policy=_policy_for(args),
                               baseline_traces=(Path(args.baseline_traces)
                                                if args.baseline_traces else None))
    except (OSError, ValueError, PilotError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_pilot_collect(args: argparse.Namespace) -> int:
    try:
        result = pilot_collect(Path(args.output), judge=Path(args.judge) if args.judge else None)
    except (OSError, ValueError, PilotError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


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
        base = _evolve_base(args)
        if args.proposal:
            record = latest_by_proposal(args.proposal, base)
            if record is None:
                from .rsi_store import RSIStore
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


def cmd_pilot_checkpoint(args: argparse.Namespace) -> int:
    try:
        policy = _policy_for(args)
        result = pilot_checkpoint(Path(args.output), Path(args.judge), policy,
                                  reuse_index=args.reuse_index)
    except (OSError, ValueError, PilotError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["stop"] else 0


def cmd_pilot_decide(args: argparse.Namespace) -> int:
    try:
        policy = _policy_for(args)
        result = pilot_decide(Path(args.output), Path(args.judge), policy,
                              reuse_index=args.reuse_index, pool=args.pool,
                              card=args.card)
    except (OSError, ValueError, PilotError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_tool_usage_from_trace(args: argparse.Namespace) -> int:
    try:
        document = yaml.safe_load(Path(args.trace).read_text(encoding="utf-8"))
        resolved = None if args.resolved is None else args.resolved == "true"
        result = tool_from_trace(document, resolved=resolved)
    except (OSError, ValueError, yaml.YAMLError, ToolUsageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"sample_id: {result['sample_id']}")
        print(f"tool_calls: {result['tool_calls']} fetch: {result['fetch_calls']} "
              f"grep: {result['grep_calls']} retries: {result['retries']}")
    return 0


def cmd_tool_usage_evaluate(args: argparse.Namespace) -> int:
    try:
        result = evaluate_tool_usage(_read_json(args.file))
    except (OSError, ValueError, ToolUsageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_tool_usage_compare(args: argparse.Namespace) -> int:
    try:
        result = compare_tool_usage(_read_json(args.baseline), _read_json(args.candidate))
    except (OSError, ValueError, ToolUsageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_candidate_validate(args: argparse.Namespace) -> int:
    try:
        candidate = validate_candidate(_read_json(args.file))
    except (OSError, ValueError, CandidateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(candidate, ensure_ascii=False, indent=2))
    return 0


def cmd_candidate_apply(args: argparse.Namespace) -> int:
    try:
        candidate = validate_candidate(_read_json(args.candidate))
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


def cmd_source_usage_from_trace(args: argparse.Namespace) -> int:
    try:
        document = yaml.safe_load(Path(args.trace).read_text(encoding="utf-8"))
        source_ok = None if args.source_ok is None else args.source_ok == "true"
        result = source_from_trace(document, source_ok=source_ok)
    except (OSError, ValueError, yaml.YAMLError, SourceUsageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"sample_id: {result['sample_id']}")
        print(f"files_read: {result['files_read']} tool_calls: {result['tool_calls']}")
    return 0


def cmd_source_usage_evaluate(args: argparse.Namespace) -> int:
    try:
        result = evaluate_source_usage(_read_json(args.file))
    except (OSError, ValueError, SourceUsageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_source_usage_compare(args: argparse.Namespace) -> int:
    try:
        result = compare_source_usage(_read_json(args.baseline), _read_json(args.candidate))
    except (OSError, ValueError, SourceUsageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_knowledge_usage_from_trace(args: argparse.Namespace) -> int:
    try:
        document = yaml.safe_load(Path(args.trace).read_text(encoding="utf-8"))
        result = from_trace(document, expected_case=args.expected_case)
    except (OSError, ValueError, yaml.YAMLError, UsageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"sample_id: {result['sample_id']}")
        print(f"hit: {result['hit']} first_hit_step={result['first_hit_step']}")
    return 0


def cmd_knowledge_usage_compare(args: argparse.Namespace) -> int:
    try:
        result = compare_usage(_read_json(args.baseline), _read_json(args.candidate))
    except (OSError, ValueError, UsageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"decision: {result['decision']}")
        print(f"reasons: {', '.join(result['reasons']) or 'none'}")
        print(f"baseline hit_rate: {result['baseline']['hit_rate']:.3f}")
        print(f"candidate hit_rate: {result['candidate']['hit_rate']:.3f}")
    return 0


def cmd_rsi_status(args: argparse.Namespace) -> int:
    path = Path(args.state)
    try:
        print(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------- traces
def cmd_traces_sync(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    state = Path(args.state) if args.state else _evolve_base(args) / "trace-state.json"
    try:
        stats = trace_sync(root, state, source_id=args.source_id)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({k: v for k, v in stats.items() if k != "attributions"},
                         ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"traces: {stats['traces']} new={stats['new']} changed={stats['changed']} reused={stats['reused']}")
        print(f"events: {stats['events']}")
        for region in stats.get("regions") or []:
            print(f"region: {region['region']} hard={region['hard']} events={region['events']}")
        if stats.get("experiment"):
            spec = stats["experiment"]
            print(f"experiment: target={spec['target_skill']} region={spec['mutable_region']}")
        print(f"snapshot_id: {stats['snapshot_id']}")
        print(f"state: {stats['state_path']}")
    return 0


def cmd_traces_status(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    state = Path(args.state) if args.state else _evolve_base(args) / "trace-state.json"
    try:
        payload = trace_status(state)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


# ---------------------------------------------------------------- health
def cmd_health(args: argparse.Namespace) -> int:
    payload = health_metrics(Path(args.root) if args.root else Path.cwd())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        if not payload.get("available"):
            print(f"metrics_health: unavailable ({payload.get('error', 'unknown')})")
        else:
            print(f"metrics_health: {payload.get('check_verdict', 'unknown')}")
            print(f"fail_count: {payload.get('fail_count', 0)}")
            for finding in (payload.get("findings") or [])[:5]:
                print(f"- {finding.get('face', '')}: {finding.get('text', '')}")
            for item in payload.get("broken") or []:
                print(f"- broken: {item}")
    if not payload.get("available"):
        return 1
    if args.check:
        if payload.get("broken"):
            return 2
        if int(payload.get("fail_count") or 0) > 0:
            return 1
    return 0


# ---------------------------------------------------------------- brief
def _format_counts(counts: Dict[str, int]) -> str:
    if not counts:
        return "none"
    return " ".join(f"{key}={counts[key]}" for key in sorted(counts))


def _metric_value(value: Any) -> str:
    return "unavailable" if value is None else str(value)


def cmd_brief(args: argparse.Namespace) -> int:
    base = _evolve_base(args)
    store = SampleStore(base=base)
    try:
        policy = _policy_for(args)
        counts = store.counts()
        conclusions = ConclusionStore.for_base(base).read()
    except (StoreError, RecordError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        plan = issue_plan(
            Path(args.root) if args.root else Path.cwd(), base, policy,
            metrics=load_metrics(Path(args.root) if args.root else Path.cwd()),
            trace_state=trace_status(base / "trace-state.json"),
        )
    except (StoreError, RecordError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    plan_counts = plan["counts"]
    metrics = plan.get("metrics") or {}
    period = metrics.get("latest_period")
    print(f"policy_hash: {policy_hash(policy)}")
    print(f"target: {(policy.get('experiment') or {}).get('target', 'skill')}")
    timeline = metrics.get("timeline") or {}
    print(
        f"metrics_period: {period.get('period') if period and timeline.get('available') else 'unavailable'}"
    )
    freshness = metrics.get("freshness") or {}
    parts = []
    for key in ("live", "structural"):
        item = freshness.get(key) or {}
        age = item.get("age_days")
        status = "missing" if not item.get("available") else (
            "stale" if item.get("stale") else "fresh"
        )
        parts.append(f"{key}={status}" + (f"({age}d)" if age is not None else ""))
    print("metrics_freshness: " + " ".join(parts))
    print(f"sessions_total: {_metric_value(metrics.get('sessions_total'))}")
    print(f"tier2_hit: {_metric_value(metrics.get('tier2_hit'))}")
    print(f"case_total: {_metric_value(metrics.get('case_total'))}")
    print(f"feedback: {_metric_value(metrics.get('feedback'))}")
    for key, value in sorted((plan_counts.get("strata") or {}).items()):
        print(
            f"stratum: {key} field_eval={value.get('field_eval', 0)} "
            f"core_test={value.get('core_test', 0)} target={value.get('target', 0)}"
        )
    last_exec = (metrics.get("last_skill_exec") or {}).get("last") \
        if isinstance(metrics.get("last_skill_exec"), dict) else None
    if last_exec:
        print(f"last_skill_exec: {last_exec.get('skill')} {last_exec.get('at')}")
    else:
        print("last_skill_exec: unavailable")
    entry = metrics.get("entry_usage") or {}
    if isinstance(entry, dict) and entry.get("available"):
        print(
            f"entry_usage: cases={_metric_value(entry.get('cases'))} "
            f"active={_metric_value(entry.get('active_cases'))} "
            f"references={_metric_value(entry.get('references'))}"
        )
    else:
        print("entry_usage: unavailable")
    print(f"trace_snapshot: {plan.get('trace_snapshot') or 'unavailable'}")
    print(f"samples: {counts['total']}")
    print(f"by_status: {_format_counts(counts['status'])}")
    print(f"by_origin: {_format_counts(counts['origin'])}")
    print(f"by_purpose: {_format_counts(counts['purpose'])}")
    print(f"candidate: {plan_counts['candidate']}")
    print(f"field: {plan_counts['field']}")
    print(f"test: {plan_counts['test']}")
    cost_plan = plan.get("cost_plan") or {}
    if cost_plan:
        print("cost_plan: " + ", ".join(f"{key}={value}" for key, value in cost_plan.items()))
    print(f"conclusions: {len(conclusions)}")
    try:
        proposals = ProposalArchive(_evolve_base(args) / "proposals.jsonl").read()
    except (OSError, ValueError):
        proposals = []
    try:
        experiments = ExperimentStore.for_base(_evolve_base(args)).read()
    except (OSError, ValueError):
        experiments = []
    try:
        from .rsi_store import RSIStore
        events = RSIStore(_evolve_base(args)).read()
    except (OSError, ValueError):
        events = []
    event_proposals = [event["data"]["proposal"] for event in events
                       if event.get("kind") == "proposal" and isinstance(event.get("data"), dict)
                       and isinstance(event["data"].get("proposal"), dict)]
    event_experiments = [
        {**event["data"]["experiment"], "proposal": event.get("proposal_id")}
        for event in events
        if event.get("kind") == "experiment" and isinstance(event.get("data"), dict)
        and isinstance(event["data"].get("experiment"), dict)
    ]
    if event_proposals:
        proposals = event_proposals
    if event_experiments:
        experiments = event_experiments
    print(f"events: {len(events)}")
    print(f"proposals: {len(proposals)}")
    if proposals:
        last = proposals[-1]
        print(f"last proposal: {last.get('status', '')} {last.get('target', '')} {last.get('id', '')}")
    print(f"experiments: {len(experiments)}")
    if experiments:
        last = experiments[-1]
        print(f"last experiment: {last.get('decision', '')} "
              f"{last.get('target_kind', '')} proposal={last.get('proposal') or ''}")
    capacity = plan.get("judgment_capacity") or {}
    print(f"judgment_capacity: pool_samples={capacity.get('potential', 0)} "
          f"required_b={capacity.get('required_b', 0)} "
          f"alpha={capacity.get('alpha', 0)}")
    for record in conclusions[-3:]:
        decision = record.get("decision", "unknown")
        reason = record.get("reason", "")
        print(f"last conclusion: {decision} {reason}".rstrip())
    print("next_actions:")
    for action in plan["next_actions"]:
        print(f"- {action}")
    return 0


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="自演进评估循环：策略、样本队列、判定与读数（v1）。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    policy = sub.add_parser("policy", help="策略文件检查/展示")
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
    sample = sub.add_parser("sample", help="样本队列与生命周期")
    sample_sub = sample.add_subparsers(dest="sample_command", required=True)

    new = sample_sub.add_parser("new", help="创建候选样本")
    new.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    new.add_argument("--from", dest="from_source", default=None,
                     choices=("trace", "postmortem"),
                     help="从已闭环的诊断 trace 或 case YAML 生成候选")
    new.add_argument("--trace", default=None, help="--from trace 的 trace 路径")
    new.add_argument("--case", default=None, help="--from postmortem 的 case YAML 路径")
    new.add_argument("--dry-run", action="store_true", help="只打印完整性与查重，不写盘")
    new.add_argument("--json", action="store_true", help="--dry-run 输出 JSON")
    new.add_argument("--id", default=None)
    new.add_argument("--object-type", default=None, choices=OBJECT_TYPE_VALUES)
    new.add_argument("--origin", default="field", choices=ORIGINS)
    new.add_argument("--purpose", default="evaluation", choices=PURPOSES)
    new.add_argument("--source", default=None)
    new.add_argument("--expected", default=None, help="JSON 对象")
    new.add_argument("--rubric", default=None, help="JSON 对象")
    new.add_argument("--input", default=None, help="JSON 对象")
    new.add_argument("--expected-kind", default=None, choices=("resolution", "assertion", "rubric"))
    new.add_argument("--proposed", default=None, help="JSON 对象（候选的待确认字段）")
    new.add_argument("--notes", default=None)
    new.set_defaults(func=cmd_sample_new)

    import_pilot_p = sample_sub.add_parser("import-pilot", help="把一次 pilot 的样本注册进队列")
    import_pilot_p.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    import_pilot_p.add_argument("--tasks", required=True)
    import_pilot_p.set_defaults(func=cmd_sample_import_pilot)
    set_answer = sample_sub.add_parser("set-answer", help="给 candidate/active 补 expected/rubric")
    set_answer.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    set_answer.add_argument("--id", required=True)
    set_answer.add_argument("--expected", default=None, help="JSON 对象")
    set_answer.add_argument("--rubric", default=None, help="JSON 对象")
    set_answer.add_argument("--expected-kind", default=None,
                            choices=("resolution", "assertion", "rubric"))
    set_answer.add_argument("--resolution", default=None,
                            help="直接写根因与修复，免拼 JSON")
    set_answer.add_argument("--confidence", default=None,
                            choices=("issue-verified", "maintainer-reviewed", "agent-reviewed"))
    set_answer.add_argument("--sanitized", default=None, choices=("true", "false"))
    set_answer.add_argument("--redaction", action="append", default=None,
                            help="脱敏项，可重复")
    set_answer.add_argument("--actor", default="maintainer")
    set_answer.add_argument("--reason", default="")
    set_answer.set_defaults(func=cmd_sample_set_answer)
    status = sample_sub.add_parser("status", help="看一条候选样本的完整性与查重")
    status.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    status.add_argument("--id", required=True)
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_sample_status)
    export_core = sample_sub.add_parser("export-core", help="把 active/core 样本写入 tracked eval/core")
    export_core.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    export_core.add_argument("--id", required=True)
    export_core.set_defaults(func=cmd_sample_export_core)

    import_s2 = sample_sub.add_parser(
        "import-s2", help="把 eval/s2 校准集导入候选队列（跳过非诊断/无症状/重复来源）"
    )
    import_s2.add_argument("--root", default=None,
                           help="校准集根目录（默认当前目录；样本仍默认锚主检出）")
    import_s2.add_argument("--source", required=True,
                           help="校准集路径，如 eval/s2/vllm-ascend.yaml")
    import_s2.add_argument("--limit", type=int, default=None,
                           help="最多创建多少条候选（默认不限）")
    import_s2.set_defaults(func=cmd_sample_import_s2)

    ingest = sample_sub.add_parser(
        "ingest-issues", help="从 GitHub issue 建诊断候选（先过滤，按需取 body）"
    )
    ingest.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    ingest.add_argument("--source", default="github",
                        help="issue 源（默认 github；已注册 github/local）")
    ingest.add_argument("--cache", default=None, help="local 源的 JSON/YAML issue 导出路径")
    ingest.add_argument("--repo", required=True, help="如 vllm-project/vllm-ascend")
    ingest.add_argument("--labels", default=None, help="逗号分隔 label 池")
    ingest.add_argument("--since", default=None, help="ISO 时间，增量拉取")
    ingest.add_argument("--min-comments", type=int, default=3)
    ingest.add_argument("--limit", type=int, default=20, help="最多创建多少条候选")
    ingest.add_argument("--state", default="ingest-state.json", help="ingest-state.json 路径")
    ingest.add_argument("--dry-run", action="store_true", help="只打印候选，不写库/不更新 state")
    ingest.add_argument("--quality-file", default=None,
                        help="agent 产出的 issue 质量/答案 JSON；低于阈值直接跳过")
    ingest.set_defaults(func=cmd_sample_ingest_issues)

    ixn = sample_sub.add_parser("import-ixn", help="导入 ixn-arena 非 held_out gold 样本")
    ixn.add_argument("--root", default=None)
    ixn.add_argument("--source", default="eval/ixn-arena")
    ixn.add_argument("--limit", type=int, default=None)
    ixn.set_defaults(func=cmd_sample_import_ixn)

    listing = sample_sub.add_parser("list", help="列出样本")
    listing.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    listing.add_argument("--status", default=None, choices=STATUSES)
    listing.add_argument("--origin", default=None, choices=ORIGINS)
    listing.set_defaults(func=cmd_sample_list)

    check_cmd = sample_sub.add_parser("check", help="复核一条样本")
    check_cmd.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    check_cmd.add_argument("--id", required=True)
    check_cmd.set_defaults(func=cmd_sample_check)

    review = sample_sub.add_parser("review", help="维护者复核候选")
    review.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    review.add_argument("--id", required=True)
    verdict = review.add_mutually_exclusive_group(required=True)
    verdict.add_argument("--approve", dest="approve", action="store_true")
    verdict.add_argument("--reject", dest="approve", action="store_false")
    review.add_argument("--actor", default="maintainer")
    review.add_argument("--reason", default="")
    review.add_argument("--json", action="store_true")
    review.set_defaults(func=cmd_sample_review)

    promote = sample_sub.add_parser("promote", help="active/field → active/core（origin 转换）")
    promote.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    promote.add_argument("--id", required=True)
    promote.add_argument("--to", required=True, choices=("core",))
    promote.add_argument("--actor", default="maintainer")
    promote.add_argument("--reason", default="")
    promote.add_argument("--export", action="store_true",
                         help="升 core 后立即写入 tracked eval/core（仅 test/regression）")
    promote.add_argument("--json", action="store_true")
    promote.set_defaults(func=cmd_sample_promote)

    retire = sample_sub.add_parser("retire", help="active（field/core origin）→ retired")
    retire.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    retire.add_argument("--id", required=True)
    retire.add_argument("--actor", default="maintainer")
    retire.add_argument("--reason", default="")
    retire.set_defaults(func=cmd_sample_retire)

    set_purpose = sample_sub.add_parser("set-purpose", help="active 样本改 purpose")
    set_purpose.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    set_purpose.add_argument("--id", required=True)
    set_purpose.add_argument("--purpose", required=True, choices=PURPOSES)
    set_purpose.add_argument("--actor", default="maintainer")
    set_purpose.add_argument("--reason", default="")
    set_purpose.set_defaults(func=cmd_sample_set_purpose)

    absorb = sample_sub.add_parser("absorb", help="答案进库：转 regression 或使 test 退休")
    absorb.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    absorb.add_argument("--id", required=True)
    absorb.add_argument("--actor", default="maintainer")
    absorb.add_argument("--reason", default="")
    absorb.set_defaults(func=cmd_sample_absorb)

    draw = sample_sub.add_parser("draw-test", help="从 active/core/evaluation 抽 test")
    draw.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    draw.add_argument("--size", type=int, default=None,
                      help="抽几条（默认读 policy.samples.test）")
    draw.add_argument("--policy", default=None, help="策略文件路径（默认 sleuth.config.yaml 的 evolution.policy）")
    draw.add_argument("--actor", default="maintainer")
    draw.add_argument("--reason", default="")
    draw.set_defaults(func=cmd_sample_draw_test)

    stage = sub.add_parser("stage", help="test / regression 的通用 runner")
    stage_sub = stage.add_subparsers(dest="stage_command", required=True)
    s_plan = stage_sub.add_parser("plan", help="生成 stage 任务")
    s_plan.add_argument("--stage", required=True, choices=("test", "regression"))
    s_plan.add_argument("--root", default=".")
    s_plan.add_argument("--output", required=True)
    s_plan.add_argument("--candidate", default=None)
    s_plan.add_argument("--baseline-traces", default=None)
    s_plan.add_argument("--limit", type=int, default=None)
    s_plan.add_argument("--full", action="store_true")
    s_plan.add_argument("--where", action="append", default=None,
                        help="按 sample.input 的 key=value 选子集，可重复")
    s_plan.add_argument("--policy", default=None)
    s_plan.set_defaults(func=cmd_stage_plan)
    s_run = stage_sub.add_parser("run", help="按外部 command 执行 stage 任务")
    s_run.add_argument("--output", required=True)
    s_run.add_argument("--command", required=True, help='JSON 列表')
    s_run.add_argument("--judge", default=None)
    s_run.add_argument("--timeout", type=float, default=600.0)
    s_run.set_defaults(func=cmd_stage_run)
    s_judge = stage_sub.add_parser("judge", help="按样本/arm 执行外部 judge")
    s_judge.add_argument("--output", required=True)
    s_judge.add_argument("--agent", default="dsh", choices=("dsh", "claude", "echo"))
    s_judge.add_argument("--timeout", type=float, default=300.0)
    s_judge.add_argument("--calibration", default=None,
                         help="judge-calibration --json 的结果；test 必须 passed")
    s_judge.set_defaults(func=cmd_stage_judge)
    s_report = stage_sub.add_parser("report", help="test 走 exact gate；regression 走硬失败")
    s_report.add_argument("--stage", required=True, choices=("test", "regression"))
    s_report.add_argument("--output", required=True)
    s_report.add_argument("--judge", required=True)
    s_report.add_argument("--card", default=None)
    s_report.add_argument("--update-stage", action="store_true",
                          help="test 报告通过后把 test-stage.yaml 标 complete")
    s_report.add_argument("--policy", default=None)
    s_report.set_defaults(func=cmd_stage_report)

    benchmark = sub.add_parser("benchmark", help="确定性 benchmark；工具/检索类改动不走诊断")
    benchmark.add_argument("--baseline-root", required=True)
    benchmark.add_argument("--candidate-root", required=True)
    benchmark.add_argument("--argv", required=True, help='JSON 列表，如 ["python3","-c","print(1)"]')
    benchmark.add_argument("--runs", type=int, default=None)
    benchmark.add_argument("--timeout", type=float, default=120.0)
    benchmark.add_argument("--policy", default=None)
    benchmark.add_argument("--json", action="store_true")
    benchmark.set_defaults(func=cmd_benchmark)

    readback = sub.add_parser("readback", help="按 EV 卡回读最新 Conclusion")
    readback.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    readback.add_argument("--card", default=None)
    readback.add_argument("--proposal", default=None)
    readback.add_argument("--measure", action="store_true", help="再跑 EV 卡的 predicted_effect.measure")
    readback.add_argument("--measure-timeout", type=int, default=120)
    readback.add_argument("--json", action="store_true")
    readback.set_defaults(func=cmd_readback)

    judge = sub.add_parser("judge", help="二元配对判定（b/c/n + 可选成本）")
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

    judge_stats = sub.add_parser(
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

    calibration = sub.add_parser(
        "judge-calibration", help="两份 0/1 标签的一致率与 kappa 门槛")
    calibration.add_argument("--a", required=True, help="评分员 A 的 JSON 标签")
    calibration.add_argument("--b", required=True, help="评分员 B 的 JSON 标签")
    calibration.add_argument("--min-raw", type=float, default=0.8)
    calibration.add_argument("--min-kappa", type=float, default=0.6)
    calibration.add_argument("--json", action="store_true")
    calibration.set_defaults(func=cmd_judge_calibration)

    replay = sub.add_parser("replay", help="S2 replay 输入准备与评分收集")
    replay_sub = replay.add_subparsers(dest="replay_command", required=True)
    replay_prepare_cmd = replay_sub.add_parser("prepare", help="产 replay 输入清单")
    replay_prepare_cmd.add_argument("--root", default=".", help="检出根目录（默认 .）")
    replay_prepare_cmd.set_defaults(func=cmd_replay_prepare)
    replay_collect_cmd = replay_sub.add_parser("collect", help="读 result 并写评分报告")
    replay_collect_cmd.add_argument("--root", default=".", help="检出根目录（默认 .）")
    replay_collect_cmd.add_argument("--report", required=True, help="评分报告输出路径")
    replay_collect_cmd.set_defaults(func=cmd_replay_collect)

    store = sub.add_parser("store", help="RSI 统一存储")
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

    experiment = sub.add_parser("experiment", help="算法适配器")
    experiment_sub = experiment.add_subparsers(dest="experiment_command", required=True)
    exp_list = experiment_sub.add_parser("list", help="列出注册算法与 policy 选择")
    exp_list.add_argument("--root", default=".", help="策略根目录")
    exp_list.add_argument("--policy", default=None, help="策略路径")
    exp_list.set_defaults(func=cmd_experiment_list)
    exp_resolve = experiment_sub.add_parser("resolve", help="按 target/algorithm 解析适配器")
    exp_resolve.add_argument("--target", required=True)
    exp_resolve.add_argument("--algorithm", default=None)
    exp_resolve.set_defaults(func=cmd_experiment_resolve)
    exp_show = experiment_sub.add_parser(
        "show", help="按提案编号合并 proposal / conclusion / experiment 记录")
    exp_show.add_argument("--root", default=None)
    exp_show.add_argument("--proposal", required=True)
    exp_show.set_defaults(func=cmd_experiment_show)

    exp_records = experiment_sub.add_parser("records", help="列出本地实验记录")
    exp_records.add_argument("--root", default=None)
    exp_records.add_argument("--limit", type=int, default=10)
    exp_records.set_defaults(func=cmd_experiment_records)
    exp_record = experiment_sub.add_parser("record", help="记录一份外部 baseline/candidate 实验结果")
    exp_record.add_argument("--root", default=None)
    exp_record.add_argument("--file", required=True, help="结果 JSON/YAML 路径或内联")
    exp_record.set_defaults(func=cmd_experiment_record)
    exp_gate = experiment_sub.add_parser("gate", help="按 target evaluator 判一个 rubric 样本")
    exp_gate.add_argument("--root", default=None)
    exp_gate.add_argument("--target", required=True)
    exp_gate.add_argument("--sample", default=None)
    exp_gate.add_argument("--scores", default=None, help="JSON 对象：维度 → 0/1/2")
    exp_gate.add_argument("--baseline", default=None, help="tooling gate：基线 tool usage JSON")
    exp_gate.add_argument("--candidate", default=None, help="tooling gate：候选 tool usage JSON")
    exp_gate.add_argument("--component", default=None, help="arena gate：目标组件")
    exp_gate.add_argument("--candidate-ref", default=None, help="arena gate：候选引用")
    exp_gate.add_argument("--note", default=None, help="arena gate：备注")
    exp_gate.add_argument("--alpha", type=float, default=0.1, help="arena gate：alpha")
    exp_gate.set_defaults(func=cmd_experiment_gate)
    exp_flow = experiment_sub.add_parser(
        "flow", help="提案 → candidate → pilot → runner → judge → gate → archive")
    exp_flow.add_argument("--root", required=True)
    exp_flow.add_argument("--proposal", required=True)
    exp_flow.add_argument("--samples", nargs="+", required=True)
    exp_flow.add_argument("--output", required=True)
    exp_flow.add_argument("--judge", default=None)
    exp_flow.add_argument("--runner-command", default=None, help="JSON argv")
    exp_flow.add_argument("--card", default=None, help="绑定 EV 卡号（行为面实验）")
    exp_flow.add_argument("--exploratory", action="store_true",
                          help="降级验收：允许 insufficient usage 与成本改善；不作为生产通过")
    exp_flow.add_argument("--dry-run", action="store_true",
                          help="只准备 candidate/pilot tasks，不跑 runner/judge")
    exp_flow.add_argument("--baseline-traces", default=None)
    exp_flow.add_argument("--archive", default=None)
    exp_flow.add_argument("--policy", default=None)
    exp_flow.add_argument("--profile", default=None, help="sleuth.config.yaml 的成本 profile")
    exp_flow.add_argument("--reuse-index", type=int, default=None)
    exp_flow.set_defaults(func=cmd_experiment_flow)

    exp_search = experiment_sub.add_parser(
        "search", help="用已产出的候选做校验、评分、策略选择并归档")
    exp_search.add_argument("--root", default=None)
    exp_search.add_argument("--scenario", required=True)
    exp_search.add_argument("--policy", choices=("best", "pareto", "gepa"), default="gepa")
    exp_search.add_argument("--archive", default=None)
    exp_search.set_defaults(func=cmd_experiment_search)

    exp_request = experiment_sub.add_parser(
        "request", help="为 agent 生成 target-specific 提案请求与 prompt")
    exp_request.add_argument("--root", default=None)
    exp_request.add_argument("--target", default=None)
    exp_request.add_argument("--component", required=True)
    exp_request.add_argument("--evidence", default=None, help="JSON 文件")
    exp_request.add_argument("--constraints", default=None, help="JSON 对象")
    exp_request.add_argument("--policy", default=None)
    exp_request.set_defaults(func=cmd_experiment_request)

    exp_propose = experiment_sub.add_parser(
        "propose", help="记录对照包络，或接收 agent 的 target-specific 提案草案")
    exp_propose.add_argument("--root", default=None)
    exp_propose.add_argument("--policy", default=None)
    exp_propose.add_argument("--target", default=None)
    exp_propose.add_argument("--algorithm", default=None)
    exp_propose.add_argument("--component", default=None)
    exp_propose.add_argument("--summary", default=None)
    exp_propose.add_argument("--budget", default=None, help="JSON 对象")
    exp_propose.add_argument("--seed", type=int, default=None)
    exp_propose.add_argument("--draft", default=None,
                             help="agent 写好的 target-specific 草案 JSON；不调用模型")
    exp_propose.set_defaults(func=cmd_experiment_propose)

    run = sub.add_parser("run", help="维护者下一步计划（不跑模型/不写库）")
    run.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    run.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    run.set_defaults(func=cmd_run)

    rsi = sub.add_parser("rsi", help="RSI 多源归因与实验计划")
    rsi_sub = rsi.add_subparsers(dest="rsi_command", required=True)
    rsi_plan = rsi_sub.add_parser("plan", help="trace/metrics/replay -> 实验计划")
    rsi_plan.add_argument("--root", default=None)
    rsi_plan.add_argument("--trace-state", default=None)
    rsi_plan.add_argument("--replay", default=None)
    rsi_plan.add_argument("--state", default=None)
    rsi_plan.add_argument("--json", action="store_true")
    rsi_plan.set_defaults(func=cmd_rsi_plan)
    rsi_attr = rsi_sub.add_parser("attribute", help="写回 agent 归因证据")
    rsi_attr.add_argument("--state", required=True)
    rsi_attr.add_argument("--file", required=True)
    rsi_attr.set_defaults(func=cmd_rsi_attribute)
    rsi_select = rsi_sub.add_parser("select", help="写回 agent 选点")
    rsi_select.add_argument("--state", required=True)
    rsi_select.add_argument("--file", required=True)
    rsi_select.set_defaults(func=cmd_rsi_select)
    pilot = sub.add_parser("pilot", help="真实 baseline/candidate pilot 编排")
    pilot_sub = pilot.add_subparsers(dest="pilot_command", required=True)
    p_prepare = pilot_sub.add_parser("prepare")
    p_prepare.add_argument("--root", required=True)
    p_prepare.add_argument("--candidate", required=True)
    p_prepare.add_argument("--samples", nargs="+", required=True)
    p_prepare.add_argument("--output", required=True)
    p_prepare.add_argument("--baseline-traces", default=None,
                           help="复用已有 baseline traces/out 的目录；只跑 candidate")
    p_prepare.set_defaults(func=cmd_pilot_prepare)
    p_collect = pilot_sub.add_parser("collect")
    p_collect.add_argument("--output", required=True)
    p_collect.add_argument("--judge", default=None, help="可选 judge JSON，用于给 source_ok 赋值")
    p_collect.set_defaults(func=cmd_pilot_collect)
    p_check = pilot_sub.add_parser("checkpoint", help="按预算与 futility 判断是否继续跑")
    p_check.add_argument("--output", required=True)
    p_check.add_argument("--judge", required=True)
    p_check.add_argument("--policy", default=None)
    p_check.add_argument("--reuse-index", type=int, default=0)
    p_check.set_defaults(func=cmd_pilot_checkpoint)

    p_decide = pilot_sub.add_parser("decide", help="配对判定并写 Run/Conclusion 记录")
    p_decide.add_argument("--output", required=True)
    p_decide.add_argument("--judge", required=True)
    p_decide.add_argument("--policy", default=None)
    p_decide.add_argument("--reuse-index", type=int, default=None)
    p_decide.add_argument("--pool", default="pilot")
    p_decide.add_argument("--card", default=None, help="写进结论的 EV 卡号")
    p_decide.set_defaults(func=cmd_pilot_decide)

    candidate = sub.add_parser("candidate", help="candidate Patch 校验/隔离 apply/rollback")
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

    source_usage = sub.add_parser("source-usage", help="源码访问效率观测/对照")
    source_sub = source_usage.add_subparsers(dest="source_command", required=True)
    source_trace = source_sub.add_parser("from-trace", help="从 diagnose trace 推导 source usage")
    source_trace.add_argument("--trace", required=True)
    source_trace.add_argument("--source-ok", choices=("true", "false"), default=None)
    source_trace.add_argument("--json", action="store_true")
    source_trace.set_defaults(func=cmd_source_usage_from_trace)
    source_eval = source_sub.add_parser("evaluate", help="汇总 source usage")
    source_eval.add_argument("--file", required=True)
    source_eval.set_defaults(func=cmd_source_usage_evaluate)
    source_cmp = source_sub.add_parser("compare", help="source usage 门禁")
    source_cmp.add_argument("--baseline", required=True)
    source_cmp.add_argument("--candidate", required=True)
    source_cmp.set_defaults(func=cmd_source_usage_compare)

    tool_usage = sub.add_parser("tool-usage", help="工具使用与工具性能观测/对照")
    tool_sub = tool_usage.add_subparsers(dest="tool_command", required=True)
    tool_trace = tool_sub.add_parser("from-trace", help="从 diagnose trace 推导 tool usage")
    tool_trace.add_argument("--trace", required=True)
    tool_trace.add_argument("--resolved", choices=("true", "false"), default=None)
    tool_trace.add_argument("--json", action="store_true")
    tool_trace.set_defaults(func=cmd_tool_usage_from_trace)
    tool_eval = tool_sub.add_parser("evaluate", help="汇总 tool usage")
    tool_eval.add_argument("--file", required=True)
    tool_eval.set_defaults(func=cmd_tool_usage_evaluate)
    tool_cmp = tool_sub.add_parser("compare", help="tool usage 门禁")
    tool_cmp.add_argument("--baseline", required=True)
    tool_cmp.add_argument("--candidate", required=True)
    tool_cmp.set_defaults(func=cmd_tool_usage_compare)

    usage = sub.add_parser("knowledge-usage", help="知识使用效率观测/对照")
    usage_sub = usage.add_subparsers(dest="usage_command", required=True)
    usage_trace = usage_sub.add_parser("from-trace", help="从 diagnose trace 推导 usage")
    usage_trace.add_argument("--trace", required=True)
    usage_trace.add_argument("--expected-case", default=None)
    usage_trace.add_argument("--json", action="store_true")
    usage_trace.set_defaults(func=cmd_knowledge_usage_from_trace)
    usage_eval = usage_sub.add_parser("evaluate", help="汇总一份 usage 记录")
    usage_eval.add_argument("--file", required=True)
    usage_eval.add_argument("--json", action="store_true")
    usage_eval.set_defaults(func=cmd_knowledge_usage_evaluate)
    usage_cmp = usage_sub.add_parser("compare", help="baseline/candidate 使用效率门禁")
    usage_cmp.add_argument("--baseline", required=True)
    usage_cmp.add_argument("--candidate", required=True)
    usage_cmp.add_argument("--json", action="store_true")
    usage_cmp.set_defaults(func=cmd_knowledge_usage_compare)
    rsi_status = rsi_sub.add_parser("status", help="读取已保存的 RSI 计划")
    rsi_status.add_argument("--state", required=True)
    rsi_status.set_defaults(func=cmd_rsi_status)

    traces = sub.add_parser("traces", help="本地 trace 归因状态")
    traces_sub = traces.add_subparsers(dest="traces_command", required=True)
    traces_sync = traces_sub.add_parser("sync", help="增量归因本地 traces")
    traces_sync.add_argument("--root", default=None)
    traces_sync.add_argument("--state", default=None)
    traces_sync.add_argument("--source-id", default="local")
    traces_sync.add_argument("--json", action="store_true")
    traces_sync.set_defaults(func=cmd_traces_sync)
    traces_status = traces_sub.add_parser("status", help="查看 trace 状态/快照")
    traces_status.add_argument("--root", default=None)
    traces_status.add_argument("--state", default=None)
    traces_status.set_defaults(func=cmd_traces_status)

    health = sub.add_parser("health", help="metrics 体检只读摘要")
    health.add_argument("--root", default=None)
    health.add_argument("--json", action="store_true")
    health.add_argument("--check", action="store_true", help="有 fail 时退出 1")
    health.set_defaults(func=cmd_health)

    brief = sub.add_parser("brief", help="样本计数与最近结论")
    brief.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    brief.set_defaults(func=cmd_brief)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (CliError, PolicyError, StoreError, RecordError, ContractError,
            AdapterError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
