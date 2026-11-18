"""算法适配器：静态注册、baseline Patch、未知算法。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.algorithms.registry import algorithm_ids, get_algorithm  # noqa: E402
from evolve.contracts import Patch  # noqa: E402


class AlgorithmRegistryTest(unittest.TestCase):
    def test_baseline_is_registered(self):
        self.assertEqual(algorithm_ids(), ["baseline"])
        algorithm = get_algorithm("baseline")
        self.assertEqual((algorithm.id, algorithm.version, algorithm.scope),
                         ("baseline", "manual", "all"))

    def test_baseline_returns_patch_with_algorithm_identity(self):
        patch = get_algorithm("baseline").propose(
            "skill", [{"failure": "x"}], {"target": "skill"}, {"rollouts": 1},
        )
        self.assertIsInstance(patch, Patch)
        self.assertEqual((patch.algorithm, patch.algorithm_version), ("baseline", "manual"))
        self.assertEqual(patch.payload["observations"], 1)
        patch.validate()

    def test_unknown_algorithm_is_an_error(self):
        with self.assertRaises(ValueError):
            get_algorithm("magic")


if __name__ == "__main__":
    unittest.main()
