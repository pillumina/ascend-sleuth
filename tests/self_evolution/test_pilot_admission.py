# -*- coding: utf-8 -*-
"""pilot 读取 SampleStore 时复用准入。"""

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.pilot import _read_samples  # noqa: E402
from evolve.samples import SampleStore  # noqa: E402


class PilotAdmissionTest(unittest.TestCase):
    def _sample(self, root, purpose="evaluation"):
        store = SampleStore(root=root)
        sample = store.new(
            id="S-ADM-1", object_type="diagnosis", source="https://example.com/1",
            origin="field", purpose=purpose,
            expected={"resolution": "ok"}, input={"title": "x"},
            provenance={"sanitized": True, "trigger": "manual_case",
                        "confidence": "maintainer-reviewed", "extraction": "manual"},
        )
        store.review(sample.id, approve=True)
        return store.path_for(sample.id)

    def test_active_evaluation_is_admitted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._sample(root)
            rows = _read_samples([str(path)], root=root)
            self.assertEqual(rows[0]["id"], "S-ADM-1")

    def test_feedback_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._sample(root, purpose="feedback")
            with self.assertRaises(Exception):
                _read_samples([str(path)], root=root)


if __name__ == "__main__":
    unittest.main()
