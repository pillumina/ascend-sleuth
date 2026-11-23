"""``brief`` 命令组：样本计数与最近结论。"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

from ..adapters.metrics import load_metrics
from ..policy import PolicyError, policy_hash
from ..proposal_engine import ProposalArchive
from ..records import ConclusionStore, ExperimentStore, RecordError
from ..runner import issue_plan
from ..samples import SampleStore, StoreError
from ..trace_attribution import status as trace_status
from .common import evolve_base, policy_for


def _format_counts(counts: Dict[str, int]) -> str:
    if not counts:
        return "none"
    return " ".join(f"{key}={counts[key]}" for key in sorted(counts))


def _metric_value(value: Any) -> str:
    return "unavailable" if value is None else str(value)


def cmd_brief(args: argparse.Namespace) -> int:
    base = evolve_base(args)
    store = SampleStore(base=base)
    try:
        policy = policy_for(args)
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
        proposals = ProposalArchive(evolve_base(args) / "proposals.jsonl").read()
    except (OSError, ValueError):
        proposals = []
    try:
        experiments = ExperimentStore.for_base(evolve_base(args)).read()
    except (OSError, ValueError):
        experiments = []
    try:
        from ..store import RSIStore
        events = RSIStore(evolve_base(args)).read()
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


def register(subparsers) -> None:
    brief = subparsers.add_parser("brief", help="样本计数与最近结论")
    brief.add_argument("--root", default=None, help="本地根目录（默认锚主检出）")
    brief.set_defaults(func=cmd_brief)
