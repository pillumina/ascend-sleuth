"""自演进看板的样本队列：只读样本库并现算完整性。"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ev_board_data  # noqa: E402


class SampleQueueTest(unittest.TestCase):
    def test_collects_sample_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            samples = root / ".s2-replay" / "evolve" / "samples"
            samples.mkdir(parents=True)
            (samples / "S-1.yaml").write_text(yaml.safe_dump({
                "id": "S-1", "status": "candidate", "object_type": "diagnosis",
                "origin": "field", "purpose": "evaluation",
                "source": "traces/t.yaml", "input": {"phenomenon": "崩"},
                "expected": {"resolution": "修复"},
                "provenance": {"trigger": "diagnosis_end", "sanitized": True,
                               "redactions": [], "confidence": "maintainer-reviewed",
                               "extraction": "auto"},
            }, allow_unicode=True), encoding="utf-8")
            result = ev_board_data.collect_samples(root)
            self.assertTrue(result["present"])
            self.assertEqual(result["count"], 1)
            self.assertEqual(result["items"][0]["id"], "S-1")
            self.assertEqual(result["items"][0]["state"], "ready")

    def test_missing_store_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            result = ev_board_data.collect_samples(Path(td))
            self.assertFalse(result["present"])
            self.assertEqual(result["items"], [])


if __name__ == "__main__":
    unittest.main()
