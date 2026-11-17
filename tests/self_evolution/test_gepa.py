"""GEPA 适配器：只测包络，不跑真实模型/rollout。"""

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.algorithms.gepa import GepaOptimizer, GepaUnavailable  # noqa: E402
from evolve.algorithms.registry import get_algorithm  # noqa: E402


def config():
    return {
        "seed_candidate": {"skill": "old"},
        "trainset": [{"input": "x", "expected": "y"}],
        "evaluator": lambda item: (1.0, "ok"),
        "task_lm": "test/model",
        "reflection_lm": "test/reflect",
        "max_metric_calls": 10,
    }


class GepaAdapterTest(unittest.TestCase):
    def test_registered_and_scoped_to_skill(self):
        self.assertEqual(get_algorithm("gepa").scope, "skill")

    def test_missing_config_is_an_error(self):
        with self.assertRaises(GepaUnavailable):
            GepaOptimizer().propose("skill", [], None, {})

    def test_wrong_target_is_an_error(self):
        with self.assertRaises(GepaUnavailable):
            GepaOptimizer().propose("knowledge", [], None, {"gepa": config()})

    def test_optimize_result_becomes_patch(self):
        result = types.SimpleNamespace(
            best_candidate={"skill": "new"}, total_metric_calls=7, candidates=[{}, {}],
        )
        fake = types.SimpleNamespace(optimize=lambda **kwargs: result)
        with mock.patch.dict(sys.modules, {"gepa": fake}):
            patch = GepaOptimizer().propose(
                "skill", [{"sample": "S-1"}], None, {"gepa": config(), "seed": 2},
            )
        self.assertEqual(patch.algorithm, "gepa")
        self.assertEqual(patch.payload["best_candidate"], "new")
        self.assertEqual(patch.payload["total_metric_calls"], 7)
        self.assertEqual(patch.seed, 2)


if __name__ == "__main__":
    unittest.main()
