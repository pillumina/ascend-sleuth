"""样本池：状态机、测试集划分、来源去重与建池。

状态转换只在这里定义一次，``samples`` 与 CLI 都调用 ``check_transition``。
函数是纯的：不读文件，样本以对象或字典传入。
"""

import hashlib
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

STATUS_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    "candidate": ("active", "rejected"),
    "active": ("retired",),
    "retired": ("candidate",),
    "rejected": (),
}

# origin 与 status 正交：active + origin=core 才是 core 样本，core 不是 status。
ORIGIN_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    "field": ("core",),
    "core": (),
}

# purpose 也只走白名单：吸收把 evaluation/feedback 转 regression；evaluation 可被抽成
# test；test 失效只能退休，不转 regression；feedback 不能转 evaluation。
PURPOSE_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    "evaluation": ("evaluation", "regression", "test"),
    "feedback": ("feedback", "regression"),
    "test": ("test",),
    "regression": ("regression",),
    "cross": ("cross",),
    "scale": ("scale",),
}


def check_transition(status: str, new_status: str) -> bool:
    """状态转换是否合法。未知状态一律非法（不猜一条默认边）。"""
    return new_status in STATUS_TRANSITIONS.get(status, ())


def assert_transition(status: str, new_status: str) -> None:
    if not check_transition(status, new_status):
        raise ValueError(
            f"invalid transition: {status!r} -> {new_status!r}; "
            f"allowed from {status!r}: {list(STATUS_TRANSITIONS.get(status, ()))}"
        )


def check_origin_transition(origin: str, new_origin: str) -> bool:
    """origin 转换：field→core 允许；core→field 禁止（core 只能退休后重开候选）。"""
    return new_origin in ORIGIN_TRANSITIONS.get(origin, ())


def assert_origin_transition(origin: str, new_origin: str) -> None:
    if not check_origin_transition(origin, new_origin):
        raise ValueError(
            f"invalid origin transition: {origin!r} -> {new_origin!r}; "
            f"allowed from {origin!r}: {list(ORIGIN_TRANSITIONS.get(origin, ()))}"
        )


def check_purpose_transition(purpose: str, new_purpose: str) -> bool:
    """purpose 转换白名单；未登记的边一律非法。"""
    return new_purpose in PURPOSE_TRANSITIONS.get(purpose, ())


def assert_purpose_transition(purpose: str, new_purpose: str) -> None:
    if not check_purpose_transition(purpose, new_purpose):
        raise ValueError(
            f"invalid purpose transition: {purpose!r} -> {new_purpose!r}; "
            f"allowed: {list(PURPOSE_TRANSITIONS.get(purpose, ()))}"
        )


def purpose_transition_errors(purpose: str, new_purpose: str) -> List[str]:
    if check_purpose_transition(purpose, new_purpose):
        return []
    allowed = ", ".join(PURPOSE_TRANSITIONS.get(purpose, ())) or "(terminal)"
    return [f"invalid purpose transition: {purpose} -> {new_purpose} (allowed: {allowed})"]


def _field(sample: Any, name: str, default: Any = None) -> Any:
    if isinstance(sample, dict):
        return sample.get(name, default)
    return getattr(sample, name, default)


def _sample_id(sample: Any) -> str:
    return str(_field(sample, "id", ""))


_ISSUE_REF = re.compile(r"(?:#|/issues/)(\d+)\s*$")
_REPO_PREFIX = re.compile(r"^(?:github|gitcode|local)/([^#]+?)(?:#|$)", re.IGNORECASE)


def _issue_key(source: str):
    match = _ISSUE_REF.search(source)
    if not match:
        return None
    repo = ""
    repo_match = _REPO_PREFIX.match(source)
    if repo_match:
        repo = repo_match.group(1).strip().split("/")[-1]
    else:
        s2_match = re.match(r"eval/s2/([^#]+)", source, re.IGNORECASE)
        if s2_match:
            repo = s2_match.group(1).strip().rsplit(".", 1)[0].split("/")[-1]
    return f"issue:{repo.lower()}:{match.group(1)}"


