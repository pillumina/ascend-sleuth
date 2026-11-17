"""metrics 只读消费：timeline、gates、执行记录与条目使用摘要。

读不到的文件/字段标记 ``available: false`` 或返回 None，不补 0；读坏文件也不
让调用方崩。本模块不联网、不跑模型、不写文件。
"""

from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

TIMELINE_REL = Path("metrics") / "timeline.yaml"
GATES_REL = Path("metrics") / "gates.yaml"
EXEC_LOG_REL = Path("metrics") / "skill-exec-log.yaml"
ENTRY_ACTIVITY_REL = Path("metrics") / "entry-activity"


def _missing(path: Path, reason: str = "not found") -> Dict[str, Any]:
    return {"available": False, "path": str(path), "reason": reason}


def _read_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML {path}: {exc}") from exc


def _period_key(period: Dict[str, Any], index: int):
    return (str(period.get("recorded_at") or ""), index)


def _latest_period(periods: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not periods:
        return None
    index, period = max(enumerate(periods), key=lambda pair: _period_key(pair[1], pair[0]))
    return period


def _latest_with(periods: List[Dict[str, Any]], pred) -> Optional[Dict[str, Any]]:
    candidates = [(index, period) for index, period in enumerate(periods) if pred(period)]
    if not candidates:
        return None
    return max(candidates, key=lambda pair: _period_key(pair[1], pair[0]))[1]


def _period_summary(period: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not period:
        return None
    return {
        key: period.get(key)
        for key in ("period", "kind", "recorded_at", "title")
        if key in period
    }


def _timeline(root: Path) -> Dict[str, Any]:
    path = root / TIMELINE_REL
    if not path.exists():
        return _missing(path)
    try:
        document = _read_yaml(path)
    except ValueError as exc:
        return _missing(path, str(exc))
    periods = document.get("periods") if isinstance(document, dict) else None
    if not isinstance(periods, list):
        return _missing(path, "timeline has no periods list")
    periods = [period for period in periods if isinstance(period, dict)]
    latest = _latest_period(periods)
    latest_live = _latest_with(periods, lambda p: p.get("kind") == "live")
    latest_structural = _latest_with(
        periods, lambda p: "case_total" in (p.get("metrics") or {})
    )
    latest_metrics = (latest_live or {}).get("metrics") or {}
    structural_metrics = (latest_structural or {}).get("metrics") or {}
    feedback = latest_metrics.get("feedback_capture")
    return {
        "available": True,
        "path": str(path),
        "periods": len(periods),
        "latest_period": _period_summary(latest),
        "latest_live_period": _period_summary(latest_live),
        "latest_structural_period": _period_summary(latest_structural),
        "sessions_total": latest_metrics.get("sessions_total"),
        "tier2_hit": latest_metrics.get("tier2_hit"),
        "case_total": structural_metrics.get("case_total"),
        "feedback": feedback if isinstance(feedback, dict) else None,
    }


def _gates(root: Path) -> Dict[str, Any]:
    path = root / GATES_REL
    if not path.exists():
        return _missing(path)
    try:
        document = _read_yaml(path)
    except ValueError as exc:
        return _missing(path, str(exc))
    if not isinstance(document, dict):
        return _missing(path, "gates must be an object")
    gates = document.get("gates")
    return {
        "available": True,
        "path": str(path),
        "gate_count": len(gates) if isinstance(gates, list) else None,
        "freshness": document.get("freshness"),
        "health": document.get("health"),
    }


def _last_skill_exec(root: Path) -> Dict[str, Any]:
    # exec-log 是跨 worktree 共享的运行时件：worktree 里跑 run/brief 也要读主检出那份。
    # 无 git 的临时目录/测试退化为 root。
    try:
        from exec_log_path import resolve as _resolve_exec_log
        path, where = _resolve_exec_log(root)
    except (ImportError, OSError):
        path, where = root / EXEC_LOG_REL, "fallback"
    if not path.exists():
        return _missing(path)
    try:
        document = _read_yaml(path)
    except ValueError as exc:
        return _missing(path, str(exc))
    records = document.get("records") if isinstance(document, dict) else None
    if not isinstance(records, list):
        return _missing(path, "exec log has no records list")
    last = records[-1] if records else None
    summary = None
    if isinstance(last, dict):
        summary = {
            "at": str(last.get("at") or ""),
            "skill": last.get("skill"),
            "source": last.get("source"),
            "version": last.get("version"),
            "products": last.get("products") or [],
        }
    return {
        "available": True,
        "path": str(path),
        "where": where,
        "count": len(records),
        "last": summary,
    }


def _entry_path(root: Path, deployment: Optional[str]) -> Path:
    directory = root / ENTRY_ACTIVITY_REL
    if deployment:
        return directory / f"{deployment}.yaml"
    preferred = directory / "ascend-sleuth.yaml"
    if preferred.exists():
        return preferred
    files = sorted(directory.glob("*.yaml")) if directory.exists() else []
    return files[0] if len(files) == 1 else preferred


def _entry_usage(root: Path, deployment: Optional[str]) -> Dict[str, Any]:
    path = _entry_path(root, deployment)
    if not path.exists():
        return _missing(path)
    try:
        document = _read_yaml(path)
    except ValueError as exc:
        return _missing(path, str(exc))
    if not isinstance(document, dict):
        return _missing(path, "entry activity must be an object")
    covered = document.get("covered") if isinstance(document.get("covered"), dict) else {}
    cases = document.get("cases") if isinstance(document.get("cases"), dict) else {}
    references = document.get("references") if isinstance(document.get("references"), dict) else {}
    tools = document.get("tools") if isinstance(document.get("tools"), dict) else {}
    cold = document.get("cold") if isinstance(document.get("cold"), dict) else {}
    active_cases = 0
    for row in cases.values():
        totals = row.get("totals") if isinstance(row, dict) else None
        if isinstance(totals, dict) and any(totals.get(key) for key in (
            "selected", "loaded", "resolved", "misdiagnosed", "self_resolved",
        )):
            active_cases += 1
    never = document.get("cold_never_looked_up")
    return {
        "available": True,
        "path": str(path),
        "deployment": covered.get("deployment"),
        "runs": covered.get("runs"),
        "weeks": covered.get("weeks") or [],
        "cases": len(cases),
        "active_cases": active_cases,
        "references": len(references),
        "tools": len(tools),
        "cold_cases": cold.get("cases"),
        "cold_never_looked_up": len(never) if isinstance(never, list) else None,
    }


def _period_age(period: Optional[Dict[str, Any]], today: date) -> Optional[int]:
    if not period:
        return None
    raw = str(period.get("recorded_at") or "")[:10]
    try:
        return (today - date.fromisoformat(raw)).days
    except ValueError:
        return None


def _freshness(timeline: Dict[str, Any], gates: Dict[str, Any],
               today: date) -> Dict[str, Any]:
    thresholds = gates.get("freshness") if isinstance(gates.get("freshness"), dict) else {}
    result = {"available": bool(gates.get("available")), "live": None, "structural": None}
    for key, period_key, max_key in (
        ("live", "latest_live_period", "live_snapshot_max_age_days"),
        ("structural", "latest_structural_period", "structural_max_age_days"),
    ):
        period = timeline.get(period_key)
        age = _period_age(period, today)
        max_age = thresholds.get(max_key)
        stale = bool(age is not None and isinstance(max_age, int) and age > max_age)
        result[key] = {
            "period": (period or {}).get("period"),
            "age_days": age,
            "max_age_days": max_age,
            "stale": stale,
            "available": bool(gates.get("available")) and period is not None and age is not None,
        }
    return result


def load_metrics(root: Any, deployment: Optional[str] = None,
                 today: Optional[date] = None) -> Dict[str, Any]:
    """读四类 metrics 文件；缺文件/坏文件用 available=False 标记。"""
    root_path = Path(root)
    timeline = _timeline(root_path)
    gates = _gates(root_path)
    freshness = _freshness(timeline, gates, today or date.today())
    return {
        "timeline": timeline,
        "gates": gates,
        "freshness": freshness,
        "last_skill_exec": _last_skill_exec(root_path),
        "entry_usage": _entry_usage(root_path, deployment),
        "latest_period": timeline.get("latest_period"),
        "sessions_total": timeline.get("sessions_total"),
        "tier2_hit": timeline.get("tier2_hit"),
        "case_total": timeline.get("case_total"),
        "feedback": timeline.get("feedback"),
    }
