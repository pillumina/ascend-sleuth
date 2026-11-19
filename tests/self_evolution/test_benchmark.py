"""确定性 benchmark：工具/检索类改动的低成本入口。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.benchmark import BenchmarkError, compare, load_argv  # noqa: E402


class BenchmarkTest(unittest.TestCase):
    def test_compare_runs_both_roots(self):
        with tempfile.TemporaryDirectory() as td:
            result = compare(Path(td), Path(td),
                             [sys.executable, "-c", "print('ok')"], runs=2)
        self.assertTrue(result["baseline"]["ok"])
        self.assertTrue(result["candidate"]["ok"])
        self.assertEqual(result["runs"], 2)
        self.assertIsNotNone(result["delta_ms"])

    def test_bad_argv_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(BenchmarkError):
                compare(Path(td), Path(td), [], runs=1)
            with self.assertRaises(BenchmarkError):
                compare(Path(td), Path(td), [sys.executable, 1], runs=1)
            with self.assertRaises(BenchmarkError):
                compare(Path(td), Path(td), [sys.executable, "-c", "print(1)"], runs=0)

    def test_missing_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(BenchmarkError):
                compare(Path(td) / "missing", Path(td),
                        [sys.executable, "-c", "print(1)"], runs=1)

    def test_argv_json(self):
        self.assertEqual(load_argv(json.dumps([sys.executable, "-c", "print(1)"])),
                         [sys.executable, "-c", "print(1)"])
        with self.assertRaises(BenchmarkError):
            load_argv('{"argv": []}')


if __name__ == "__main__":
    unittest.main()
