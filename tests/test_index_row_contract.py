# -*- coding: utf-8 -*-
"""索引行格式的 Python 侧契约：与面板 host 的 parseListRow 共用一份 fixture。"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_index  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


class IndexRowContractTest(unittest.TestCase):
    def test_fixture_line_parses_to_expected_object(self):
        line = (FIXTURES / "index-row.list").read_text(encoding="utf-8").strip()
        expected = json.loads((FIXTURES / "index-row.expected.json").read_text(encoding="utf-8"))
        self.assertEqual(build_index.parse_read_line(line), expected)


if __name__ == "__main__":
    unittest.main()
