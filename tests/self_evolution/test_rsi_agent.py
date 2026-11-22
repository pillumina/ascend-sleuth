"""agent 归因/选点回写：只接受注册 region/证据。"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.rsi import apply_attribution, apply_selection  # noqa: E402


PLAN = {"status": "needs_agent_attribution", "stages": {"attribute": "attribute.trace_rule",
        "select_region": "select.region_hardcount"}, "experiment": None}


class RsiAgentWritebackTest(unittest.TestCase):
    def test_attribution_accepts_registered_region_with_evidence(self):
        plan = apply_attribution(dict(PLAN), {
            "regions": [{"region": "diagnose.routing_hints", "evidence": "trace t1", "confidence": 0.8}]
        })
        self.assertEqual(plan["stages"]["attribute"], "attribute.agent")
        self.assertEqual(plan["agent_attribution"][0]["region"], "diagnose.routing_hints")

    def test_unknown_region_is_rejected(self):
        with self.assertRaises(ValueError):
            apply_attribution(dict(PLAN), {
                "regions": [{"region": "free.form", "evidence": "x", "confidence": 0.8}]
            })

    def test_selection_sets_experiment(self):
        plan = apply_selection(dict(PLAN), {"region": "diagnose.trace_evidence", "evidence": "x"})
        self.assertEqual(plan["experiment"]["mutable_region"], "diagnose.trace_evidence")
        self.assertEqual(plan["stages"]["select_region"], "select.region_agent")


if __name__ == "__main__":
    unittest.main()
