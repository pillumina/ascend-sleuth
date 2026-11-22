"""sediment_batch 的口径回归测试。

护三件事，都是"错了不会报错、只会让人多干一遍"的那一类：

1. **「可沉淀」只认已有事实**：终态、报告、候选——任一即可；只有终态但没有素材的不进批量
   （让 agent 去读十几单的原始事件再起草，成本比它省下的还高）。
2. **分组不按名字前缀硬合**：同一 issue 的两条 session 合成一组（`2026-08-30-10521-el0008`
   与 `...-evidence-demo`），而名字里没有 issue 号的（`2026-09-21-upstream-...-sweep`）各自成组——
   按前缀合会把不相关的问题并到一起，起草时就会把两份结论搅成一份。
3. **回写只动 sedimented 那一处**：trace 是带注释与块标量的 YAML，整份 dump 会毁掉现场；
   三种写法（单行映射 / 块 / 缺失）都要改对，改完还得能解析回来。
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sediment_batch as sb  # noqa: E402


def write_trace(d: Path, sid: str, body: str) -> Path:
    p = d / (sid + ".yaml")
    p.write_text(body, encoding="utf-8")
    return p


BASE = """session_id: {sid}
status: {status}
updated_at: '{upd}'
active_case: {active}
{report}sedimented: {sed}
"""


class GroupKeyTest(unittest.TestCase):
    def test_same_issue_number_groups(self):
        a = sb.group_key({"active_case": None}, "2026-08-30-10521-el0008")
        b = sb.group_key({"active_case": None}, "2026-08-30-10521-evidence-demo")
        self.assertEqual(a, b)

    def test_numeric_after_prefix_still_groups(self):
        a = sb.group_key({"active_case": None}, "2026-08-31-msllm-1655-gemma2-hf")
        b = sb.group_key({"active_case": None}, "2026-08-31-msllm-1780-fsdp2-resume-log")
        self.assertNotEqual(a, b, "不同 issue 号不能被并成一组")

    def test_no_issue_number_stays_alone(self):
        a = sb.group_key({"active_case": None}, "2026-09-21-upstream-vllm-ascend-sweep")
        self.assertEqual(a, "session:2026-09-21-upstream-vllm-ascend-sweep")

    def test_same_active_case_groups(self):
        a = sb.group_key({"active_case": "VLLM-ASC-12430"}, "2026-09-16-12430-a")
        b = sb.group_key({"active_case": "VLLM-ASC-12430"}, "2026-04-01-999-b")
        self.assertEqual(a, b)

    def test_placeholder_case_is_not_a_key(self):
        a = sb.group_key({"active_case": "pending-investigation"}, "2026-10-18-18178-x")
        self.assertFalse(a.startswith("case:"))


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_report_or_candidates_make_it_actionable(self):
        write_trace(self.d, "2026-10-01-111-a", BASE.format(
            sid="2026-10-01-111-a", status="in_progress", upd="2026-10-01T10:00",
            active="null", report="report_file: 2026-10-01-111-a.report.md\n", sed="none\n"))
        rows, bad = sb.collect(self.d)
        self.assertEqual(bad, [])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["actionable"])
        self.assertIn("有报告", rows[0]["why"])

    def test_terminal_without_material_is_not_actionable(self):
        write_trace(self.d, "2026-10-01-222-b", BASE.format(
            sid="2026-10-01-222-b", status="escalated", upd="2026-10-01T10:00",
            active="null", report="", sed="none\n"))
        rows, _ = sb.collect(self.d)
        self.assertFalse(rows[0]["actionable"])
        self.assertIn("已收尾", rows[0]["why"])

    def test_all_reference_candidates_produced_is_not_actionable(self):
        write_trace(self.d, "2026-10-01-555-e", BASE.format(
            sid="2026-10-01-555-e", status="resolved", upd="2026-10-01T10:00",
            active="null", report="report_file: r.md\n", sed="none\n")
            + "sediment_candidates:\n"
              "  - {kind: reference, summary: x, status: produced, ref_id: ref-x}\n"
              "  - {kind: reference, summary: y, status: produced, ref_id: ref-y}\n")
        rows, _ = sb.collect(self.d)
        self.assertFalse(rows[0]["actionable"])
        self.assertEqual(rows[0]["producedRefs"], ["ref-x", "ref-y"])
        self.assertIn("已产出先验词条 2 条", rows[0]["why"])

    def test_mixed_produced_and_pending_is_still_actionable(self):
        write_trace(self.d, "2026-10-01-666-f", BASE.format(
            sid="2026-10-01-666-f", status="resolved", upd="2026-10-01T10:00",
            active="null", report="report_file: r.md\n", sed="none\n")
            + "sediment_candidates:\n"
              "  - {kind: reference, summary: x, status: produced, ref_id: ref-x}\n"
              "  - {kind: reference, summary: y, status: proposed}\n")
        rows, _ = sb.collect(self.d)
        self.assertTrue(rows[0]["actionable"])
        self.assertEqual(rows[0]["producedRefs"], ["ref-x"])

    def test_group_with_report_only_session_stays_actionable(self):
        # 同一 issue 的两条 session：777-a 只产出了先验词条，777-b 只有报告。
        # 777-b 还没沉淀，整组不能因为 777-a 产出了词条就进「已产出」。
        write_trace(self.d, "2026-10-01-777-a", BASE.format(
            sid="2026-10-01-777-a", status="resolved", upd="2026-10-01T10:00",
            active="null", report="report_file: a.md\n", sed="none\n")
            + "sediment_candidates:\n"
              "  - {kind: reference, summary: x, status: produced, ref_id: ref-x}\n")
        write_trace(self.d, "2026-10-01-777-b", BASE.format(
            sid="2026-10-01-777-b", status="resolved", upd="2026-10-01T11:00",
            active="null", report="report_file: b.md\n", sed="none\n"))
        rows, _ = sb.collect(self.d)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["actionable"], "同组还有只有报告的 session，不能判已沉淀")
        self.assertEqual(rows[0]["producedRefs"], ["ref-x"])

    def test_already_sedimented_is_skipped(self):
        write_trace(self.d, "2026-10-01-333-c", BASE.format(
            sid="2026-10-01-333-c", status="resolved", upd="2026-10-01T10:00",
            active="null", report="report_file: r.md\n", sed="{state: submitted}\n"))
        rows, _ = sb.collect(self.d)
        self.assertFalse(rows[0]["actionable"])
        self.assertIn("submitted", rows[0]["sedimented"])

    def test_unreadable_trace_is_reported_not_dropped(self):
        write_trace(self.d, "2026-10-01-444-d", "status: [unclosed\n")
        rows, bad = sb.collect(self.d)
        self.assertEqual(rows, [])
        self.assertEqual(bad, ["2026-10-01-444-d"])


class RewriteSedimentedTest(unittest.TestCase):
    def test_single_line_form(self):
        text = 'session_id: x\nsedimented: {state: knowledge, caseId: "VLLM-ASC-1"}\nstatus: resolved\n'
        new, changed = sb.rewrite_sedimented(text, "postmortems/inbox/x.case.yaml")
        self.assertTrue(changed)
        doc = __import__("yaml").safe_load(new)
        self.assertEqual(doc["sedimented"]["state"], "submitted")
        self.assertEqual(doc["sedimented"]["inboxPath"], "postmortems/inbox/x.case.yaml")
        self.assertEqual(doc["status"], "resolved", "回写不许碰别的顶层字段")

    def test_block_form_only_touches_state_line(self):
        text = ("session_id: x\n"
                "sedimented:\n"
                "  state: none\n"
                "  case_id: \"\"\n"
                "feedback:\n  outcome: pending\n")
        new, changed = sb.rewrite_sedimented(text, "")
        self.assertTrue(changed)
        doc = __import__("yaml").safe_load(new)
        self.assertEqual(doc["sedimented"]["state"], "submitted")
        self.assertEqual(doc["sedimented"]["case_id"], "", "块里其余键要留着")
        self.assertEqual(doc["feedback"]["outcome"], "pending")

    def test_absent_key_is_appended(self):
        text = "session_id: x\nstatus: resolved\n"
        new, changed = sb.rewrite_sedimented(text, "")
        self.assertTrue(changed)
        doc = __import__("yaml").safe_load(new)
        self.assertEqual(doc["sedimented"]["state"], "submitted")

    def test_comments_and_block_scalars_survive(self):
        text = ("# 头注释\nsession_id: x\nsummary: >\n  多行结论\n"
                "sedimented: {state: none}\n")
        new, _ = sb.rewrite_sedimented(text, "")
        self.assertIn("# 头注释", new)
        self.assertIn("summary: >", new)

    def test_mark_submitted_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            p = write_trace(d, "2026-10-01-555-e", BASE.format(
                sid="2026-10-01-555-e", status="resolved", upd="2026-10-01T10:00",
                active="null", report="", sed="none\n"))
            before = p.read_text(encoding="utf-8")
            written, skipped, failed = sb.mark_submitted(d, ["2026-10-01-555-e"], "", apply=False)
            self.assertEqual((written, skipped, failed), (["2026-10-01-555-e"], [], []))
            self.assertEqual(p.read_text(encoding="utf-8"), before, "dry-run 不许写盘")

    def test_mark_submitted_apply_writes_and_parses(self):
        import yaml
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            p = write_trace(d, "2026-10-01-666-f", BASE.format(
                sid="2026-10-01-666-f", status="resolved", upd="2026-10-01T10:00",
                active="null", report="", sed="none\n"))
            written, _, failed = sb.mark_submitted(d, ["2026-10-01-666-f"], "postmortems/inbox/a.yaml", apply=True)
            self.assertEqual(failed, [])
            self.assertEqual(written, ["2026-10-01-666-f"])
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
            self.assertEqual(doc["sedimented"]["state"], "submitted")

    def test_missing_session_is_failure_not_silence(self):
        with tempfile.TemporaryDirectory() as t:
            _, _, failed = sb.mark_submitted(Path(t), ["nope"], "", apply=False)
            self.assertEqual(len(failed), 1)


if __name__ == "__main__":
    unittest.main()
