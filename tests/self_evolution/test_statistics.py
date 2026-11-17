"""统计纯函数：精确配对检验、配对 CI、非劣。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.statistics import (  # noqa: E402
    exact_mcnemar_ge,
    non_inferior,
    paired_diff_ci,
    rate,
)


class ExactMcNemarTest(unittest.TestCase):
    def test_known_values(self):
        self.assertAlmostEqual(exact_mcnemar_ge(4, 0), 0.0625)
        self.assertAlmostEqual(exact_mcnemar_ge(1, 0), 0.5)
        self.assertAlmostEqual(exact_mcnemar_ge(2, 0), 0.25)
        self.assertAlmostEqual(exact_mcnemar_ge(0, 1), 1.0)
        self.assertAlmostEqual(exact_mcnemar_ge(0, 4), 1.0)
        self.assertAlmostEqual(exact_mcnemar_ge(1, 1), 0.75)
        self.assertAlmostEqual(exact_mcnemar_ge(3, 1), 0.3125)

    def test_no_discordant_pairs_is_one(self):
        self.assertEqual(exact_mcnemar_ge(0, 0), 1.0)

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            exact_mcnemar_ge(-1, 0)
        with self.assertRaises(TypeError):
            exact_mcnemar_ge(1.0, 0)


class PairedDifferenceTest(unittest.TestCase):
    def test_empty_and_single(self):
        empty = paired_diff_ci([])
        self.assertIsNone(empty["mean"])
        self.assertEqual(empty["n"], 0)
        single = paired_diff_ci([0.5])
        self.assertAlmostEqual(single["mean"], 0.5)
        self.assertIsNone(single["low"])
        self.assertIsNone(single["high"])

    def test_ci_brackets_mean(self):
        ci = paired_diff_ci([1.0, 1.0, 0.0, 1.0])
        self.assertAlmostEqual(ci["mean"], 0.75)
        self.assertLess(ci["low"], ci["mean"])
        self.assertGreater(ci["high"], ci["mean"])
        self.assertEqual(ci["n"], 4)

    def test_none_values_are_unknown_not_zero(self):
        ci = paired_diff_ci([1.0, None, 0.0])
        self.assertEqual(ci["n"], 2)
        self.assertAlmostEqual(ci["mean"], 0.5)

    def test_non_inferior(self):
        self.assertTrue(non_inferior([1.0, 1.0, 1.0]))
        self.assertFalse(non_inferior([-1.0, -1.0, -1.0]))
        self.assertIsNone(non_inferior([]))
        self.assertIsNone(non_inferior([0.1]))

    def test_rate(self):
        self.assertAlmostEqual(rate(3, 4), 0.75)
        self.assertIsNone(rate(0, 0))
        with self.assertRaises(ValueError):
            rate(5, 4)


class ArenaBridgeTest(unittest.TestCase):
    """eval_arena 的旧 (b, n) 签名必须与 statistics 的新 (b, c) 实现一致。"""

    def test_eval_arena_wrapper_matches_statistics(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import eval_arena as ea  # noqa: PLC0415

        for b, c in ((0, 0), (1, 0), (4, 0), (3, 1), (0, 4), (5, 5)):
            self.assertAlmostEqual(
                ea.exact_mcnemar_ge(b, b + c),
                exact_mcnemar_ge(b, c),
                msg=f"b={b}, c={c}",
            )
        self.assertEqual(ea.exact_mcnemar_ge(0, 0), 1.0)


if __name__ == "__main__":
    unittest.main()
