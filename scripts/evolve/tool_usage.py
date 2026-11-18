"""工具使用与工具性能：从 diagnose trace 推导，做 tooling 改动的门禁。

和 ``source_usage`` 的区别：那一层看 agent 的源码访问行为（files/tool/fetch/
grep），这一层看工具本身的运行情况（缓存命中、重试、工具耗时、失败）。
两者都只读 trace，不执行工具。

字段缺失一律记 unknown，不补 0。``resolved`` 由外部（judge）绑定，不在
trace 里猜。
"""

from typing import Any, Dict, List, Optional

from .source_usage import SourceUsageError
from .source_usage import from_trace as source_from_trace

GATE_FIELDS = ("tool_calls", "fetch_calls", "grep_calls", "retries",
               "cache_hits", "tool_ms")
LOWER_IS_BETTER = ("tool_calls", "fetch_calls", "grep_calls", "retries", "tool_ms")
HIGHER_IS_BETTER = ("cache_hits",)
OBSERVED_FIELDS = GATE_FIELDS + ("failures",)
EPSILON = 1e-9


class ToolUsageError(ValueError):
    pass


def _int(value: Any, name: str, *, optional: bool = False) -> Optional[int]:
    if value is None and optional:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ToolUsageError(f"{name} must be a non-negative integer")
    return value


def _num(value: Any, name: str, *, optional: bool = False) -> Optional[float]:
    if value is None and optional:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise ToolUsageError(f"{name} must be a non-negative number")
    return float(value)


def validate_record(record: Any) -> Dict[str, Any]:
    if not isinstance(record, dict):
        raise ToolUsageError("tool usage record must be an object")
    sample_id = record.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id.strip():
        raise ToolUsageError("sample_id is required")
    out: Dict[str, Any] = {"sample_id": sample_id}
    for field in OBSERVED_FIELDS:
        out[field] = _num(record.get(field), field, optional=True) \
            if field == "tool_ms" else _int(record.get(field), field, optional=True)
    resolved = record.get("resolved")
    if resolved is not None and not isinstance(resolved, bool):
        raise ToolUsageError("resolved must be boolean or null")
    out["resolved"] = resolved
    return out


def _records(data: Any) -> List[Dict[str, Any]]:
    items = data.get("samples") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ToolUsageError("tool usage data must be a non-empty list or {samples: [...]}")
    out = [validate_record(item) for item in items]
    ids = [item["sample_id"] for item in out]
    if len(set(ids)) != len(ids):
        raise ToolUsageError("tool usage sample_id must be unique")
    return out


def summarize(data: Any) -> Dict[str, Any]:
    records = _records(data)
    result: Dict[str, Any] = {"n": len(records)}
    for field in OBSERVED_FIELDS:
        values = [item[field] for item in records if item[field] is not None]
        result[field] = sum(values) if values else None
    resolved = [item["resolved"] for item in records]
    result["resolved"] = sum(1 for item in resolved if item) \
        if all(item is not None for item in resolved) else None
    return result


def _paired(b, c, ids, field):
    pairs = [(b[i][field], c[i][field]) for i in ids
             if b[i][field] is not None and c[i][field] is not None]
    if not pairs:
        return {"n": 0, "unknown": len(ids), "baseline": None,
                "candidate": None, "delta": None}
    total_b = sum(pair[0] for pair in pairs)
    total_c = sum(pair[1] for pair in pairs)
    return {"n": len(pairs), "unknown": len(ids) - len(pairs),
            "baseline": total_b, "candidate": total_c, "delta": total_c - total_b}


