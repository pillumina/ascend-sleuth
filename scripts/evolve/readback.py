"""合入后按 EV 卡回读最近的 Conclusion。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .records import ConclusionStore, RecordError


class ReadbackError(ValueError):
    pass


def latest_by_proposal(proposal: str, base: Path) -> Optional[Dict[str, Any]]:
    if not isinstance(proposal, str) or not proposal.strip():
        raise ReadbackError("proposal is required")
    try:
        records = ConclusionStore.for_base(Path(base)).read()
    except (OSError, RecordError) as exc:
        raise ReadbackError(f"cannot read conclusions: {exc}") from exc
    hits = [record for record in records if record.get("proposal") == proposal.strip()]
    if not hits:
        return None
    return sorted(hits, key=lambda record: str(record.get("at") or ""))[-1]


def latest_conclusion(card: str, base: Path) -> Optional[Dict[str, Any]]:
    if not isinstance(card, str) or not card.strip():
        raise ReadbackError("card is required")
    try:
        records = ConclusionStore.for_base(Path(base)).read()
    except (OSError, RecordError) as exc:
        raise ReadbackError(f"cannot read conclusions: {exc}") from exc
    hits = [record for record in records if record.get("card") == card.strip()]
    if not hits:
        return None
    return sorted(hits, key=lambda record: str(record.get("at") or ""))[-1]


def summary(record: Dict[str, Any]) -> Dict[str, Any]:
    versions = record.get("versions") or {}
    cost = record.get("cost") or {}
    tokens = cost.get("tokens") if isinstance(cost, dict) else None
    return {
        "card": record.get("card"),
        "proposal": record.get("proposal"),
        "decision": record.get("decision"),
        "b": record.get("b"),
        "c": record.get("c"),
        "n": record.get("n"),
        "p_value": record.get("p_value"),
        "alpha_eff": record.get("alpha_eff"),
        "model": versions.get("model"),
        "candidate": versions.get("candidate"),
        "cost": tokens,
        "cost_paired": cost.get("paired") if isinstance(cost, dict) else None,
        "cost_missing": cost.get("missing") if isinstance(cost, dict) else None,
        "at": record.get("at"),
    }
