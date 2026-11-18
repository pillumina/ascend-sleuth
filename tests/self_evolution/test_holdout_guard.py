"""开源 issue 与 holdout 封存集的硬隔离。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.holdout_guard import HoldoutError, is_holdout_source, issue_numbers  # noqa: E402


class HoldoutGuardTest(unittest.TestCase):
    def test_extracts_fixture_issue_numbers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "eval").mkdir()
            (root / "eval" / "holdout.yaml").write_text(
                "entries:\n- fixture: VLLM-ASC-13329.fixture.yaml\n"
                "- fixture: SGL-PD-HEAP-001.fixture.yaml\n",
                encoding="utf-8",
            )
            self.assertEqual(issue_numbers(root), {"13329", "001"})

    def test_source_match_is_hard(self):
        numbers = {"13329"}
        self.assertTrue(is_holdout_source("vllm-project/vllm-ascend#13329", numbers))
        self.assertFalse(is_holdout_source("vllm-project/vllm-ascend#1", numbers))
        self.assertTrue(is_holdout_source("https://github.com/vllm-project/vllm-ascend/issues/13329", numbers))

    def test_missing_manifest_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(issue_numbers(Path(td)), set())


if __name__ == "__main__":
    unittest.main()
