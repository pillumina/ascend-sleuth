"""源码访问使用记录：从 diagnose source_analysis 事件推导。

只做观测与门禁，不下载源码、不执行查询。缺失字段保持 None；真实 trace
没有的 cache/download 数据不补 0。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from .statistics import paired_diff_ci

OBSERVED_FIELDS = ("files_read", "tool_calls", "fetch_calls", "grep_calls",
                  "followups", "downloads", "bytes", "elapsed_ms")
GATE_FIELDS = ("files_read", "tool_calls", "fetch_calls", "grep_calls",
               "followups", "elapsed_ms")
EPSILON = 1e-9


class SourceUsageError(ValueError):
    pass


def _int(value: Any, name: str, *, optional: bool = False) -> Optional[int]:
    if value is None and optional:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SourceUsageError(f"{name} must be a non-negative integer")
    return value


def _num(value: Any, name: str, *, optional: bool = False) -> Optional[float]:
    if value is None and optional:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise SourceUsageError(f"{name} must be a non-negative number")
    return float(value)


def validate_record(record: Any) -> Dict[str, Any]:
    if not isinstance(record, dict):
        raise SourceUsageError("source usage record must be an object")
    sample_id = record.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id.strip():
        raise SourceUsageError("sample_id is required")
    out = {"sample_id": sample_id}
    for name in OBSERVED_FIELDS:
        out[name] = _int(record.get(name), name, optional=True) if name != "elapsed_ms" else _num(record.get(name), name, optional=True)
    out["cache_hits"] = _int(record.get("cache_hits"), "cache_hits", optional=True)
    out["source_ok"] = record.get("source_ok")
    if out["source_ok"] is not None and not isinstance(out["source_ok"], bool):
        raise SourceUsageError("source_ok must be boolean or null")
    repos = record.get("repos") or []
    refs = record.get("refs") or []
    if not isinstance(repos, list) or not all(isinstance(x, str) for x in repos):
        raise SourceUsageError("repos must be a string list")
    if not isinstance(refs, list) or not all(isinstance(x, str) for x in refs):
        raise SourceUsageError("refs must be a string list")
    out["repos"] = sorted(set(repos))
    out["refs"] = sorted(set(refs))
    return out


def _records(data: Any) -> List[Dict[str, Any]]:
    items = data.get("samples") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise SourceUsageError("source usage data must be a non-empty list")
    out = [validate_record(item) for item in items]
    ids = [item["sample_id"] for item in out]
    if len(set(ids)) != len(ids):
        raise SourceUsageError("source usage sample_id must be unique")
    return out


def _sum(values: List[Optional[int]]) -> Optional[int]:
    return sum(values) if all(v is not None for v in values) else None


def summarize(data: Any) -> Dict[str, Any]:
    records = _records(data)
    result = {"n": len(records), "repos": sorted({r for item in records for r in item["repos"]}),
              "refs": sorted({r for item in records for r in item["refs"]})}
    for field in OBSERVED_FIELDS:
        values = [item[field] for item in records]
        result[field] = _sum(values) if field != "elapsed_ms" else (sum(values) if all(v is not None for v in values) else None)
    result["cache_hits"] = _sum([item["cache_hits"] for item in records])
    ok = [item["source_ok"] for item in records]
    result["source_ok"] = (sum(1 for item in ok if item) if all(v is not None for v in ok) else None)
    return result


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
    """源码结论不降，且效率项至少一项改善、没有项变差。

    效率项逐样本配对：两侧都有值的样本才算这一项的总数。只在一侧有值的
    样本不进入总数——两侧样本集不同时，各自求和会把「一侧缺数据」算成
    「另一侧变好/变差」。
    """
    b = {item["sample_id"]: item for item in _records(baseline)}
    c = {item["sample_id"]: item for item in _records(candidate)}
    if set(b) != set(c):
        raise SourceUsageError("baseline/candidate sample_id sets must match")
    ids = sorted(b)
    bs, cs = summarize([b[i] for i in ids]), summarize([c[i] for i in ids])
    reasons: List[str] = []
    ok_pairs = [(b[i]["source_ok"], c[i]["source_ok"]) for i in ids
                if b[i]["source_ok"] is not None and c[i]["source_ok"] is not None]
    if len(ok_pairs) != len(ids):
        reasons.append("source_correctness_unknown")
        bs["source_ok"] = cs["source_ok"] = None
    else:
        b_ok = sum(1 for pair in ok_pairs if pair[0])
        c_ok = sum(1 for pair in ok_pairs if pair[1])
        bs["source_ok"], cs["source_ok"] = b_ok, c_ok
        if c_ok < b_ok:
            reasons.append("source_correctness_regressed")
    paired: Dict[str, Dict[str, Any]] = {}
    deltas = {}
    improved = worsened = 0
    partial: List[str] = []
    for field in GATE_FIELDS:
        pairs = [(b[i][field], c[i][field]) for i in ids
                 if b[i][field] is not None and c[i][field] is not None]
        if not pairs:
            paired[field] = {"n": 0, "unknown": len(ids), "baseline": None,
                             "candidate": None, "delta": None}
            deltas[field] = None
            continue
        total_b = sum(pair[0] for pair in pairs)
        total_c = sum(pair[1] for pair in pairs)
        paired[field] = {"n": len(pairs), "unknown": len(ids) - len(pairs),
                         "baseline": total_b, "candidate": total_c,
                         "delta": total_c - total_b}
        bs[field], cs[field] = total_b, total_c
        deltas[field] = total_c - total_b
        if field == "elapsed_ms":
            continue
        if paired[field]["unknown"]:
            partial.append(field)
            continue
        if deltas[field] < -EPSILON:
            improved += 1
        elif deltas[field] > EPSILON:
            worsened += 1
    deltas["cache_hits"] = None
    elapsed_diffs = [c[i]["elapsed_ms"] - b[i]["elapsed_ms"] for i in ids
                     if b[i]["elapsed_ms"] is not None and c[i]["elapsed_ms"] is not None]
    elapsed_delta = paired["elapsed_ms"]["delta"]
    if elapsed_delta is None or abs(elapsed_delta) <= EPSILON:
        elapsed_state = "neutral"
    elif paired["elapsed_ms"]["unknown"]:
        elapsed_state = "unconfirmed"
    else:
        elapsed_state = _elapsed_state(elapsed_delta, paired_diff_ci(elapsed_diffs))
    if elapsed_state == "worse":
        worsened += 1
    elif elapsed_state == "better":
        improved += 1
    elif (elapsed_state == "unconfirmed"
          and paired["elapsed_ms"]["delta"] is not None
          and paired["elapsed_ms"]["delta"] > 0):
        reasons.append("source_elapsed_inconclusive")
    if any(paired[field]["delta"] is not None and paired[field]["delta"] > EPSILON
           for field in partial):
        reasons.append("source_efficiency_partial_unknown")
    if worsened:
        reasons.append("source_efficiency_regressed")
    if not improved:
        reasons.append("no_source_efficiency_improvement")
    if any(r in ("source_correctness_regressed", "source_efficiency_regressed") for r in reasons):
        decision = "reject"
    elif reasons:
        decision = "insufficient"
    else:
        decision = "accept"
    ci = {}
    for field in GATE_FIELDS:
        diffs = [c[i][field] - b[i][field] for i in ids
                 if b[i][field] is not None and c[i][field] is not None]
        ci[field] = paired_diff_ci(diffs)
    return {"decision": decision, "baseline": bs, "candidate": cs,
            "deltas": deltas, "reasons": reasons, "paired": paired, "ci": ci}


def _elapsed(document: Dict[str, Any], events: List[Dict[str, Any]]) -> Optional[float]:
    stamps = []
    for event in events:
        value = event.get("ts")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            stamps.append(float(value))
    if len(stamps) < 2:
        return None
    return max(0.0, max(stamps) - min(stamps))


def from_trace(document: Any, source_ok: Optional[bool] = None) -> Dict[str, Any]:
    if not isinstance(document, dict):
        raise SourceUsageError("trace must be an object")
    events = [e for e in document.get("trace") or [] if e.get("action") == "source_analysis"]
    if not events:
        raise SourceUsageError("trace has no source_analysis events")
    repos = sorted({str(e["repo"]) for e in events if e.get("repo")})
    refs = sorted({str(e["ref"]) for e in events if e.get("ref")})
    files = []
    calls = None
    fetches = None
    greps = None
    followups = None
    for e in events:
        for item in (e.get("files_read") or e.get("files") or []):
            files.append(str(item))
        tool_calls = e.get("tool_calls")
        derived_fetch = derived_grep = 0
        if isinstance(tool_calls, list):
            calls = (calls or 0) + len(tool_calls)
            derived_fetch = sum(
                1 for call in tool_calls
                if "src_fetch.py" in str(call) or "git fetch" in str(call)
            )
            derived_grep = sum(1 for call in tool_calls if "grep" in str(call))
        if isinstance(e.get("fetch_calls"), int):
            fetches = (fetches or 0) + e["fetch_calls"]
        elif isinstance(tool_calls, list):
            fetches = (fetches or 0) + derived_fetch
        if isinstance(e.get("grep_calls"), int):
            greps = (greps or 0) + e["grep_calls"]
        elif isinstance(tool_calls, list):
            greps = (greps or 0) + derived_grep
        if isinstance(e.get("followup"), list):
            followups = (followups or 0) + len(e["followup"])
    return validate_record({
        "sample_id": str(document.get("session_id") or "unknown"),
        "repos": repos, "refs": refs,
        "files_read": len(set(files)), "tool_calls": calls,
        "fetch_calls": fetches, "grep_calls": greps,
        "followups": followups,
        "elapsed_ms": _elapsed(document, events),
        "source_ok": source_ok,
    })


def evaluate(data: Any) -> Dict[str, Any]:
    """单个 rollout 集只出观测，不做 accept/reject。"""
    return summarize(data)
