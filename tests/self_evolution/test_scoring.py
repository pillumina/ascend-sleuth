"""rubric 评分：阈值、0 分退回、缺维度。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.scoring import RubricError, score_rubric  # noqa: E402


RUBRIC = {
    "dimensions": ["来源可追", "根因完整", "可复用"],
    "threshold": 0.7,
}


class RubricScoringTest(unittest.TestCase):
    def test_above_threshold_passes(self):
        result = score_rubric(RUBRIC, {"来源可追": 2, "根因完整": 2, "可复用": 1})
        self.assertTrue(result.passed)
        self.assertAlmostEqual(result.score, 5 / 6)
        self.assertEqual(result.failed_dimensions, [])

    def test_zero_dimension_rejects_even_with_high_average(self):
        result = score_rubric(RUBRIC, {"来源可追": 2, "根因完整": 2, "可复用": 0})
        self.assertFalse(result.passed)
        self.assertEqual(result.failed_dimensions, ["可复用"])

    def test_missing_dimension_is_not_zero_filled(self):
        result = score_rubric(RUBRIC, {"来源可追": 2, "根因完整": 2})
        self.assertFalse(result.passed)
        self.assertEqual(result.missing, ["可复用"])
        self.assertIsNone(result.score)

    def test_explicit_threshold_overrides_default(self):
        result = score_rubric(
            RUBRIC, {"来源可追": 2, "根因完整": 2, "可复用": 1}, threshold=1.0,
        )
        self.assertFalse(result.passed)
        self.assertEqual(result.threshold, 1.0)

    def test_bad_shape_and_values_are_errors(self):
        with self.assertRaises(RubricError):
            score_rubric({}, {})
        with self.assertRaises(RubricError):
            score_rubric(RUBRIC, {"来源可追": 3, "根因完整": 2, "可复用": 2})
        with self.assertRaises(RubricError):
            score_rubric({**RUBRIC, "threshold": 1.5}, {})


if __name__ == "__main__":
    unittest.main()
