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


if __name__ == "__main__":
    unittest.main()
