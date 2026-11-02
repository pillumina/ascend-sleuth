"""演进体检器的配置结构检查：判据 id 不能重复。

为什么：体检器按 id 找判据，重复条目会被判两遍、阈值只取第一条。复制粘贴一条判据在
`--check` 下必须表现为"结论不可用"（退 2），而不是安静地按第一条继续。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evolution_health as EH  # noqa: E402


class DuplicateGateIdTest(unittest.TestCase):
    def test_duplicate_gate_id_is_broken(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "proposals").mkdir()
            (root / "proposals" / "gates.yaml").write_text(
                "gates:\n"
                "  - id: repeated\n"
                "    dimension: backlog_count\n"
                "    op: \">\"\n"
                "    value: 1\n"
                "  - id: repeated\n"
                "    dimension: backlog_count\n"
                "    op: \">\"\n"
                "    value: 99\n",
                encoding="utf-8",
            )
            payload = EH.evaluate(root)
            self.assertEqual(payload["check_verdict"], "broken")
            self.assertTrue(any("重复" in e and "repeated" in e for e in payload["errors"]),
                            payload["errors"])


if __name__ == "__main__":
    unittest.main()
