"""知识库内容哈希：稳定、按内容变化、缺目录记 unknown。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.kb_content import content_rev  # noqa: E402


class KbContentTest(unittest.TestCase):
    def test_stable_and_content_addressed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            case = root / "knowledge" / "inference" / "a.yaml"
            case.parent.mkdir(parents=True)
            case.write_text("id: A\n", encoding="utf-8")
            first = content_rev(root)
            self.assertNotEqual(first, "unknown")
            self.assertEqual(first, content_rev(root))
            case.write_text("id: B\n", encoding="utf-8")
            self.assertNotEqual(first, content_rev(root))
            # references/ 与运行时件不进这个坐标
            (root / "references").mkdir()
            (root / "references" / "x.yaml").write_text("id: R\n", encoding="utf-8")
            after_ref = content_rev(root)
            self.assertEqual(after_ref, content_rev(root))

    def test_missing_knowledge_is_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(content_rev(Path(td)), "unknown")
