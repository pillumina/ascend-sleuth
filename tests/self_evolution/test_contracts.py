"""数据契约的字段、枚举与序列化回归测试。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.contracts import (  # noqa: E402
    ORIGINS,
    STATUSES,
    Conclusion,
    ContractError,
    Run,
    Sample,
    Version,
)


def make_sample(**overrides):
    values = dict(
        id="S-1",
        status="candidate",
        object_type="diagnosis",
        origin="field",
        purpose="evaluation",
        source="https://example.com/issues/1",
        expected={"namespace": "inference/vllm-ascend"},
    )
    values.update(overrides)
    return Sample(**values)


class SampleContractTest(unittest.TestCase):
    def test_roundtrip_keeps_fields(self):
        sample = make_sample(notes="n", proposed={"expected": {"category": "interrupt"}})
        restored = Sample.from_dict(sample.to_dict())
        self.assertEqual(restored, sample)

    def test_active_without_answer_fails(self):
        sample = make_sample(status="active", expected=None, rubric=None)
        errors = sample.errors()
        self.assertTrue(any("active sample" in message for message in errors))

    def test_candidate_can_defer_answer_but_admission_cannot(self):
        sample = make_sample(expected=None, rubric=None)
        self.assertEqual(sample.errors(), [])
        errors = sample.errors(require_answer=True)
        self.assertTrue(any("before admission" in message for message in errors))

    def test_candidate_may_have_proposed_fields(self):
        sample = make_sample(expected=None, proposed={"expected": {"category": "interrupt"}})
        self.assertEqual(sample.errors(), [])

    def test_active_with_rubric_ok(self):
        sample = make_sample(status="active", expected=None, rubric={"source": 2})
        self.assertEqual(sample.errors(), [])

    def test_core_is_an_origin_not_a_status(self):
        self.assertNotIn("core", STATUSES)
        self.assertIn("core", ORIGINS)

    def test_invalid_enums(self):
        for field, value in (
            ("status", "field"),
            ("status", "core"),
            ("object_type", "card"),
            ("origin", "online"),
            ("purpose", "benchmark"),
            ("expected_kind", "answer"),
        ):
            sample = make_sample(**{field: value})
            self.assertTrue(
                any(field in message for message in sample.errors()),
                f"{field}={value!r} 应报错",
            )

    def test_limits_only_for_scale(self):
        sample = make_sample(limits={"max_tokens": 1000})
        self.assertTrue(any("only valid for purpose=scale" in m for m in sample.errors()))
        sample = make_sample(purpose="scale", limits={"max_tokens": 1000})
        self.assertEqual(sample.errors(), [])

    def test_invalid_id_rejected(self):
        for value in ("", "../x", "a/b", ".hidden", ".."):
            self.assertTrue(any("id is required" in m for m in make_sample(id=value).errors()))

    def test_unknown_field_rejected_on_read(self):
        data = make_sample().to_dict()
        data["surprise"] = True
        with self.assertRaises(ContractError):
            Sample.from_dict(data)

    def test_expected_kind_rubric_requires_rubric(self):
        sample = make_sample(expected_kind="rubric")
        self.assertTrue(any("requires rubric" in m for m in sample.errors()))

    def test_validate_raises(self):
        with self.assertRaises(ContractError):
            make_sample(status="active", expected=None).validate()


class VersionRunConclusionTest(unittest.TestCase):
    def _version(self):
        return Version(
            protocol="p1",
            policy="policy-3",
            base_kb="9f2c1a",
            candidate_kb="9f2c1a",
            candidate="4d8e0b",
            model="deepseek-flash/default",
        )

    def test_version_roundtrip_and_required(self):
        version = self._version()
        self.assertEqual(Version.from_dict(version.to_dict()), version)
        with self.assertRaises(ContractError):
            Version.from_dict({"protocol": "p1"})
        with self.assertRaises(ContractError):
            Version.from_dict({**version.to_dict(), "extra": "x"})

    def test_placeholder_answer_is_rejected_for_active_but_retireable(self):
        active = make_sample(status="active", expected={"resolution": "（待补：维护者结论）"})
        self.assertTrue(any("placeholder" in error for error in active.errors(require_answer=True)))
        retired = make_sample(status="retired", expected={"resolution": "（待补：维护者结论）"})
        self.assertFalse(any("placeholder" in error for error in retired.errors()))

    def test_version_carries_algorithm_identity(self):
        version = Version(
            protocol="p1", policy="policy-3", base_kb="a", candidate_kb="a",
            candidate="b", model="m", algorithm="gepa", algorithm_version="v1",
            budget={"rollouts": 30}, seed=7,
        )
        self.assertEqual(Version.from_dict(version.to_dict()), version)
        self.assertEqual(version.to_dict()["algorithm"], "gepa")

    def test_run_roundtrip(self):
        run = Run(
            sample="S-1",
            versions=self._version(),
            metrics={"case_hit": True, "root_cause": None},
            cost={"tokens": {"billed": 10}},
            harness_session="sess-1",
            at="2026-11-17T09:30:00+08:00",
        )
        self.assertEqual(Run.from_dict(run.to_dict()), run)

    def test_conclusion_roundtrip(self):
        conclusion = Conclusion(
            decision="insufficient",
            metrics={"case_hit": 0.6},
            cost={"tokens": 10},
            reason="b=2, c=0, p=0.25 > alpha_eff=0.10",
            versions=self._version(),
            pool_hash="5c1d2e",
            reuse_index=1,
            alpha_eff=0.05,
            b=2,
            c=0,
            n=9,
            p_value=0.25,
            at="2026-11-17T09:35:00+08:00",
        )
        self.assertEqual(Conclusion.from_dict(conclusion.to_dict()), conclusion)

    def test_conclusion_record_fields_roundtrip(self):
        conclusion = Conclusion(
            decision="accept",
            versions=self._version(),
            b=4,
            c=0,
            n=9,
            p_value=0.0625,
            alpha_eff=0.10,
            delta_q=4 / 9,
            cost_ratio=1.05,
            sample="S-1",
            card="EV-2026-001",
            pool="pool-x",
            pool_hash="abc123",
            at="2026-11-17T09:35:00+08:00",
        )
        data = conclusion.to_dict()
        self.assertAlmostEqual(data["cost_ratio"], 1.05)
        self.assertEqual(data["sample"], "S-1")
        self.assertEqual(data["card"], "EV-2026-001")
        self.assertEqual(data["pool"], "pool-x")
        self.assertEqual(Conclusion.from_dict(data), conclusion)

    def test_conclusion_rejects_unknown_decision(self):
        with self.assertRaises(ContractError):
            Conclusion(decision="maybe").validate()


if __name__ == "__main__":
    unittest.main()
