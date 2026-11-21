# -*- coding: utf-8 -*-
"""单一配置 sleuth.config.yaml 的读取、profile、流水线与 store 优先级。"""

import tempfile
import unittest
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sleuth_config as SC  # noqa: E402
from evolve.policy import load_config_policy  # noqa: E402
from evolve.store import StoreConfig  # noqa: E402


class SleuthConfigTest(unittest.TestCase):
    def test_unified_config_carries_role_policy_store_sync(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sleuth.config.yaml").write_text(yaml.safe_dump({
                "schema": SC.SCHEMA,
                "evolution": {
                    "role": "signal-only",
                    "store": {"backend": "memory"},
                    "policy": {"decision": {"alpha": 0.05}},
                    "profiles": {"latency": {"cost": {"primary_dimension": "time"}}},
                },
                "sync": {"mode": "offline"},
            }), encoding="utf-8")
            cfg = SC.load_config(root)
            self.assertEqual(SC.role(cfg), "signal-only")
            self.assertEqual(SC.sync_mode(cfg), "offline")
            self.assertEqual(SC.store_for(cfg)["backend"], "memory")
            self.assertEqual(load_config_policy(cfg)["decision"]["alpha"], 0.05)
            self.assertEqual(load_config_policy(cfg, "latency")["cost"]["primary_dimension"], "time")

    def test_autonomy_professional_names_map_to_rfc_levels(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sleuth.config.yaml").write_text(yaml.safe_dump({
                "schema": SC.SCHEMA,
                "evolution": {
                    "role": "maintainer",
                    "policy": {
                        "autonomy": {
                            "default": "batch_review",
                            "overrides": {"docs.normative": "propose",
                                          "docs.non_normative": "supervised_auto"},
                        },
                    },
                },
            }), encoding="utf-8")
            policy = load_config_policy(SC.load_config(root))
            self.assertEqual(policy["autonomy"]["default"], "A2")
            self.assertEqual(policy["autonomy"]["overrides"]["docs.normative"], "A1")
            self.assertEqual(policy["autonomy"]["overrides"]["docs.non_normative"], "A3")

    def test_pipeline_preset_extends_default(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config" / "rsi").mkdir(parents=True)
            (root / "config" / "rsi" / "pipelines.yaml").write_text(yaml.safe_dump({
                "pipelines": {
                    "default": {"stages": {
                        "attribute": "attribute.trace_rule",
                        "select_region": "select.region_hardcount",
                        "select_candidate": "select.best",
                        "propose": "propose.agent",
                        "judge": "judge.subagent",
                        "gate": "gate.paired",
                    }},
                    "no_proposal": {"extends": "default",
                                    "stages": {"propose": "propose.none"}},
                },
            }), encoding="utf-8")
            (root / "sleuth.config.yaml").write_text(yaml.safe_dump({
                "schema": SC.SCHEMA,
                "evolution": {
                    "role": "maintainer",
                    "pipeline": "no_proposal",
                    "pipeline_config": ["config/rsi/pipelines.yaml"],
                },
            }), encoding="utf-8")
            policy = load_config_policy(SC.load_config(root))
            self.assertEqual(policy["experiment"]["stages"]["propose"], "propose.none")
            self.assertEqual(policy["experiment"]["stages"]["judge"], "judge.subagent")

    def test_config_file_wins_over_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sleuth.config.yaml").write_text(yaml.safe_dump({
                "schema": SC.SCHEMA, "evolution": {"role": "off"},
            }), encoding="utf-8")
            self.assertEqual(SC.role(SC.load_config(root)), "off")

    def test_unknown_top_level_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sleuth.config.yaml").write_text(yaml.safe_dump({
                "schema": SC.SCHEMA, "unexpected": True,
            }), encoding="utf-8")
            with self.assertRaises(SC.ConfigError):
                SC.load_config(root)

    def test_unknown_profile_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "sleuth.config.yaml").write_text(yaml.safe_dump({
                "schema": SC.SCHEMA, "evolution": {"role": "off"},
            }), encoding="utf-8")
            cfg = SC.load_config(root)
            with self.assertRaises(SC.ConfigError):
                SC.policy_for(cfg, "missing")

    def test_store_config_reads_unified_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / ".s2-replay" / "evolve"
            base.mkdir(parents=True)
            (root / "sleuth.config.yaml").write_text(yaml.safe_dump({
                "schema": SC.SCHEMA,
                "evolution": {"store": {"backend": "local", "path": ".s2-replay/evolve/events.jsonl"}},
            }), encoding="utf-8")
            cfg = StoreConfig.load(base)
            self.assertEqual(cfg.backend, "local")
            self.assertTrue(str(cfg.options["path"]).endswith("events.jsonl"))


if __name__ == "__main__":
    unittest.main()
