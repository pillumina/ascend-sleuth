"""维护者入口：从样本队列、结论和策略生成一周的下一步动作。

``issue_plan`` 只读文件、不跑模型、不写库。它把“候选待审、field/test 不足、
还没有结论、test 还没抽”这些规则收在一处，CLI 的 ``run`` 与 ``brief`` 共用。
"""

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from .decision import required_exclusive_wins
from .pools import stratum_of
from .policy import policy_hash
from .records import ConclusionStore
from .samples import SampleStore

import yaml


def _purpose_count(samples: List[Any], purpose: str) -> int:
    return sum(1 for sample in samples if sample.purpose == purpose)


def issue_plan(root: Any, base: Any, policy: Dict[str, Any],
               metrics: Optional[Dict[str, Any]] = None,
               trace_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """返回计划字典；``root`` 用于 metrics 读取与无 ``base`` 时的默认落点。"""
    root_path = Path(root) if root is not None else Path(".")
    base_path = Path(base) if base is not None else None
    metrics = metrics or {}
    if base_path is not None:
        store = SampleStore(base=base_path)
        conclusions = ConclusionStore.for_base(base_path).read()
    else:
        store = SampleStore(root_path)
        conclusions = ConclusionStore.for_root(root_path).read()
    samples = store.read_all()
    by_status = Counter(sample.status for sample in samples)
    by_origin = Counter(sample.origin for sample in samples)
    by_purpose = Counter(sample.purpose for sample in samples)
    targets = policy.get("samples") or {}
    target_field = int(targets.get("field_eval", 0) or 0)
    target_test = int(targets.get("test", 0) or 0)
    target_core_regression = int(targets.get("core_regression", 0) or 0)

    field_eval = sum(
        1 for sample in samples
        if sample.status == "active" and sample.origin == "field"
        and sample.purpose == "evaluation"
    )
    core_eval = sum(
        1 for sample in samples
        if sample.status == "active" and sample.origin == "core"
        and sample.purpose == "evaluation"
    )
    core_test = sum(
        1 for sample in samples
        if sample.status == "active" and sample.origin == "core"
        and sample.purpose == "test"
    )
    core_regression = sum(
        1 for sample in samples
        if sample.status == "active" and sample.origin == "core"
        and sample.purpose == "regression"
    )
    strata_targets = (targets.get("strata") or {}) if isinstance(targets, dict) else {}
    strata_counts: Dict[str, Dict[str, int]] = {}
    for sample in samples:
        if sample.status != "active":
            continue
        key = stratum_of(sample)
        bucket = strata_counts.setdefault(
            key, {"field_eval": 0, "core_test": 0, "target": 0},
        )
        if sample.purpose == "evaluation" and sample.origin == "field":
            bucket["field_eval"] += 1
        if sample.purpose == "test" and sample.origin == "core":
            bucket["core_test"] += 1
    for key, target in strata_targets.items():
        strata_counts.setdefault(
            key, {"field_eval": 0, "core_test": 0, "target": 0},
        )["target"] = int(target)
    strata_short = sorted(
        key for key, bucket in strata_counts.items()
        if bucket["target"] and bucket["core_test"] < bucket["target"]
    )

    missing_answer = [
        sample.id for sample in samples
        if sample.status == "candidate" and not sample.expected and not sample.rubric
    ]

    counts: Dict[str, int] = {
        "total": len(samples),
        "candidate": by_status.get("candidate", 0),
        "active": by_status.get("active", 0),
        "field": sum(1 for sample in samples if sample.status == "active" and sample.origin == "field"),
        "core": sum(1 for sample in samples if sample.status == "active" and sample.origin == "core"),
        "evaluation": sum(1 for sample in samples if sample.status == "active" and sample.purpose == "evaluation"),
        "feedback": sum(1 for sample in samples if sample.status == "active" and sample.purpose == "feedback"),
        "test": sum(1 for sample in samples if sample.status == "active" and sample.purpose == "test"),
        "regression": sum(1 for sample in samples if sample.status == "active" and sample.purpose == "regression"),
        "field_eval": field_eval,
        "core_eval": core_eval,
        "core_test": core_test,
        "core_regression": core_regression,
        "conclusions": len(conclusions),
    }
    counts["strata"] = {
        key: dict(value) for key, value in sorted(strata_counts.items())
    }

    actions: List[str] = []
    warnings: List[str] = []
    if counts["candidate"]:
        actions.append(
            f"review_candidates: {counts['candidate']} candidate(s) pending review"
        )
    if not conclusions:
        actions.append(
            "no_conclusion: run judge/judge-stats --record after a paired comparison"
        )
    if field_eval < target_field:
        actions.append(
            f"field_eval_short: {field_eval}/{target_field}; add field evaluation samples"
        )
    if core_test < target_test:
        if core_eval > 0:
            actions.append(
                f"draw_test: {core_test}/{target_test}; draw test from active/core evaluation"
            )
        else:
            actions.append(
                f"test_short: {core_test}/{target_test}; no active/core evaluation sample yet"
            )
    if core_regression < target_core_regression:
        actions.append(
            f"core_regression_short: {core_regression}/{target_core_regression}; "
            "add core regression samples"
        )
    alpha = float((policy.get("decision") or {}).get("alpha", 0.10))
    required = required_exclusive_wins(alpha)
    potential = field_eval + counts["candidate"]
    if potential < required:
        actions.append(
            f"judgment_capacity_short: pool_samples={potential} < required_b={required}; "
            "this pool can only return insufficient"
        )
    if missing_answer:
        warnings.append(
            "candidate(s) missing answer: " + ", ".join(sorted(missing_answer))
        )
    if core_test > target_test:
        warnings.append(
            f"test set has {core_test} sample(s), policy target is {target_test}"
        )
    freshness = metrics.get("freshness") or {}
    timeline = metrics.get("timeline") or {}
    if not trace_state or not trace_state.get("available"):
        actions.append("traces_unattributed: run traces sync before attribution-driven evolution")
    if timeline.get("available") is False:
        actions.append(
            "metrics_unavailable: run trace_entry_activity --apply / metrics_snapshot "
            "before trusting trend readouts"
        )
    else:
        unavailable = []
        stale: Dict[str, List[str]] = {}
        for key in ("live", "structural"):
            item = freshness.get(key) or {}
            if not item.get("available"):
                unavailable.append(key)
            elif item.get("stale"):
                stale.setdefault(str(item.get("period") or "unknown"), []).append(key)
        if unavailable:
            actions.append(
                "metrics_freshness_unavailable: " + ", ".join(unavailable)
                + "; run trace_entry_activity --apply / metrics_snapshot"
            )
        for period in sorted(stale):
            keys = stale[period]
            item = freshness.get(keys[0]) or {}
            actions.append(
                f"metrics_stale: {period} ({', '.join(keys)}) is "
                f"{item.get('age_days')} days old (max {item.get('max_age_days')}); "
                "refresh before deciding"
            )
    if strata_short:
        actions.append(
            "test_strata_short: " + ", ".join(
                f"{key} {strata_counts[key]['core_test']}/{strata_counts[key]['target']}"
                for key in strata_short
            )
        )
    stage = root_path / "eval" / "core" / "test-stage.yaml"
    if stage.is_file():
        try:
            doc = yaml.safe_load(stage.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            warnings.append(f"test-stage unreadable: {exc}")
        else:
            if str(doc.get("status") or "") != "complete":
                actions.append(
                    "test_stage_not_started: " + str(doc.get("reason") or "test replay not run")
                )
    if not samples:
        warnings.append("sample store is empty")
    if not actions:
        actions.append("no_action: nothing required this week")

    if metrics is None:
        metrics = {"available": False, "reason": "metrics not loaded by caller"}
    runs = (policy.get("cost") or {}).get("runs") or {}
    cost_plan = {
        "pilot_max_pairs": runs.get("max_pairs"),
        "baseline_reuse": bool(runs.get("baseline_reuse", True)),
        "test_samples": (policy.get("samples") or {}).get("test"),
        "regression_pairs": runs.get("regression_pairs"),
        "regression_full_pairs": runs.get("regression_full_pairs"),
        "benchmark_runs": runs.get("benchmark_runs"),
    }
    return {
        "policy_hash": policy_hash(policy),
        "trace_snapshot": (trace_state or {}).get("snapshot_id"),
        "trace_state": trace_state or {"available": False},
        "target": ((policy.get("experiment") or {}).get("target") or "skill"),
        "algorithm": ((policy.get("experiment") or {}).get("algorithm") or "baseline"),
        "counts": counts,
        "metrics": metrics,
        "judgment_capacity": {"potential": potential, "required_b": required,
                              "alpha": alpha},
        "cost_plan": cost_plan,
        "next_actions": actions,
        "warnings": warnings,
    }


def render_plan(plan: Dict[str, Any]) -> str:
    """把计划渲染成给人读的短报告。"""
    counts = plan.get("counts") or {}
    lines = [
        f"policy_hash: {plan.get('policy_hash', '')}",
        f"target: {plan.get('target', 'skill')}",
        f"algorithm: {plan.get('algorithm', 'baseline')}",
        f"trace_snapshot: {plan.get('trace_snapshot') or 'unavailable'}",
        (
            "samples: {total} (candidate={candidate} active={active} "
            "field={field} core={core} test={test})"
        ).format(
            total=counts.get("total", 0),
            candidate=counts.get("candidate", 0),
            active=counts.get("active", 0),
            field=counts.get("field", 0),
            core=counts.get("core", 0),
            test=counts.get("test", 0),
        ),
        "cost_plan: " + ", ".join(
            f"{key}={value}" for key, value in (plan.get("cost_plan") or {}).items()
        ),
        "next_actions:",
    ]
    for action in plan.get("next_actions") or ["no_action"]:
        lines.append(f"- {action}")
    metrics = plan.get("metrics") or {}
    period = metrics.get("latest_period")
    if period:
        lines.append(
            "metrics_latest: {period} ({kind})".format(
                period=period.get("period", "unavailable"),
                kind=period.get("kind", "unknown"),
            )
        )
    else:
        lines.append("metrics_latest: unavailable")
    lines.append(f"sessions_total: {_metric_value(metrics.get('sessions_total'))}")
    lines.append(f"tier2_hit: {_metric_value(metrics.get('tier2_hit'))}")
    lines.append(f"case_total: {_metric_value(metrics.get('case_total'))}")
    lines.append(f"feedback: {_metric_value(metrics.get('feedback'))}")
    strata = counts.get("strata") or {}
    if strata:
        lines.append("strata:")
        for key, value in sorted(strata.items()):
            lines.append(
                f"- {key}: field_eval={value.get('field_eval', 0)} "
                f"core_test={value.get('core_test', 0)} target={value.get('target', 0)}"
            )
    last = (metrics.get("last_skill_exec") or {}).get("last") if isinstance(
        metrics.get("last_skill_exec"), dict) else None
    if last:
        lines.append(f"last_skill_exec: {last.get('skill')} {last.get('at')}")
    else:
        lines.append("last_skill_exec: unavailable")
    entry = metrics.get("entry_usage") or {}
    if isinstance(entry, dict) and entry.get("available"):
        lines.append(
            "entry_usage: cases={cases} active={active} references={refs} "
            "cold={cold}".format(
                cases=_metric_value(entry.get("cases")),
                active=_metric_value(entry.get("active_cases")),
                refs=_metric_value(entry.get("references")),
                cold=_metric_value(entry.get("cold_cases")),
            )
        )
    else:
        lines.append("entry_usage: unavailable")
    warnings = plan.get("warnings") or []
    if warnings:
        lines.append("warnings:")
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)


def _metric_value(value: Any) -> str:
    return "unavailable" if value is None else str(value)
