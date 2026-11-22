#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用已有真实 pilot 轨迹重放一次 pilot → judge → gate，输出 stage 验收报告。"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

import yaml

from evolve.pilot import _judge_counts, collect, decide
from evolve.policy import load_policy


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(pilot: Path, keep: bool = False) -> Dict[str, Any]:
    pilot = Path(pilot)
    judge = pilot / "judge.json"
    tasks = _load(pilot / "tasks.json")
    judge_data = _load(judge)
    td = tempfile.mkdtemp(prefix="rsi-replay-")
    try:
        output = Path(td) / "pilot"
        shutil.copytree(pilot, output)
        base = Path(td) / ".s2-replay" / "evolve"
        collected = collect(output, judge=judge)
        counts = _judge_counts(tasks, judge_data)
        result = decide(output, judge, load_policy(None), base=base)
        conclusion = result.get("conclusion") or {}
        candidate = tasks.get("candidate") or {}
        stages = [
            {"id": "attribute", "state": "partial",
             "detail": f"{len(tasks.get('samples') or [])} sample refs; source paths may be stale"},
            {"id": "select_region", "state": "evidence",
             "detail": candidate.get("target_component")},
            {"id": "select_candidate", "state": "evidence",
             "detail": candidate.get("candidate_id")},
            {"id": "propose", "state": "evidence",
             "detail": f"{candidate.get('file')} base_rev={candidate.get('base_rev')}"},
            {"id": "execute", "state": "pass" if collected.get("complete") else "fail",
             "detail": f"arms={ {a: len(v or []) for a, v in (collected.get('arms') or {}).items()} }"},
            {"id": "judge", "state": "pass" if counts["n"] == len(tasks.get("samples") or []) else "partial",
             "detail": f"b={counts['b']} c={counts['c']} n={counts['n']} meta={judge_data.get('meta')}"},
            {"id": "gate", "state": "pass" if conclusion.get("decision") else "fail",
             "detail": f"decision={conclusion.get('decision')} reason={conclusion.get('reason')}"},
        ]
        return {
            "pilot": str(pilot), "temporary_output": str(output) if keep else None,
            "stages": stages, "decision": conclusion.get("decision"),
            "conclusion": conclusion,
            "agent_heuristic": {
                "state": "available",
                "detail": "candidate was produced by the recorded agent pilot",
                "candidate_id": candidate.get("candidate_id"),
            },
            "gepa": {
                "state": "blocked",
                "detail": "this pilot has one candidate; no same-target candidate population to select over",
            },
            "data_gaps": [
                gap for gap in (
                    "sample paths in tasks.json may point at removed worktrees",
                    "no proposal/decision/rollout event writer in the historical pilot",
                )
            ],
        }
    finally:
        if not keep:
            shutil.rmtree(td, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    report = validate(Path(args.pilot), keep=args.keep)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
