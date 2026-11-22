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
EPSILON = 1e-9


def _number(value: Any, name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ExperimentError(f"{name} must be a number")
    if not 0 <= float(value) <= 1:
        raise ExperimentError(f"{name} must be between 0 and 1")
    return float(value)


def _validate_usage_side(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ExperimentError(f"knowledge_usage.{name} must be an object")
    n = value.get("n")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise ExperimentError(f"knowledge_usage.{name}.n must be a positive integer")
    hits = value.get("hits")
    wrong = value.get("wrong_cases")
    if not isinstance(hits, int) or isinstance(hits, bool) or not 0 <= hits <= n:
        raise ExperimentError(f"knowledge_usage.{name}.hits must be 0..n")
    if wrong is not None and (not isinstance(wrong, int) or isinstance(wrong, bool)
                              or not 0 <= wrong <= n):
        raise ExperimentError(f"knowledge_usage.{name}.wrong_cases must be 0..n or null")
    resolved = value.get("resolved")
    if resolved is not None and (not isinstance(resolved, int) or isinstance(resolved, bool)
                                 or not 0 <= resolved <= n):
        raise ExperimentError(f"knowledge_usage.{name}.resolved must be 0..n or null")
    rate = value.get("hit_rate")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool):
        raise ExperimentError(f"knowledge_usage.{name}.hit_rate must be a number")
    if abs(float(rate) - hits / n) > 1e-6:
        raise ExperimentError(f"knowledge_usage.{name}.hit_rate does not match hits/n")
    for field in ("first_hit_step", "candidates_examined", "full_body_reads",
                  "reference_lookups", "tokens", "elapsed_ms"):
        item = value.get(field)
        if item is not None and (not isinstance(item, (int, float)) or isinstance(item, bool) or item < 0):
            raise ExperimentError(f"knowledge_usage.{name}.{field} must be non-negative or null")
    return value


def _validate_usage_evidence(usage: Dict[str, Any]) -> None:
    for key in ("baseline", "candidate", "deltas", "reasons"):
        if key not in usage:
            raise ExperimentError(f"knowledge_usage.{key} is required")
    baseline = _validate_usage_side(usage.get("baseline"), "baseline")
    candidate = _validate_usage_side(usage.get("candidate"), "candidate")
    if baseline["n"] != candidate["n"]:
        raise ExperimentError("knowledge_usage baseline/candidate n must match")
    if not isinstance(usage.get("reasons"), list):
        raise ExperimentError("knowledge_usage.reasons must be a list")
    deltas = usage.get("deltas")
    if not isinstance(deltas, dict):
        raise ExperimentError("knowledge_usage.deltas must be an object")
    for field in ("first_hit_step", "candidates_examined", "full_body_reads",
                  "reference_lookups", "tokens", "elapsed_ms"):
        if field not in deltas:
            raise ExperimentError(f"knowledge_usage.deltas.{field} is required")
        item = deltas[field]
        if item is not None and (not isinstance(item, (int, float)) or isinstance(item, bool)):
            raise ExperimentError(f"knowledge_usage.deltas.{field} must be numeric or null")
        bv, cv = baseline.get(field), candidate.get(field)
        if bv is not None and cv is not None and item is not None:
            if abs(float(item) - (float(cv) - float(bv))) > 1e-6:
                raise ExperimentError(f"knowledge_usage.deltas.{field} does not match sides")
    if usage.get("decision") == "accept":
        if usage.get("reasons"):
            raise ExperimentError("knowledge_usage accept must have no reasons")
        if baseline.get("resolved") is not None and candidate.get("resolved") is not None:
            if candidate["resolved"] < baseline["resolved"]:
                raise ExperimentError("knowledge_usage accept regresses resolved count")
        elif baseline["wrong_cases"] is not None and candidate["wrong_cases"] is not None:
            if candidate["hits"] < baseline["hits"] or candidate["wrong_cases"] > baseline["wrong_cases"]:
                raise ExperimentError("knowledge_usage accept regresses accuracy/wrong_cases")
        else:
            raise ExperimentError("knowledge_usage accept requires known wrong_cases or resolved")
        improved = any(item is not None and item < -EPSILON for item in deltas.values())
        worsened = any(item is not None and item > EPSILON for item in deltas.values())
        if not improved or worsened:
            raise ExperimentError("knowledge_usage accept requires improvement without regression")


def _validate_source_side(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ExperimentError(f"source_usage.{name} must be an object")
    n = value.get("n")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise ExperimentError(f"source_usage.{name}.n must be a positive integer")
    ok = value.get("source_ok")
    if ok is not None and (not isinstance(ok, int) or isinstance(ok, bool) or not 0 <= ok <= n):
        raise ExperimentError(f"source_usage.{name}.source_ok must be 0..n or null")
    for field in ("files_read", "tool_calls", "fetch_calls", "grep_calls",
                  "followups", "downloads", "bytes", "elapsed_ms", "cache_hits"):
        item = value.get(field)
        if item is not None and (not isinstance(item, (int, float)) or isinstance(item, bool) or item < 0):
            raise ExperimentError(f"source_usage.{name}.{field} must be non-negative or null")
    return value


def _validate_source_usage_evidence(usage: Dict[str, Any]) -> None:
    for key in ("baseline", "candidate", "deltas", "reasons"):
        if key not in usage:
            raise ExperimentError(f"source_usage.{key} is required")
    baseline = _validate_source_side(usage.get("baseline"), "baseline")
    candidate = _validate_source_side(usage.get("candidate"), "candidate")
    if baseline["n"] != candidate["n"]:
        raise ExperimentError("source_usage baseline/candidate n must match")
    if not isinstance(usage.get("reasons"), list):
        raise ExperimentError("source_usage.reasons must be a list")
    deltas = usage.get("deltas")
    if not isinstance(deltas, dict):
        raise ExperimentError("source_usage.deltas must be an object")
    for field in ("files_read", "tool_calls", "fetch_calls", "grep_calls",
                  "followups", "elapsed_ms"):
        if field not in deltas:
            raise ExperimentError(f"source_usage.deltas.{field} is required")
        item = deltas[field]
        if item is not None and (not isinstance(item, (int, float)) or isinstance(item, bool)):
            raise ExperimentError(f"source_usage.deltas.{field} must be numeric or null")
        bv, cv = baseline.get(field), candidate.get(field)
        if bv is not None and cv is not None:
            if item is None or abs(float(item) - (float(cv) - float(bv))) > 1e-6:
                raise ExperimentError(f"source_usage.deltas.{field} does not match sides")
        elif item is not None:
            raise ExperimentError(f"source_usage.deltas.{field} must be null when a side is unknown")
    if usage.get("decision") == "accept":
        if usage.get("reasons"):
            raise ExperimentError("source_usage accept must have no reasons")
        if baseline.get("source_ok") is None or candidate.get("source_ok") is None:
            raise ExperimentError("source_usage accept requires source correctness")
        if candidate["source_ok"] < baseline["source_ok"]:
            raise ExperimentError("source_usage accept regresses correctness")
        lower = ("files_read", "tool_calls", "fetch_calls", "grep_calls",
                 "followups", "elapsed_ms")
        improved = any(deltas[f] is not None and deltas[f] < -EPSILON for f in lower)
        worsened = any(deltas[f] is not None and deltas[f] > EPSILON for f in lower)
        if not improved or worsened:
            raise ExperimentError("source_usage accept requires improvement without regression")


def _side(value: Any, name: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ExperimentError(f"{name} must be an object")
    score = _number(value.get("score"), f"{name}.score")
    samples = value.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ExperimentError(f"{name}.samples must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in samples):
        raise ExperimentError(f"{name}.samples must contain non-empty strings")
    per_sample = value.get("per_sample")
    normalized: Dict[str, Any] = {"score": score, "samples": list(samples)}
    if per_sample is not None:
        if not isinstance(per_sample, dict):
            raise ExperimentError(f"{name}.per_sample must be an object")
        if set(per_sample) != set(samples):
            raise ExperimentError(f"{name}.per_sample must match samples")
        for sample_id, item in per_sample.items():
            if item not in (0, 1):
                raise ExperimentError(f"{name}.per_sample.{sample_id} must be 0 or 1")
        normalized["per_sample"] = {str(key): int(value) for key, value in per_sample.items()}
    return normalized


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
    exploratory = record.get("exploratory") is True
    if decision == "accept" and exploratory:
        if paired is None or not isinstance(paired, dict):
            raise ExperimentError("exploratory accept requires paired evidence {b,c,n}")
        b, c, n = paired.get("b"), paired.get("c"), paired.get("n")
        for name, value in (("b", b), ("c", c), ("n", n)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ExperimentError(f"paired.{name} must be a non-negative integer")
        if n < b + c:
            raise ExperimentError("paired.n must be >= paired.b + paired.c")
        if candidate["score"] < baseline["score"]:
            raise ExperimentError("exploratory accept requires candidate.score >= baseline.score")
    elif decision == "accept":
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
        snapshot = record.get("conclusion_snapshot")
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        primary = (snapshot.get("metrics") or {}).get("cost_primary")
        ratio = snapshot.get("cost_ratio")
        cost_path = (
            isinstance(primary, str) and primary != "tokens"
            and isinstance(ratio, (int, float)) and 0 <= ratio <= 0.9
        )
        if b <= c and not cost_path:
            raise ExperimentError("accept requires paired.b > paired.c or a cost-path conclusion")
        if not cost_path:
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
    if record.get("proposal"):
        result["proposal"] = str(record["proposal"])
    if record.get("ev_card"):
        result["ev_card"] = str(record["ev_card"])
    if exploratory:
        result["exploratory"] = True
    for key in ("proposal_snapshot", "conclusion_snapshot", "judge_meta"):
        value = record.get(key)
        if isinstance(value, dict):
            result[key] = value
    if record.get("judge_sha256"):
        result["judge_sha256"] = str(record["judge_sha256"])
    sample_context = record.get("sample_context")
    if sample_context is not None:
        if not isinstance(sample_context, list):
            raise ExperimentError("sample_context must be a list")
        cleaned = []
        for item in sample_context:
            if not isinstance(item, dict):
                raise ExperimentError("each sample_context item must be an object")
            sid = item.get("id")
            if not isinstance(sid, str) or not sid.strip():
                raise ExperimentError("sample_context.id is required")
            cleaned.append({"id": sid, "title": str(item.get("title") or "")})
        result["sample_context"] = cleaned
    stage_reports = record.get("stage_reports")
    if stage_reports is not None:
        if not isinstance(stage_reports, list):
            raise ExperimentError("stage_reports must be a list")
        cleaned = []
        for item in stage_reports:
            if not isinstance(item, dict):
                raise ExperimentError("each stage_report must be an object")
            stage_id = item.get("id")
            if not isinstance(stage_id, str) or not stage_id.strip():
                raise ExperimentError("stage_report.id is required")
            cleaned.append({
                "id": stage_id,
                "label": str(item.get("label") or stage_id),
                "state": str(item.get("state") or "empty"),
                "summary": str(item.get("summary") or ""),
                "fields": [str(field) for field in (item.get("fields") or [])
                           if str(field).strip()],
            })
        result["stage_reports"] = cleaned
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
    source_usage = record.get("source_usage")
    if component == "diagnose.source_usage" and decision == "accept" and source_usage is None and not exploratory:
        raise ExperimentError("source usage accept requires source_usage gate evidence")
    if source_usage is not None:
        if not isinstance(source_usage, dict):
            raise ExperimentError("source_usage must be an object")
        if source_usage.get("decision") not in ("accept", "reject", "insufficient"):
            raise ExperimentError("source_usage.decision must be accept/reject/insufficient")
        _validate_source_usage_evidence(source_usage)
        if decision == "accept" and not exploratory and (source_usage.get("decision") != "accept" or source_usage.get("reasons")):
            raise ExperimentError("accept requires source_usage.decision=accept and no reasons")
        result["source_usage"] = source_usage
    usage = record.get("knowledge_usage")
    if component == "diagnose.knowledge_usage" and decision == "accept" and usage is None and not exploratory:
        raise ExperimentError("knowledge usage accept requires knowledge_usage gate evidence")
    if usage is not None:
        if not isinstance(usage, dict):
            raise ExperimentError("knowledge_usage must be an object")
        if usage.get("decision") not in ("accept", "reject", "insufficient"):
            raise ExperimentError("knowledge_usage.decision must be accept/reject/insufficient")
        _validate_usage_evidence(usage)
        if decision == "accept" and not exploratory and (usage.get("decision") != "accept" or usage.get("reasons")):
            raise ExperimentError("accept requires knowledge_usage.decision=accept and no reasons")
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
