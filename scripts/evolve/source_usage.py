"""源码访问使用记录：从 diagnose source_analysis 事件推导。

只做观测与门禁，不下载源码、不执行查询。缺失字段保持 None；真实 trace
没有的 cache/download 数据不补 0。
"""

from typing import Any, Dict, List, Optional

from .statistics import paired_diff_ci
from .usage import (EPSILON, check_bool, check_int, check_num, count_directions, decide,
                    diff_intervals, elapsed_state as elapsed_direction,
                    pair_rows, partial_regressed, parse_records)

OBSERVED_FIELDS = ("files_read", "tool_calls", "fetch_calls", "grep_calls",
                  "followups", "downloads", "bytes", "elapsed_ms")
GATE_FIELDS = ("files_read", "tool_calls", "fetch_calls", "grep_calls",
               "followups", "elapsed_ms")

class SourceUsageError(ValueError):
    pass


def validate_record(record: Any) -> Dict[str, Any]:
    if not isinstance(record, dict):
        raise SourceUsageError("source usage record must be an object")
    sample_id = record.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id.strip():
        raise SourceUsageError("sample_id is required")
    out = {"sample_id": sample_id}
    for name in OBSERVED_FIELDS:
        if name == "elapsed_ms":
            out[name] = check_num(record.get(name), name, SourceUsageError, optional=True)
        else:
            out[name] = check_int(record.get(name), name, SourceUsageError, optional=True)
    out["cache_hits"] = check_int(record.get("cache_hits"), "cache_hits",
                                  SourceUsageError, optional=True)
    out["source_ok"] = check_bool(record.get("source_ok"), "source_ok",
                                  SourceUsageError, optional=True)
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
    return parse_records(data, validate_record, SourceUsageError, "source usage")


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
    paired = pair_rows(b, c, ids, GATE_FIELDS, aggregate="sum")
    deltas = {field: paired[field]["delta"] for field in GATE_FIELDS}
    deltas["cache_hits"] = None
    elapsed_diffs = [c[i]["elapsed_ms"] - b[i]["elapsed_ms"] for i in ids
                     if b[i]["elapsed_ms"] is not None and c[i]["elapsed_ms"] is not None]
    elapsed_delta = paired["elapsed_ms"]["delta"]
    if elapsed_delta is None or abs(elapsed_delta) <= EPSILON:
        elapsed = "neutral"
    elif paired["elapsed_ms"]["unknown"]:
        elapsed = "unconfirmed"
    else:
        elapsed = elapsed_direction(elapsed_delta, paired_diff_ci(elapsed_diffs))
    counts = count_directions(paired, GATE_FIELDS,
                              elapsed_field="elapsed_ms", elapsed=elapsed)
    if (elapsed == "unconfirmed" and elapsed_delta is not None
            and elapsed_delta > 0):
        reasons.append("source_elapsed_inconclusive")
    if partial_regressed(paired, counts["partial"]):
        reasons.append("source_efficiency_partial_unknown")
    if counts["worsened"]:
        reasons.append("source_efficiency_regressed")
    if not counts["improved"]:
        reasons.append("no_source_efficiency_improvement")
    decision = decide(reasons, ("source_correctness_regressed",
                                "source_efficiency_regressed"))
    ci = diff_intervals(b, c, ids, GATE_FIELDS)
    for field in GATE_FIELDS:
        if paired[field]["delta"] is not None:
            bs[field], cs[field] = paired[field]["baseline"], paired[field]["candidate"]
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
