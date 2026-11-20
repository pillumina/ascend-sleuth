# -*- coding: utf-8 -*-
"""旧 JSONL -> RSIStore 幂等迁移。"""

import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.migrate import migrate_legacy  # noqa: E402
from evolve.rsi_store import RSIStore  # noqa: E402


class MigrateTest(unittest.TestCase):
    def _base(self, td):
        base = Path(td) / ".s2-replay" / "evolve"
        base.mkdir(parents=True)
        records = {
            "experiments.jsonl": {
                "target_kind": "skill", "target_component": "diagnose.knowledge_usage",
                "summary": "legacy", "decision": "reject", "at": "2026-01-01T00:00:00+00:00",
                "samples": ["s1", "s2"],
                "baseline": {"samples": ["s1", "s2"], "score": 0.5},
                "candidate": {"samples": ["s1", "s2"], "score": 0.5},
            },
            "conclusions.jsonl": {"decision": "insufficient", "at": "2026-01-01T00:00:01+00:00"},
            "runs.jsonl": {"sample": "s1", "at": "2026-01-01T00:00:02+00:00"},
        }
        for name, record in records.items():
            (base / name).write_text(json.dumps(record) + "\n", encoding="utf-8")
        return base

    def test_migrate_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            base = self._base(td)
            first = migrate_legacy(base)
            self.assertEqual(first["counts"], {"proposals": 1, "experiments": 1,
                                               "decisions": 1, "rollouts": 1,
                                               "skipped": 0, "duplicates": 0})
            second = migrate_legacy(base)
            self.assertEqual(second["counts"]["skipped"], 3)
            store = RSIStore(base)
            self.assertEqual(len(store.read()), 4)
            events = store.read()
            experiment = [e for e in events if e["kind"] == "experiment"][0]
            self.assertEqual(experiment["data"]["rollout"]["decision"], "reject")
            self.assertEqual(experiment["data"]["proposal"]["status"], "reject")

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            base = self._base(td)
            result = migrate_legacy(base, dry_run=True)
            self.assertEqual(result["counts"]["experiments"], 1)
            self.assertEqual(RSIStore(base).read(), [])


if __name__ == "__main__":
    unittest.main()
