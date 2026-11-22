"""metrics 只读消费：缺文件标记、latest period 与关键读数。"""

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evolve.adapters.metrics import load_metrics  # noqa: E402
from metrics_fixture import write_metrics  # noqa: E402


class MetricsTest(unittest.TestCase):
    def test_reads_latest_period_and_key_readings(self):
        with tempfile.TemporaryDirectory() as td:
            root = write_metrics(Path(td))
            metrics = load_metrics(root)
        self.assertTrue(metrics["timeline"]["available"])
        self.assertEqual(metrics["latest_period"]["period"], "2026-W36-live")
        self.assertEqual(metrics["latest_period"]["kind"], "live")
        self.assertEqual(metrics["sessions_total"], 11)
        self.assertEqual(metrics["tier2_hit"], 4)
        self.assertEqual(metrics["case_total"], 42)
        self.assertEqual(metrics["feedback"], {
            "resolved": 2, "not_resolved": 1, "partial": 0,
        })
        self.assertTrue(metrics["gates"]["available"])
        self.assertEqual(metrics["gates"]["gate_count"], 1)
        self.assertEqual(metrics["last_skill_exec"]["last"]["skill"], "evolve-check")
        entry = metrics["entry_usage"]
        self.assertTrue(entry["available"])
        self.assertEqual(entry["cases"], 2)
        self.assertEqual(entry["active_cases"], 1)
        self.assertEqual(entry["references"], 1)
        self.assertEqual(entry["cold_cases"], 172)

    def test_live_period_age_marks_stale_against_gates(self):
        with tempfile.TemporaryDirectory() as td:
            root = write_metrics(Path(td))
            metrics = load_metrics(root, today=date(2026, 9, 10))
        live = metrics["freshness"]["live"]
        self.assertEqual(live["age_days"], 8)
        self.assertEqual(live["max_age_days"], 7)
        self.assertTrue(live["stale"])

    def test_missing_files_are_marked_not_zero(self):
        with tempfile.TemporaryDirectory() as td:
            metrics = load_metrics(Path(td))
        self.assertFalse(metrics["timeline"]["available"])
        self.assertIsNone(metrics["latest_period"])
        self.assertIsNone(metrics["sessions_total"])
        self.assertIsNone(metrics["tier2_hit"])
        self.assertIsNone(metrics["case_total"])
        self.assertIsNone(metrics["feedback"])
        self.assertFalse(metrics["gates"]["available"])
        self.assertFalse(metrics["last_skill_exec"]["available"])
        self.assertFalse(metrics["entry_usage"]["available"])

    def test_broken_file_is_marked_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "metrics").mkdir()
            (root / "metrics" / "timeline.yaml").write_text("periods: [", encoding="utf-8")
            metrics = load_metrics(root)
        self.assertFalse(metrics["timeline"]["available"])
        self.assertIsNone(metrics["sessions_total"])


if __name__ == "__main__":
    unittest.main()
