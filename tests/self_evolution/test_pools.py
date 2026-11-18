"""样本池：状态机、按哈希划测试集、来源去重与建池。"""

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.contracts import Sample  # noqa: E402
from evolve.pools import (  # noqa: E402
    build_pool,
    check_origin_transition,
    check_purpose_transition,
    check_transition,
    dedup,
    ensure_unique_ids,
    origin_transition_errors,
    pool_hash,
    purpose_transition_errors,
    select_pool,
    source_group,
    split_test,
    stratum_of,
    transition_errors,
)


def sample(sid, **overrides):
    values = dict(
        id=sid,
        status="active",
        object_type="diagnosis",
        origin="field",
        purpose="evaluation",
        source=f"https://example.com/issues/{sid}",
        expected={"namespace": "inference/vllm-ascend"},
    )
    values.update(overrides)
    return Sample(**values)


class TransitionTest(unittest.TestCase):
    def test_legal_edges(self):
        legal = [
            ("candidate", "active"),
            ("candidate", "rejected"),
            ("active", "retired"),
            ("retired", "candidate"),
        ]
        for status, target in legal:
            self.assertTrue(check_transition(status, target), f"{status}->{target}")
            self.assertEqual(transition_errors(status, target), [])

    def test_illegal_edges(self):
        illegal = [
            ("candidate", "core"),
            ("candidate", "retired"),
            ("active", "core"),
            ("active", "rejected"),
            ("active", "candidate"),
            ("retired", "active"),
            ("retired", "core"),
            ("rejected", "candidate"),
            ("rejected", "active"),
            ("unknown", "active"),
        ]
        for status, target in illegal:
            self.assertFalse(check_transition(status, target), f"{status}->{target}")
            self.assertTrue(transition_errors(status, target))

    def test_origin_transitions(self):
        self.assertTrue(check_origin_transition("field", "core"))
        self.assertFalse(check_origin_transition("core", "field"))
        self.assertFalse(check_origin_transition("core", "core"))
        self.assertEqual(origin_transition_errors("field", "core"), [])
        self.assertTrue(origin_transition_errors("core", "field"))

    def test_purpose_transitions(self):
        allowed = [
            ("evaluation", "regression"),
            ("evaluation", "test"),
            ("feedback", "regression"),
            ("evaluation", "evaluation"),
            ("feedback", "feedback"),
            ("test", "test"),
            ("regression", "regression"),
        ]
        for old, new in allowed:
            self.assertTrue(check_purpose_transition(old, new), f"{old}->{new}")
            self.assertEqual(purpose_transition_errors(old, new), [])
        denied = [
            ("feedback", "evaluation"),
            ("test", "regression"),
            ("evaluation", "feedback"),
            ("regression", "evaluation"),
            ("cross", "evaluation"),
        ]
        for old, new in denied:
            self.assertFalse(check_purpose_transition(old, new), f"{old}->{new}")
            self.assertTrue(purpose_transition_errors(old, new))


