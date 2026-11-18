"""外部实验记录：任何 harness 用 subagent 编排出的 baseline/candidate 对照。

本模块不调用模型、不生成诊断；只校验一份结果 JSON 是否可复核，再交给
``ExperimentStore`` 追加。算法可以是 baseline、gepa，也可以是 agent 编排的
reflection；记录必须写清算法/版本、样本、两侧分数和判定。
"""

from typing import Any, Dict, List

from .evaluations.registry import get_eval_profile
from .stages import get_stage
from .statistics import exact_mcnemar_ge
from .targets.registry import TARGETS, get_target


class ExperimentError(ValueError):
    """实验记录字段缺失或非法。"""


DECISIONS = ("accept", "reject", "insufficient", "unknown")
EXECUTIONS = ("library", "subagent", "manual")


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
    execution = record.get("execution")
    if execution not in EXECUTIONS:
        raise ExperimentError(f"execution must be one of {list(EXECUTIONS)}")
    samples = record.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ExperimentError("samples must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in samples):
        raise ExperimentError("samples must contain non-empty strings")
    if len(set(samples)) != len(samples):
        raise ExperimentError("samples must not contain duplicates")
    baseline = _side(record.get("baseline"), "baseline")
    candidate = _side(record.get("candidate"), "candidate")
    if len(set(baseline["samples"])) != len(baseline["samples"]):
        raise ExperimentError("baseline.samples must not contain duplicates")
    if len(set(candidate["samples"])) != len(candidate["samples"]):
        raise ExperimentError("candidate.samples must not contain duplicates")
    if set(baseline["samples"]) != set(candidate["samples"]):
        raise ExperimentError("baseline/candidate samples must be the same set")
    if set(samples) != set(baseline["samples"]):
        raise ExperimentError("top-level samples must match baseline/candidate")
    paired = record.get("paired")
    if decision == "accept":
        if paired is None:
            raise ExperimentError("accept requires paired evidence {b,c,n}")
        if not isinstance(paired, dict):
            raise ExperimentError("paired must be an object")
        b, c, n = paired.get("b"), paired.get("c"), paired.get("n")
        for name, value in (("b", b), ("c", c), ("n", n)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ExperimentError(f"paired.{name} must be a non-negative integer")
        if n < b + c:
            raise ExperimentError("paired.n must be >= paired.b + paired.c")
        if b <= c:
            raise ExperimentError("accept requires paired.b > paired.c")
        p_value = exact_mcnemar_ge(b, c)
        alpha = paired.get("alpha_eff", 0.1)
        if not isinstance(alpha, (int, float)) or isinstance(alpha, bool) or not 0 < alpha <= 0.1:
            raise ExperimentError("paired.alpha_eff must be in (0, 0.1]")
        if p_value > alpha:
            raise ExperimentError(
                f"accept requires exact paired p={p_value:.4f} <= alpha_eff={alpha}"
            )
        if candidate["score"] <= baseline["score"]:
            raise ExperimentError("accept requires candidate.score > baseline.score")
    spec = get_target(target)
    if execution == "subagent":
        profile_id = record.get("eval_profile_id")
        if profile_id != "subagent_judge":
            raise ExperimentError(
                "execution=subagent requires eval_profile_id='subagent_judge'"
            )
        profile = get_eval_profile(profile_id)
        if record.get("eval_ready") is not False:
            raise ExperimentError("execution=subagent must set eval_ready=false")
        eval_ready = False
    else:
        profile_id = record.get("eval_profile_id") or spec.eval_profile_id
        if profile_id not in {spec.eval_profile_id}:
            raise ExperimentError(
                f"eval_profile_id {profile_id!r} is not allowed for target {target!r}"
            )
        profile = get_eval_profile(profile_id)
        ready_input = record.get("eval_ready", profile.implemented)
        if not isinstance(ready_input, bool):
            raise ExperimentError("eval_ready must be boolean")
        eval_ready = bool(profile.implemented and ready_input)
    result = {
        "target_kind": target,
        "target_component": component,
        "algorithm": algorithm,
        "algorithm_version": version,
        "execution": execution,
        "decision": decision,
        "samples": list(samples),
        "baseline": baseline,
        "candidate": candidate,
        "eval_profile_id": profile.id,
        "eval_ready": eval_ready,
        "summary": str(record.get("summary") or ""),
    }
    stages = record.get("stages")
    if stages is not None:
        if not isinstance(stages, dict):
            raise ExperimentError("stages must be an object")
        normalized_stages = {}
        for point, stage_id in stages.items():
            spec = get_stage(str(stage_id))
            if spec.point != point:
                raise ExperimentError(
                    f"stage {stage_id!r} is {spec.point}, not {point!r}"
                )
            normalized_stages[point] = spec.id
        result["stages"] = normalized_stages
    usage = record.get("knowledge_usage")
    if usage is not None:
        if not isinstance(usage, dict):
            raise ExperimentError("knowledge_usage must be an object")
        if usage.get("decision") not in ("accept", "reject", "insufficient"):
            raise ExperimentError("knowledge_usage.decision must be accept/reject/insufficient")
        if decision == "accept" and usage.get("decision") != "accept":
            raise ExperimentError("accept requires knowledge_usage.decision=accept")
        result["knowledge_usage"] = usage
    if paired is not None:
        result["paired"] = {
            "b": paired.get("b"), "c": paired.get("c"), "n": paired.get("n"),
            "p_value": exact_mcnemar_ge(paired["b"], paired["c"]),
            "alpha_eff": paired.get("alpha_eff", 0.1),
        }
    for key in ("budget", "seed"):
        if key in record:
            result[key] = record[key]
    return result
