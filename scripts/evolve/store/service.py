# -*- coding: utf-8 -*-
"""RSI 存储服务：只依赖 Backend 端口，不依赖具体文件格式。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from .config import StoreConfig
from .local import LocalJsonlBackend
from .memory import MemoryBackend
from .models import KINDS, RSIEvent, RSIStoreError
from .ports import Backend

BACKENDS: Dict[str, Type[Backend]] = {
    "local": LocalJsonlBackend,
    "memory": MemoryBackend,
}


def open_store(base: Path, config: Optional[StoreConfig] = None) -> "RSIStore":
    config = config or StoreConfig.load(base)
    if config.backend not in BACKENDS:
        raise RSIStoreError(f"unknown store backend {config.backend!r}; "
                            f"expected one of {sorted(BACKENDS)}")
    if config.backend == "local":
        path = Path(config.options.get("path") or (Path(base) / "rsi-events.jsonl"))
        backend = LocalJsonlBackend(path)
    else:
        backend = MemoryBackend()
    return RSIStore(Path(base), backend=backend, config=config)


class RSIStore:
    def __init__(self, base: Path, *, backend: Optional[Backend] = None,
                 config: Optional[StoreConfig] = None):
        self.base = Path(base)
        self.config = config or StoreConfig.load(self.base)
        self.backend = backend or open_store(self.base, self.config).backend
        self.path = getattr(self.backend, "path", None)

    def append(self, kind: str, data: Dict[str, Any], *,
               experiment_id: Optional[str] = None,
               proposal_id: Optional[str] = None,
               event_id: Optional[str] = None,
               at: Optional[str] = None) -> Dict[str, Any]:
        event = RSIEvent(kind=kind, data=data, event_id=event_id or "",
                         at=at or "", experiment_id=experiment_id,
                         proposal_id=proposal_id).to_dict()
        self.backend.append(event)
        return event

    def event_ids(self) -> set:
        return {str(row.get("event_id")) for row in self.read()}

    def read(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = [RSIEvent.from_dict(row).to_dict() for row in self.backend.read()]
        if kind is None:
            return rows
        return [row for row in rows if row.get("kind") == kind]

    def history(self, *, experiment_id: Optional[str] = None,
                proposal_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self.read()
        if experiment_id is not None:
            rows = [row for row in rows if row.get("experiment_id") == experiment_id]
        if proposal_id is not None:
            rows = [row for row in rows if row.get("proposal_id") == proposal_id]
        return sorted(rows, key=lambda row: str(row.get("at") or ""))

    def get_experiment(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        rows = [row for row in self.read("experiment")
                if row.get("experiment_id") == experiment_id]
        return rows[-1] if rows else None

    def get_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        rows = [row for row in self.read("proposal")
                if row.get("proposal_id") == proposal_id]
        if not rows:
            return None
        proposal = (rows[-1].get("data") or {}).get("proposal")
        return proposal if isinstance(proposal, dict) else None

    def record_experiment(self, proposal: Dict[str, Any], experiment: Dict[str, Any],
                          conclusion: Dict[str, Any], tasks: Dict[str, Any],
                          collected: Dict[str, Any], decision: str,
                          *, experiment_id: Optional[str] = None) -> Dict[str, Any]:
        proposal_id = str(proposal.get("id") or "")
        experiment_id = experiment_id or f"EX-{proposal_id or uuid.uuid4().hex[:8]}"
        collected_arms = collected.get("arms") or {}
        rollout = {
            "samples": [str(row.get("short_id") or row.get("id"))
                        for row in tasks.get("samples") or []],
            "arms": {arm: len(rows or []) for arm, rows in collected_arms.items()},
            "workspace": tasks.get("workspace"),
            "rolled_back": bool(proposal.get("rolled_back")),
            "decision": decision,
        }
        self.append("proposal", {"proposal": proposal},
                    experiment_id=experiment_id, proposal_id=proposal_id or None)
        self.append("decision", {"conclusion": conclusion},
                    experiment_id=experiment_id, proposal_id=proposal_id or None)
        self.append("rollout", {"rollout": rollout},
                    experiment_id=experiment_id, proposal_id=proposal_id or None)
        return self.append(
            "experiment",
            {"proposal": proposal, "conclusion": conclusion,
             "experiment": experiment, "rollout": rollout},
            experiment_id=experiment_id, proposal_id=proposal_id or None,
        )
