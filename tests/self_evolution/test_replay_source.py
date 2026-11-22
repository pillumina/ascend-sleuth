"""S2 replay 结果 → 组件失败信号。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.replay_source import scan_failures  # noqa: E402


class ReplaySourceTest(unittest.TestCase):
    def test_result_failures_become_soft_signals(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            results = root / ".s2-replay"
            results.mkdir()
            (results / "1.result.yaml").write_text(
                "routing_ok: false\n", encoding="utf-8")
            (results / "2.result.yaml").write_text(
                "tier2_hit: false\n", encoding="utf-8")
            (results / "3.result.yaml").write_text(
                "root_cause_ok: false\n", encoding="utf-8")
            (results / "4.result.yaml").write_text(
                "root_cause_ok: true\n", encoding="utf-8")
            data = scan_failures(root)
            self.assertEqual(data["sample_count"], 4)
            self.assertFalse(data["components"]["routing"]["hard"])
            self.assertEqual(data["components"]["routing"]["events"], 1)
            self.assertEqual(data["components"]["case_hit"]["events"], 1)

    def test_missing_dir(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(scan_failures(Path(td))["available"])


if __name__ == "__main__":
    unittest.main()
