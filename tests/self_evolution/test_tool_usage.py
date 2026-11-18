"""工具使用与工具性能：从 trace 推导与配对门禁。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.tool_usage import (  # noqa: E402
    ToolUsageError, compare, from_trace, summarize,
)


def row(sample, calls=4, fetch=1, grep=2, retries=0, cache=0, ms=100.0,
        resolved=True):
    return {"sample_id": sample, "tool_calls": calls, "fetch_calls": fetch,
            "grep_calls": grep, "retries": retries, "cache_hits": cache,
            "tool_ms": ms, "failures": 0, "resolved": resolved}


class ToolUsageTest(unittest.TestCase):
    def test_from_trace_counts_tool_signals(self):
        trace = {"session_id": "s1", "trace": [
            {"action": "source_analysis", "repo": "r", "ref": "main",
             "tool_calls": ["src_fetch.py r main", "grep a.py", "retry fetch"],
             "cache_hits": 2, "tool_ms": 12.5, "fetch_exit": 0},
            {"action": "source_analysis", "tool_calls": ["src_fetch.py r v2"],
             "fetch_exit": 4, "verify": "miss"},
        ]}
        out = from_trace(trace, resolved=True)
        self.assertEqual(out["tool_calls"], 4)
        self.assertEqual(out["fetch_calls"], 2)
        self.assertEqual(out["grep_calls"], 1)
        self.assertEqual(out["retries"], 1)
        self.assertEqual(out["cache_hits"], 2)
        self.assertAlmostEqual(out["tool_ms"], 12.5)
        self.assertEqual(out["failures"], 2)
        self.assertTrue(out["resolved"])

    def test_missing_source_events_raise(self):
        with self.assertRaises(ToolUsageError):
            from_trace({"session_id": "s", "trace": []})

    def test_accept_when_tools_cheaper_and_resolution_not_worse(self):
        base = [row("a", calls=6, fetch=2, retries=2, ms=200.0)]
        cand = [row("a", calls=3, fetch=1, retries=0, ms=100.0)]
        self.assertEqual(compare(base, cand)["decision"], "accept")

    def test_resolution_regression_rejects(self):
        base = [row("a", resolved=True)]
        cand = [row("a", resolved=False)]
        self.assertEqual(compare(base, cand)["decision"], "reject")

    def test_resolution_unknown_is_insufficient(self):
        base = [row("a", resolved=None)]
        cand = [row("a", resolved=None)]
        self.assertEqual(compare(base, cand)["decision"], "insufficient")

    def test_unpaired_samples_do_not_create_regression(self):
        base = [row("a", calls=2), row("b", calls=None)]
        cand = [row("a", calls=2), row("b", calls=9)]
        out = compare(base, cand)
        self.assertEqual(out["paired"]["tool_calls"]["n"], 1)
        self.assertNotIn("tool_efficiency_regressed", out["reasons"])
        self.assertEqual(out["decision"], "insufficient")

    def test_summary_keeps_missing_unknown(self):
        out = summarize([row("a", cache=None), row("b", cache=None)])
        self.assertIsNone(out["cache_hits"])
        self.assertEqual(out["tool_calls"], 8)


if __name__ == "__main__":
    unittest.main()
