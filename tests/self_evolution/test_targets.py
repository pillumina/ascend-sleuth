"""优化目标：与评估对象分开，按 target 静态分发。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.targets.registry import (  # noqa: E402
    TARGETS,
    get_target,
    resolve_optimizer,
    target_ids,
)


class TargetRegistryTest(unittest.TestCase):
    def test_four_targets_are_registered(self):
        self.assertEqual(target_ids(), ["harness", "knowledge", "skill", "tooling"])
        self.assertEqual(TARGETS["harness"].authority, "A1")
        self.assertEqual(TARGETS["skill"].authority, "A2")

    def test_unknown_target_is_an_error(self):
        with self.assertRaises(ValueError):
            get_target("magic")

    def test_baseline_resolves_for_every_target(self):
        for key in target_ids():
            spec, optimizer = resolve_optimizer(key)
            self.assertEqual(spec.id, key)
            self.assertEqual(optimizer.id, "baseline")

    def test_unregistered_algorithm_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_optimizer("skill", "magic")

    def test_algorithm_not_allowed_for_target_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_optimizer("harness", "ael")


if __name__ == "__main__":
    unittest.main()
