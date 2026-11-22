# -*- coding: utf-8 -*-
"""RSI 事件流完整性检查。"""

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.store import MemoryBackend, RSIStore, verify  # noqa: E402


class StoreVerifyTest(unittest.TestCase):
    def test_reports_missing_conclusion_orphans_and_bad_time(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            store = RSIStore(base, backend=MemoryBackend())
            store.append("experiment", {
                "proposal": {"id": "P-1"}, "conclusion": {}, "experiment": {},
                "rollout": {},
            }, experiment_id="EX-1", proposal_id="P-1", at="2026-01-01T00:00:00+00:00")
            store.append("decision", {"conclusion": {}}, at="2026-01-01T00:00:00+00:00")
            store.append("rollout", {"run": {"trace_ref": "/no/such/trace.yaml"}},
                         at="not-a-time")
            result = verify(base, store)
            codes = {issue["code"] for issue in result["issues"]}
            self.assertIn("experiment_without_conclusion", codes)
            self.assertIn("orphan_decision", codes)
            self.assertIn("orphan_rollout", codes)
            self.assertIn("bad_timestamp", codes)
            self.assertIn("missing_trace", codes)

    def test_clean_store_ok(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            store = RSIStore(base, backend=MemoryBackend())
            store.append("experiment", {
                "proposal": {"id": "P-1"}, "conclusion": {"decision": "accept"},
                "experiment": {}, "rollout": {},
            }, experiment_id="EX-1", proposal_id="P-1", at="2026-01-01T00:00:00+00:00")
            result = verify(base, store)
            self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
