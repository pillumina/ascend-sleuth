"""判定语义：四种结论、复用折减、成本路径与方法分派。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.decision import (  # noqa: E402
    DECISION_METHODS,
    Decision,
    DecisionResult,
    decide,
    decide_binary,
    decide_cost_primary,
    decide_paired_score,
)


class BinaryDecisionTest(unittest.TestCase):
    def test_four_outcomes(self):
        self.assertEqual(decide_binary(4, 0, 9).decision, Decision.ACCEPT)
        self.assertEqual(decide_binary(1, 0, 9).decision, Decision.INSUFFICIENT)
        self.assertEqual(decide_binary(0, 1, 9).decision, Decision.REJECT)
        self.assertEqual(decide_binary(0, 0, 9).decision, Decision.INSUFFICIENT)

    def test_two_discordant_pairs_are_not_enough(self):
        result = decide_binary(2, 0, 9)
        self.assertEqual(result.decision, Decision.INSUFFICIENT)
        self.assertAlmostEqual(result.p_value, 0.25)

    def test_reuse_index_tightens_threshold(self):
        self.assertEqual(decide_binary(4, 0, 9, k=0).decision, Decision.ACCEPT)
        result = decide_binary(4, 0, 9, k=1)
        self.assertEqual(result.decision, Decision.INSUFFICIENT)
        self.assertAlmostEqual(result.alpha_eff, 0.05)

    def test_cost_missing_still_allows_quality_accept(self):
        result = decide_binary(4, 0, 9, cost_b=None, cost_c=100)
        self.assertEqual(result.decision, Decision.ACCEPT)
        self.assertIsNone(result.cost_ratio)

    def test_cost_over_budget_blocks_accept(self):
        result = decide_binary(4, 0, 9, cost_b=100, cost_c=120)
        self.assertEqual(result.decision, Decision.INSUFFICIENT)
        self.assertAlmostEqual(result.cost_ratio, 1.2)

    def test_cost_within_budget(self):
        result = decide_binary(4, 0, 9, cost_b=100, cost_c=105)
        self.assertEqual(result.decision, Decision.ACCEPT)

    def test_zero_discordant_pairs_without_cost_drop_is_insufficient(self):
        result = decide_binary(0, 0, 9)
        self.assertEqual(result.decision, Decision.INSUFFICIENT)
        self.assertFalse(result.cost_path)

    def test_zero_discordant_pairs_with_cost_drop_accepts(self):
        result = decide_binary(0, 0, 9, cost_b=100, cost_c=80, epsilon=0.10)
        self.assertEqual(result.decision, Decision.ACCEPT)
        self.assertTrue(result.cost_path)

    def test_quality_regression_rejects_even_with_cost_drop(self):
        result = decide_binary(0, 1, 9, cost_b=100, cost_c=50)
        self.assertEqual(result.decision, Decision.REJECT)

    def test_constraint_failure_rejects(self):
        result = decide_binary(4, 0, 9, constraints_ok=False)
        self.assertEqual(result.decision, Decision.REJECT)

    def test_input_validation(self):
        for kwargs in (
            dict(b=-1, c=0, n=9),
            dict(b=0, c=-1, n=9),
            dict(b=1, c=0, n=0),
            dict(b=1, c=0, n=None),
            dict(b=1, c=0, n=9, alpha=0),
            dict(b=1, c=0, n=9, alpha=1),
            dict(b=1, c=0, n=9, k=-1),
            dict(b=1, c=0, n=9, cost_b=-1, cost_c=1),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    decide_binary(**kwargs)

    def test_n_is_required(self):
        with self.assertRaises(TypeError):
            decide_binary(4, 0)  # type: ignore[call-arg]

    def test_result_roundtrip(self):
        result = decide_binary(4, 0, 9, cost_b=100, cost_c=100)
        restored = DecisionResult.from_dict(result.to_dict())
        self.assertEqual(restored.decision, result.decision)
        self.assertEqual(restored.b, 4)
        self.assertEqual(restored.c, 0)


class CostPrimaryDecisionTest(unittest.TestCase):
    def test_zero_discordant_pairs_cost_path(self):
        accepted = decide_cost_primary(0, 0, 9, cost_b=100, cost_c=80)
        self.assertEqual(accepted.decision, Decision.ACCEPT)
        self.assertTrue(accepted.cost_path)
        rejected = decide_cost_primary(0, 0, 9, cost_b=100, cost_c=120)
        self.assertEqual(rejected.decision, Decision.REJECT)
        unknown = decide_cost_primary(0, 0, 9)
        self.assertEqual(unknown.decision, Decision.UNKNOWN)

    def test_accepts_cost_drop_with_non_inferior_quality(self):
        result = decide_cost_primary(1, 0, 9, cost_b=100, cost_c=80)
        self.assertEqual(result.decision, Decision.ACCEPT)

    def test_cost_increase_rejects(self):
        self.assertEqual(
            decide_cost_primary(1, 0, 9, cost_b=100, cost_c=120).decision,
            Decision.REJECT,
        )

    def test_missing_cost_is_unknown(self):
        self.assertEqual(
            decide_cost_primary(1, 0, 9).decision,
            Decision.UNKNOWN,
        )

    def test_quality_regression_rejects(self):
        self.assertEqual(
            decide_cost_primary(0, 1, 9, cost_b=100, cost_c=50).decision,
            Decision.REJECT,
        )

    def test_small_cost_drop_is_insufficient(self):
        self.assertEqual(
            decide_cost_primary(1, 0, 9, cost_b=100, cost_c=95, epsilon=0.10).decision,
            Decision.INSUFFICIENT,
        )

    def test_n_is_required(self):
        with self.assertRaises(TypeError):
            decide_cost_primary(0, 0)  # type: ignore[call-arg]


class PairedScoreDecisionTest(unittest.TestCase):
    def test_ci_above_zero_accepts(self):
        self.assertEqual(decide_paired_score([1, 1, 1]).decision, Decision.ACCEPT)

    def test_ci_straddling_zero_is_insufficient(self):
        self.assertEqual(
            decide_paired_score([2, -1, 1, -1]).decision,
            Decision.INSUFFICIENT,
        )

    def test_single_sample_is_insufficient(self):
        self.assertEqual(decide_paired_score([1]).decision, Decision.INSUFFICIENT)

    def test_no_data_is_unknown(self):
        self.assertEqual(decide_paired_score([]).decision, Decision.UNKNOWN)


class DispatcherTest(unittest.TestCase):
    def test_registry_has_required_methods(self):
        self.assertIn("paired_binary", DECISION_METHODS)
        self.assertIn("cost_primary", DECISION_METHODS)

    def test_unknown_method_raises(self):
        with self.assertRaises(ValueError):
            decide("magic", b=1, c=0)

    def test_dispatch_paired_binary(self):
        result = decide("paired_binary", b=4, c=0, n=9)
        self.assertEqual(result.decision, Decision.ACCEPT)


if __name__ == "__main__":
    unittest.main()
