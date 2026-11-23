"""tail_exec_log：执行记录的摘要与聚合口径。"""

import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tail_exec_log as tel  # noqa: E402


class SummarizeTest(unittest.TestCase):
    def test_datetime_is_stringified(self):
        row = {"seq": 3, "skill": "evolve-check",
               "at": datetime(2026, 11, 20, 10, 30), "source": "user",
               "products": [{"id": "C-1", "status": "draft"}, "S-2"]}
        out = tel.summarize(row)
        self.assertEqual(out["at"], "2026-11-20 10:30:00")
        # 非对象 product 不认（正常记录是 dict）；保留一条以钉住行为。
        self.assertEqual(out["products"], ["C-1(draft)"])
        self.assertEqual(out["seq"], 3)

    def test_missing_fields_default(self):
        out = tel.summarize({})
        self.assertEqual(out["at"], "")
        self.assertEqual(out["products"], [])
        self.assertEqual(out["decision_reason"], "")


class AggregateTest(unittest.TestCase):
    def test_counts_and_no_signal(self):
        rows = [
            {"skill": "evolve-check", "products": [], "decision_reason": "无演进信号",
             "at": "2026-11-20T10:00:00"},
            {"skill": "evolve-check", "products": ["C-1"], "decision_reason": "记信号",
             "at": "2026-11-21T10:00:00"},
            {"skill": "diagnose", "products": [], "decision_reason": "无演进信号",
             "at": "2026-11-19T10:00:00"},
        ]
        out = tel.aggregate(rows)
        self.assertEqual(out["total"], 3)
        self.assertEqual(out["by_skill"], {"evolve-check": 2, "diagnose": 1})
        self.assertEqual(out["evolve_check_runs"], 2)
        self.assertEqual(out["evolve_check_no_signal"], 1)
        self.assertEqual(out["first_at"], "2026-11-19T10:00:00")
        self.assertEqual(out["last_at"], "2026-11-21T10:00:00")

    def test_empty_rows(self):
        out = tel.aggregate([])
        self.assertEqual(out["total"], 0)
        self.assertIsNone(out["first_at"])
        self.assertIsNone(out["last_at"])


class LoadRecordsTest(unittest.TestCase):
    def test_missing_file_is_normal_degradation(self):
        with tempfile.TemporaryDirectory() as td:
            records, state, path, _where = tel.load_records(
                Path(td), explicit=Path(td) / "none.yaml")
            self.assertEqual((records, state), ([], "missing"))
            self.assertEqual(path, Path(td) / "none.yaml")

    def test_broken_and_empty_documents(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "log.yaml"
            path.write_text(": not yaml: [", encoding="utf-8")
            self.assertEqual(tel.load_records(Path(td), explicit=path)[1], "broken")
            path.write_text("records: []\n", encoding="utf-8")
            self.assertEqual(tel.load_records(Path(td), explicit=path)[1], "empty")
            path.write_text("records:\n- {skill: evolve-check}\n", encoding="utf-8")
            records, state, _, _ = tel.load_records(Path(td), explicit=path)
            self.assertEqual(state, "ok")
            self.assertEqual(records, [{"skill": "evolve-check"}])


if __name__ == "__main__":
    unittest.main()
