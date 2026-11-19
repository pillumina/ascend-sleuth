"""eval/core 样本：读取、导出与本地/核心重复检测。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.samples import SampleStore, StoreError  # noqa: E402


class CoreSampleTest(unittest.TestCase):
    def _sample(self, store, sample_id="S-1"):
        sample = store.new(
            id=sample_id, object_type="diagnosis", source=f"traces/{sample_id}.yaml",
            purpose="evaluation", expected={"resolution": "r"},
            provenance={"trigger": "diagnosis_end", "sanitized": True,
                        "redactions": [], "confidence": "maintainer-reviewed",
                        "extraction": "auto"},
        )
        store.review(sample.id, approve=True)
        store.promote(sample.id, to="core")
        return store.set_purpose(sample.id, "regression")

    def test_export_moves_to_eval_core_and_reloads(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SampleStore(root=root)
            sample = self._sample(store)
            path = store.export_core(sample.id)
            self.assertTrue(path.is_file())
            self.assertIn("eval/core/samples", path.as_posix())
            self.assertFalse(store.path_for(sample.id).exists())
            self.assertEqual(store.load(sample.id).purpose, "regression")
            self.assertEqual([s.id for s in store.read_all()], [sample.id])

    def test_core_sample_is_not_rewritten_locally(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SampleStore(root=root)
            sample = self._sample(store)
            store.export_core(sample.id)
            with self.assertRaises(StoreError):
                store.retire(sample.id)

    def test_duplicate_local_and_core_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SampleStore(root=root)
            sample = self._sample(store)
            store.export_core(sample.id)
            local = store.path_for(sample.id)
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_text(store.core_path_for(sample.id).read_text(encoding="utf-8"),
                             encoding="utf-8")
            with self.assertRaises(StoreError):
                store.read_all()


if __name__ == "__main__":
    unittest.main()
