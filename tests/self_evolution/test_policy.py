"""策略加载、未知键、哈希与 A3 降级测试。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

import sleuth_config as SC  # noqa: E402
from evolve.policy import (  # noqa: E402
    DEFAULTS,
    PolicyError,
    canonical_hash,
    load_config_policy,
    load_policy,
    policy_hash,
    resolve_autonomy,
)


class PolicyLoadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, data, name="policy.yaml"):
        path = self.root / name
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return path

    def test_tracked_policy_matches_defaults(self):
        loaded = load_config_policy(SC.load_config(ROOT))
        self.assertEqual(loaded, DEFAULTS)

    def test_missing_file_fails(self):
        with self.assertRaises(PolicyError):
            load_policy(self.root / "missing.yaml")

    def test_partial_policy_is_merged_with_defaults(self):
        path = self.write({"decision": {"alpha": 0.2}})
        policy = load_policy(path)
        self.assertEqual(policy["decision"]["alpha"], 0.2)
        self.assertEqual(policy["decision"]["method"], "paired_binary")
        self.assertEqual(policy["samples"], DEFAULTS["samples"])
        self.assertEqual(policy["experiment"], DEFAULTS["experiment"])

    def test_free_form_strata_and_budget_are_allowed(self):
        path = self.write({
            "samples": {"strata": {"inference/vllm-ascend/interrupt": 2}},
            "experiment": {"budget": {"rollouts": 30}},
        })
        policy = load_policy(path)
        self.assertEqual(policy["samples"]["strata"]["inference/vllm-ascend/interrupt"], 2)
        self.assertEqual(policy["experiment"]["budget"]["rollouts"], 30)

    def test_top_level_unknown_key_fails(self):
        path = self.write({**DEFAULTS, "unknown": 1})
        with self.assertRaises(PolicyError) as ctx:
            load_policy(path)
        self.assertIn("unknown policy key: unknown", str(ctx.exception))

    def test_nested_unknown_key_fails(self):
        path = self.write({"autonomy": {"default": "A2", "surprise": True}})
        with self.assertRaises(PolicyError) as ctx:
            load_policy(path)
        self.assertIn("autonomy.surprise", str(ctx.exception))

    def test_overrides_are_free_form_but_levels_are_validated(self):
        path = self.write({"autonomy": {"overrides": {"my.component": "A1"}}})
        policy = load_policy(path)
        self.assertEqual(resolve_autonomy(policy, "my.component"), "A1")
        bad = self.write({"autonomy": {"overrides": {"my.component": "A9"}}}, "bad.yaml")
        with self.assertRaises(PolicyError):
            load_policy(bad)

    def test_invalid_enums_fail(self):
        cases = [
            {"autonomy": {"default": "A9"}},
            {"objective": {"primary": "vibes"}},
            {"decision": {"method": "magic"}},
            {"samples": {"split": "random"}},
            {"cost": {"primary_dimension": "money"}},
            {"rubrics": {"threshold": 1.5}},
            {"experiment": {"algorithm": "magic"}},
            {"experiment": {"target": "magic"}},
            {"experiment": {"target": "harness", "algorithm": "ael"}},
        ]
        for index, data in enumerate(cases):
            with self.subTest(data=data):
                path = self.write(data, f"bad-{index}.yaml")
                with self.assertRaises(PolicyError):
                    load_policy(path)

    def test_null_policy_file_means_defaults(self):
        path = self.root / "empty.yaml"
        path.write_text("", encoding="utf-8")
        self.assertEqual(load_policy(path), DEFAULTS)


class PolicyHashTest(unittest.TestCase):
    def test_hash_is_stable_and_canonical(self):
        first = policy_hash(DEFAULTS)
        self.assertEqual(first, policy_hash(load_policy(None)))
        self.assertEqual(first, canonical_hash(DEFAULTS))
        self.assertEqual(len(first), 64)

    def test_hash_changes_with_decision_policy(self):
        changed = {**DEFAULTS, "decision": {"method": "paired_binary", "alpha": 0.05}}
        self.assertNotEqual(policy_hash(DEFAULTS), policy_hash(changed))

    def test_key_order_does_not_change_hash(self):
        reordered = {
            key: DEFAULTS[key]
            for key in reversed(list(DEFAULTS))
        }
        self.assertEqual(policy_hash(DEFAULTS), policy_hash(reordered))


class AutonomyResolutionTest(unittest.TestCase):
    def test_default_and_override(self):
        policy = load_policy(None)
        self.assertEqual(resolve_autonomy(policy, "unknown.component"), "A2")
        self.assertEqual(resolve_autonomy(policy, "docs.normative"), "A1")
        self.assertEqual(resolve_autonomy(policy, "feedback.pool"), "A2")

    def test_a3_falls_back_to_a2_without_auto_merge(self):
        policy = load_policy(None)
        self.assertEqual(resolve_autonomy(policy, "docs.non_normative"), "A2")
        enabled = load_policy(None)
        enabled["autonomy"]["auto_merge"]["enabled"] = True
        self.assertEqual(resolve_autonomy(enabled, "docs.non_normative"), "A3")

    def test_non_a3_levels_are_not_affected_by_auto_merge(self):
        policy = load_policy(None)
        policy["autonomy"]["auto_merge"]["enabled"] = False
        self.assertEqual(resolve_autonomy(policy, "docs.normative"), "A1")


if __name__ == "__main__":
    unittest.main()
