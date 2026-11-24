# -*- coding: utf-8 -*-
"""留一效用审计循环（LOO）。

机制出处是 SkillProx 的后向审计（未经广泛认可，作设计参考 + 小池自证）。
流程：基线全量评测一遍，逐单元去掉后再评一遍，``效用(u) = 基线指标 − 去掉 u
后指标``；效用 ≤ 阈值的单元（含零效用冗余）进收缩队列（附证据），收缩执行走
正常知识 PR，不在本循环内。

它是 ``audit`` 类循环：不产出更好的候选，只对现有快照做单元消融。状态 schema
保持 ``loo-audit-v1``，预算以单样本评测计。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .budget import Budget
from .contract import LoopError
from .decisions import DecisionLog
from ..errors import EvolveError

LOO_STATE_SCHEMA = "loo-audit-v1"


class LooError(LoopError, EvolveError):
    """状态机输入或动作顺序不合法。"""


@dataclass
class AuditUnit:
    id: str
    label: str = ""
    base_scores: Dict[str, float] = field(default_factory=dict)
    ablated_scores: Dict[str, float] = field(default_factory=dict)

    def utility(self) -> Optional[float]:
        """平均效用；基线或消融未评完返回 None。"""
        if not self.base_scores or len(self.ablated_scores) != len(self.base_scores):
            return None
        n = len(self.base_scores)
        return round((sum(self.base_scores.values()) - sum(self.ablated_scores.values())) / n, 9)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "label": self.label,
                "base_scores": dict(self.base_scores),
                "ablated_scores": dict(self.ablated_scores)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditUnit":
        if not isinstance(data.get("id"), str) or not data["id"].strip():
            raise LooError("unit id is required")
        return cls(id=data["id"], label=str(data.get("label") or ""),
                   base_scores={k: float(v) for k, v in (data.get("base_scores") or {}).items()},
                   ablated_scores={k: float(v) for k, v in (data.get("ablated_scores") or {}).items()})


def _check_score(score: Any) -> float:
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        raise LooError("score must be a number")
    if not 0 <= float(score) <= 1:
        raise LooError("score must be between 0 and 1")
    return float(score)


class LooAudit:
    """审计循环状态机。评测预算以单样本评测次数计（基线与消融各单元数×样本数次）。"""

    id = "loo"
    version = "v2"

    def __init__(self, units: List[AuditUnit], samples: List[str],
                 max_audit_calls: int, shrink_threshold: float = 0.0,
                 target_kind: str = "", audit_set: str = "",
                 budget: Optional[Budget] = None,
                 decision_log: Optional[DecisionLog] = None,
                 run_id: str = ""):
        if not units or not all(u.id.strip() for u in units):
            raise LooError("units must be non-empty with ids")
        ids = [u.id for u in units]
        if len(set(ids)) != len(ids):
            raise LooError("unit ids must not contain duplicates")
        if not samples or len(set(samples)) != len(samples):
            raise LooError("samples must be non-empty without duplicates")
        if not isinstance(max_audit_calls, int) or isinstance(max_audit_calls, bool) \
                or max_audit_calls <= 0:
            raise LooError("max_audit_calls must be a positive integer")
        self.units = list(units)
        self.samples = list(samples)
        self.max_audit_calls = max_audit_calls
        self.shrink_threshold = float(shrink_threshold)
        self.target_kind = str(target_kind or "")
        self.audit_set = str(audit_set or "")
        self.budget = budget or Budget(target_runs=max_audit_calls)
        if self.budget.target_runs is None:
            self.budget.target_runs = max_audit_calls
        self.decision_log = decision_log
        self.run_id = str(run_id or "")
        self._pending: Optional[tuple] = None  # (unit_id, variant, sample_id)

    @property
    def calls(self) -> int:
        return self.budget.spent("target_runs")

    @calls.setter
    def calls(self, value: int) -> None:
        self.budget.used["target_runs"] = int(value)

    # -- actions ---------------------------------------------------------
    def next_action(self) -> Dict[str, Any]:
        for unit in self.units:
            for sid in self.samples:
                if sid not in unit.base_scores:
                    return self._budget_or_evaluate(unit.id, "full", sid)
            for sid in self.samples:
                if sid not in unit.ablated_scores:
                    return self._budget_or_evaluate(unit.id, f"without:{unit.id}", sid)
        return {"kind": "stop", "reason": "complete"}

    def _budget_or_evaluate(self, unit_id: str, variant: str, sample_id: str) -> Dict[str, Any]:
        # 预算只在还有剩余工作时拦截；全部评完则正常 complete，
        # 否则「恰好用满预算」会被误报成 budget 截断。
        if not self.budget.can_spend("target_runs"):
            return {"kind": "stop", "reason": "budget"}
        return self._evaluate_action(unit_id, variant, sample_id)

    def _evaluate_action(self, unit_id: str, variant: str, sample_id: str) -> Dict[str, Any]:
        self._pending = (unit_id, variant, sample_id)
        return {"kind": "evaluate", "unit_id": unit_id, "variant": variant,
                "sample_id": sample_id}

    def record_evaluation(self, unit_id: str, variant: str, sample_id: str,
                          score: Any) -> None:
        if not self.budget.can_spend("target_runs"):
            raise LooError("max_audit_calls reached")
        if self._pending is None or self._pending != (unit_id, variant, sample_id):
            raise LooError("no matching evaluate action pending; call next_action first")
        unit = self._unit(unit_id)
        value = _check_score(score)
        if variant == "full":
            unit.base_scores[sample_id] = value
        elif variant == f"without:{unit_id}":
            unit.ablated_scores[sample_id] = value
        else:
            raise LooError(f"unknown variant {variant!r}")
        self.budget.spend("target_runs")
        self._pending = None

    def apply(self, action: Dict[str, Any], result: Dict[str, Any]) -> None:
        if not isinstance(action, dict) or not isinstance(result, dict):
            raise LooError("action and result must be objects")
        kind = action.get("kind")
        if kind == "evaluate":
            if "score" not in result:
                raise LooError("evaluate result requires score")
            self.record_evaluation(
                str(action.get("unit_id") or ""), str(action.get("variant") or ""),
                str(action.get("sample_id") or ""), result["score"],
            )
        elif kind == "stop":
            return
        else:
            raise LooError(f"unsupported action kind {kind!r}")

    # -- selection / result ---------------------------------------------
    def utilities(self) -> Dict[str, float]:
        return {u.id: u.utility() for u in self.units if u.utility() is not None}

    def shrink_queue(self) -> List[Dict[str, Any]]:
        """负效用收缩队列，效用升序；含每单元的证据（哪些样例被别的单元覆盖）。"""
        queue = []
        for unit in self.units:
            utility = unit.utility()
            if utility is None or utility > self.shrink_threshold:
                continue
            evidence = [
                {"sample_id": sid, "base": unit.base_scores[sid],
                 "ablated": unit.ablated_scores[sid]}
                for sid in self.samples
                if unit.ablated_scores.get(sid, 0) >= unit.base_scores.get(sid, 0)
            ]
            queue.append({"unit_id": unit.id, "label": unit.label,
                          "utility": utility, "evidence": evidence})
        queue.sort(key=lambda item: item["utility"])
        return queue

    def result(self) -> Dict[str, Any]:
        return {
            "loop": self.id,
            "target_kind": self.target_kind,
            "audit_set": self.audit_set,
            "samples": list(self.samples),
            "units": len(self.units),
            "calls": self.calls,
            "max_audit_calls": self.max_audit_calls,
            "budget": self.budget.to_dict(),
            "shrink_threshold": self.shrink_threshold,
            "utilities": self.utilities(),
            "shrink_queue": self.shrink_queue(),
        }

    def best_snapshot(self) -> None:
        """审计循环不产出更好的候选。"""
        return None

    # -- persistence -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_schema": LOO_STATE_SCHEMA,
            "loop": self.id,
            "samples": list(self.samples),
            "max_audit_calls": self.max_audit_calls,
            "shrink_threshold": self.shrink_threshold,
            "target_kind": self.target_kind,
            "audit_set": self.audit_set,
            "units": [u.to_dict() for u in self.units],
            "calls": self.calls,
            "budget": self.budget.to_dict(),
            "pending": list(self._pending) if self._pending else None,
            "decision_log": str(self.decision_log.path) if self.decision_log else None,
            "run_id": self.run_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LooAudit":
        if data.get("state_schema") not in (None, LOO_STATE_SCHEMA):
            raise LooError("loo audit state schema mismatch")
        missing = [key for key in ("samples", "max_audit_calls", "units")
                   if key not in data]
        if missing:
            raise LooError("state missing: " + ", ".join(missing))
        if not isinstance(data["samples"], list) or not isinstance(data["units"], list):
            raise LooError("state samples/units must be lists")
        units = [AuditUnit.from_dict(u) for u in data["units"]]
        if not units:
            raise LooError("state has no units")
        audit = cls(units=units, samples=list(data["samples"]),
                    max_audit_calls=int(data["max_audit_calls"]),
                    shrink_threshold=float(data.get("shrink_threshold", 0.0)),
                    target_kind=str(data.get("target_kind") or ""),
                    audit_set=str(data.get("audit_set") or ""))
        audit.calls = int(data.get("calls", 0))
        if isinstance(data.get("budget"), dict):
            audit.budget = Budget.from_dict(data["budget"])
            if audit.budget.target_runs is None:
                audit.budget.target_runs = audit.max_audit_calls
        pending = data.get("pending")
        if pending:
            audit._pending = tuple(pending)
        if data.get("decision_log"):
            audit.decision_log = DecisionLog(str(data["decision_log"]))
        audit.run_id = str(data.get("run_id") or "")
        return audit

    def _unit(self, unit_id: str) -> AuditUnit:
        for unit in self.units:
            if unit.id == unit_id:
                return unit
        raise LooError(f"unknown unit {unit_id!r}")
