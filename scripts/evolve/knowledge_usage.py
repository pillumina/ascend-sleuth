"""知识使用效率的观测与门禁。

这里不执行 diagnose，也不读 case 正文；只校验一条诊断 rollout 暴露的
使用记录。字段全部来自 trace/实验记录，缺失就记 unknown，不补零。
"""

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .harness_usage import read_session
from .statistics import paired_diff_ci

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
    resolution = record.get("resolution_ok")
    if resolution is not None and not isinstance(resolution, bool):
        raise UsageError("resolution_ok must be boolean or null")
    if hit and first_step is None:
        raise UsageError("hit=true requires first_hit_step")
    return {
        "sample_id": sample_id, "hit": hit, "wrong_cases": wrong,
        "candidates_examined": candidate_examined,
        "full_body_reads": full_body, "reference_lookups": refs,
        "first_hit_step": first_step, "tokens": tokens, "elapsed_ms": elapsed,
        "resolution_ok": resolution,
    }


def _tokens_from_doc(document: Dict[str, Any]) -> Optional[int]:
    """trace 显式写了就用；没写就按 harness_session 读 DSH 会话累计。"""
    value = document.get("tokens")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, dict):
        total = value.get("total")
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            return total
        items = [item for item in value.values()
                 if isinstance(item, int) and not isinstance(item, bool) and item >= 0]
        if items:
            return sum(items)
    session = document.get("harness_session")
    if isinstance(session, str) and session:
        usage = read_session(session)
        if usage and usage.get("tokens") is not None:
            total = usage["tokens"]
            start = document.get("tokens_start")
            if isinstance(start, int) and not isinstance(start, bool) and 0 <= start <= total:
                return total - start
            return total
    return None


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
    resolutions = [item["resolution_ok"] for item in records]
    result["resolved"] = (sum(1 for item in resolutions if item)
                          if all(item is not None for item in resolutions) else None)
    return result


EPSILON = 1e-9


def _paired_row(b: Dict[str, Dict[str, Any]], c: Dict[str, Dict[str, Any]],
                ids: List[str], field: str) -> Dict[str, Any]:
    """按样本配对：只用两侧都有值的样本算均值，缺失数单独报。"""
    pairs = [(b[i][field], c[i][field]) for i in ids
             if b[i][field] is not None and c[i][field] is not None]
    if not pairs:
        return {"n": 0, "unknown": len(ids), "baseline": None,
                "candidate": None, "delta": None}
    mean_b = sum(pair[0] for pair in pairs) / len(pairs)
    mean_c = sum(pair[1] for pair in pairs) / len(pairs)
    return {"n": len(pairs), "unknown": len(ids) - len(pairs),
            "baseline": mean_b, "candidate": mean_c, "delta": mean_c - mean_b}


def _elapsed_state(delta, ci):
    """连续成本项只在置信区间排除 0 时才判方向。"""
    if delta is None or abs(delta) <= EPSILON:
        return "neutral"
    low, high = ci.get("low"), ci.get("high")
    if low is not None and low > 0:
        return "worse"
    if high is not None and high < 0:
        return "better"
    return "unconfirmed"


