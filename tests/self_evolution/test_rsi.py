"""RSI 多源计划：trace/metrics/replay 归因与 agent 补位标记。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.rsi import build_plan  # noqa: E402


class RsiPlanTest(unittest.TestCase):
    def test_trace_only_actionable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "trace-state.json"
            state.write_text(json.dumps({
                "snapshot_id": "snap", "processed": {
                    "t1": {"attribution": {"events": [
                        {"component": "routing", "hard": True}
                    ]}}
                }
            }), encoding="utf-8")
            plan = build_plan(root, trace_state=state)
            self.assertEqual(plan["status"], "actionable")
            self.assertEqual(plan["experiment"]["mutable_region"], "diagnose.routing_hints")

    def test_unknown_components_need_agent_attribution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "trace-state.json"
            state.write_text(json.dumps({
                "snapshot_id": "snap", "processed": {
                    "t1": {"attribution": {"events": [
                        {"component": "mystery", "hard": True}
                    ]}}
                }
            }), encoding="utf-8")
            plan = build_plan(root, trace_state=state)
            self.assertEqual(plan["status"], "needs_agent_attribution")
            self.assertEqual(plan["stages"]["attribute"], "attribute.agent")

    def test_no_sources(self):
        with tempfile.TemporaryDirectory() as td:
            plan = build_plan(Path(td))
            self.assertEqual(plan["status"], "no_sources")


if __name__ == "__main__":
    unittest.main()
