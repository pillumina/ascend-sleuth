"""样本池入口：把 pilot 的样本注册进队列，重复导入不重复。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.samples import SampleStore, import_pilot  # noqa: E402


class SampleImportTest(unittest.TestCase):
    def test_import_pilot_registers_candidates_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sample = root / "E2E-1001.yaml"
            sample.write_text(yaml.safe_dump({
                "id": "E2E-1001", "source": "github/e2e#1001",
                "input": {"title": "t"}, "expected": {"resolution": "ok"},
            }), encoding="utf-8")
            tasks = root / "tasks.json"
            tasks.write_text(json.dumps({
                "candidate_id": "C-1",
                "samples": [{"id": "E2E-1001", "short_id": "1001",
                             "path": str(sample), "expected": {}}],
            }), encoding="utf-8")
            store = SampleStore(root=root)
            first = import_pilot(store, tasks)
            second = import_pilot(store, tasks)
            self.assertEqual(first["created"], ["1001"])
            self.assertEqual(second["created"], [])
            self.assertEqual(second["skipped"], ["1001"])
            loaded = store.load("1001")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.status, "candidate")
            self.assertEqual(loaded.object_type, "diagnosis")
            self.assertEqual(loaded.expected, {"resolution": "ok"})


if __name__ == "__main__":
    unittest.main()
