"""外部实验记录：任何 harness 用 subagent 编排出的 baseline/candidate 对照。

本模块不调用模型、不生成诊断；只校验一份结果 JSON 是否可复核，再交给
``ExperimentStore`` 追加。算法可以是 baseline、gepa，也可以是 agent 编排的
reflection；记录必须写清算法/版本、样本、两侧分数和判定。
"""

from typing import Any, Dict, List

from .targets.registry import TARGETS, get_target


class ExperimentError(ValueError):
    """实验记录字段缺失或非法。"""


DECISIONS = ("accept", "reject", "insufficient", "unknown")


def _number(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ExperimentError(f"{name} must be a number")
    if not 0 <= float(value) <= 1:
        raise ExperimentError(f"{name} must be between 0 and 1")
    return float(value)


def _side(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ExperimentError(f"{name} must be an object")
    score = _number(value.get("score"), f"{name}.score")
    samples = value.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ExperimentError(f"{name}.samples must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in samples):
        raise ExperimentError(f"{name}.samples must contain non-empty strings")
    return {"score": score, "samples": list(samples)}


def validate_experiment(record: Any) -> Dict[str, Any]:
    if not isinstance(record, dict):
        raise ExperimentError("experiment must be an object")
    target = record.get("target_kind")
    if target not in TARGETS:
        raise ExperimentError(f"unknown target_kind {target!r}")
    component = record.get("target_component")
    if not isinstance(component, str) or not component.strip():
        raise ExperimentError("target_component is required")
    algorithm = record.get("algorithm")
    version = record.get("algorithm_version")
    for name, value in (("algorithm", algorithm), ("algorithm_version", version)):
        if not isinstance(value, str) or not value.strip():
            raise ExperimentError(f"{name} is required")
    decision = record.get("decision")
    if decision not in DECISIONS:
        raise ExperimentError(f"decision must be one of {list(DECISIONS)}")
    samples = record.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ExperimentError("samples must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in samples):
        raise ExperimentError("samples must contain non-empty strings")
    baseline = _side(record.get("baseline"), "baseline")
    candidate = _side(record.get("candidate"), "candidate")
    if set(baseline["samples"]) != set(candidate["samples"]):
        raise ExperimentError("baseline/candidate samples must be the same set")
    spec = get_target(target)
    result = {
        "target_kind": target,
        "target_component": component,
        "algorithm": algorithm,
        "algorithm_version": version,
        "decision": decision,
        "samples": list(samples),
        "baseline": baseline,
        "candidate": candidate,
        "eval_profile_id": record.get("eval_profile_id") or spec.eval_profile_id,
        "eval_ready": bool(record.get("eval_ready", False)),
        "summary": str(record.get("summary") or ""),
    }
    for key in ("budget", "seed"):
        if key in record:
            result[key] = record[key]
    return result
