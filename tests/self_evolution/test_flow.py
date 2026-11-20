# -*- coding: utf-8 -*-
"""Proposal -> candidate -> pilot -> judge -> gate -> archive 端到端。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.flow import run_proposal  # noqa: E402
from evolve.policy import load_policy  # noqa: E402
from evolve.proposal_engine import ProposalArchive, ProposalEngine  # noqa: E402


def _repo(root: Path):
    (root / "skills" / "diagnose").mkdir(parents=True)
    (root / "skills" / "diagnose" / "SKILL.md").write_text(
        "# diagnose\n\n阶段二载全文，按知识候选核对。\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)


def _draft():
    return {
        "target_kind": "skill",
        "target_component": "diagnose.knowledge_usage",
        "summary": "阶段二只载筛出的候选",
        "expected": "读取量下降",
        "risk": "低",
        "rollback": "恢复原阶段二",
        "candidate": {
            "candidate_id": "C-FLOW-1", "target_kind": "skill",
            "target_component": "diagnose.knowledge_usage",
            "region": "diagnose.knowledge_usage",
            "file": "skills/diagnose/SKILL.md", "base_rev": "HEAD",
            "old_text": "阶段二载全文，按知识候选核对。\n",
            "new_text": "阶段二只载筛出的候选全文，按知识候选核对。\n",
        },
    }


class FlowTest(unittest.TestCase):
    def test_proposal_to_decision_and_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"; root.mkdir(); _repo(root)
            archive = ProposalArchive(Path(td) / "proposals.jsonl")
            engine = ProposalEngine(archive)
            proposal = engine.add(_draft())
            samples = []
            for i in range(4):
                path = Path(td) / f"S-{1000+i}.yaml"
                path.write_text(yaml.safe_dump({
                    "id": f"S-{1000+i}", "source": f"github/x/{i}",
                    "input": {"title": f"S-{i}"}, "expected": {"resolution": "ok"},
                }), encoding="utf-8")
                samples.append(str(path))
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({
                "baseline": {str(1000+i): 0 for i in range(4)},
                "candidate": {str(1000+i): 1 for i in range(4)},
                "meta": {"agent": "test"},
            }), encoding="utf-8")

            def runner(tasks):
                for arm in ("baseline", "candidate"):
                    for sample in tasks["samples"]:
                        sid = sample["short_id"]
                        (Path(tasks["arms"][arm]["trace_dir"]) / f"{sid}.yaml").write_text(
                            yaml.safe_dump({"session_id": sid, "model": "test", "trace": []}),
                            encoding="utf-8")
                        (Path(tasks["arms"][arm]["out_dir"]) / f"{sid}.out.md").write_text(
                            "ok", encoding="utf-8")

            result = run_proposal(root, proposal, samples, Path(td) / "pilot",
                                  load_policy(None), judge, archive, runner=runner)
            self.assertEqual(result["conclusion"]["decision"], "accept")
            rows = ProposalArchive(Path(td) / "proposals.jsonl").read()
            self.assertEqual(rows[-1]["status"], "accept")
            self.assertTrue((Path(td) / "pilot" / "candidate-worktree").exists())

    def test_requires_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            engine = ProposalEngine(ProposalArchive(Path(td) / "proposals.jsonl"))
            p = engine.add({
                "target_kind": "skill", "target_component": "diagnose.knowledge_usage",
                "summary": "x", "change": {"files": ["skills/diagnose/SKILL.md"], "diff": "+ x"},
                "expected": "x", "risk": "低", "rollback": "x",
            })
            with self.assertRaises(Exception):
                run_proposal(Path(td), p, ["s"], Path(td) / "out", load_policy(None),
                             Path(td) / "j", ProposalArchive(Path(td) / "a.jsonl"))


if __name__ == "__main__":
    unittest.main()
