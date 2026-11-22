# -*- coding: utf-8 -*-
"""提案引擎：表示、校验、候选池、Pareto 选择与闭环。"""

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.proposal_engine import (  # noqa: E402
    GepaPolicy, ParetoPolicy, ProposalArchive, ProposalEngine,
)


def skill_draft(component="diagnose.knowledge_usage", diff="+ 只载筛出的候选"):
    return {
        "target_kind": "skill",
        "target_component": component,
        "summary": "阶段二只载筛出的候选",
        "change": {"files": ["skills/diagnose/SKILL.md"], "diff": diff},
        "expected": "读取量下降",
        "risk": "低",
        "rollback": "恢复原阶段二说明",
    }


class ProposalEngineTest(unittest.TestCase):
    def test_pareto_selects_dominating_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            engine = ProposalEngine(ProposalArchive(Path(td) / "proposals.jsonl"))
            a = engine.add(skill_draft())
            engine.evaluate(a, {"s1": 1, "s2": 0})
            b = engine.add(skill_draft(diff="+ 只载筛出的候选，保留兜底"))
            engine.evaluate(b, {"s1": 1, "s2": 1})
            selected = ParetoPolicy().choose(engine.proposals, ["s1", "s2"])
            self.assertEqual(selected.id, b.id)

    def test_codec_rejects_wrong_extension(self):
        with tempfile.TemporaryDirectory() as td:
            engine = ProposalEngine(ProposalArchive(Path(td) / "proposals.jsonl"))
            p = engine.add({
                "target_kind": "knowledge",
                "target_component": "knowledge.case_content",
                "summary": "补判别",
                "change": {"files": ["scripts/x.py"], "diff": "+ x"},
                "expected": "提升",
                "risk": "低",
                "rollback": "恢复",
            })
            self.assertEqual(p.status, "invalid")
            self.assertTrue(any("outside" in e or "forbidden" in e for e in p.errors))

    def test_candidate_proposal_keeps_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            engine = ProposalEngine(ProposalArchive(Path(td) / "proposals.jsonl"))
            p = engine.add({
                "target_kind": "knowledge",
                "summary": "补判别",
                "expected": "提升",
                "risk": "低",
                "rollback": "恢复",
                "candidate": {
                    "candidate_id": "C-K1", "target_kind": "knowledge",
                    "target_component": "knowledge.case_content",
                    "region": "knowledge.case_content",
                    "file": "knowledge/inference/vllm-ascend/case.yaml",
                    "base_rev": "HEAD",
                    "old_text": "quickly_check: 旧判别\n",
                    "new_text": "quickly_check: 新判别\n",
                },
            })
            self.assertEqual(p.status, "candidate")
            self.assertEqual(p.candidate["candidate_id"], "C-K1")
            self.assertEqual(p.component, "knowledge.case_content")

    def test_gepa_loop_selects_child(self):
        with tempfile.TemporaryDirectory() as td:
            engine = ProposalEngine(ProposalArchive(Path(td) / "proposals.jsonl"))
            calls = {"n": 0}

            def proposer(parent, failures, round_no):
                calls["n"] += 1
                if parent is None:
                    return [skill_draft(diff="+ seed")]
                return [skill_draft(diff="+ child")]

            def evaluator(proposal, samples):
                return ({"s1": 1, "s2": 1 if "child" in proposal.artifact["diff"] else 0},
                        {"s1": "", "s2": "still miss" if "child" not in proposal.artifact["diff"] else ""})

            result = engine.run(proposer, evaluator, ["s1", "s2"],
                                max_rounds=2, population=4, policy=GepaPolicy())
            self.assertEqual(result["rounds"], 2)
            self.assertEqual(result["selected"]["artifact"]["diff"], "+ child")
            self.assertGreaterEqual(calls["n"], 2)

    def test_evaluation_budget_stops_loop(self):
        with tempfile.TemporaryDirectory() as td:
            engine = ProposalEngine(ProposalArchive(Path(td) / "proposals.jsonl"))

            def proposer(parent, failures, round_no):
                return [skill_draft(diff=f"+ {round_no}"), skill_draft(diff=f"+ {round_no}b")]

            def evaluator(proposal, samples):
                return ({"s1": 1, "s2": 1}, {})

            result = engine.run(proposer, evaluator, ["s1", "s2"],
                                max_rounds=3, population=10, max_evaluations=1)
            self.assertEqual(result["stop_reason"], "evaluation_budget")
            self.assertEqual(result["evaluations"], 1)

    def test_token_budget_stops_loop(self):
        with tempfile.TemporaryDirectory() as td:
            engine = ProposalEngine(ProposalArchive(Path(td) / "proposals.jsonl"))

            def proposer(parent, failures, round_no):
                return [skill_draft(diff="+ token")]

            def evaluator(proposal, samples):
                return ({"s1": 1, "s2": 1}, {}, 10)

            result = engine.run(proposer, evaluator, ["s1", "s2"],
                                max_rounds=3, population=10, max_tokens=5)
            self.assertEqual(result["stop_reason"], "token_budget")
            self.assertEqual(result["tokens"], 10)
            self.assertEqual(result["evaluations"], 1)

    def test_archive_latest_by_id(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "proposals.jsonl"
            engine = ProposalEngine(ProposalArchive(path))
            p = engine.add(skill_draft())
            engine.evaluate(p, {"s1": 1, "s2": 1})
            latest = ProposalArchive(path).latest(p.id)
            self.assertEqual(latest["status"], "evaluated")

    def test_two_engines_on_same_archive_get_distinct_ids(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "proposals.jsonl"
            a = ProposalEngine(ProposalArchive(path))
            first = a.add(skill_draft())
            b = ProposalEngine(ProposalArchive(path))
            second = b.add(skill_draft())
            self.assertNotEqual(first.id, second.id)
            self.assertEqual(second.id, "P-0002")

    def test_archive_records_proposals(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "proposals.jsonl"
            engine = ProposalEngine(ProposalArchive(path))
            p = engine.add(skill_draft())
            engine.evaluate(p, {"s1": 1})
            rows = ProposalArchive(path).read()
            self.assertTrue(rows)
            self.assertEqual(rows[-1]["id"], p.id)


if __name__ == "__main__":
    unittest.main()
