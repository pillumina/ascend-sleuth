# -*- coding: utf-8 -*-
"""对照臂：只把 seed 在样本上评一遍，不提案、不选新候选。

它是多臂实验里的 baseline control。与 ``select.none`` / ``propose.none``
的组合语义一致，但作为搜索循环注册，实验层不用为对照臂写特例。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .budget import Budget
from .contract import LoopError, Snapshot
from .decisions import DecisionLog

BASELINE_STATE_SCHEMA = "baseline-control-v1"


class BaselineLoop:
    id = "baseline"
    version = "v1"

    def __init__(self, seed_skill: str, samples: List[str],
                 target: str = "", component: str = "",
                 max_target_runs: Optional[int] = None,
                 budget: Optional[Budget] = None,
                 decision_log: Optional[DecisionLog] = None,
                 run_id: str = ""):
        if not isinstance(seed_skill, str) or not seed_skill.strip():
            raise LoopError("seed_skill is required")
        if not samples or not all(isinstance(s, str) and s.strip() for s in samples):
            raise LoopError("samples must be non-empty strings")
        if len(set(samples)) != len(samples):
            raise LoopError("samples must not contain duplicates")
        self.samples = list(samples)
        self.target = str(target or "")
        self.component = str(component or "")
        self.budget = budget or Budget(target_runs=max_target_runs)
        self.decision_log = decision_log
        self.run_id = str(run_id or "")
        self.snapshot = Snapshot.from_text(
            "seed", seed_skill, target=self.target, component=self.component,
        )

    @property
    def calls(self) -> int:
        return self.budget.spent("target_runs")

    def next_action(self) -> Dict[str, Any]:
        missing = [sid for sid in self.samples if sid not in self.snapshot.scores]
        if not missing:
            return {"kind": "stop", "reason": "baseline_control"}
        if not self.budget.can_spend("target_runs"):
            return {"kind": "stop", "reason": "budget"}
        return {"kind": "evaluate", "candidate_id": "seed",
                "skill": self.snapshot.text, "sample_id": missing[0]}

    def record_evaluation(self, sample_id: str, score: Any, feedback: str = "") -> None:
        if sample_id not in self.samples:
            raise LoopError(f"unknown sample {sample_id!r}")
        if sample_id in self.snapshot.scores:
            raise LoopError(f"sample {sample_id!r} already evaluated")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise LoopError("score must be a number")
        if not 0 <= float(score) <= 1:
            raise LoopError("score must be between 0 and 1")
        if not self.budget.can_spend("target_runs"):
            raise LoopError("target_runs budget exhausted")
        self.snapshot.scores[sample_id] = float(score)
        self.snapshot.feedback[sample_id] = str(feedback or "")
        self.budget.spend("target_runs")

    def apply(self, action: Dict[str, Any], result: Dict[str, Any]) -> None:
        if not isinstance(action, dict) or not isinstance(result, dict):
            raise LoopError("action and result must be objects")
        kind = action.get("kind")
        if kind == "evaluate":
            if "score" not in result:
                raise LoopError("evaluate result requires score")
            self.record_evaluation(
                str(action.get("sample_id") or ""), result["score"],
                str(result.get("feedback") or ""),
            )
        elif kind == "stop":
            return
        else:
            raise LoopError(f"unsupported action kind {kind!r}")

    def best_snapshot(self) -> Snapshot:
        return self.snapshot

    def result(self) -> Dict[str, Any]:
        mean = (sum(self.snapshot.scores.values()) / len(self.samples)
                if len(self.snapshot.scores) == len(self.samples) else None)
        return {
            "loop": self.id,
            "best_id": "seed",
            "best_skill": self.snapshot.text,
            "best_score": mean,
            "scores": dict(self.snapshot.scores),
            "calls": self.calls,
            "budget": self.budget.to_dict(),
            "samples": list(self.samples),
            "target": self.target,
            "component": self.component,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_schema": BASELINE_STATE_SCHEMA,
            "loop": self.id,
            "samples": list(self.samples),
            "target": self.target,
            "component": self.component,
            "snapshot": self.snapshot.to_dict(),
            "budget": self.budget.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaselineLoop":
        if data.get("state_schema") not in (None, BASELINE_STATE_SCHEMA):
            raise LoopError("baseline state schema mismatch")
        snapshot = Snapshot.from_dict(data.get("snapshot") or {})
        loop = cls(
            seed_skill=snapshot.text, samples=list(data.get("samples") or []),
            target=str(data.get("target") or ""),
            component=str(data.get("component") or ""),
            budget=Budget.from_dict(data.get("budget")),
        )
        loop.snapshot = snapshot
        return loop