def compare(baseline: Any, candidate: Any) -> Dict[str, Any]:
    """准确率不降、wrong_case 不增，且至少一个效率项改善、没有效率项变差。

    效率项逐样本配对：两侧都有值的样本才算这一项的均值。只在一侧有值的
    样本不进入均值，也不当改善或回退证据——两侧样本集不同时，各自求均值
    会把「一侧缺数据」算成「另一侧变好/变差」。
    """
    b = {item["sample_id"]: item for item in _records(baseline)}
    c = {item["sample_id"]: item for item in _records(candidate)}
    if set(b) != set(c):
        raise UsageError("baseline/candidate sample_id sets must match")
    ids = sorted(b)
    b_sum = summarize([b[i] for i in ids])
    c_sum = summarize([c[i] for i in ids])
    reasons = []
    resolution_complete = all(
        b[i]["resolution_ok"] is not None and c[i]["resolution_ok"] is not None
        for i in ids
    )
    if c_sum["hits"] < b_sum["hits"]:
        reasons.append("accuracy_regressed")
    if resolution_complete:
        resolved_b = sum(1 for i in ids if b[i]["resolution_ok"])
        resolved_c = sum(1 for i in ids if c[i]["resolution_ok"])
        b_sum["resolved"], c_sum["resolved"] = resolved_b, resolved_c
        if resolved_c < resolved_b:
            reasons.append("resolution_regressed")
    else:
        if b_sum["wrong_cases"] is None or c_sum["wrong_cases"] is None:
            reasons.append("wrong_cases_unknown")
        elif c_sum["wrong_cases"] > b_sum["wrong_cases"]:
            reasons.append("wrong_cases_increased")
    paired = {field: _paired_row(b, c, ids, field) for field in EFFICIENCY_FIELDS}
    deltas = {field: paired[field]["delta"] for field in EFFICIENCY_FIELDS}
    elapsed_diffs = [c[i]["elapsed_ms"] - b[i]["elapsed_ms"] for i in ids
                     if b[i]["elapsed_ms"] is not None and c[i]["elapsed_ms"] is not None]
    elapsed_delta = paired["elapsed_ms"]["delta"]
    if elapsed_delta is None or abs(elapsed_delta) <= EPSILON:
        elapsed_state = "neutral"
    elif paired["elapsed_ms"]["unknown"]:
        elapsed_state = "unconfirmed"
    else:
        elapsed_state = _elapsed_state(elapsed_delta, paired_diff_ci(elapsed_diffs))
    improved = 0
    worsened = 0
    partial = []
    for field in EFFICIENCY_FIELDS:
        if field == "elapsed_ms":
            continue
        row = paired[field]
        if row["delta"] is None:
            continue
        if row["unknown"]:
            partial.append(field)
            continue
        if row["delta"] < -EPSILON:
            improved += 1
        elif row["delta"] > EPSILON:
            worsened += 1
    if elapsed_state == "worse":
        worsened += 1
    elif elapsed_state == "better":
        improved += 1
    elif (elapsed_state == "unconfirmed"
          and paired["elapsed_ms"]["delta"] is not None
          and paired["elapsed_ms"]["delta"] > 0):
        reasons.append("elapsed_inconclusive")
    if any(paired[field]["delta"] is not None and paired[field]["delta"] > EPSILON
           for field in partial):
        reasons.append("efficiency_partial_unknown")
    if worsened:
        reasons.append("efficiency_regressed")
    if not improved:
        reasons.append("no_efficiency_improvement")
    if any(r in ("accuracy_regressed", "wrong_cases_increased", "resolution_regressed",
                 "efficiency_regressed") for r in reasons):
        decision = "reject"
    elif reasons:
        decision = "insufficient"
    else:
        decision = "accept"
    ci = {}
    for field in EFFICIENCY_FIELDS:
        diffs = [c[i][field] - b[i][field] for i in ids
                 if b[i][field] is not None and c[i][field] is not None]
        ci[field] = paired_diff_ci(diffs)
    b_side = dict(b_sum)
    c_side = dict(c_sum)
    for field in EFFICIENCY_FIELDS:
        b_side[field] = paired[field]["baseline"]
        c_side[field] = paired[field]["candidate"]
    return {
        "decision": decision,
        "baseline": b_side, "candidate": c_side, "deltas": deltas,
        "reasons": reasons,
        "paired": paired,
        "ci": ci,
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


def from_trace(document: Any, expected_case: Optional[str] = None,
               resolution_ok: Optional[bool] = None) -> Dict[str, Any]:
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
    full_loads = set()
    for event in events:
        if event.get("action") != "load_full":
            continue
        if event.get("case"):
            full_loads.add(str(event["case"]))
        listed = event.get("candidates")
        if isinstance(listed, list):
            full_loads.update(str(item) for item in listed if item)
    shortlist = full_loads | checks
    candidates = len(shortlist) if shortlist else None
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
        "resolution_ok": resolution_ok,
        "reference_lookups": refs,
        "wrong_cases": wrong,
        "tokens": _tokens_from_doc(document),
        "elapsed_ms": _elapsed_ms(document, events),
    })


def evaluate(data: Any) -> Dict[str, Any]:
    """单个 rollout 集只出观测，不做 accept/reject。"""
    return summarize(data)
