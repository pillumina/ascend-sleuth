"""用量记录的共用骨架：数值校验、按样本配对、区间与 accept/insufficient/reject 判定。

三个用量维度（知识 / 源码 / 工具）的字段与判定理由不同，但下面这些形状相同：
非负数校验、``{samples: [...]}`` 或裸列表的解析、按样本配对后的和或均值、
逐字段置信区间、连续成本项的方向判定、以及 accept/insufficient/reject 的收尾。

这里只收共用的机制，不替各维度决定理由文案与准确率口径——那些留在各自的模块。
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from .statistics import paired_diff_ci

EPSILON = 1e-9


def check_int(value: Any, name: str, error, *, optional: bool = False) -> Optional[int]:
    if value is None and optional:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise error(f"{name} must be a non-negative integer")
    return value


def check_num(value: Any, name: str, error, *, optional: bool = False) -> Optional[float]:
    if value is None and optional:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise error(f"{name} must be a non-negative number")
    return float(value)


def check_bool(value: Any, name: str, error, *, optional: bool = False) -> Optional[bool]:
    if value is None and optional:
        return None
    if not isinstance(value, bool):
        raise error(f"{name} must be boolean or null" if optional else f"{name} must be boolean")
    return value


def parse_records(data: Any, validate: Callable[[Any], Dict[str, Any]],
                  error, label: str) -> List[Dict[str, Any]]:
    """接受裸列表或 ``{samples: [...]}``；逐条校验并拒绝重复 sample_id。"""
    items = data.get("samples") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise error(f"{label} data must be a non-empty list or {{samples: [...]}}")
    out = [validate(item) for item in items]
    ids = [item["sample_id"] for item in out]
    if len(set(ids)) != len(ids):
        raise error(f"{label} sample_id must be unique")
    return out


def pair_rows(baseline: Dict[str, Dict[str, Any]], candidate: Dict[str, Dict[str, Any]],
              ids: List[str], fields: Tuple[str, ...], *,
              aggregate: str = "sum") -> Dict[str, Dict[str, Any]]:
    """只用两侧都有值的样本算这一项：和或均值，缺失数单独报。

    两侧样本集不同时，各自求和/求均值会把「一侧缺数据」算成「另一侧变好或变差」。
    """
    if aggregate not in ("sum", "mean"):
        raise ValueError(f"unknown aggregate {aggregate!r}")
    out: Dict[str, Dict[str, Any]] = {}
    for field in fields:
        pairs = [(baseline[i][field], candidate[i][field]) for i in ids
                 if baseline[i][field] is not None and candidate[i][field] is not None]
        if not pairs:
            out[field] = {"n": 0, "unknown": len(ids), "baseline": None,
                          "candidate": None, "delta": None}
            continue
        total_b = sum(pair[0] for pair in pairs)
        total_c = sum(pair[1] for pair in pairs)
        if aggregate == "mean":
            total_b /= len(pairs)
            total_c /= len(pairs)
        out[field] = {"n": len(pairs), "unknown": len(ids) - len(pairs),
                      "baseline": total_b, "candidate": total_c,
                      "delta": total_c - total_b}
    return out


def diff_intervals(baseline: Dict[str, Dict[str, Any]],
                   candidate: Dict[str, Dict[str, Any]], ids: List[str],
                   fields: Tuple[str, ...]) -> Dict[str, Dict[str, Any]]:
    intervals: Dict[str, Dict[str, Any]] = {}
    for field in fields:
        diffs = [candidate[i][field] - baseline[i][field] for i in ids
                 if baseline[i][field] is not None and candidate[i][field] is not None]
        intervals[field] = paired_diff_ci(diffs)
    return intervals


def elapsed_state(delta: Optional[float], interval: Dict[str, Any]) -> str:
    """连续成本项只在置信区间排除 0 时才判方向。"""
    if delta is None or abs(delta) <= EPSILON:
        return "neutral"
    low, high = interval.get("low"), interval.get("high")
    if low is not None and low > 0:
        return "worse"
    if high is not None and high < 0:
        return "better"
    return "unconfirmed"


def count_directions(paired: Dict[str, Dict[str, Any]], fields: Tuple[str, ...], *,
                     higher_is_better: Tuple[str, ...] = (),
                     elapsed_field: Optional[str] = None,
                     elapsed: str = "neutral") -> Dict[str, Any]:
    """逐字段数改善/变差；缺失一侧的字段记 partial，不参与计数。"""
    improved = worsened = 0
    partial: List[str] = []
    for field in fields:
        if field == elapsed_field:
            continue
        row = paired[field]
        if row["delta"] is None:
            continue
        if row["unknown"]:
            partial.append(field)
            continue
        delta = row["delta"]
        if field in higher_is_better:
            if delta > EPSILON:
                improved += 1
            elif delta < -EPSILON:
                worsened += 1
        else:
            if delta < -EPSILON:
                improved += 1
            elif delta > EPSILON:
                worsened += 1
    if elapsed == "worse":
        worsened += 1
    elif elapsed == "better":
        improved += 1
    return {"improved": improved, "worsened": worsened, "partial": partial}


def partial_regressed(paired: Dict[str, Dict[str, Any]], partial: List[str], *,
                      higher_is_better: Tuple[str, ...] = ()) -> bool:
    for field in partial:
        delta = paired[field]["delta"]
        if delta is None:
            continue
        if field in higher_is_better:
            if delta < -EPSILON:
                return True
        elif delta > EPSILON:
            return True
    return False


def decide(reasons: List[str], reject_reasons: Tuple[str, ...]) -> str:
    if any(reason in reject_reasons for reason in reasons):
        return "reject"
    if reasons:
        return "insufficient"
    return "accept"
