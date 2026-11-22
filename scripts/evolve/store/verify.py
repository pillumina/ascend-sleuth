# -*- coding: utf-8 -*-
"""RSI 事件流完整性检查：身份、关联、时间、rollout 证据。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .service import RSIStore, open_store


def _issue(code: str, detail: str, severity: str = "warning") -> Dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail}


def verify(base: Path, store: RSIStore = None) -> Dict[str, Any]:
    store = store or open_store(Path(base))
    events = store.read()
    issues: List[Dict[str, str]] = []
    ids = [str(event.get("event_id") or "") for event in events]
    for event_id, count in Counter(ids).items():
        if not event_id:
            issues.append(_issue("missing_event_id", "event without event_id", "error"))
        elif count > 1:
            issues.append(_issue("duplicate_event_id", f"{event_id} x{count}", "error"))
    counts = {kind: len(store.read(kind))
              for kind in ("proposal", "experiment", "decision", "rollout")}
    experiments = [event for event in events if event.get("kind") == "experiment"]
    for event in experiments:
        data = event.get("data") or {}
        if not data.get("proposal"):
            issues.append(_issue("experiment_without_proposal", str(event.get("experiment_id"))))
        if not data.get("conclusion"):
            issues.append(_issue("experiment_without_conclusion", str(event.get("experiment_id"))))
    experiment_ids = Counter(str(event.get("experiment_id")) for event in experiments)
    for experiment_id, count in experiment_ids.items():
        if count > 1:
            issues.append(_issue("duplicate_experiment_id", f"{experiment_id} x{count}"))
    for event in events:
        if event.get("kind") in ("decision", "rollout") and not event.get("experiment_id"):
            issues.append(_issue("orphan_" + str(event.get("kind")), str(event.get("event_id"))))
        at = str(event.get("at") or "")
        try:
            datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            issues.append(_issue("bad_timestamp", f"{event.get('event_id')} {at!r}", "error"))
        if event.get("kind") == "rollout":
            run = (event.get("data") or {}).get("run") or {}
            trace_ref = run.get("trace_ref")
            if trace_ref and not Path(trace_ref).exists():
                issues.append(_issue("missing_trace", str(trace_ref)))
    errors = sum(1 for issue in issues if issue["severity"] == "error")
    return {"base": str(base), "store_path": str(store.path) if store.path else None,
            "counts": counts, "issues": issues, "ok": errors == 0}
