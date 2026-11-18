"""知识使用效率的观测与门禁。

这里不执行 diagnose，也不读 case 正文；只校验一条诊断 rollout 暴露的
使用记录。字段全部来自 trace/实验记录，缺失就记 unknown，不补零。
"""

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

EFFICIENCY_FIELDS = (
    "first_hit_step", "candidates_examined", "full_body_reads",
    "reference_lookups", "tokens", "elapsed_ms",
)


class UsageError(ValueError):
    pass


def _int(value: Any, name: str, *, optional: bool = False) -> Optional[int]:
    if value is None and optional:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise UsageError(f"{name} must be a non-negative integer")
    return value


def _num(value: Any, name: str, *, optional: bool = False) -> Optional[float]:
    if value is None and optional:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise UsageError(f"{name} must be a non-negative number")
    return float(value)


def validate_record(record: Any) -> Dict[str, Any]:
    if not isinstance(record, dict):
        raise UsageError("usage record must be an object")
    sample_id = record.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id.strip():
        raise UsageError("sample_id is required")
    hit = record.get("hit")
    if not isinstance(hit, bool):
        raise UsageError("hit must be boolean")
    wrong = _int(record.get("wrong_cases"), "wrong_cases", optional=True)
    candidate_examined = _int(record.get("candidates_examined"), "candidates_examined", optional=True)
    full_body = _int(record.get("full_body_reads"), "full_body_reads", optional=True)
    refs = _int(record.get("reference_lookups"), "reference_lookups", optional=True)
    first_step = _int(record.get("first_hit_step"), "first_hit_step", optional=True)
    tokens = _int(record.get("tokens"), "tokens", optional=True)
    elapsed = _num(record.get("elapsed_ms"), "elapsed_ms", optional=True)
    if hit and first_step is None:
        raise UsageError("hit=true requires first_hit_step")
    return {
        "sample_id": sample_id, "hit": hit, "wrong_cases": wrong,
        "candidates_examined": candidate_examined,
        "full_body_reads": full_body, "reference_lookups": refs,
        "first_hit_step": first_step, "tokens": tokens, "elapsed_ms": elapsed,
    }


def _records(data: Any) -> List[Dict[str, Any]]:
    items = data.get("samples") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise UsageError("usage data must be a non-empty list or {samples: [...]}")
    out = [validate_record(item) for item in items]
    ids = [item["sample_id"] for item in out]
    if len(set(ids)) != len(ids):
        raise UsageError("usage sample_id must be unique")
    return out


def summarize(data: Any) -> Dict[str, Any]:
    records = _records(data)
    hits = sum(1 for item in records if item["hit"])
    wrong_values = [item["wrong_cases"] for item in records]
    result: Dict[str, Any] = {
        "n": len(records),
        "hits": hits,
        "hit_rate": hits / len(records),
        "wrong_cases": (sum(wrong_values) if all(v is not None for v in wrong_values) else None),
    }
    for field in EFFICIENCY_FIELDS:
        values = [item[field] for item in records if item[field] is not None]
        result[field] = (sum(values) / len(values)) if values else None
    return result


def compare(baseline: Any, candidate: Any) -> Dict[str, Any]:
    """准确率不降、wrong_case 不增，且至少一个效率项改善、没有效率项变差。"""
    b = {item["sample_id"]: item for item in _records(baseline)}
    c = {item["sample_id"]: item for item in _records(candidate)}
    if set(b) != set(c):
        raise UsageError("baseline/candidate sample_id sets must match")
    b_sum = summarize(list(b.values()))
    c_sum = summarize(list(c.values()))
    reasons = []
    if c_sum["hits"] < b_sum["hits"]:
        reasons.append("accuracy_regressed")
    if b_sum["wrong_cases"] is None or c_sum["wrong_cases"] is None:
        reasons.append("wrong_cases_unknown")
    elif c_sum["wrong_cases"] > b_sum["wrong_cases"]:
        reasons.append("wrong_cases_increased")
    deltas = {}
    improved = 0
    worsened = 0
    for field in EFFICIENCY_FIELDS:
        bv, cv = b_sum[field], c_sum[field]
        if bv is None or cv is None:
            deltas[field] = None
            continue
        delta = cv - bv
        deltas[field] = delta
        if delta < 0:
            improved += 1
        elif delta > 0:
            worsened += 1
    if worsened:
        reasons.append("efficiency_regressed")
    if not improved:
        reasons.append("no_efficiency_improvement")
    if any(r in ("accuracy_regressed", "wrong_cases_increased", "efficiency_regressed") for r in reasons):
        decision = "reject"
    elif reasons:
        decision = "insufficient"
    else:
        decision = "accept"
    return {
        "decision": decision,
        "baseline": b_sum, "candidate": c_sum, "deltas": deltas,
        "reasons": reasons,
    }


def _elapsed_ms(document: Dict[str, Any], events: List[Dict[str, Any]]) -> Optional[float]:
    stamps = []
    for value in (document.get("created_at"), document.get("updated_at")):
        if isinstance(value, str):
            try:
                stamps.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
            except ValueError:
                pass
    for event in events:
        value = event.get("ts")
        if isinstance(value, str):
            try:
                stamps.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
            except ValueError:
                pass
    if len(stamps) < 2:
        return None
    return max(0.0, (max(stamps) - min(stamps)).total_seconds() * 1000)


def from_trace(document: Any, expected_case: Optional[str] = None) -> Dict[str, Any]:
    """从 diagnose trace 推导一条 usage 记录；缺失项不补 0。"""
    if not isinstance(document, dict):
        raise UsageError("trace must be an object")
    events = document.get("trace")
    if not isinstance(events, list):
        raise UsageError("trace.trace must be a list")
    checks = {
        str(event.get("case")) for event in events
        if event.get("action") == "quickly_check" and event.get("case")
    }
    full_loads = {
        str(event.get("case")) for event in events
        if event.get("action") == "load_full" and event.get("case")
    }
    if not full_loads:
        full_loads = checks
    considered = None
    for event in events:
        if event.get("action") == "load_index":
            value = event.get("considered_candidates")
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                considered = value
            elif isinstance(value, list):
                considered = len(value)
    candidates = considered if considered is not None else (len(checks) if checks else None)
    refs = sum(
        1 for event in events
        if event.get("action") == "reference_lookup" and event.get("outcome") != "skipped"
    )
    hit_event = next((event for event in events if event.get("action") == "hit"), None)
    hit_case = str(hit_event.get("case")) if hit_event and hit_event.get("case") else None
    if expected_case:
        hit = hit_case == expected_case
        wrong = 1 if hit_case and not hit else 0
    else:
        hit = hit_event is not None
        wrong = None
    first_step = None
    if hit and hit_event is not None:
        step = hit_event.get("step")
        if isinstance(step, int) and not isinstance(step, bool) and step >= 0:
            first_step = step
    return validate_record({
        "sample_id": str(document.get("session_id") or "unknown"),
        "hit": hit,
        "first_hit_step": first_step,
        "candidates_examined": candidates,
        "full_body_reads": (len(full_loads) if full_loads else (len(checks) if checks else None)),
        "reference_lookups": refs,
        "wrong_cases": wrong,
        "tokens": None,
        "elapsed_ms": _elapsed_ms(document, events),
    })


def evaluate(data: Any) -> Dict[str, Any]:
    """单个 rollout 集只出观测，不做 accept/reject。"""
    return summarize(data)
