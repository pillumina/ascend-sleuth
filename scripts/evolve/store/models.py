# -*- coding: utf-8 -*-
"""存储领域模型：一条不可变 RSI 事件。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..contracts import now_iso

SCHEMA = "rsi-store-v1"
KINDS = ("experiment", "proposal", "decision", "rollout", "archive")


class RSIStoreError(ValueError):
    pass


@dataclass(frozen=True)
class RSIEvent:
    kind: str
    data: Dict[str, Any]
    event_id: str = ""
    at: str = ""
    experiment_id: Optional[str] = None
    proposal_id: Optional[str] = None
    schema: str = SCHEMA

    def validate(self) -> "RSIEvent":
        if self.kind not in KINDS:
            raise RSIStoreError(f"unknown event kind {self.kind!r}")
        if not isinstance(self.data, dict):
            raise RSIStoreError("event data must be an object")
        if self.schema != SCHEMA:
            raise RSIStoreError(f"event schema must be {SCHEMA!r}")
        for name in ("experiment_id", "proposal_id"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise RSIStoreError(f"{name} must be a non-empty string or null")
        return self

    def to_dict(self) -> Dict[str, Any]:
        event = RSIEvent(
            kind=self.kind, data=self.data,
            event_id=self.event_id or f"E-{uuid.uuid4().hex[:12]}",
            at=self.at or now_iso(), experiment_id=self.experiment_id,
            proposal_id=self.proposal_id, schema=self.schema,
        ).validate()
        return {
            "schema": event.schema, "event_id": event.event_id, "kind": event.kind,
            "at": event.at, "experiment_id": event.experiment_id,
            "proposal_id": event.proposal_id, "data": event.data,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "RSIEvent":
        if not isinstance(data, dict):
            raise RSIStoreError("event must be an object")
        return cls(
            kind=str(data.get("kind") or ""),
            data=data.get("data") if isinstance(data.get("data"), dict) else {},
            event_id=str(data.get("event_id") or ""),
            at=str(data.get("at") or ""),
            experiment_id=data.get("experiment_id"),
            proposal_id=data.get("proposal_id"),
            schema=str(data.get("schema") or SCHEMA),
        ).validate()
