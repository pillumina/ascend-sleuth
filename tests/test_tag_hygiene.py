# -*- coding: utf-8 -*-
"""tag 自动删除项：目录叶子名（框架名）仍要命中。"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tag_hygiene  # noqa: E402


class AutoDropTest(unittest.TestCase):
    def test_framework_leaf_tag_is_still_auto_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "knowledge" / "training" / "verl" / "interrupt" / "x.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(yaml.safe_dump({"cases": [{
                "id": "X-1",
                "category": "interrupt",
                "tags": ["verl", "interrupt", "keep-me"],
            }]}, allow_unicode=True, sort_keys=False), encoding="utf-8")
            self.assertEqual(tag_hygiene.auto_drop(root), {"verl", "interrupt"})


if __name__ == "__main__":
    unittest.main()
