"""知识使用指标与门禁：效率不降、准确率不降才 accept。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.knowledge_usage import UsageError, compare, summarize  # noqa: E402
from evolve.regions import REGIONS  # noqa: E402


def row(sample, hit=True, step=1, candidates=1, body=1, refs=0, wrong=0, tokens=100):
    return {"sample_id": sample, "hit": hit, "first_hit_step": step if hit else None,
            "candidates_examined": candidates, "full_body_reads": body,
            "reference_lookups": refs, "wrong_cases": wrong, "tokens": tokens}


class KnowledgeUsageTest(unittest.TestCase):
    def test_region_is_registered(self):
        self.assertIn("diagnose.knowledge_usage", REGIONS)

    def test_summary_uses_only_present_numbers(self):
        out = summarize([row("a"), row("b", hit=False, step=None, tokens=None)])
        self.assertEqual(out["n"], 2)
        self.assertEqual(out["hits"], 1)
        self.assertAlmostEqual(out["tokens"], 100.0)

    def test_accept_when_accuracy_not_worse_and_efficiency_better(self):
        base = [row("a", step=4, candidates=3, body=3), row("b", step=5, candidates=3, body=3)]
        cand = [row("a", step=2, candidates=1, body=1), row("b", step=2, candidates=1, body=1)]
        result = compare(base, cand)
        self.assertEqual(result["decision"], "accept")
        self.assertEqual(result["reasons"], [])

    def test_reject_on_wrong_case_or_accuracy_regression(self):
        base = [row("a")]
        self.assertEqual(compare(base, [row("a", wrong=1)])["decision"], "reject")
        self.assertEqual(compare(base, [row("a", hit=False, step=None)])["decision"], "reject")

    def test_insufficient_when_no_efficiency_gain(self):
        base = [row("a")]
        self.assertEqual(compare(base, [row("a")])["decision"], "insufficient")

    def test_missing_hit_step_is_unknown_not_zero(self):
        with self.assertRaises(UsageError):
            summarize([row("a", hit=False, step=None)] + [{"sample_id": "b", "hit": True}])


if __name__ == "__main__":
    unittest.main()
