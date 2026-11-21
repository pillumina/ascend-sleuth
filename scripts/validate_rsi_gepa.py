#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用两个真实 pilot 的候选与 judge 数据跑一次 GEPA 选择，输出评估报告。"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from evolve.pilot import collect, decide
from evolve.policy import load_policy
from evolve.proposal_engine import GepaPolicy, ProposalArchive, ProposalEngine


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_one(pilot: Path, base: Path, exploratory: bool = False,
                 primary_dimension: str = "tokens") -> Dict[str, Any]:
    pilot = Path(pilot)
    tasks = _load(pilot / "tasks.json")
    judge = _load(pilot / "judge.json")
    collected = collect(pilot, judge=pilot / "judge.json")
    policy = load_policy(None)
    policy["cost"]["primary_dimension"] = primary_dimension
    result = decide(pilot, pilot / "judge.json", policy, base=base,
                    exploratory=exploratory)
    candidate = tasks.get("candidate") or {}
    candidate["base_rev"] = candidate.get("base_rev") or "HEAD"
    proposal = ProposalEngine(ProposalArchive(base / f"{pilot.name}.jsonl")).add({
        "target_kind": candidate.get("target_kind"),
        "target_component": candidate.get("target_component"),
        "summary": f"{pilot.name} candidate",
        "expected": candidate.get("expected_effect", ""),
        "risk": "unknown", "rollback": "restore",
        "candidate": candidate,
    })
    scores = {str(row.get("short_id") or row.get("id")): int(judge["candidate"][str(row.get("short_id") or row.get("id"))])
              for row in tasks.get("samples") or []}
    proposal.scores = scores
    proposal.status = "evaluated" if (result.get("conclusion") or {}).get("decision") == "accept" else "rejected"
    return {"pilot": str(pilot), "proposal": proposal, "scores": scores,
            "decision": (result.get("conclusion") or {}).get("decision"),
            "conclusion": result.get("conclusion")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", action="append", required=True, help="至少两个真实 pilot 目录")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--exploratory", action="store_true")
    parser.add_argument("--primary-dimension", default="tokens")
    args = parser.parse_args()
    if len(args.pilot) < 2:
        print("error: pass at least two pilots", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="rsi-gepa-validate-") as td:
        base = Path(td)
        rows = [evaluate_one(Path(item), base, exploratory=args.exploratory,
                              primary_dimension=args.primary_dimension)
                for item in args.pilot]
        samples = sorted(set(rows[0]["scores"]) & set(rows[1]["scores"]))
        selected = GepaPolicy().choose([row["proposal"] for row in rows], samples)
        report = {
            "samples": samples,
            "candidates": [{"pilot": row["pilot"], "id": row["proposal"].id,
                            "scores": row["scores"], "gate": row["decision"]}
                           for row in rows],
            "gepa_selected": selected.id if selected else None,
            "gepa_selected_pilot": next((row["pilot"] for row in rows
                                          if selected and row["proposal"].id == selected.id), None),
            "gate_ok": [row["decision"] for row in rows],
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
