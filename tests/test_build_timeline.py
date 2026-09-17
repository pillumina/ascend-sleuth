"""build_timeline 的口径回归测试。

`metrics/timeline.yaml` 是生成物，读侧（面板、周批、结算）只读它。源/生成物这层
就是为"两个人各 append 一期不互相覆盖"而设的（build_timeline.py 头注）。这里护三件事：
期号与文件名一致、期号唯一、排序稳定；以及冲突标记要报得让人知道下一步做什么。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_timeline as bt  # noqa: E402

PERIOD_TMPL = """period: {period}
kind: live
title: "{title}"
recorded_at: {date}
source: unit-test
metrics:
  sessions_total: {n}
"""


class BuildTimelineTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "metrics" / "timeline.d").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_period(self, name, period=None, date="2026-09-01", n=1, title="t"):
        p = self.root / "metrics" / "timeline.d" / f"{name}.yaml"
        p.write_text(PERIOD_TMPL.format(period=period or name, date=date, n=n, title=title),
                     encoding="utf-8")
        return p

    def test_missing_source_dir_is_reported_not_faked(self):
        """源目录不存在 → 空结果 + 如实说明（不假装有数据）。"""
        empty = Path(self.tmp.name) / "nope"
        periods, errors = bt.collect_sources(empty)
        self.assertEqual(periods, [])
        self.assertTrue(errors and "源目录不存在" in errors[0])

    def test_period_must_match_filename(self):
        """期号即文件名——不一致会让"重跑一次"变成"两期同名不同数"。"""
        self.write_period("2026-W36", period="2026-W37")
        _, errors = bt.collect_sources(self.root)
        self.assertTrue(any("与文件名不一致" in e for e in errors))

    def test_duplicate_period_is_reported(self):
        self.write_period("2026-W36", period="2026-W36")
        self.write_period("2026-W36-2", period="2026-W36")
        _, errors = bt.collect_sources(self.root)
        self.assertTrue(any("重复" in e for e in errors))

    def test_sorted_ascending_by_recorded_at(self):
        """升序（旧在前）：与既有文件的历史顺序一致，人读趋势不用倒着看。"""
        self.write_period("2026-W37", date="2026-09-10", n=3)
        self.write_period("2026-W36", date="2026-09-03", n=1)
        self.write_period("2026-W36b", period="2026-W36b", date="2026-08-27", n=2)
        periods, errors = bt.collect_sources(self.root)
        self.assertEqual(errors, [])
        self.assertEqual([p["period"] for p in periods], ["2026-W36b", "2026-W36", "2026-W37"])
        self.assertEqual([p["metrics"]["sessions_total"] for p in periods], [2, 1, 3])

    def test_conflict_marked_file_is_skipped_with_actionable_error(self):
        """两个人写了同一期号 → git 冲突标记进源文件；报错必须说下一步做什么。"""
        p = self.write_period("2026-W36")
        p.write_text("<<<<<<< HEAD\n" + p.read_text(encoding="utf-8") + "=======\n"
                     + PERIOD_TMPL.format(period="2026-W36", date="2026-09-03", n=9, title="x")
                     + ">>>>>>> other\n", encoding="utf-8")
        periods, errors = bt.collect_sources(self.root)
        self.assertEqual(periods, [])
        self.assertTrue(any("冲突标记" in e for e in errors))
        self.assertTrue(any("加后缀" in e for e in errors))   # 报错带下一步

    def test_render_contains_header_and_all_periods(self):
        self.write_period("2026-W36", date="2026-09-03", n=1)
        self.write_period("2026-W37", date="2026-09-10", n=2)
        periods, _ = bt.collect_sources(self.root)
        text = bt.render(periods)
        self.assertIn("GENERATED", text)
        self.assertIn("2026-W36", text)
        self.assertIn("2026-W37", text)

    def test_conflict_marker_detection(self):
        self.assertTrue(bt.conflict_marked("a\n<<<<<<< HEAD\nb"))
        self.assertFalse(bt.conflict_marked("a: 1\nb: 2\n"))


if __name__ == "__main__":
    unittest.main()
