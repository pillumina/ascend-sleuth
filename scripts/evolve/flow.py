# -*- coding: utf-8 -*-
"""Proposal -> candidate -> pilot -> judge -> gate -> archive 编排。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typing import Any, Callable, Dict, List, Optional

from .experiments import ExperimentError, validate_experiment
from .candidate import rollback_workspace
from .pilot import collect as pilot_collect, decide as pilot_decide, prepare as pilot_prepare
from .records import ExperimentStore
from .proposal_engine import Proposal, ProposalArchive, ProposalEngine


class FlowError(ValueError):
    pass


def run_proposal(root: Path, proposal: Proposal, samples: List[str], output: Path,
                 policy: Dict[str, Any], judge: Path,
                 archive: ProposalArchive,
                 runner: Optional[Callable[[Dict[str, Any]], None]] = None,
                 baseline_traces: Optional[Path] = None,
                 reuse_index: int = 0) -> Dict[str, Any]:
    if not proposal.candidate:
        raise FlowError("proposal has no candidate; provide draft.candidate")
    root, output = Path(root), Path(output)
    candidate_path = output.parent / f"{proposal.id}.candidate.json"
    candidate_path.write_text(json.dumps(proposal.candidate, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    tasks = pilot_prepare(root, candidate_path, samples, output, policy=policy,
                          baseline_traces=baseline_traces)
    if runner is not None:
        runner(tasks)
    _reject_fallback(tasks)
    collected = pilot_collect(output, judge=judge)
    result = pilot_decide(output, judge, policy, reuse_index=reuse_index,
                          proposal=proposal.id)
    decision = (result.get("conclusion") or {}).get("decision") or "unknown"
    proposal.status = decision
    proposal.decision = decision
    proposal.conclusion_ref = str(output.parent / "conclusions.jsonl")
    proposal.workspace = str(tasks.get("workspace") or "")
    if decision != "accept" and proposal.workspace:
        rollback_workspace(Path(root), Path(proposal.workspace))
        proposal.rolled_back = True
    archive.append(proposal)
    experiment = _experiment_record(proposal, tasks, judge, decision,
                                    result.get("conclusion") or {})
    ExperimentStore.for_base(archive.path.parent).append(experiment)
    return {"candidate": proposal.candidate, "tasks": tasks, "collected": collected,
            "conclusion": result.get("conclusion"), "decision": decision,
            "experiment": experiment}


def _side_scores(judge: Dict[str, Any], side: str, samples: List[str]) -> Dict[str, float]:
    raw = judge.get(side) or {}
    if not isinstance(raw, dict):
        raise FlowError(f"judge.{side} must be an object")
    values = [float(raw[s]) for s in samples if s in raw]
    if len(values) != len(samples):
        raise FlowError(f"judge.{side} is missing samples")
    return {sample: float(raw[sample]) for sample in samples}


def _reject_fallback(tasks: Dict[str, Any]) -> None:
    for sample in tasks.get("samples") or []:
        sid = str(sample.get("short_id") or sample.get("id"))
        for arm in tasks.get("arms") or {}:
            path = Path(tasks["arms"][arm]["trace_dir"]) / f"{sid}.yaml"
            if not path.exists():
                continue
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                raise FlowError(f"unreadable trace {path}: {exc}") from exc
            if doc.get("adapter_fallback"):
                raise FlowError(
                    f"adapter fallback trace is not valid evidence: {path}")


def _experiment_record(proposal: Proposal, tasks: Dict[str, Any], judge: Path,
                       decision: str, conclusion: Dict[str, Any]) -> Dict[str, Any]:
    data = json.loads(Path(judge).read_text(encoding="utf-8"))
    samples = [str(row.get("short_id") or row.get("id")) for row in tasks.get("samples") or []]
    baseline = _side_scores(data, "baseline", samples)
    candidate = _side_scores(data, "candidate", samples)
    record = {
        "target_kind": proposal.target,
        "target_component": proposal.component,
        "algorithm": "agent_draft",
        "algorithm_version": "v1",
        "execution": "subagent",
        "decision": decision,
        "samples": samples,
        "baseline": {"score": sum(baseline.values()) / len(baseline),
                     "samples": samples},
        "candidate": {"score": sum(candidate.values()) / len(candidate),
                      "samples": samples},
        "eval_profile_id": "subagent_judge",
        "eval_ready": False,
        "summary": proposal.summary,
        "proposal": proposal.id,
    }
    if conclusion.get("b") is not None:
        record["paired"] = {"b": conclusion["b"], "c": conclusion["c"],
                            "n": conclusion["n"],
                            "alpha_eff": conclusion.get("alpha_eff", 0.1)}
    try:
        return validate_experiment(record)
    except ExperimentError as exc:
        raise FlowError(f"experiment record invalid: {exc}") from exc
