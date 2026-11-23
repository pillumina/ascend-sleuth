# -*- coding: utf-8 -*-
"""文件原语：原子写、YAML 读写、固定 LF。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _fs  # noqa: E402


class AtomicWriteTest(unittest.TestCase):
    def test_writes_lf_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "a.txt"
            _fs.atomic_write_text(path, "a\nb\n")
            self.assertEqual(path.read_bytes(), b"a\nb\n")
            self.assertEqual(list(Path(td).iterdir()), [path])

    def test_verify_true_still_writes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "a.txt"
            _fs.atomic_write_text(path, "x\n", verify=True)
            self.assertEqual(path.read_text(encoding="utf-8"), "x\n")

    def test_yaml_roundtrip_keeps_unicode_and_lf(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "a.yaml"
            _fs.write_yaml(path, {"title": "中文", "n": 1})
            self.assertEqual(_fs.load_yaml(path), {"title": "中文", "n": 1})
            self.assertNotIn(b"\r\n", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
