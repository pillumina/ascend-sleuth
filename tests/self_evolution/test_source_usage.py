"""源码访问使用效率：观测与门禁。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.experiments import ExperimentError, validate_experiment  # noqa: E402
from evolve.source_usage import (  # noqa: E402
    SourceUsageError, compare, from_trace, summarize,
)


def row(sample, files=2, calls=4, fetch=1, grep=2, elapsed=1000, correct=True):
    return {"sample_id": sample, "repos": ["r"], "refs": ["main"],
            "files_read": files, "tool_calls": calls, "fetch_calls": fetch,
            "grep_calls": grep, "followups": 0, "elapsed_ms": elapsed,
            "cache_hits": None, "downloads": None, "bytes": None,
            "source_ok": correct}


class SourceUsageTest(unittest.TestCase):
    def test_from_trace_counts_source_events(self):
        trace = {"session_id": "s1", "trace": [
            {"action": "source_analysis", "repo": "r", "ref": "main",
             "files_read": ["a.py", "b.py"],
             "tool_calls": ["src_fetch.py r main", "grep a.py", "grep b.py"]},
            {"action": "source_analysis", "repo": "r", "ref": "v2",
             "files_read": ["a.py"], "tool_calls": ["git fetch v2"]},
        ]}
        out = from_trace(trace)
        self.assertEqual(out["files_read"], 2)
        self.assertEqual(out["tool_calls"], 4)
        self.assertEqual(out["fetch_calls"], 2)
        self.assertEqual(out["grep_calls"], 2)
        self.assertIsNone(out["source_ok"])

    def test_empty_tool_calls_is_zero_not_unknown(self):
        trace = {"session_id": "s", "trace": [
            {"action": "source_analysis", "tool_calls": []},
        ]}
        out = from_trace(trace)
        self.assertEqual(out["tool_calls"], 0)
        self.assertEqual(out["fetch_calls"], 0)
        self.assertEqual(out["grep_calls"], 0)

    def test_files_field_and_missing_tools(self):
        trace = {"session_id": "s", "trace": [
            {"action": "source_analysis", "repo": "r", "files": ["a.py"]},
        ]}
        out = from_trace(trace)
        self.assertEqual(out["files_read"], 1)
        self.assertIsNone(out["tool_calls"])

    def test_empty_source_accept_evidence_is_rejected(self):
        record = {
            "target_kind": "skill", "target_component": "diagnose.source_usage",
            "algorithm": "subagent-reflection", "algorithm_version": "1",
            "execution": "subagent", "decision": "accept", "samples": ["S-1"],
            "baseline": {"score": 0.5, "samples": ["S-1"]},
            "candidate": {"score": 0.6, "samples": ["S-1"]},
            "paired": {"b": 4, "c": 0, "n": 4},
            "source_usage": {"decision": "accept", "baseline": {}, "candidate": {},
                             "deltas": {}, "reasons": []},
        }
        with self.assertRaises(ExperimentError):
            validate_experiment(record)

    def test_fake_delta_is_rejected(self):
        record = {
            "target_kind": "skill", "target_component": "diagnose.source_usage",
            "algorithm": "subagent-reflection", "algorithm_version": "1",
            "execution": "subagent", "decision": "accept", "samples": ["S-1"],
            "baseline": {"score": 0.5, "samples": ["S-1"]},
            "candidate": {"score": 0.6, "samples": ["S-1"]},
            "paired": {"b": 4, "c": 0, "n": 4},
            "source_usage": {
                "decision": "accept", "reasons": [],
                "baseline": {"n": 1, "source_ok": 1, "files_read": 2,
                             "tool_calls": 2, "fetch_calls": 1, "grep_calls": 1},
                "candidate": {"n": 1, "source_ok": 1, "files_read": 2,
                              "tool_calls": 2, "fetch_calls": 1, "grep_calls": 1},
                "deltas": {"files_read": -1, "tool_calls": 0, "fetch_calls": 0,
                           "grep_calls": 0, "followups": None, "downloads": None,
                           "bytes": None, "elapsed_ms": None, "cache_hits": None},
            },
        }
        with self.assertRaises(ExperimentError):
            validate_experiment(record)

    def test_missing_values_are_unknown(self):
        out = summarize([row("a", files=None, calls=None, fetch=None, grep=None, elapsed=None)])
        self.assertIsNone(out["files_read"])
        self.assertIsNone(out["tool_calls"])

    def test_accept_requires_correctness_and_efficiency(self):
        base = [row("a", files=4, calls=8, fetch=2, grep=4, elapsed=2000)]
        cand = [row("a", files=2, calls=4, fetch=1, grep=2, elapsed=1000)]
        self.assertEqual(compare(base, cand)["decision"], "accept")

    def test_correctness_unknown_or_regressed_is_not_accept(self):
        base = [row("a")]
        self.assertEqual(compare(base, [row("a", correct=None)])["decision"], "insufficient")
        self.assertEqual(compare(base, [row("a", correct=False)])["decision"], "reject")

    def test_efficiency_regression_rejects(self):
        base = [row("a", files=2)]
        self.assertEqual(compare(base, [row("a", files=3)])["decision"], "reject")

    def test_source_accept_requires_evidence(self):
        record = {
            "target_kind": "skill", "target_component": "diagnose.source_usage",
            "algorithm": "subagent-reflection", "algorithm_version": "1",
            "execution": "subagent", "decision": "accept", "samples": ["S-1"],
            "baseline": {"score": 0.5, "samples": ["S-1"]},
            "candidate": {"score": 0.6, "samples": ["S-1"]},
            "paired": {"b": 4, "c": 0, "n": 4},
        }
        with self.assertRaises(ExperimentError):
            validate_experiment(record)

    def test_compare_requires_same_samples(self):
        with self.assertRaises(SourceUsageError):
            compare([row("a")], [row("b")])

    def test_paired_totals_ignore_samples_missing_on_one_arm(self):
        base = [row("a", files=4), row("b", files=None)]
        cand = [row("a", files=2), row("b", files=9)]
        out = compare(base, cand)
        self.assertEqual(out["paired"]["files_read"]["n"], 1)
        self.assertEqual(out["paired"]["files_read"]["unknown"], 1)
        self.assertEqual(out["baseline"]["files_read"], 4)
        self.assertEqual(out["candidate"]["files_read"], 2)

    def test_tiny_delta_is_not_a_change(self):
        base = [row("a", elapsed=1000.0)]
        cand = [row("a", elapsed=1000.0000000001)]
        out = compare(base, cand)
        self.assertNotIn("source_efficiency_regressed", out["reasons"])
        self.assertEqual(out["decision"], "insufficient")

    def test_partial_elapsed_change_is_unconfirmed(self):
        base = [row("a", elapsed=1000), row("b", elapsed=None)]
        cand = [row("a", elapsed=9000), row("b", elapsed=1000)]
        out = compare(base, cand)
        self.assertIn("source_elapsed_inconclusive", out["reasons"])
        self.assertEqual(out["decision"], "insufficient")

    def test_partial_threshold_uses_the_same_epsilon(self):
        base = [row("a", elapsed=1000.0), row("b", elapsed=None)]
        tiny = [row("a", elapsed=1000.00000000005), row("b", elapsed=1000)]
        self.assertNotIn("source_elapsed_inconclusive", compare(base, tiny)["reasons"])
        real = [row("a", elapsed=1000.001), row("b", elapsed=1000)]
        self.assertIn("source_elapsed_inconclusive", compare(base, real)["reasons"])


if __name__ == "__main__":
    unittest.main()
