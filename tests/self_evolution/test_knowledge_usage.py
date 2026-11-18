"""知识使用指标与门禁：效率不降、准确率不降才 accept。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.knowledge_usage import UsageError, compare, from_trace, summarize  # noqa: E402
from evolve.regions import REGIONS  # noqa: E402
from evolve.experiments import ExperimentError, validate_experiment  # noqa: E402


def row(sample, hit=True, step=1, candidates=1, body=1, refs=0, wrong=0, tokens=100,
        elapsed=1000):
    return {"sample_id": sample, "hit": hit, "first_hit_step": step if hit else None,
            "candidates_examined": candidates, "full_body_reads": body,
            "reference_lookups": refs, "wrong_cases": wrong, "tokens": tokens,
            "elapsed_ms": elapsed}


class KnowledgeUsageTest(unittest.TestCase):
    def test_from_trace_derives_usage_without_zero_fill(self):
        trace = {
            "session_id": "s1",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:02+00:00",
            "trace": [
                {"action": "load_index", "considered_candidates": 5},
                {"action": "quickly_check", "case": "C-1"},
                {"action": "quickly_check", "case": "C-2"},
                {"action": "reference_lookup", "outcome": "hit"},
                {"action": "reference_lookup", "outcome": "skipped"},
                {"action": "hit", "case": "C-2", "step": 3},
            ],
        }
        out = from_trace(trace, expected_case="C-2")
        self.assertEqual(out["candidates_examined"], 5)
        self.assertEqual(out["full_body_reads"], 2)
        self.assertEqual(out["reference_lookups"], 1)
        self.assertEqual(out["first_hit_step"], 3)
        self.assertTrue(out["hit"])
        self.assertEqual(out["wrong_cases"], 0)
        self.assertAlmostEqual(out["elapsed_ms"], 2000.0)

    def test_from_trace_marks_wrong_final_case(self):
        trace = {"session_id": "s2", "trace": [{"action": "hit", "case": "C-1", "step": 2}]}
        out = from_trace(trace, expected_case="C-2")
        self.assertFalse(out["hit"])
        self.assertIsNone(out["first_hit_step"])
        self.assertEqual(out["wrong_cases"], 1)

    def test_region_is_registered(self):
        self.assertIn("diagnose.knowledge_usage", REGIONS)

    def test_summary_uses_only_present_numbers(self):
        out = summarize([row("a"), row("b", hit=False, step=None, tokens=None)])
        self.assertEqual(out["n"], 2)
        self.assertEqual(out["hits"], 1)
        self.assertAlmostEqual(out["tokens"], 100.0)

    def test_accept_when_accuracy_not_worse_and_efficiency_better(self):
        base = [row("a", step=4, candidates=3, body=3), row("b", step=5, candidates=3, body=3)]
        cand = [row("a", step=2, candidates=1, body=1), row("b", step=2, candidates=1, body=1)]
        result = compare(base, cand)
        self.assertEqual(result["decision"], "accept")
        self.assertEqual(result["reasons"], [])

    def test_reject_on_wrong_case_or_accuracy_regression(self):
        base = [row("a")]
        self.assertEqual(compare(base, [row("a", wrong=1)])["decision"], "reject")
        self.assertEqual(compare(base, [row("a", hit=False, step=None)])["decision"], "reject")

    def test_insufficient_when_no_efficiency_gain(self):
        base = [row("a")]
        self.assertEqual(compare(base, [row("a")])["decision"], "insufficient")

    def test_missing_efficiency_field_stays_unknown(self):
        out = summarize([{"sample_id": "a", "hit": False, "first_hit_step": None,
                          "candidates_examined": 1, "full_body_reads": 1,
                          "reference_lookups": 1}])
        self.assertIsNone(out["wrong_cases"])
        self.assertEqual(out["candidates_examined"], 1)

    def test_knowledge_usage_accept_requires_usage_evidence(self):
        record = {
            "target_kind": "skill", "target_component": "diagnose.knowledge_usage",
            "algorithm": "subagent-reflection", "algorithm_version": "1",
            "execution": "subagent", "decision": "accept", "samples": ["S-1"],
            "baseline": {"score": 0.5, "samples": ["S-1"]},
            "candidate": {"score": 0.6, "samples": ["S-1"]},
            "paired": {"b": 4, "c": 0, "n": 4},
        }
        with self.assertRaises(ExperimentError):
            validate_experiment(record)
        record["knowledge_usage"] = {"decision": "accept"}
        with self.assertRaises(ExperimentError):
            validate_experiment(record)

    def test_missing_hit_step_is_unknown_not_zero(self):
        with self.assertRaises(UsageError):
            summarize([row("a", hit=False, step=None)] + [{"sample_id": "b", "hit": True}])

    def test_unpaired_samples_do_not_create_regression(self):
        # 基线在 b 上没记全文读取数；候选记了 5。两侧样本集不同，逐侧求均值
        # 会把候选的 5 算成回退——配对比只该用两侧都有值的 a、c 两个样本。
        base = [row("a", body=1), row("b", body=None), row("c", body=1)]
        cand = [row("a", body=1), row("b", body=5), row("c", body=1)]
        result = compare(base, cand)
        self.assertEqual(result["paired"]["full_body_reads"]["n"], 2)
        self.assertEqual(result["paired"]["full_body_reads"]["unknown"], 1)
        self.assertNotIn("efficiency_regressed", result["reasons"])
        self.assertEqual(result["decision"], "insufficient")

    def test_partial_improvement_cannot_make_accept(self):
        base = [row("a", candidates=3), row("b", candidates=None)]
        cand = [row("a", candidates=1), row("b", candidates=1)]
        result = compare(base, cand)
        self.assertEqual(result["paired"]["candidates_examined"]["n"], 1)
        self.assertNotEqual(result["decision"], "accept")

    def test_tiny_delta_is_not_a_change(self):
        base = [row("a", elapsed=1000.0)]
        cand = [row("a", elapsed=1000.00000000005)]
        result = compare(base, cand)
        self.assertNotIn("efficiency_regressed", result["reasons"])
        self.assertEqual(result["decision"], "insufficient")

    def test_partial_regression_is_insufficient(self):
        base = [row("a", elapsed=1000), row("b", elapsed=None)]
        cand = [row("a", elapsed=9000), row("b", elapsed=1000)]
        result = compare(base, cand)
        self.assertIn("efficiency_partial_unknown", result["reasons"])
        self.assertEqual(result["decision"], "insufficient")

    def test_from_trace_reads_candidates_list_on_load_full(self):
        trace = {"session_id": "s3", "trace": [
            {"action": "load_index", "considered_candidates": ["C-1", "C-2", "C-3"]},
            {"action": "load_full", "candidates": ["C-1", "C-2"]},
            {"action": "quickly_check", "case": "C-3"},
        ]}
        out = from_trace(trace)
        self.assertEqual(out["candidates_examined"], 3)
        self.assertEqual(out["full_body_reads"], 2)

    @staticmethod
    def _usage_record(decision, wrong):
        side = {"n": 1, "hits": 0, "hit_rate": 0.0, "wrong_cases": wrong,
                "first_hit_step": None, "candidates_examined": 3,
                "full_body_reads": 2, "reference_lookups": 1,
                "tokens": None, "elapsed_ms": 1000.0}
        return {
            "target_kind": "skill", "target_component": "diagnose.knowledge_usage",
            "algorithm": "subagent-reflection", "algorithm_version": "1",
            "execution": "subagent", "eval_profile_id": "subagent_judge",
            "eval_ready": False, "decision": decision, "samples": ["S-1"],
            "baseline": {"score": 0.5, "samples": ["S-1"]},
            "candidate": {"score": 0.6, "samples": ["S-1"]},
            "knowledge_usage": {
                "decision": decision, "reasons": ["wrong_cases_unknown"],
                "baseline": dict(side), "candidate": dict(side),
                "deltas": {"first_hit_step": None, "candidates_examined": 0,
                           "full_body_reads": 0, "reference_lookups": 0,
                           "tokens": None, "elapsed_ms": 0.0},
            },
        }

    def test_reject_record_may_carry_unknown_wrong_cases(self):
        validate_experiment(self._usage_record("reject", None))

    def test_accept_record_requires_known_wrong_cases(self):
        record = self._usage_record("accept", None)
        record["knowledge_usage"]["reasons"] = []
        with self.assertRaises(ExperimentError):
            validate_experiment(record)


if __name__ == "__main__":
    unittest.main()
