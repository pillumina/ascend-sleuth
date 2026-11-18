"""源码访问使用记录：从 diagnose source_analysis 事件推导。

只做观测与门禁，不下载源码、不执行查询。缺失字段保持 None；真实 trace
没有的 cache/download 数据不补 0。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

LOWER_FIELDS = ("files_read", "tool_calls", "fetch_calls", "grep_calls",
                "followups", "downloads", "bytes", "elapsed_ms")


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
    for name in LOWER_FIELDS:
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
    for field in LOWER_FIELDS:
        values = [item[field] for item in records]
        result[field] = _sum(values) if field != "elapsed_ms" else (sum(values) if all(v is not None for v in values) else None)
    result["cache_hits"] = _sum([item["cache_hits"] for item in records])
    ok = [item["source_ok"] for item in records]
    result["source_ok"] = (sum(1 for item in ok if item) if all(v is not None for v in ok) else None)
    return result


def compare(baseline: Any, candidate: Any) -> Dict[str, Any]:
    b = {item["sample_id"]: item for item in _records(baseline)}
    c = {item["sample_id"]: item for item in _records(candidate)}
    if set(b) != set(c):
        raise SourceUsageError("baseline/candidate sample_id sets must match")
    bs, cs = summarize(list(b.values())), summarize(list(c.values()))
    reasons: List[str] = []
    if bs["source_ok"] is None or cs["source_ok"] is None:
        reasons.append("source_correctness_unknown")
    elif cs["source_ok"] < bs["source_ok"]:
        reasons.append("source_correctness_regressed")
    deltas = {}
    improved = worsened = 0
    for field in ("files_read", "tool_calls", "fetch_calls", "grep_calls",
                  "followups", "downloads", "bytes", "elapsed_ms"):
        bv, cv = bs[field], cs[field]
        if bv is None or cv is None:
            deltas[field] = None
            continue
        delta = cv - bv
        deltas[field] = delta
        improved += 1 if delta < 0 else 0
        worsened += 1 if delta > 0 else 0
    if bs["cache_hits"] is not None and cs["cache_hits"] is not None:
        delta = cs["cache_hits"] - bs["cache_hits"]
        deltas["cache_hits"] = delta
        improved += 1 if delta > 0 else 0
        worsened += 1 if delta < 0 else 0
    else:
        deltas["cache_hits"] = None
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
    return {"decision": decision, "baseline": bs, "candidate": cs,
            "deltas": deltas, "reasons": reasons}


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
        if tool_calls:
            calls = (calls or 0) + len(tool_calls)
            fetches = (fetches or 0) + sum(
                1 for call in tool_calls
                if "src_fetch.py" in str(call) or "git fetch" in str(call)
            )
            greps = (greps or 0) + sum(1 for call in tool_calls if "grep" in str(call))
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