class SplitTestTest(unittest.TestCase):
    def test_only_active_core_evaluation_is_eligible(self):
        samples = [
            sample("core-1", status="active", origin="core", purpose="evaluation"),
            sample("core-2", status="active", origin="core", purpose="evaluation"),
            sample("field-1", status="active", origin="field", purpose="evaluation"),
            sample("core-reg", status="active", origin="core", purpose="regression"),
            sample("retired", status="retired", origin="core", purpose="evaluation"),
            sample("not-promoted", status="active", origin="field", purpose="evaluation"),
        ]
        chosen = {item.id for item in split_test(samples, size=4)}
        self.assertEqual(chosen, {"core-1", "core-2"})

    def test_issue_source_group_normalizes_s2_and_github(self):
        s2 = sample("S2-1", source="eval/s2/vllm-ascend.yaml#10097")
        gh = sample("GH-1", source="github/vllm-project/vllm-ascend#10097")
        self.assertEqual(source_group(s2), source_group(gh))

    def test_strata_quota_selects_each_type(self):
        samples = [
            sample(f"i-{i}", status="active", origin="core", purpose="evaluation",
                   expected={"namespace": "inference/vllm-ascend", "category": "interrupt"})
            for i in range(4)
        ] + [
            sample(f"p-{i}", status="active", origin="core", purpose="evaluation",
                   expected={"namespace": "training/verl", "category": "precision"})
            for i in range(4)
        ]
        chosen = split_test(
            samples, size=2,
            strata={"inference/vllm-ascend/interrupt": 1, "training/verl/precision": 1},
        )
        self.assertEqual(len(chosen), 2)
        self.assertEqual(
            {stratum_of(item) for item in chosen},
            {"inference/vllm-ascend/interrupt", "training/verl/precision"},
        )

    def test_strata_targets_cannot_exceed_size(self):
        with self.assertRaises(ValueError):
            split_test([], size=1, strata={"a": 1, "b": 1})

    def test_size_and_stability(self):
        samples = [
            sample(f"core-{i}", status="active", origin="core", purpose="evaluation")
            for i in range(10)
        ]
        first = [item.id for item in split_test(samples, size=4)]
        second = [item.id for item in split_test(list(reversed(samples)), size=4)]
        self.assertEqual(first, second, "排序只看 id 的 SHA-256，与输入顺序无关")
        expected = sorted(
            samples,
            key=lambda item: hashlib.sha256(item.id.encode("utf-8")).hexdigest(),
        )[:4]
        self.assertEqual(first, [item.id for item in expected])

    def test_fewer_than_size_returns_all(self):
        samples = [sample("core-1", status="active", origin="core", purpose="evaluation")]
        self.assertEqual([item.id for item in split_test(samples, size=4)], ["core-1"])

    def test_group_split_keeps_source_group_together(self):
        samples = [
            sample(f"group-a-{i}", status="active", origin="core",
                   purpose="evaluation", source="source-a")
            for i in range(2)
        ] + [
            sample(f"group-b-{i}", status="active", origin="core",
                   purpose="evaluation", source="source-b")
            for i in range(4)
        ]
        chosen = split_test(samples, size=4, method="group")
        self.assertEqual(len(chosen), 4)
        sources = {item.source for item in chosen}
        self.assertEqual(sources, {"source-b"}, "整组恰好 4 条时不应拆开")

    def test_unknown_split_method(self):
        with self.assertRaises(ValueError):
            split_test([], method="random")

    def test_zero_and_negative_size(self):
        self.assertEqual(split_test([], size=0), [])
        with self.assertRaises(ValueError):
            split_test([], size=-1)


class DedupBuildPoolTest(unittest.TestCase):
    def test_dedup_by_normalized_source(self):
        samples = [
            sample("a", source="https://example.com/issues/1"),
            sample("b", source="https://example.com/issues/1/"),
            sample("c", source="https://example.com/issues/2"),
        ]
        self.assertEqual([item.id for item in dedup(samples)], ["a", "c"])

    def test_empty_sources_do_not_collapse_into_one(self):
        samples = [
            sample("a", source=""),
            sample("b", source=""),
        ]
        self.assertEqual([item.id for item in dedup(samples)], ["a", "b"])

    def test_build_pool_filters_and_dedups(self):
        samples = [
            sample("a", source="s1"),
            sample("b", source="s1"),
            sample("c", status="retired", source="s2"),
            sample("d", status="rejected", source="s3"),
            sample("e", purpose="feedback", source="s4"),
        ]
        pool = build_pool(samples)
        self.assertEqual([item.id for item in pool], ["a", "e"])
        pool = build_pool(samples, purpose="feedback")
        self.assertEqual([item.id for item in pool], ["e"])
        pool = build_pool(samples, statuses=("retired",))
        self.assertEqual([item.id for item in pool], ["c"])

    def test_select_pool_selector(self):
        samples = [sample("a"), sample("b", purpose="feedback")]
        self.assertEqual(
            [item.id for item in select_pool(samples, {"purpose": "feedback"})],
            ["b"],
        )
        with self.assertRaises(ValueError):
            select_pool(samples, {"purpose": "feedback", "bogus": 1})

    def test_pool_hash_is_stable_and_content_sensitive(self):
        samples = [sample("a"), sample("b", source="s2")]
        self.assertEqual(pool_hash(samples), pool_hash(list(reversed(samples))))
        changed = [sample("a", purpose="regression"), sample("b", source="s2")]
        self.assertNotEqual(pool_hash(samples), pool_hash(changed))

    def test_ensure_unique_ids(self):
        self.assertEqual(ensure_unique_ids([sample("a"), sample("b")]), [])
        self.assertEqual(ensure_unique_ids([sample("a"), sample("a")]), ["a"])


if __name__ == "__main__":
    unittest.main()
