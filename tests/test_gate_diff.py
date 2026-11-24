"""gate_diff：baseline/after 结果的读取口径。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gate_diff  # noqa: E402


class LoadResultsTest(unittest.TestCase):
    def test_missing_dir_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(gate_diff.load_results(Path(td) / "nope"), {})

    def test_reads_json_by_stem_and_marks_broken(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "fixture-a.json").write_text(
                json.dumps({"fixture": "a", "top3": ["X"]}), encoding="utf-8")
            (root / "fixture-b.json").write_text("{bad", encoding="utf-8")
            out = gate_diff.load_results(root)
            self.assertEqual(out["fixture-a"]["fixture"], "a")
            self.assertIsNone(out["fixture-b"])


if __name__ == "__main__":
    unittest.main()