def source_group(sample: Any) -> str:
    """来源分组键：同一 issue/同一来源归一化后算一组。

    空来源没有可归并的来源身份，按 id 各自成组，避免把所有无来源候选
    误合并成一类（它们本来就不该进池）。
    """
    source = str(_field(sample, "source", "") or "").strip().rstrip("/")
    if not source:
        return f"id:{_sample_id(sample)}"
    issue = _issue_key(source)
    if issue:
        return issue
    return source.lower()


def dedup(samples: Iterable[Any]) -> List[Any]:
    """按来源分组去重，保留每组第一条；顺序不变。"""
    seen = set()
    out: List[Any] = []
    for sample in samples:
        group = source_group(sample)
        if group in seen:
            continue
        seen.add(group)
        out.append(sample)
    return out


def stratum_of(sample: Any) -> str:
    """case 子类型键：``expected.namespace/category``；缺失记 unknown。

    不把 issue label 当类型真值；类型来自维护者补的 expected。object_type 与
    stratum 正交：diagnosis/case/reference/trace 下面仍可再分 namespace×category。
    """
    expected = _field(sample, "expected") or {}
    namespace = str(expected.get("namespace") or "").strip()
    category = str(expected.get("category") or "").strip()
    fault_class = str(expected.get("fault_class") or "").strip()
    base = f"{namespace}/{category}" if namespace and category else (namespace or category)
    if base and fault_class:
        return f"{base}/{fault_class}"
    return base or "unknown"


def stratify(samples: Iterable[Any]) -> Dict[str, List[Any]]:
    grouped: Dict[str, List[Any]] = {}
    for sample in samples:
        grouped.setdefault(stratum_of(sample), []).append(sample)
    return grouped


def _test_sort_key(sample: Any) -> Tuple[str, str]:
    sid = _sample_id(sample)
    return hashlib.sha256(sid.encode("utf-8")).hexdigest(), sid


def split_test(samples: Iterable[Any], size: int = 4, method: str = "hash",
               strata: Optional[Dict[str, int]] = None) -> List[Any]:
    """从 active + origin=core 的 evaluation 样本里稳定抽 ``size`` 条测试。

    ``method="hash"``（默认）按 id 的 SHA-256 排序；``method="group"`` 先按
    来源分组、组内按 id 哈希，尽量整组划出，避免同一问题换措辞后同时进评估
    和测试。field origin、非 active 状态与非 evaluation 用途都不参与。
    """
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("size must be a non-negative integer")
    if method not in ("hash", "group"):
        raise ValueError("method must be 'hash' or 'group'")
    if strata is not None:
        if not isinstance(strata, dict):
            raise ValueError("strata must be an object of stratum -> target")
        for key, value in strata.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("strata keys must be non-empty strings")
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("strata targets must be non-negative integers")
        if sum(strata.values()) > size:
            raise ValueError("strata targets exceed test size")
    eligible = [
        sample for sample in samples
        if _field(sample, "status") == "active"
        and _field(sample, "origin") == "core"
        and _field(sample, "purpose") == "evaluation"
    ]
    if strata:
        chosen: List[Any] = []
        remaining = sorted(eligible, key=_test_sort_key)
        for key in sorted(strata):
            target = strata[key]
            bucket = [sample for sample in remaining if stratum_of(sample) == key]
            picked = bucket[:target]
            chosen.extend(picked)
            picked_ids = {id(sample) for sample in picked}
            remaining = [sample for sample in remaining if id(sample) not in picked_ids]
        for sample in remaining:
            if len(chosen) >= size:
                break
            chosen.append(sample)
        return sorted(chosen, key=_test_sort_key)[:size]

    if method == "hash":
        return sorted(eligible, key=_test_sort_key)[:size]

    grouped: Dict[str, List[Any]] = {}
    for sample in eligible:
        grouped.setdefault(source_group(sample), []).append(sample)
    ordered: List[List[Any]] = [
        sorted(members, key=_test_sort_key)
        for _, members in sorted(
            grouped.items(),
            key=lambda item: hashlib.sha256(item[0].encode("utf-8")).hexdigest(),
        )
    ]
    # 先整组优先：恰好填满 size 的最大组直接划出；否则按组大到小尽量整组放。
    by_size = sorted(
        ordered,
        key=lambda members: (
            -len(members),
            hashlib.sha256(source_group(members[0]).encode("utf-8")).hexdigest(),
        ),
    )
    for members in by_size:
        if len(members) == size:
            return list(members)
    chosen: List[Any] = []
    for members in by_size:
        if len(chosen) + len(members) <= size:
            chosen.extend(members)
    if len(chosen) < size:
        picked = {id(member) for member in chosen}
        for members in by_size:
            for member in members:
                if len(chosen) >= size:
                    break
                if id(member) not in picked:
                    chosen.append(member)
                    picked.add(id(member))
    return chosen[:size]


