# -*- coding: utf-8 -*-
"""提案搜索循环：把 ``ProposalEngine.run`` 的同步闭环搬到动作协议上。

它是提案层的循环实现，不是新的评测算法：动作只有 reflect（产草案）与
evaluate（评草案），选择策略由 ``policy`` 决定。``ProposalEngine.run`` 仍保留，
作为同步兼容入口，内部驱动本类。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .budget import Budget
from .contract import LoopError

PROPOSAL_STATE_SCHEMA = "proposal-loop-v1"


class ProposalLoop:
    id = "proposal"
    version = "v1"

    def __init__(self, engine, samples: List[str], *, max_rounds: int = 3,
                 population: int = 4, max_evaluations: Optional[int] = None,
                 max_tokens: Optional[int] = None, policy: Any = None):
        if not samples or len(set(samples)) != len(samples):
            raise LoopError("samples must be unique and non-empty")
        if max_rounds < 1 or population < 1:
            raise LoopError("max_rounds and population must be positive")
        if max_evaluations is not None and max_evaluations < 1:
            raise LoopError("max_evaluations must be positive")
        if max_tokens is not None and max_tokens < 1:
            raise LoopError("max_tokens must be positive")
        self.engine = engine
        self.samples = list(samples)
        self.max_rounds = max_rounds
        self.population = population
        self.max_tokens = max_tokens
        self.budget = Budget(target_runs=max_evaluations)
        self.policy = policy
        self.rounds = 0
        self.reflected: List[str] = []
        self.evaluations = 0
        self.tokens = 0
        self.pending: Optional[Dict[str, Any]] = None
        self.stop_reason: Optional[str] = None

    # -- actions ---------------------------------------------------------
    def next_action(self) -> Dict[str, Any]:
        if self.pending is not None:
            return self.pending
        if self.stop_reason is not None:
            return {"kind": "stop", "reason": self.stop_reason}
        if not self.budget.can_spend("target_runs"):
            self.stop_reason = "evaluation_budget"
            return {"kind": "stop", "reason": self.stop_reason}
        if self.max_tokens is not None and self.tokens >= self.max_tokens:
            self.stop_reason = "token_budget"
            return {"kind": "stop", "reason": self.stop_reason}
        for proposal in self.engine.proposals:
            if proposal.status == "candidate":
                self.pending = {"kind": "evaluate",
                                "proposal_id": proposal.id,
                                "samples": list(self.samples)}
                return self.pending
        if len(self.engine.proposals) >= self.population:
            self.stop_reason = "population"
            return {"kind": "stop", "reason": self.stop_reason}
        if self.rounds >= self.max_rounds:
            self.stop_reason = "rounds"
            return {"kind": "stop", "reason": self.stop_reason}
        parent = self.policy.choose(self.engine.proposals, self.samples, self.reflected)
        self.rounds += 1
        if parent is None:
            if self.engine.proposals:
                self.stop_reason = "no_parent"
                return {"kind": "stop", "reason": self.stop_reason}
            self.pending = {"kind": "reflect", "parent": None,
                            "failures": [], "round": self.rounds}
            return self.pending
        self.reflected.append(parent.id)
        self.pending = {"kind": "reflect", "parent": parent.id,
                        "failures": self.engine.failures(parent, self.samples),
                        "round": self.rounds}
        return self.pending

    def apply(self, action: Dict[str, Any], result: Dict[str, Any]) -> None:
        if self.pending is None or action != self.pending:
            raise LoopError("no matching proposal action pending")
        kind = action.get("kind")
        if kind == "reflect":
            drafts = result.get("drafts")
            if drafts is None:
                draft = result.get("draft")
                drafts = [draft] if draft is not None else []
            if not isinstance(drafts, list):
                raise LoopError("reflect result requires a drafts list")
            parent = action.get("parent")
            for draft in drafts:
                self.engine.add(draft, parent=parent)
        elif kind == "evaluate":
            proposal = self.proposal(str(action.get("proposal_id") or ""))
            scores = result.get("scores")
            if not isinstance(scores, dict):
                raise LoopError("evaluate result requires a scores object")
            feedback = result.get("feedback") or {}
            tokens = result.get("tokens")
            self.engine.evaluate(proposal, scores, feedback, tokens=tokens)
            self.budget.spend("target_runs")
            self.evaluations += 1
            if tokens is not None:
                self.tokens += int(tokens)
        else:
            raise LoopError(f"unsupported action kind {kind!r}")
        self.pending = None

    def proposal(self, proposal_id: str):
        for proposal in self.engine.proposals:
            if proposal.id == proposal_id:
                return proposal
        raise LoopError(f"unknown proposal {proposal_id!r}")

    def parent_proposal(self):
        if self.pending is None or self.pending.get("kind") != "reflect":
            raise LoopError("no reflect action pending")
        parent = self.pending.get("parent")
        return None if parent is None else self.proposal(str(parent))

    # -- result ----------------------------------------------------------
    def result(self) -> Dict[str, Any]:
        selected = self.policy.choose(self.engine.proposals, self.samples, [])
        return {
            "loop": self.id,
            "rounds": self.rounds,
            "proposals": len(self.engine.proposals),
            "selected": selected.to_dict() if selected else None,
            "stop_reason": self.stop_reason or "rounds",
            "evaluations": self.evaluations,
            "tokens": self.tokens,
            "archive": str(self.engine.archive.path),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_schema": PROPOSAL_STATE_SCHEMA,
            "samples": list(self.samples),
            "max_rounds": self.max_rounds,
            "population": self.population,
            "max_tokens": self.max_tokens,
            "reflected": list(self.reflected),
            "rounds": self.rounds,
            "evaluations": self.evaluations,
            "tokens": self.tokens,
            "pending": self.pending,
            "stop_reason": self.stop_reason,
            "budget": self.budget.to_dict(),
            "archive": str(self.engine.archive.path),
            "proposals": [proposal.to_dict() for proposal in self.engine.proposals],
        }
