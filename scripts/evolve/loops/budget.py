# -*- coding: utf-8 -*-
"""循环预算：目标执行、worker 调用与 token 三类，统一记账与停止原因。

旧状态机的 ``max_metric_calls`` / ``max_audit_calls`` 都映射到 ``target_runs``，
所以旧状态文件仍能读。预算只在还有剩余工作时拦截；恰好用满不算截断。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .contract import LoopError

BUDGET_KINDS = ("target_runs", "worker_calls", "tokens")


@dataclass
class Budget:
    target_runs: Optional[int] = None
    worker_calls: Optional[int] = None
    tokens: Optional[int] = None
    used: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for kind in BUDGET_KINDS:
            limit = getattr(self, kind)
            if limit is not None and (
                not isinstance(limit, int) or isinstance(limit, bool) or limit < 1
            ):
                raise LoopError(f"budget {kind} must be a positive integer or null")
        for kind, value in self.used.items():
            if kind not in BUDGET_KINDS:
                raise LoopError(f"unknown budget kind {kind!r}")
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise LoopError(f"used {kind} must be a non-negative integer")

    def limit(self, kind: str) -> Optional[int]:
        self._check_kind(kind)
        return getattr(self, kind)

    def spent(self, kind: str) -> int:
        self._check_kind(kind)
        return int(self.used.get(kind, 0))

    def remaining(self, kind: str) -> Optional[int]:
        limit = self.limit(kind)
        if limit is None:
            return None
        return max(0, limit - self.spent(kind))

    def can_spend(self, kind: str, amount: int = 1) -> bool:
        self._check_kind(kind)
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise LoopError("budget amount must be a non-negative integer")
        limit = self.limit(kind)
        return limit is None or self.spent(kind) + amount <= limit

    def spend(self, kind: str, amount: int = 1) -> None:
        self._check_kind(kind)
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise LoopError("budget amount must be a non-negative integer")
        if not self.can_spend(kind, amount):
            raise LoopError(f"{kind} budget exhausted")
        self.used[kind] = self.spent(kind) + amount

    def stop_reason(self) -> Optional[str]:
        for kind in BUDGET_KINDS:
            if not self.can_spend(kind):
                return f"{kind}_budget"
        return None

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {kind: getattr(self, kind) for kind in BUDGET_KINDS}
        data["used"] = dict(self.used)
        return data

    @classmethod
    def from_dict(cls, data: Any) -> "Budget":
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise LoopError("budget must be an object")
        return cls(
            target_runs=data.get("target_runs"),
            worker_calls=data.get("worker_calls"),
            tokens=data.get("tokens"),
            used={str(k): int(v) for k, v in (data.get("used") or {}).items()},
        )

    @staticmethod
    def _check_kind(kind: str) -> None:
        if kind not in BUDGET_KINDS:
            raise LoopError(f"unknown budget kind {kind!r}; expected {list(BUDGET_KINDS)}")
