"""用量记录共用骨架：配对聚合、方向计数与判定收尾。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.usage_dimensions import BY_COMPONENT, BY_NAME, DIMENSIONS  # noqa: E402
from evolve.usage import (  # noqa: E402
    count_directions,
    decide,
    pair_rows,
    partial_regressed,
    parse_records,
)


class UsageError(ValueError):
    pass


def records(*rows):
    return {row["sample_id"]: row for row in rows}


class DimensionsTest(unittest.TestCase):
    def test_every_dimension_wires_the_same_four_hooks(self):
        for dimension in DIMENSIONS:
            self.assertTrue(dimension.label.endswith("-usage"), dimension.name)
            self.assertTrue(dimension.arm_key.endswith("_usage"), dimension.name)
            for hook in (dimension.from_trace, dimension.evaluate, dimension.compare):
                self.assertTrue(callable(hook), dimension.name)

    def test_names_and_components_are_unique(self):
        self.assertEqual(len(BY_NAME), len(DIMENSIONS))
        self.assertEqual(len(BY_COMPONENT), len([d for d in DIMENSIONS if d.component]))
        for dimension in DIMENSIONS:
            if dimension.component:
                self.assertIs(BY_COMPONENT[dimension.component], dimension)


class PairRowsTest(unittest.TestCase):
    def test_sum_aggregate_counts_only_paired_samples(self):
        b = records({"sample_id": "S1", "n": 10}, {"sample_id": "S2", "n": 5})
        c = records({"sample_id": "S1", "n": 7}, {"sample_id": "S2", "n": None})
        paired = pair_rows(b, c, ["S1", "S2"], ("n",), aggregate="sum")
        self.assertEqual(paired["n"]["baseline"], 10)
        self.assertEqual(paired["n"]["candidate"], 7)
        self.assertEqual(paired["n"]["delta"], -3)
        self.assertEqual(paired["n"]["n"], 1)
        self.assertEqual(paired["n"]["unknown"], 1)

    def test_mean_aggregate_uses_mean_of_paired_samples(self):
        b = records({"sample_id": "S1", "n": 4}, {"sample_id": "S2", "n": 8})
        c = records({"sample_id": "S1", "n": 2}, {"sample_id": "S2", "n": 4})
        paired = pair_rows(b, c, ["S1", "S2"], ("n",), aggregate="mean")
        self.assertEqual(paired["n"]["baseline"], 6)
        self.assertEqual(paired["n"]["candidate"], 3)
        self.assertEqual(paired["n"]["delta"], -3)

    def test_field_without_pairs_is_unknown(self):
        b = records({"sample_id": "S1", "n": 1})
        c = records({"sample_id": "S1", "n": None})
        paired = pair_rows(b, c, ["S1"], ("n",))
        self.assertEqual(paired["n"], {"n": 0, "unknown": 1, "baseline": None,
                                       "candidate": None, "delta": None})


class DirectionsTest(unittest.TestCase):
    def paired(self, delta, unknown=0, field="calls"):
        return {field: {"n": 1, "unknown": unknown, "baseline": 1,
                        "candidate": 2, "delta": delta}}

    def test_lower_is_better(self):
        counts = count_directions(self.paired(-2), ("calls",))
        self.assertEqual((counts["improved"], counts["worsened"]), (1, 0))
        counts = count_directions(self.paired(2), ("calls",))
        self.assertEqual((counts["improved"], counts["worsened"]), (0, 1))

    def test_higher_is_better_flips_direction(self):
        counts = count_directions(self.paired(3, field="cache_hits"),
                                  ("cache_hits",), higher_is_better=("cache_hits",))
        self.assertEqual((counts["improved"], counts["worsened"]), (1, 0))
        counts = count_directions(self.paired(-3, field="cache_hits"),
                                  ("cache_hits",), higher_is_better=("cache_hits",))
        self.assertEqual((counts["improved"], counts["worsened"]), (0, 1))

    def test_missing_side_goes_to_partial_not_counts(self):
        counts = count_directions(self.paired(5, unknown=1), ("calls",))
        self.assertEqual(counts["partial"], ["calls"])
        self.assertEqual((counts["improved"], counts["worsened"]), (0, 0))

    def test_elapsed_state_is_counted_separately(self):
        counts = count_directions(self.paired(0), ("ms",), elapsed_field="ms",
                                  elapsed="worse")
        self.assertEqual((counts["improved"], counts["worsened"]), (0, 1))
        counts = count_directions(self.paired(0), ("ms",), elapsed_field="ms",
                                  elapsed="better")
        self.assertEqual((counts["improved"], counts["worsened"]), (1, 0))


class PartialRegressedTest(unittest.TestCase):
    def paired(self, delta, field="calls"):
        return {field: {"n": 1, "unknown": 1, "baseline": 1,
                        "candidate": 2, "delta": delta}}

    def test_lower_is_better_regresses_on_positive_delta(self):
        self.assertTrue(partial_regressed(self.paired(1), ["calls"]))
        self.assertFalse(partial_regressed(self.paired(-1), ["calls"]))

    def test_higher_is_better_regresses_on_negative_delta(self):
        self.assertTrue(partial_regressed(self.paired(-1, "cache_hits"),
                                          ["cache_hits"],
                                          higher_is_better=("cache_hits",)))
        self.assertFalse(partial_regressed(self.paired(1, "cache_hits"),
                                           ["cache_hits"],
                                           higher_is_better=("cache_hits",)))

    def test_missing_delta_is_not_a_regression(self):
        self.assertFalse(partial_regressed(self.paired(None), ["calls"]))


class DecideTest(unittest.TestCase):
    def test_reject_takes_precedence(self):
        self.assertEqual(decide(["accuracy_regressed", "note"], ("accuracy_regressed",)),
                         "reject")
        self.assertEqual(decide(["note"], ("accuracy_regressed",)), "insufficient")
        self.assertEqual(decide([], ("accuracy_regressed",)), "accept")


class ParseRecordsTest(unittest.TestCase):
    @staticmethod
    def validate(item):
        if not isinstance(item, dict) or not item.get("sample_id"):
            raise UsageError("sample_id is required")
        return {"sample_id": item["sample_id"]}

    def test_accepts_bare_list_and_wrapped_object(self):
        for data in ([{"sample_id": "S1"}], {"samples": [{"sample_id": "S1"}]}):
            self.assertEqual(parse_records(data, self.validate, UsageError, "usage"),
                             [{"sample_id": "S1"}])

    def test_rejects_empty_and_duplicate_ids(self):
        with self.assertRaises(UsageError):
            parse_records([], self.validate, UsageError, "usage")
        with self.assertRaises(UsageError):
            parse_records([{"sample_id": "S1"}, {"sample_id": "S1"}],
                          self.validate, UsageError, "usage")


if __name__ == "__main__":
    unittest.main()
