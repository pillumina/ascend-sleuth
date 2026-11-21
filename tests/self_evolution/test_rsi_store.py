# -*- coding: utf-8 -*-
"""存储端口、配置与后端切换。"""

import tempfile
import unittest
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.store import MemoryBackend, RSIStore, RSIStoreError, StoreConfig, open_store  # noqa: E402


class RSIStoreTest(unittest.TestCase):
    def test_memory_backend_history(self):
        store = RSIStore(Path("."), backend=MemoryBackend())
        store.append("proposal", {"proposal": {"id": "P-1"}}, proposal_id="P-1", experiment_id="EX-1")
        store.append("decision", {"decision": "accept"}, proposal_id="P-1", experiment_id="EX-1")
        self.assertEqual(len(store.history(proposal_id="P-1")), 2)
        self.assertEqual(len(store.history(experiment_id="EX-1")), 2)
        self.assertEqual(store.get_proposal("P-1"), {"id": "P-1"})
        self.assertIsNone(store.get_proposal("missing"))

    def test_unknown_event_kind_is_rejected(self):
        store = RSIStore(Path("."), backend=MemoryBackend())
        with self.assertRaises(RSIStoreError):
            store.append("unknown", {})

    def test_config_selects_local_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / ".s2-replay" / "evolve"
            base.mkdir(parents=True)
            (root / "sleuth.config.yaml").write_text(yaml.safe_dump({
                "schema": "sleuth-config-v1",
                "evolution": {"store": {"backend": "local",
                                        "path": ".s2-replay/evolve/events.jsonl"}},
            }), encoding="utf-8")
            store = open_store(base)
            store.append("archive", {"status": "archived"})
            self.assertTrue((base / "events.jsonl").exists())
            self.assertEqual(store.read("archive")[0]["data"]["status"], "archived")

    def test_store_config_env_backend(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            import os
            old = os.environ.get("SLEUTH_RSI_STORE_BACKEND")
            os.environ["SLEUTH_RSI_STORE_BACKEND"] = "memory"
            try:
                store = open_store(base)
                self.assertIsInstance(store.backend, MemoryBackend)
            finally:
                if old is None:
                    del os.environ["SLEUTH_RSI_STORE_BACKEND"]
                else:
                    os.environ["SLEUTH_RSI_STORE_BACKEND"] = old

    def test_unknown_backend_is_rejected(self):
        with self.assertRaises(RSIStoreError):
            open_store(Path("."), StoreConfig(backend="remote"))


if __name__ == "__main__":
    unittest.main()
