"""条目使用记录的格式与聚合口径回归。

护三件事，它们的失效形态都是**静默**的：
  ① 一行一条且能解析回来——源文件配了 `merge=union`（行级合并），一旦写成多行，
     两人同周各追加一次就会拼出非法 YAML，而那时文件已经合进 main 了；
  ② 搬运行只进 `totals`、不进 `by_week` 与本期增量——它载的是生命周期累计值，
     混进增量会把排行与「长期零选中」一起污染；
  ③ `last_hit` 由最近一次 resolved / misdiagnosed 运行所处的周推出，**自证的那次不算**
     （自证不是独立命中，与结算脚本同一口径）。
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import entry_activity as ea  # noqa: E402


def case_row(**kw):
    row = {"run": "2026-10-16-0920", "deployment": "d1", "checkout": "abc", "kb_rev": "abc",
           "sessions": 1, "kind": "case", "id": "CASE-1",
           "selected": 0, "loaded": 0, "resolved": 0, "misdiagnosed": 0,
           "self_resolved": 0, "excluded": 0}
    row.update(kw)
    return row


def baseline_row(**kw):
    row = {"run": "baseline-2026-10-18", "deployment": "d1", "kind": "baseline", "id": "CASE-1",
           "resolved": 0, "misdiagnosed": 0, "self_resolved": 0}
    row.update(kw)
    return row


class RowRoundTripTest(unittest.TestCase):
    """一行一条：写成一行、能解回来、键序稳定。"""

    def test_row_is_one_line_and_parses_back(self):
        text = ea.format_row(case_row(selected=3, loaded=2, resolved=1))
        self.assertEqual(len(text.splitlines()), 1, "一条记录必须写在一行里（union 是行级合并）")
        back = ea.parse_row(text)
        self.assertEqual(back["id"], "CASE-1")
        self.assertEqual(back["selected"], 3)
        self.assertEqual(back["run"], "2026-10-16-0920")

    def test_values_with_colon_and_hash_are_quoted(self):
        row = baseline_row(note="搬自 confidence 块，2026-10-18: 已核 #123")
        back = ea.parse_row(ea.format_row(row))
        self.assertEqual(back["note"], row["note"], "含 `: ` 或 ` #` 的值不加引号会被静默截断")

    def test_purpose_only_writes_nonzero_entries(self):
        row = {"run": "2026-10-16-0920", "deployment": "d1", "checkout": "abc", "kb_rev": "abc",
               "sessions": 1, "kind": "ref", "id": "ref-a", "lookups": 3, "hit": 2, "miss": 1,
               "skipped": 0, "purpose": {"signature": 2, "background": 0, "fix": 1}}
        back = ea.parse_row(ea.format_row(row))
        self.assertEqual(back["purpose"], {"signature": 2, "fix": 1})

    def test_shape_check_requires_every_count_key(self):
        bad = case_row()
        del bad["loaded"]
        problems = ea.check_row_shape(bad)
        self.assertTrue(any("缺计数键" in p for p in problems), problems)

    def test_shape_check_rejects_unknown_keys(self):
        problems = ea.check_row_shape(case_row(oops=1))
        self.assertTrue(any("不该有键" in p for p in problems), problems)

    def test_run_shape_is_enforced(self):
        self.assertTrue(ea.check_row_shape(case_row(run="2026-10-16")))
        self.assertFalse([p for p in ea.check_row_shape(case_row(run="2026-10-16-0920")) if "run" in p])


class WeekTest(unittest.TestCase):
    def test_run_week(self):
        self.assertEqual(ea.week_of_run("2026-10-16-0920"), ea.iso_week(
            __import__("datetime").date(2026, 10, 16)))

    def test_baseline_run_week(self):
        self.assertEqual(ea.week_of_run("baseline-2026-10-18"), ea.iso_week(
            __import__("datetime").date(2026, 10, 18)))

    def test_last_hit_value_normalisation(self):
        self.assertEqual(ea.week_of_value("2026-W39"), "2026-W39")
        self.assertEqual(ea.week_of_value("2026-09-16"), ea.iso_week(
            __import__("datetime").date(2026, 9, 16)))
        self.assertIsNone(ea.week_of_value("下周三"), "认不出来就给 None，不猜一个周")


class AggregateTest(unittest.TestCase):
    def agg(self, rows, cases=10, refs=()):
        return ea.aggregate(rows, "d1", cases, list(refs))

    def test_counts_sum_across_runs_and_weeks(self):
        rows = [case_row(selected=3, loaded=2), case_row(run="2026-10-17-1005", selected=2, loaded=1)]
        doc = self.agg(rows)
        self.assertEqual(doc["cases"]["CASE-1"]["totals"]["selected"], 5)
        self.assertEqual(sorted(doc["cases"]["CASE-1"]["by_week"]), sorted(
            {ea.week_of_run("2026-10-16-0920"), ea.week_of_run("2026-10-17-1005")}))

    def test_baseline_enters_totals_only(self):
        rows = [baseline_row(resolved=4, misdiagnosed=1, last_hit="2026-W39")]
        doc = self.agg(rows)
        e = doc["cases"]["CASE-1"]
        self.assertEqual(e["totals"]["resolved"], 4)
        self.assertIs(e["totals"]["baseline"], True)
        self.assertEqual(e["by_week"], {}, "搬运行不计入本期增量")
        self.assertEqual(e["last_hit"], "2026-W39", "搬运行自带的 last_hit 透传")

    def test_cold_counts_only_non_baseline_covered_cases(self):
        doc = self.agg([baseline_row(resolved=1), case_row()], cases=10)
        self.assertEqual(doc["cold"]["cases"], 9, "只有非 baseline 行覆盖的条目才算有活动")

    def test_last_hit_from_latest_outcome_run_not_self_report(self):
        rows = [case_row(run="2026-10-16-0920", resolved=1),
                case_row(run="2026-10-17-1005", self_resolved=1)]
        e = self.agg(rows)["cases"]["CASE-1"]
        self.assertEqual(e["last_hit"], ea.week_of_run("2026-10-16-0920"),
                         "自证的那次解决不计入「最后」")

    def test_last_hit_is_independent_of_row_order(self):
        """同一个 id 既有本期 resolved 又有搬运行时，「最后」取更近的那一周，与行序无关。"""
        case = case_row(run="2026-10-17-1005", resolved=1)
        base = baseline_row(run="baseline-2026-10-18", resolved=1, last_hit="2026-W35")
        a = self.agg([case, base])["cases"]["CASE-1"]["last_hit"]
        b = self.agg([base, case])["cases"]["CASE-1"]["last_hit"]
        self.assertEqual(a, b, "两种行序必须得同一个答案")
        self.assertEqual(a, ea.week_of_run("2026-10-17-1005"), "取更近的那一周")

    def test_other_deployments_are_not_merged(self):
        doc = self.agg([case_row(), case_row(deployment="d2", selected=9)])
        self.assertEqual(doc["cases"]["CASE-1"]["totals"]["selected"], 0)
        self.assertEqual(doc["covered"]["deployment"], "d1")

    def test_tool_percentile_is_call_weighted(self):
        rows = [
            {"run": "2026-10-16-0920", "deployment": "d1", "checkout": "a", "kb_rev": "a",
             "kind": "tool", "id": "read", "calls": 9, "p50_ms": 100, "p90_ms": 200,
             "errors": 0, "timeouts": 0},
            {"run": "2026-10-17-1005", "deployment": "d1", "checkout": "a", "kb_rev": "a",
             "kind": "tool", "id": "read", "calls": 1, "p50_ms": 9000, "p90_ms": 9000,
             "errors": 1, "timeouts": 0},
        ]
        t = self.agg(rows)["tools"]["read"]
        self.assertEqual(t["calls"], 10)
        self.assertEqual(t["errors"], 1)
        self.assertEqual(t["p50_ms"], 990, "跨运行的分位按调用次数加权，不给假装精确的数")

    def test_cold_never_looked_up_lists_library_refs(self):
        doc = self.agg([case_row()], refs=["ref-a", "ref-b"])
        self.assertEqual(doc["cold_never_looked_up"], ["ref-a", "ref-b"])
        doc2 = self.agg([case_row(), {"run": "2026-10-16-0920", "deployment": "d1", "checkout": "a",
                                      "kb_rev": "a", "sessions": 1, "kind": "ref", "id": "ref-a",
                                      "lookups": 1, "hit": 1, "miss": 0, "skipped": 0}],
                        refs=["ref-a", "ref-b"])
        self.assertEqual(doc2["cold_never_looked_up"], ["ref-b"])


class RenderAndSourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_append_creates_header_then_appends_without_rewriting(self):
        f = ea.append_rows(self.root, "2026-W42", [case_row()])
        first = f.read_text(encoding="utf-8")
        ea.append_rows(self.root, "2026-W42", [case_row(id="CASE-2", run="2026-10-17-1005")])
        second = f.read_text(encoding="utf-8")
        self.assertTrue(second.startswith(first.rstrip("\n")), "追加不得改写已经写下的行")
        rows, problems = ea.read_source(self.root)
        self.assertEqual(problems, [])
        self.assertEqual([r["id"] for r in rows], ["CASE-1", "CASE-2"])
        self.assertTrue(all(r["_week"] == "2026-W42" for r in rows))

    def test_generated_file_is_byte_stable(self):
        rows = [case_row(selected=1), baseline_row(resolved=2)]
        doc = ea.aggregate(rows, "d1", 10, [])
        self.assertEqual(ea.render(doc), ea.render(doc))

    def test_render_has_no_generated_date(self):
        doc = ea.aggregate([case_row()], "d1", 10, [])
        head = ea.render(doc).split("covered:")[0]
        self.assertNotRegex(head, r"\d{4}-\d{2}-\d{2}", "生成物头注不写日期（会随每次重建变）")


if __name__ == "__main__":
    unittest.main()
