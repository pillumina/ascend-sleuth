"""维护者入口：从样本队列、结论和策略生成一周的下一步动作。

``issue_plan`` 只读文件、不跑模型、不写库。它把“候选待审、field/test 不足、
还没有结论、test 还没抽”这些规则收在一处，CLI 的 ``run`` 与 ``brief`` 共用。
"""

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from .policy import policy_hash
from .records import ConclusionStore
from .samples import SampleStore


def _purpose_count(samples: List[Any], purpose: str) -> int:
    return sum(1 for sample in samples if sample.purpose == purpose)


def issue_plan(root: Any, base: Any, policy: Dict[str, Any]) -> Dict[str, Any]:
    """返回计划字典；``root`` 只用于无 ``base`` 时的默认落点。"""
    base_path = Path(base) if base is not None else None
    if base_path is not None:
        store = SampleStore(base=base_path)
        conclusions = ConclusionStore.for_base(base_path).read()
    else:
        store = SampleStore(Path(root))
        conclusions = ConclusionStore.for_root(Path(root)).read()
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
    if missing_answer:
        warnings.append(
            "candidate(s) missing answer: " + ", ".join(sorted(missing_answer))
        )
    if core_test > target_test:
        warnings.append(
            f"test set has {core_test} sample(s), policy target is {target_test}"
        )
    if not samples:
        warnings.append("sample store is empty")
    if not actions:
        actions.append("no_action: nothing required this week")

    return {
        "policy_hash": policy_hash(policy),
        "counts": counts,
        "next_actions": actions,
        "warnings": warnings,
    }


def render_plan(plan: Dict[str, Any]) -> str:
    """把计划渲染成给人读的短报告。"""
    counts = plan.get("counts") or {}
    lines = [
        f"policy_hash: {plan.get('policy_hash', '')}",
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
        "next_actions:",
    ]
    for action in plan.get("next_actions") or ["no_action"]:
        lines.append(f"- {action}")
    warnings = plan.get("warnings") or []
    if warnings:
        lines.append("warnings:")
        for warning in warnings:
            lines.append(f"- {warning}")
    return "\n".join(lines)
