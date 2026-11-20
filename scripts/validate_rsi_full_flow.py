#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用已有真实 pilot 的候选轨迹走一遍完整 flow（探索性可选）。"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Dict

from evolve.flow import run_proposal
from evolve.policy import load_policy
from evolve.proposal_engine import ProposalArchive, ProposalEngine


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", required=True)
    parser.add_argument("--sample", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--base", default=".s2-replay/evolve")
    parser.add_argument("--exploratory", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    pilot = Path(args.pilot).resolve()
    tasks = _load(pilot / "tasks.json")
    candidate = dict(tasks.get("candidate") or {})
    candidate["candidate_id"] = candidate.get("candidate_id") or "C-REAL-FLOW"
    base = Path(args.base).resolve()
    archive = ProposalArchive(base / "proposals.jsonl")
    engine = ProposalEngine(archive)
    proposal = engine.add({
        "target_kind": candidate.get("target_kind"),
        "target_component": candidate.get("target_component"),
        "summary": f"{pilot.name} full flow",
        "expected": candidate.get("expected_effect", ""),
        "risk": "unknown", "rollback": "restore",
        "candidate": candidate,
    })
    policy = load_policy(None)
    policy["samples"]["field_eval"] = 1
    output = Path(tempfile.mkdtemp(prefix="rsi-full-flow-")) / "pilot"

    def runner(new_tasks):
        for row in new_tasks.get("samples") or []:
            sid = row["short_id"]
            for arm in ("candidate",):
                src_trace = pilot / arm / "traces" / f"{sid}.yaml"
                src_out = pilot / arm / "out" / f"{sid}.out.md"
                if src_trace.exists():
                    (Path(new_tasks["arms"][arm]["trace_dir"]) / f"{sid}.yaml").write_text(
                        src_trace.read_text(encoding="utf-8"), encoding="utf-8")
                if src_out.exists():
                    (Path(new_tasks["arms"][arm]["out_dir"]) / f"{sid}.out.md").write_text(
                        src_out.read_text(encoding="utf-8"), encoding="utf-8")

    result = run_proposal(Path(args.root).resolve(), proposal, [str(Path(args.sample).resolve())],
                          output, policy, pilot / "judge.json", archive, runner=runner,
                          baseline_traces=pilot / "baseline", exploratory=args.exploratory)
    payload = {"proposal": proposal.id, "decision": result["decision"],
               "exploratory": bool(result["experiment"].get("exploratory")),
               "experiment": result["experiment"],
               "event": result["event"]}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
