# -*- coding: utf-8 -*-
"""RSI 统一事件存储：experiment / proposal / decision / rollout / archive。

JSONL 是权威事件流；现有 conclusions/experiments/proposals 保留为投影。
一条 experiment 事件内嵌 proposal、decision、experiment record 和 rollout 摘要，
便于按 experiment 或 proposal 回读完整历史。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .contracts import now_iso
from .records import JsonlStore

SCHEMA = "rsi-store-v1"
KINDS = ("experiment", "proposal", "decision", "rollout", "archive")


class RSIStoreError(ValueError):
    pass


class RSIStore:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.path = self.base / "rsi-events.jsonl"
        self._store = JsonlStore(self.path)

    def append(self, kind: str, data: Dict[str, Any], *,
               experiment_id: Optional[str] = None,
               proposal_id: Optional[str] = None) -> Dict[str, Any]:
        if kind not in KINDS:
            raise RSIStoreError(f"unknown event kind {kind!r}")
        if not isinstance(data, dict):
            raise RSIStoreError("event data must be an object")
        event = {
            "schema": SCHEMA,
            "event_id": f"E-{uuid.uuid4().hex[:12]}",
            "kind": kind,
            "at": now_iso(),
            "experiment_id": experiment_id,
            "proposal_id": proposal_id,
            "data": data,
        }
        self._store.append(event)
        return event

    def read(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self._store.read()
        if kind is None:
            return rows
        return [row for row in rows if row.get("kind") == kind]

    def history(self, *, experiment_id: Optional[str] = None,
                proposal_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self._store.read()
        if experiment_id is not None:
            rows = [row for row in rows if row.get("experiment_id") == experiment_id]
        if proposal_id is not None:
            rows = [row for row in rows if row.get("proposal_id") == proposal_id]
        return sorted(rows, key=lambda row: str(row.get("at") or ""))

    def get_experiment(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        rows = [row for row in self.read("experiment")
                if row.get("experiment_id") == experiment_id]
        return rows[-1] if rows else None

    def record_experiment(self, proposal: Dict[str, Any], experiment: Dict[str, Any],
                          conclusion: Dict[str, Any], tasks: Dict[str, Any],
                          collected: Dict[str, Any], decision: str,
                          *, experiment_id: Optional[str] = None) -> Dict[str, Any]:
        proposal_id = str(proposal.get("id") or "")
        experiment_id = experiment_id or f"EX-{proposal_id or uuid.uuid4().hex[:8]}"
        arms = tasks.get("arms") or {}
        collected_arms = collected.get("arms") or {}
        rollout = {
            "samples": [str(row.get("short_id") or row.get("id"))
                        for row in tasks.get("samples") or []],
            "arms": {arm: len(rows or []) for arm, rows in collected_arms.items()},
            "workspace": tasks.get("workspace"),
            "rolled_back": bool(proposal.get("rolled_back")),
            "decision": decision,
        }
        return self.append(
            "experiment",
            {"proposal": proposal, "conclusion": conclusion,
             "experiment": experiment, "rollout": rollout},
            experiment_id=experiment_id, proposal_id=proposal_id or None,
        )
