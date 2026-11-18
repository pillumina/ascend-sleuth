"""评测面注册表：target 到 scorer/gate 的显式映射。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.evaluations.registry import (  # noqa: E402
    EVAL_PROFILES,
    eval_profile_ids,
    get_eval_profile,
)
from evolve.targets.registry import resolve_evaluator  # noqa: E402


class EvalProfileTest(unittest.TestCase):
    def test_profiles_are_registered(self):
        self.assertEqual(
            eval_profile_ids(), ["arena", "end_to_end", "replay_trace", "rubric", "subagent_judge"]
        )
        self.assertTrue(EVAL_PROFILES["arena"].implemented)
        self.assertTrue(EVAL_PROFILES["rubric"].implemented)
        self.assertTrue(EVAL_PROFILES["replay_trace"].implemented)
        self.assertFalse(EVAL_PROFILES["subagent_judge"].implemented)

    def test_unknown_profile_is_an_error(self):
        with self.assertRaises(ValueError):
            get_eval_profile("magic")

    def test_targets_resolve_to_eval_profiles(self):
        self.assertEqual(resolve_evaluator("skill")[1].id, "arena")
        self.assertEqual(resolve_evaluator("knowledge")[1].id, "rubric")
        self.assertEqual(resolve_evaluator("tooling")[1].id, "replay_trace")
        self.assertEqual(resolve_evaluator("harness")[1].id, "end_to_end")


if __name__ == "__main__":
    unittest.main()
