"""RSI stage 注册表与 GEPA 组合。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.agent_gepa import GepaSession  # noqa: E402
from evolve.stages import get_stage, stage_ids  # noqa: E402


class StageRegistryTest(unittest.TestCase):
    def test_points_and_gepa_composition(self):
        self.assertIn("attribute.trace_rule", stage_ids("attribute"))
        self.assertIn("attribute.agent", stage_ids("attribute"))
        self.assertIn("select.pareto", stage_ids("select_candidate"))
        self.assertIn("select.region_agent", stage_ids("select_region"))
        self.assertIn("propose.reflection", stage_ids("propose"))
        self.assertIn("judge.subagent", stage_ids("judge"))
        self.assertIn("gate.paired", stage_ids("gate"))
        session = GepaSession("seed", ["S-1"])
        self.assertEqual(session.select_stage.id, "select.pareto")
        self.assertEqual(session.propose_stage.id, "propose.agent")
        self.assertEqual(session.result()["stages"],
                         {"select_candidate": "select.pareto", "propose": "propose.agent"})

    def test_unknown_stage_is_an_error(self):
        with self.assertRaises(ValueError):
            get_stage("select.magic")


if __name__ == "__main__":
    unittest.main()
