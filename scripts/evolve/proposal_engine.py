# -*- coding: utf-8 -*-
"""通用提案引擎：表示、校验、候选池、搜索策略与归档。

框架不绑定 GEPA：GEPA 只是 ``ParetoPolicy + 反思 proposer`` 的组合。
候选生成/评估由 callable 或外部 agent 提供；本模块不调用模型。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .contracts import now_iso
from .records import JsonlStore
from .proposals import ProposalError, validate_draft
from .selectors import BestSelector, ParetoSelector


ARTIFACT_KIND = {
    "skill": "text",
    "knowledge": "yaml",
    "tooling": "code",
    "harness": "config",
}


@dataclass
class Proposal:
    id: str
    target: str
    component: str
    summary: str
    artifact_kind: str
    artifact: Dict[str, Any]
    draft: Dict[str, Any]
    parent: Optional[str] = None
    expected: str = ""
    risk: str = ""
    rollback: str = ""
    evidence: List[str] = field(default_factory=list)
    candidate: Optional[Dict[str, Any]] = None
    status: str = "candidate"
    decision: Optional[str] = None
    conclusion_ref: Optional[str] = None
    workspace: Optional[str] = None
    rolled_back: bool = False
    scores: Dict[str, float] = field(default_factory=dict)
    feedback: Dict[str, str] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    @property
    def skill(self) -> str:
        """兼容 selectors 的文本长度排序；不是“只支持 skill”。"""
        return str(self.artifact.get("diff") or self.summary or "")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "target": self.target, "component": self.component,
            "summary": self.summary, "artifact_kind": self.artifact_kind,
            "artifact": self.artifact, "parent": self.parent,
            "expected": self.expected, "risk": self.risk, "rollback": self.rollback,
            "evidence": list(self.evidence),
            "candidate": dict(self.candidate) if self.candidate else None,
            "status": self.status, "decision": self.decision,
            "conclusion_ref": self.conclusion_ref,
            "workspace": self.workspace, "rolled_back": self.rolled_back,
            "scores": dict(self.scores), "feedback": dict(self.feedback),
            "errors": list(self.errors), "at": now_iso(),
        }


def codec_errors(proposal: Proposal) -> List[str]:
    errors: List[str] = []
    files = proposal.artifact.get("files") or []
    diff = proposal.artifact.get("diff") or ""
    kind = proposal.artifact_kind
    if not isinstance(diff, str) or not diff.strip():
        errors.append("artifact.diff is required")
    if kind == "yaml":
        for path in files:
            if not str(path).endswith((".yaml", ".yml")):
                errors.append(f"yaml proposal cannot change {path}")
    elif kind == "code":
        for path in files:
            text = str(path)
            if not (text.endswith(".py") or text.startswith("source-catalog.d/")):
                errors.append(f"code proposal cannot change {path}")
    elif kind == "config":
        for path in files:
            if not str(path).endswith((".yaml", ".yml", ".json", ".py")):
                errors.append(f"config proposal cannot change {path}")
    return errors


def proposal_from_draft(proposal_id: str, draft: Dict[str, Any],
                        parent: Optional[str] = None) -> Proposal:
    target = str(draft.get("target_kind") or "")
    if target not in ARTIFACT_KIND:
        raise ProposalError(f"unknown target_kind {target!r}")
    patch = validate_draft(draft)
    payload = patch.payload
    change = payload.get("change") or {}
    proposal = Proposal(
        id=proposal_id, target=target, component=patch.target_component,
        summary=patch.summary, artifact_kind=ARTIFACT_KIND[target],
        artifact={"files": list(change.get("files") or []),
                  "diff": change.get("diff") or ""},
        draft=draft, parent=parent, expected=payload.get("expected") or "",
        risk=payload.get("risk") or "", rollback=payload.get("rollback") or "",
        evidence=list(payload.get("evidence") or []),
        candidate=payload.get("candidate"),
    )
    proposal.errors = codec_errors(proposal)
    return proposal


class ProposalArchive:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._store = JsonlStore(self.path)

    def append(self, proposal: Proposal) -> None:
        self._store.append(proposal.to_dict())

    def read(self) -> List[Dict[str, Any]]:
        return self._store.read()

    def latest(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        hits = [row for row in self.read() if row.get("id") == proposal_id]
        return hits[-1] if hits else None


class BestPolicy:
    id = "select.best"

    def choose(self, candidates: List[Proposal], samples: List[str],
               reflected: Iterable[str] = ()) -> Optional[Proposal]:
        done = [c for c in candidates
                if c.status == "evaluated" and len(c.scores) == len(samples)]
        return BestSelector().choose(done, samples, set(reflected))


class ParetoPolicy:
    id = "select.pareto"

    def choose(self, candidates: List[Proposal], samples: List[str],
               reflected: Iterable[str] = ()) -> Optional[Proposal]:
        done = [c for c in candidates
                if c.status == "evaluated" and len(c.scores) == len(samples)]
        return ParetoSelector().choose(done, samples, set(reflected))


class GepaPolicy(ParetoPolicy):
    """GEPA 的选择层：Pareto front + 未反射候选；反思由调用方提供。"""

    id = "gepa"


class ProposalEngine:
    """生成 -> 校验 -> 评分 -> 选择 -> 归档；不绑定具体算法。"""

    def __init__(self, archive: ProposalArchive):
        self.archive = archive
        self.proposals: List[Proposal] = []
        self.reflected: List[str] = []
        existing = [str(row.get("id") or "") for row in archive.read()]
        numbers = [int(item.split("-")[1]) for item in existing
                   if item.startswith("P-") and item.split("-")[1].isdigit()]
        self._next = max(numbers, default=0) + 1
        self.evaluations = 0
        self.tokens = 0

    def _id(self) -> str:
        value = f"P-{self._next:04d}"
        self._next += 1
        return value

    def add(self, draft: Dict[str, Any], parent: Optional[str] = None) -> Proposal:
        proposal_id = self._id()
        try:
            proposal = proposal_from_draft(proposal_id, draft, parent=parent)
        except ProposalError as exc:
            target = str(draft.get("target_kind") or "")
            proposal = Proposal(
                id=proposal_id, target=target,
                component=str(draft.get("target_component") or ""),
                summary=str(draft.get("summary") or ""),
                artifact_kind=ARTIFACT_KIND.get(target, "unknown"),
                artifact=draft.get("change") if isinstance(draft.get("change"), dict) else {},
                draft=draft, parent=parent, errors=[str(exc)],
            )
        proposal.status = "invalid" if proposal.errors else "candidate"
        self.proposals.append(proposal)
        self.archive.append(proposal)
        return proposal

    def evaluate(self, proposal: Proposal, scores: Dict[str, float],
                 feedback: Optional[Dict[str, str]] = None,
                 tokens: Optional[int] = None) -> Proposal:
        if proposal.status == "invalid":
            return proposal
        proposal.scores = {str(k): float(v) for k, v in scores.items()}
        proposal.feedback = {str(k): str(v) for k, v in (feedback or {}).items()}
        proposal.status = "evaluated"
        self.evaluations += 1
        if tokens is not None:
            self.tokens += int(tokens)
        self.archive.append(proposal)
        return proposal

    def failures(self, proposal: Proposal, samples: List[str], threshold: float = 0.0) -> List[Dict[str, str]]:
        return [{"sample": sid, "score": proposal.scores[sid],
                 "feedback": proposal.feedback.get(sid, "")}
                for sid in samples if proposal.scores.get(sid, 0.0) <= threshold]

    def run(self, proposer: Callable[[Optional[Proposal], List[Dict[str, str]], int], List[Dict[str, Any]]],
            evaluator: Callable[[Proposal, List[str]], tuple], samples: List[str],
            *, max_rounds: int = 3, population: int = 4,
            max_evaluations: Optional[int] = None,
            max_tokens: Optional[int] = None,
            policy: Optional[Any] = None) -> Dict[str, Any]:
        """闭环：proposer -> validate -> evaluate -> select -> reflect -> proposer。"""
        if not samples or len(set(samples)) != len(samples):
            raise ProposalError("samples must be unique and non-empty")
        if max_rounds < 1 or population < 1:
            raise ProposalError("max_rounds and population must be positive")
        if max_evaluations is not None and max_evaluations < 1:
            raise ProposalError("max_evaluations must be positive")
        if max_tokens is not None and max_tokens < 1:
            raise ProposalError("max_tokens must be positive")
        policy = policy or ParetoPolicy()
        rounds = 0
        stop_reason = "rounds"
        while rounds < max_rounds and len(self.proposals) < population:
            if max_evaluations is not None and self.evaluations >= max_evaluations:
                stop_reason = "evaluation_budget"
                break
            if max_tokens is not None and self.tokens >= max_tokens:
                stop_reason = "token_budget"
                break
            parent = policy.choose(self.proposals, samples, self.reflected)
            if parent is None:
                # 首次：用 seed（无父）生成；之后没有可反思候选就停。
                if self.proposals:
                    stop_reason = "no_parent"
                    break
                drafts = proposer(None, [], 0)
            else:
                self.reflected.append(parent.id)
                drafts = proposer(parent, self.failures(parent, samples), rounds + 1)
            added = 0
            for draft in drafts:
                proposal = self.add(draft, parent=parent.id if parent else None)
                if proposal.status == "evaluated":
                    continue
                if proposal.status == "invalid":
                    continue
                result = evaluator(proposal, samples)
                if len(result) == 3:
                    scores, feedback, tokens = result
                else:
                    scores, feedback = result
                    tokens = None
                self.evaluate(proposal, scores, feedback, tokens=tokens)
                added += 1
                if max_evaluations is not None and self.evaluations >= max_evaluations:
                    stop_reason = "evaluation_budget"
                    break
                if max_tokens is not None and self.tokens >= max_tokens:
                    stop_reason = "token_budget"
                    break
            rounds += 1
            if stop_reason in ("evaluation_budget", "token_budget"):
                break
            if added == 0:
                stop_reason = "no_valid"
                break
        if stop_reason not in ("evaluation_budget", "token_budget") and len(self.proposals) >= population:
            stop_reason = "population"
        selected = policy.choose(self.proposals, samples, [])
        return {
            "rounds": rounds,
            "proposals": len(self.proposals),
            "selected": selected.to_dict() if selected else None,
            "stop_reason": stop_reason,
            "evaluations": self.evaluations,
            "tokens": self.tokens,
            "archive": str(self.archive.path),
        }