def compare(baseline: Any, candidate: Any) -> Dict[str, Any]:
    """工具结论不降，且至少一项工具指标改善、没有项变差。逐样本配对。"""
    b = {item["sample_id"]: item for item in _records(baseline)}
    c = {item["sample_id"]: item for item in _records(candidate)}
    if set(b) != set(c):
        raise ToolUsageError("baseline/candidate sample_id sets must match")
    ids = sorted(b)
    bs, cs = summarize([b[i] for i in ids]), summarize([c[i] for i in ids])
    reasons: List[str] = []
    resolved_pairs = [(b[i]["resolved"], c[i]["resolved"]) for i in ids
                      if b[i]["resolved"] is not None and c[i]["resolved"] is not None]
    if len(resolved_pairs) != len(ids):
        reasons.append("resolved_unknown")
        bs["resolved"] = cs["resolved"] = None
    else:
        b_ok = sum(1 for pair in resolved_pairs if pair[0])
        c_ok = sum(1 for pair in resolved_pairs if pair[1])
        bs["resolved"], cs["resolved"] = b_ok, c_ok
        if c_ok < b_ok:
            reasons.append("resolved_regressed")
    paired = {field: _paired(b, c, ids, field) for field in GATE_FIELDS}
    deltas = {field: paired[field]["delta"] for field in GATE_FIELDS}
    improved = worsened = 0
    partial: List[str] = []
    for field in GATE_FIELDS:
        row = paired[field]
        if row["delta"] is None:
            continue
        if row["unknown"]:
            partial.append(field)
            continue
        delta = row["delta"]
        if field in HIGHER_IS_BETTER:
            if delta > EPSILON:
                improved += 1
            elif delta < -EPSILON:
                worsened += 1
        else:
            if delta < -EPSILON:
                improved += 1
            elif delta > EPSILON:
                worsened += 1
    partial_regressed = any(
        paired[field]["delta"] is not None and (
            paired[field]["delta"] < -EPSILON if field in HIGHER_IS_BETTER
            else paired[field]["delta"] > EPSILON)
        for field in partial
    )
    if partial_regressed:
        reasons.append("tool_efficiency_partial_unknown")
    if worsened:
        reasons.append("tool_efficiency_regressed")
    if not improved:
        reasons.append("no_tool_efficiency_improvement")
    if any(r in ("resolved_regressed", "tool_efficiency_regressed") for r in reasons):
        decision = "reject"
    elif reasons:
        decision = "insufficient"
    else:
        decision = "accept"
    for field in GATE_FIELDS:
        bs[field] = paired[field]["baseline"]
        cs[field] = paired[field]["candidate"]
    return {"decision": decision, "baseline": bs, "candidate": cs,
            "deltas": deltas, "reasons": reasons, "paired": paired}


def from_trace(document: Any, resolved: Optional[bool] = None) -> Dict[str, Any]:
    """从 trace 的 ``source_analysis`` 事件读工具指标；没有事件就报错。"""
    if not isinstance(document, dict):
        raise ToolUsageError("trace must be an object")
    events = [e for e in document.get("trace") or []
              if isinstance(e, dict) and e.get("action") == "source_analysis"]
    if not events:
        raise ToolUsageError("trace has no source_analysis events")
    try:
        source = source_from_trace(document)
    except SourceUsageError as exc:
        raise ToolUsageError(str(exc)) from exc
    retries = cache_hits = 0
    tool_ms = 0.0
    failures = 0
    has_ms = has_retries = has_cache = has_failures = has_calls = False
    for event in events:
        current: List[str] = []
        if isinstance(event.get("tool_calls"), list):
            has_calls = True
            current = [str(call) for call in event["tool_calls"]]
        if isinstance(event.get("retries"), int):
            has_retries = True
            retries += event["retries"]
        elif current:
            has_retries = True
            retries += sum(1 for call in current if "retry" in call.lower())
        if isinstance(event.get("cache_hits"), int):
            has_cache = True
            cache_hits += event["cache_hits"]
        if isinstance(event.get("tool_ms"), (int, float)):
            tool_ms += float(event["tool_ms"])
            has_ms = True
        if isinstance(event.get("fetch_exit"), int):
            has_failures = True
            if event["fetch_exit"] != 0:
                failures += 1
        if event.get("verify") in ("hit", "miss", "skipped"):
            has_failures = True
            if event.get("verify") == "miss":
                failures += 1
    record = validate_record({
        "sample_id": str(document.get("session_id") or "unknown"),
        "tool_calls": source["tool_calls"],
        "fetch_calls": source["fetch_calls"],
        "grep_calls": source["grep_calls"],
        "retries": retries if (has_retries or has_calls) else None,
        "cache_hits": cache_hits if has_cache else None,
        "tool_ms": tool_ms if has_ms else None,
        "failures": failures if has_failures else None,
        "resolved": resolved,
    })
    return record


def evaluate(data: Any) -> Dict[str, Any]:
    """单个 rollout 集只出观测，不做 accept/reject。"""
    return summarize(data)