def build_pool(
    samples: Iterable[Any],
    purpose: Optional[str] = None,
    origin: Optional[str] = None,
    statuses: Tuple[str, ...] = ("active",),
) -> List[Any]:
    """建池：按状态/用途/来源过滤，再按来源去重，按 id 排序。"""
    selected = []
    for sample in samples:
        if _field(sample, "status") not in statuses:
            continue
        if purpose is not None and _field(sample, "purpose") != purpose:
            continue
        if origin is not None and _field(sample, "origin") != origin:
            continue
        selected.append(sample)
    return sorted(dedup(selected), key=_sample_id)


def select_pool(samples: Iterable[Any], selector: Optional[Dict[str, Any]] = None) -> List[Any]:
    """小字典选择器：``{"purpose": ..., "origin": ..., "statuses": [...]}``。"""
    selector = dict(selector or {})
    statuses = tuple(selector.pop("statuses", ("active",)))
    unknown = [key for key in selector if key not in ("purpose", "origin")]
    if unknown:
        raise ValueError(f"unknown pool selector key(s): {', '.join(sorted(unknown))}")
    return build_pool(samples, statuses=statuses, **selector)


def pool_hash(samples: Iterable[Any]) -> str:
    """样本池内容哈希：id + 用途 + 状态 + 来源，用于复用计数与纪元比对。"""
    rows = []
    for sample in samples:
        rows.append("|".join(
            str(_field(sample, name, ""))
            for name in ("id", "object_type", "status", "origin", "purpose", "source")
        ))
    payload = "\n".join(sorted(rows))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ensure_unique_ids(samples: Iterable[Any]) -> List[str]:
    """返回重复 id 列表；建池前调用。"""
    seen = set()
    duplicates = set()
    for sample in samples:
        sid = _sample_id(sample)
        if sid in seen:
            duplicates.add(sid)
        seen.add(sid)
    return sorted(duplicates)


def transition_errors(status: str, new_status: str) -> List[str]:
    """给 ``samples.check`` 用的错误串；合法时为空。"""
    if check_transition(status, new_status):
        return []
    allowed = ", ".join(STATUS_TRANSITIONS.get(status, ())) or "(terminal)"
    return [f"invalid transition: {status} -> {new_status} (allowed: {allowed})"]


def origin_transition_errors(origin: str, new_origin: str) -> List[str]:
    if check_origin_transition(origin, new_origin):
        return []
    allowed = ", ".join(ORIGIN_TRANSITIONS.get(origin, ())) or "(terminal)"
    return [f"invalid origin transition: {origin} -> {new_origin} (allowed: {allowed})"]


# 测试里常用到的小工具：状态机边集合的只读视图。
LEGAL_TARGETS: Dict[str, Tuple[str, ...]] = STATUS_TRANSITIONS
LEGAL_ORIGIN_TARGETS: Dict[str, Tuple[str, ...]] = ORIGIN_TRANSITIONS
LEGAL_PURPOSE_TARGETS: Dict[str, Tuple[str, ...]] = PURPOSE_TRANSITIONS
