"""pilot manifest/collect 的样本 ID 映射与重复保护。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.pilot import PilotError, _short_id  # noqa: E402


class PilotIdTest(unittest.TestCase):
    def test_extracts_issue_from_common_forms(self):
        self.assertEqual(_short_id("GH-VLLM-PROJECT-VLLM-ASCEND-13934"), "13934")
        self.assertEqual(_short_id("VLLM-ASC-10253"), "10253")
        self.assertEqual(_short_id("2026-11-18-15815-qwen"), "15815")

    def test_collision_is_visible(self):
        self.assertEqual(_short_id("GH-X-10253"), _short_id("VLLM-ASC-10253"))


if __name__ == "__main__":
    unittest.main()
