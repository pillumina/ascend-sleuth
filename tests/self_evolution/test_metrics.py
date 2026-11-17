"""指标登记表与最小聚合；对象类型注册表的默认值。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.decision import DECISION_METHODS  # noqa: E402
from evolve.metrics import (  # noqa: E402
    DEFAULT_METRICS,
    ROLE_CONSTRAINT,
    ROLE_HARD,
    ROLE_PRIMARY,
    aggregate,
    aggregate_metric,
    get_metric,
    pass_rate,
)
from evolve.object_types import OBJECT_TYPES, get_object_type, validate_registry  # noqa: E402


class MetricsTest(unittest.TestCase):
    def test_default_metrics_have_roles_and_directions(self):
        self.assertEqual(DEFAULT_METRICS["case_hit"].role, ROLE_PRIMARY)
        self.assertEqual(DEFAULT_METRICS["routing"].role, ROLE_CONSTRAINT)
        self.assertEqual(DEFAULT_METRICS["safety"].role, ROLE_HARD)
        self.assertEqual(DEFAULT_METRICS["safety"].direction, "pass")

    def test_unknown_metric_raises(self):
        with self.assertRaises(ValueError):
            get_metric("nope")

    def test_aggregate_skips_unknown_and_none(self):
        self.assertAlmostEqual(aggregate([True, False, None, "unknown"]), 0.5)
        self.assertAlmostEqual(aggregate([1, 2, 3]), 2.0)
        self.assertIsNone(aggregate([]))
        self.assertIsNone(aggregate([None, "unknown"]))

    def test_aggregate_metric_reads_dicts_and_objects(self):
        runs = [
            {"metrics": {"case_hit": True}},
            {"metrics": {"case_hit": False}},
            {"metrics": {}},
        ]
        self.assertAlmostEqual(aggregate_metric(runs, "case_hit"), 0.5)

    def test_pass_rate(self):
        self.assertAlmostEqual(pass_rate([True, True, False]), 2 / 3)
        self.assertIsNone(pass_rate([]))


class ObjectTypeRegistryTest(unittest.TestCase):
    def test_registry_covers_all_four_objects(self):
        self.assertEqual(set(OBJECT_TYPES), {"diagnosis", "case", "reference", "trace"})
        validate_registry()

    def test_defaults_are_implemented(self):
        for spec in OBJECT_TYPES.values():
            self.assertIn(spec.default_decision_method, DECISION_METHODS)
            self.assertIn(spec.default_origin, ("core", "field"))
            self.assertTrue(spec.allowed_purposes)

    def test_unknown_object_type_raises(self):
        with self.assertRaises(ValueError):
            get_object_type("card")

    def test_diagnosis_allows_all_purposes_and_uses_binary_decision(self):
        diagnosis = get_object_type("diagnosis")
        self.assertEqual(diagnosis.scorer, "replay")
        self.assertEqual(diagnosis.default_decision_method, "paired_binary")
        self.assertIn("test", diagnosis.allowed_purposes)


if __name__ == "__main__":
    unittest.main()
