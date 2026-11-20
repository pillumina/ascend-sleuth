# -*- coding: utf-8 -*-
"""Proposal -> candidate -> pilot -> judge -> gate -> archive 编排。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .pilot import collect as pilot_collect, decide as pilot_decide, prepare as pilot_prepare
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
    collected = pilot_collect(output, judge=judge)
    result = pilot_decide(output, judge, policy, reuse_index=reuse_index,
                          proposal=proposal.id)
    decision = (result.get("conclusion") or {}).get("decision") or "unknown"
    proposal.status = decision
    proposal.decision = decision
    proposal.conclusion_ref = str(output.parent / "conclusions.jsonl")
    archive.append(proposal)
    return {"candidate": proposal.candidate, "tasks": tasks, "collected": collected,
            "conclusion": result.get("conclusion"), "decision": decision}
