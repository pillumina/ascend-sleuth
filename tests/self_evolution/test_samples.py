"""样本本地库：创建、复核、晋升、退休、非法转换与复核清单。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

from evolve.contracts import Sample  # noqa: E402
from evolve.samples import SampleStore, StoreError  # noqa: E402

EXPECTED = {"namespace": "inference/vllm-ascend", "category": "interrupt"}


class SampleStoreTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = SampleStore(self.root)

    def create(self, sid="S-1", source=None, **overrides):
        values = dict(
            id=sid,
            object_type="diagnosis",
            source=source or f"https://example.com/issues/{sid}",
            origin="field",
            purpose="evaluation",
            expected=dict(EXPECTED),
        )
        values.update(overrides)
        return self.store.new(**values)

    def write_raw(self, data):
        path = self.store.samples_dir / f"{data['id']}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return path


class LifecycleTest(SampleStoreTestBase):
    def test_new_writes_candidate_yaml_under_gitignored_runtime_dir(self):
        self.create()
        path = self.store.samples_dir / "S-1.yaml"
        self.assertTrue(path.exists())
        self.assertIn(".s2-replay/evolve/samples", path.as_posix())
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(raw["status"], "candidate")
        self.assertEqual(raw["origin"], "field")
        self.assertEqual(raw["expected"], EXPECTED)
        self.assertEqual(raw["created_at"], raw["updated_at"])

    def test_review_approve_sets_active_field(self):
        self.create()
        sample = self.store.review("S-1", approve=True)
        self.assertEqual((sample.status, sample.origin), ("active", "field"))
        self.assertEqual(sample.history[-1]["from"], "candidate")
        self.assertEqual(sample.history[-1]["to"], "active")

    def test_review_reject_is_terminal(self):
        self.create()
        sample = self.store.review("S-1", approve=False, reason="missing evidence")
        self.assertEqual(sample.status, "rejected")
        with self.assertRaises(StoreError):
            self.store.review("S-1", approve=True)

    def test_promote_changes_origin_not_status(self):
        self.create()
        self.store.review("S-1", approve=True)
        sample = self.store.promote("S-1", to="core")
        self.assertEqual((sample.status, sample.origin), ("active", "core"))
        self.assertEqual(sample.history[-1]["from"], "active")
        self.assertEqual(sample.history[-1]["to"], "active")
        self.assertEqual(sample.history[-1]["from_origin"], "field")
        self.assertEqual(sample.history[-1]["to_origin"], "core")
        self.assertEqual(self.store.check("S-1"), [])

    def test_retire_from_field_and_core_origin(self):
        self.create()
        self.store.review("S-1", approve=True)
        self.assertEqual(self.store.retire("S-1").status, "retired")
        self.create("S-2")
        self.store.review("S-2", approve=True)
        self.store.promote("S-2", to="core")
        self.assertEqual(self.store.retire("S-2").status, "retired")

    def test_retired_can_revive_only_to_candidate(self):
        self.create()
        self.store.review("S-1", approve=True)
        self.store.retire("S-1")
        sample = self.store.revive("S-1")
        self.assertEqual((sample.status, sample.origin), ("candidate", "field"))
        self.assertEqual(self.store.review("S-1", approve=True).status, "active")

    def test_list_filters(self):
        self.create("S-1")
        self.create("S-2", source="https://example.com/issues/2")
        self.store.review("S-1", approve=True)
        self.assertEqual([s.id for s in self.store.list()], ["S-1", "S-2"])
        self.assertEqual([s.id for s in self.store.list(status="active")], ["S-1"])
        self.assertEqual([s.id for s in self.store.list(origin="field")], ["S-1", "S-2"])

    def test_counts(self):
        self.create("S-1")
        self.create("S-2", source="https://example.com/issues/2")
        self.store.review("S-1", approve=True)
        counts = self.store.counts()
        self.assertEqual(counts["total"], 2)
        self.assertEqual(counts["status"], {"candidate": 1, "active": 1})
        self.assertEqual(counts["origin"], {"field": 2})


class IllegalMutationTest(SampleStoreTestBase):
    def test_promote_candidate_directly_to_core_is_rejected(self):
        self.create()
        with self.assertRaises(StoreError):
            self.store.promote("S-1", to="core")

    def test_promote_only_to_core(self):
        self.create()
        self.store.review("S-1", approve=True)
        with self.assertRaises(StoreError):
            self.store.promote("S-1", to="field")

    def test_promote_twice_is_rejected(self):
        self.create()
        self.store.review("S-1", approve=True)
        self.store.promote("S-1", to="core")
        with self.assertRaises(StoreError):
            self.store.promote("S-1", to="core")

    def test_review_rejects_missing_answer(self):
        self.create(expected=None, rubric=None)
        with self.assertRaises(StoreError) as ctx:
            self.store.review("S-1", approve=True)
        self.assertIn("expected or rubric", str(ctx.exception))
        self.assertEqual(self.store.load("S-1").status, "candidate")

    def test_review_reject_allows_incomplete_candidate(self):
        self.create(expected=None, rubric=None)
        self.assertEqual(self.store.review("S-1", approve=False).status, "rejected")

    def test_test_purpose_candidate_is_rejected_at_review(self):
        self.create(purpose="test")
        with self.assertRaises(StoreError) as ctx:
            self.store.review("S-1", approve=True)
        self.assertIn("purpose=test", str(ctx.exception))
        self.assertEqual(self.store.require("S-1").status, "candidate")

    def test_feedback_cannot_be_promoted_to_core(self):
        self.create(purpose="feedback")
        self.store.review("S-1", approve=True)
        before = self.store.load("S-1")
        with self.assertRaises(StoreError) as ctx:
            self.store.promote("S-1", to="core")
        self.assertIn("feedback", str(ctx.exception))
        after = self.store.load("S-1")
        self.assertEqual(after.origin, "field")
        self.assertEqual(len(after.history), len(before.history), "失败不落盘")

    def test_candidate_cannot_start_at_core_origin(self):
        with self.assertRaises(StoreError):
            self.create(origin="core")

    def test_core_origin_cannot_revive_to_field_candidate(self):
        self.create()
        self.store.review("S-1", approve=True)
        self.store.promote("S-1", to="core")
        self.store.retire("S-1")
        with self.assertRaises(StoreError):
            self.store.revive("S-1")

    def test_retire_candidate_is_rejected(self):
        self.create()
        with self.assertRaises(StoreError):
            self.store.retire("S-1")

    def test_retire_rejected_is_rejected(self):
        self.create()
        self.store.review("S-1", approve=False)
        with self.assertRaises(StoreError):
            self.store.retire("S-1")

    def test_revive_active_is_rejected(self):
        self.create()
        self.store.review("S-1", approve=True)
        with self.assertRaises(StoreError):
            self.store.revive("S-1")

    def test_review_twice_is_rejected(self):
        self.create()
        self.store.review("S-1", approve=True)
        with self.assertRaises(StoreError):
            self.store.review("S-1", approve=True)

    def test_missing_sample(self):
        with self.assertRaises(StoreError):
            self.store.review("nope", approve=True)
        self.assertEqual(self.store.check("nope"), ["no such sample: nope"])

    def test_path_traversal_id_rejected(self):
        with self.assertRaises(StoreError):
            self.store.new(
                id="../escape",
                object_type="diagnosis",
                source="https://example.com/issues/9",
                expected=dict(EXPECTED),
            )


class DuplicateAndCheckTest(SampleStoreTestBase):
    def test_duplicate_id(self):
        self.create()
        with self.assertRaises(StoreError):
            self.create()

    def test_duplicate_source(self):
        self.create("S-1")
        with self.assertRaises(StoreError):
            self.create("S-2", source="https://example.com/issues/S-1/")

    def test_missing_answer_fails_check(self):
        self.create(expected=None)
        errors = self.store.check("S-1")
        self.assertTrue(any("expected or rubric" in message for message in errors))

    def test_valid_candidate_passes_check(self):
        self.create()
        self.assertEqual(self.store.check("S-1"), [])

    def test_duplicate_source_found_by_check_even_if_store_write_was_bypassed(self):
        self.create("S-1")
        self.write_raw(Sample(
            id="S-2",
            status="candidate",
            object_type="diagnosis",
            origin="field",
            purpose="evaluation",
            source="https://example.com/issues/S-1",
            expected=dict(EXPECTED),
        ).to_dict())
        self.assertTrue(any("duplicate source" in m for m in self.store.check("S-2")))

    def test_duplicate_id_field_is_reported(self):
        self.create("S-1")
        data = Sample(
            id="S-1",
            status="candidate",
            object_type="diagnosis",
            origin="field",
            purpose="evaluation",
            source="https://example.com/issues/other",
            expected=dict(EXPECTED),
        ).to_dict()
        wrong_name = self.store.samples_dir / "A.yaml"
        wrong_name.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        self.assertTrue(any("duplicate sample id" in m for m in self.store.check("S-1")))

    def test_filename_id_mismatch_is_an_error(self):
        self.create("S-1")
        data = Sample(
            id="OTHER",
            status="candidate",
            object_type="diagnosis",
            origin="field",
            purpose="evaluation",
            source="https://example.com/issues/other",
            expected=dict(EXPECTED),
        ).to_dict()
        (self.store.samples_dir / "S-1.yaml").write_text(
            yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        with self.assertRaises(StoreError):
            self.store.load("S-1")

    def test_test_purpose_requires_active_core_origin(self):
        self.create(purpose="test")
        self.assertTrue(any("purpose=test" in m for m in self.store.check("S-1")))
        valid = Sample(
            id="S-3",
            status="active",
            object_type="diagnosis",
            origin="core",
            purpose="test",
            source="https://example.com/issues/S-3",
            expected=dict(EXPECTED),
        )
        self.write_raw(valid.to_dict())
        self.assertEqual(self.store.check("S-3"), [])

    def test_feedback_cannot_live_in_core(self):
        self.write_raw(Sample(
            id="S-4",
            status="active",
            object_type="diagnosis",
            origin="core",
            purpose="feedback",
            source="https://example.com/issues/S-4",
            expected=dict(EXPECTED),
        ).to_dict())
        errors = self.store.check("S-4")
        self.assertTrue(any("feedback must stay" in m for m in errors))

    def test_active_core_origin_is_allowed(self):
        self.write_raw(Sample(
            id="S-5",
            status="active",
            object_type="diagnosis",
            origin="core",
            purpose="evaluation",
            source="https://example.com/issues/S-5",
            expected=dict(EXPECTED),
        ).to_dict())
        self.assertEqual(self.store.check("S-5"), [])

    def test_unknown_status_is_reported(self):
        data = Sample(
            id="S-6",
            status="candidate",
            object_type="diagnosis",
            origin="field",
            purpose="evaluation",
            source="https://example.com/issues/S-6",
            expected=dict(EXPECTED),
        ).to_dict()
        data["status"] = "core"
        self.write_raw(data)
        self.assertTrue(any("status must be one of" in m for m in self.store.check("S-6")))

    def test_unknown_object_type_is_reported(self):
        data = Sample(
            id="S-7",
            status="candidate",
            object_type="diagnosis",
            origin="field",
            purpose="evaluation",
            source="https://example.com/issues/S-7",
            expected=dict(EXPECTED),
        ).to_dict()
        data["object_type"] = "card"
        self.write_raw(data)
        self.assertTrue(any("object_type must be one of" in m
                            for m in self.store.check("S-7")))

    def test_atomic_write_leaves_no_temp_files(self):
        self.create()
        leftovers = list(self.store.samples_dir.glob(".tmp-*"))
        self.assertEqual(leftovers, [])
        self.assertEqual(len(list(self.store.samples_dir.glob("*.yaml"))), 1)


class PurposeLifecycleTest(SampleStoreTestBase):
    def active(self, sid="S-1", purpose="evaluation", origin="field"):
        self.create(sid, purpose=purpose)
        self.store.review(sid, approve=True)
        if origin == "core":
            self.store.promote(sid, to="core")
        return self.store.require(sid)

    def test_set_purpose_requires_active(self):
        self.create("S-1")
        with self.assertRaises(StoreError):
            self.store.set_purpose("S-1", "regression")

    def test_evaluation_to_test_requires_core_origin(self):
        self.active("S-1", origin="field")
        with self.assertRaises(StoreError) as ctx:
            self.store.set_purpose("S-1", "test")
        self.assertIn("origin=core", str(ctx.exception))

        self.active("S-2", origin="core")
        sample = self.store.set_purpose("S-2", "test")
        self.assertEqual(sample.purpose, "test")
        self.assertEqual(sample.history[-1]["from_purpose"], "evaluation")
        self.assertEqual(sample.history[-1]["to_purpose"], "test")
        self.assertEqual(self.store.check("S-2"), [])

    def test_feedback_cannot_become_test_or_evaluation(self):
        self.active("S-1", purpose="feedback", origin="field")
        for target in ("test", "evaluation"):
            with self.subTest(target=target):
                with self.assertRaises(StoreError):
                    self.store.set_purpose("S-1", target)

    def test_test_cannot_become_regression(self):
        self.active("S-1", origin="core")
        self.store.set_purpose("S-1", "test")
        with self.assertRaises(StoreError) as ctx:
            self.store.set_purpose("S-1", "regression")
        self.assertIn("invalid purpose transition", str(ctx.exception))

    def test_set_same_purpose_is_noop(self):
        self.active("S-1")
        before = self.store.require("S-1")
        after = self.store.set_purpose("S-1", "evaluation")
        self.assertEqual(after.purpose, "evaluation")
        self.assertEqual(len(after.history), len(before.history))

    def test_absorb_evaluation_to_regression(self):
        self.active("S-1", purpose="evaluation", origin="field")
        sample = self.store.absorb("S-1")
        self.assertEqual((sample.status, sample.purpose), ("active", "regression"))
        self.assertEqual(sample.history[-1]["from_purpose"], "evaluation")
        self.assertEqual(sample.history[-1]["to_purpose"], "regression")

    def test_absorb_feedback_to_regression(self):
        self.active("S-1", purpose="feedback", origin="field")
        sample = self.store.absorb("S-1")
        self.assertEqual((sample.status, sample.purpose), ("active", "regression"))

    def test_absorb_test_retires_not_regression(self):
        self.active("S-1", purpose="evaluation", origin="core")
        self.store.set_purpose("S-1", "test")
        sample = self.store.absorb("S-1")
        self.assertEqual((sample.status, sample.purpose), ("retired", "test"))
        self.assertEqual(sample.history[-1]["to"], "retired")
        self.assertIn("test invalidated", sample.history[-1]["reason"])
        self.assertEqual(self.store.check("S-1"), [])
        again = self.store.absorb("S-1")
        self.assertEqual((again.status, again.purpose), ("retired", "test"))
        self.assertEqual(len(again.history), len(sample.history), "重复吸收不重复写")

    def test_absorb_regression_is_noop(self):
        self.active("S-1", purpose="evaluation", origin="field")
        absorbed = self.store.absorb("S-1")
        before = self.store.require("S-1")
        again = self.store.absorb("S-1")
        self.assertEqual(again.purpose, "regression")
        self.assertEqual(len(again.history), len(before.history))
        self.assertEqual(again.updated_at, before.updated_at)

    def test_absorb_cross_is_rejected(self):
        sample = Sample(
            id="S-9",
            status="active",
            object_type="diagnosis",
            origin="core",
            purpose="cross",
            source="https://example.com/issues/S-9",
            expected=dict(EXPECTED),
        )
        self.write_raw(sample.to_dict())
        with self.assertRaises(StoreError):
            self.store.absorb("S-9")

    def test_draw_test_selects_only_active_core_evaluation(self):
        self.active("S-1", purpose="evaluation", origin="core")
        self.active("S-2", purpose="evaluation", origin="core")
        self.active("S-3", purpose="evaluation", origin="field")
        self.active("S-4", purpose="regression", origin="core")
        drawn = self.store.draw_test(size=4)
        self.assertEqual({item.id for item in drawn}, {"S-1", "S-2"})
        for item in drawn:
            self.assertEqual(item.purpose, "test")
            self.assertEqual(item.status, "active")
            self.assertEqual(item.origin, "core")
            self.assertEqual(item.history[-1]["from_purpose"], "evaluation")
            self.assertEqual(item.history[-1]["to_purpose"], "test")
        self.assertEqual(self.store.require("S-3").purpose, "evaluation")
        self.assertEqual(self.store.require("S-4").purpose, "regression")

    def test_draw_test_size_zero(self):
        self.active("S-1", origin="core")
        self.assertEqual(self.store.draw_test(size=0), [])

    def test_draw_test_is_idempotent_when_test_set_exists(self):
        for i in range(8):
            self.create(id=f"S-{i}", source=f"https://example.com/{i}")
            self.store.review(f"S-{i}", approve=True)
            self.store.promote(f"S-{i}", to="core")
        first = self.store.draw_test(size=4)
        second = self.store.draw_test(size=4)
        self.assertEqual(len(first), 4)
        self.assertEqual([s.id for s in first], [s.id for s in second])
        self.assertEqual(
            len([s for s in self.store.read_all() if s.purpose == "test"]),
            4,
        )

    def test_draw_test_fills_remaining_after_absorb_retires_one(self):
        for i in range(6):
            self.create(id=f"S-{i}", source=f"https://example.com/{i}")
            self.store.review(f"S-{i}", approve=True)
            self.store.promote(f"S-{i}", to="core")
        drawn = self.store.draw_test(size=4)
        self.assertEqual(len(drawn), 4)
        self.store.absorb(drawn[0].id)
        refilled = self.store.draw_test(size=4)
        self.assertEqual(len(refilled), 4)
        self.assertEqual(len([s for s in self.store.read_all() if s.purpose == "test" and s.status == "active"]), 4)

    def test_draw_test_reduces_targets_after_existing_test_samples(self):
        for i in range(6):
            self.create(id=f"S-{i}", source=f"https://example.com/{i}",
                        expected={"namespace": "inference/vllm-ascend", "category": "interrupt"})
            self.store.review(f"S-{i}", approve=True)
            self.store.promote(f"S-{i}", to="core")
        self.store.draw_test(size=3)
        drawn = self.store.draw_test(
            size=4, strata={"inference/vllm-ascend/interrupt": 4},
        )
        self.assertEqual(len(drawn), 4)

    def test_draw_test_returns_fewer_when_pool_is_small(self):
        self.active("S-1", origin="core")
        self.assertEqual([item.id for item in self.store.draw_test(size=4)], ["S-1"])


class SetAnswerTest(SampleStoreTestBase):
    def test_candidate_can_receive_answer_and_then_review(self):
        self.create("S-1", expected=None)
        sample = self.store.set_answer("S-1", expected=dict(EXPECTED))
        self.assertEqual(sample.expected, EXPECTED)
        self.assertEqual(sample.status, "candidate")
        self.assertEqual(sample.history[-1]["reason"], "answer set by maintainer")
        self.assertEqual(self.store.check("S-1"), [])
        self.assertEqual(self.store.review("S-1", approve=True).status, "active")

    def test_active_can_receive_answer(self):
        self.write_raw(Sample(
            id="S-1",
            status="active",
            object_type="diagnosis",
            origin="field",
            purpose="evaluation",
            source="https://example.com/issues/S-1",
            expected=None,
        ).to_dict())
        sample = self.store.set_answer("S-1", expected=dict(EXPECTED))
        self.assertEqual((sample.status, sample.expected), ("active", EXPECTED))
        self.assertEqual(self.store.check("S-1"), [])

    def test_failure_does_not_write(self):
        self.create("S-1", expected={"namespace": "old"})
        before = self.store.load("S-1")
        with self.assertRaises(StoreError):
            self.store.set_answer("S-1", expected=None, rubric=None)
        after = self.store.load("S-1")
        self.assertEqual(after.expected, before.expected)
        self.assertEqual(len(after.history), len(before.history))

    def test_rubric_sets_expected_kind(self):
        self.create("S-1", expected=None)
        sample = self.store.set_answer("S-1", rubric={"source": 2})
        self.assertEqual(sample.expected_kind, "rubric")
        self.assertEqual(sample.rubric, {"source": 2})

    def test_rejected_or_retired_cannot_receive_answer(self):
        self.create("S-1", expected=None)
        self.store.review("S-1", approve=False)
        with self.assertRaises(StoreError):
            self.store.set_answer("S-1", expected=dict(EXPECTED))

    def test_negative_answer_is_rejected_by_admission(self):
        self.create("S-1", expected=None)
        with self.assertRaises(StoreError):
            self.store.set_answer("S-1", expected={})


if __name__ == "__main__":
    unittest.main()
