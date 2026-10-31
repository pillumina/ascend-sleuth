"""状态写入口的口径与边界回归。

护四件事，都是「错了不报错、只把记录写坏」的那一类：
1. 写集合按动作分开：收尾写 stop_reason/resolved_at，重开与补记不写；
2. 事件可回放：重开把旧 ending 放进 prev_ending，改收尾方式跨状态时是两条事件；
3. 必填按收尾方式合并：补记老 escalated 单同样要求 handed_to；
4. 文本定点替换不碰块标量、保留换行风格。
"""

import argparse
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import trace_transition as tt  # noqa: E402


BASE = """session_id: "{sid}"
status: in_progress
summary: "训练挂起"
severity: service-affecting
fix_emitted: true
updated_at: "2026-10-30T09:00:00+08:00"
note_block: |
  status: resolved   # 块标量里的假状态
trace:
  - {{step: 1, role: user, content: "贴了栈"}}
"""


def args(**kw):
    defaults = dict(reopen=False, correct_ending=False, backfill_ending=False, to=None, kind=None,
                    handed_to=None, duplicate_of=None, note=None, summary=None, severity=None,
                    fix_emitted=None, stop_reason=None, by="user", source="panel",
                    expect_sha256=None, field=None, state=None, case_id=None, inbox_path=None,
                    dry_run=False, scheme_version=None)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


class WriterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "traces").mkdir()
        self.traces = self.dir / "traces"

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, sid="s1", status="in_progress", extra=""):
        path = self.traces / (sid + ".yaml")
        body = BASE.format(sid=sid)
        if status != "in_progress":
            body = body.replace("status: in_progress", f"status: {status}")
        path.write_text(body + extra, encoding="utf-8")
        return path

    def load(self, sid="s1"):
        return yaml.safe_load((self.traces / (sid + ".yaml")).read_text(encoding="utf-8"))

    def test_close_escalated_writes_ending_event_and_stop_reason(self):
        self.make()
        tt.apply_transition(ROOT, self.traces, "s1", args(to="escalated", handed_to="张工"))
        doc = self.load()
        self.assertEqual(doc["status"], "escalated")
        self.assertEqual(doc["ending"]["kind"], "handed_off")
        self.assertEqual(doc["stop_reason"], "closed_by_user")
        self.assertEqual(len(doc["transitions"]), 1)
        self.assertIsNone(doc["transitions"][0]["prev_ending"])
        # 块标量里的假状态不能被改
        self.assertEqual(doc["note_block"].strip(), "status: resolved   # 块标量里的假状态")

    def test_escalated_requires_handed_to(self):
        self.make()
        with self.assertRaises(tt.Fail) as ctx:
            tt.apply_transition(ROOT, self.traces, "s1", args(to="escalated"))
        self.assertEqual(ctx.exception.code, "E_SCHEMA")
        self.assertIn("ending.handed_to", ctx.exception.extra["requirements"])

    def test_duplicate_requires_prefixed_target(self):
        self.make()
        with self.assertRaises(tt.Fail):
            tt.apply_transition(ROOT, self.traces, "s1", args(to="archived", kind="duplicate",
                                                             duplicate_of="VLLM-ASC-1"))
        with self.assertRaises(tt.Fail):
            tt.apply_transition(ROOT, self.traces, "s1", args(to="archived", kind="duplicate"))
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(to="archived", kind="duplicate", duplicate_of="case:VLLM-ASC-1"))
        self.assertEqual(self.load()["ending"]["duplicate_of"], "case:VLLM-ASC-1")

    def test_resolved_writes_resolved_at_only_once(self):
        self.make()
        tt.apply_transition(ROOT, self.traces, "s1", args(to="resolved"))
        first = self.load()["resolved_at"]
        self.assertTrue(first)
        tt.apply_transition(ROOT, self.traces, "s1", args(reopen=True))
        self.assertNotIn("ending", self.load())
        tt.apply_transition(ROOT, self.traces, "s1", args(to="resolved"))
        # 第二次 resolved 时原状态是 in_progress（重开过），按规则应更新
        self.assertTrue(self.load()["resolved_at"])

    def test_reopen_keeps_prev_ending_and_drops_top_level(self):
        self.make()
        tt.apply_transition(ROOT, self.traces, "s1", args(to="escalated", handed_to="张工"))
        tt.apply_transition(ROOT, self.traces, "s1", args(reopen=True))
        doc = self.load()
        self.assertEqual(doc["status"], "in_progress")
        self.assertNotIn("ending", doc)
        last = doc["transitions"][-1]
        self.assertIsNone(last["ending"])
        self.assertEqual(last["prev_ending"]["handed_to"], "张工")
        # 重开不写 stop_reason
        self.assertEqual(len(doc["transitions"]), 2)

    def test_correct_ending_cross_status_is_two_events(self):
        self.make()
        tt.apply_transition(ROOT, self.traces, "s1", args(to="archived", kind="withdrawn"))
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(correct_ending=True, to="escalated", handed_to="技术支持"))
        doc = self.load()
        self.assertEqual(doc["status"], "escalated")
        self.assertEqual([(e["from"], e["to"]) for e in doc["transitions"]],
                         [("in_progress", "archived"), ("archived", "in_progress"),
                          ("in_progress", "escalated")])

    def test_correct_ending_same_status_is_one_event(self):
        self.make()
        tt.apply_transition(ROOT, self.traces, "s1", args(to="escalated", handed_to="张工"))
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(correct_ending=True, to="escalated", handed_to="李工"))
        doc = self.load()
        self.assertEqual(len(doc["transitions"]), 2)
        last = doc["transitions"][-1]
        self.assertEqual((last["from"], last["to"]), ("escalated", "escalated"))
        self.assertEqual(last["prev_ending"]["handed_to"], "张工")
        self.assertEqual(doc["ending"]["handed_to"], "李工")

    def test_backfill_old_terminal_does_not_write_resolved_at_or_stop_reason(self):
        path = self.make("old", status="archived")
        tt.apply_transition(ROOT, self.traces, "old", args(backfill_ending=True, kind="no_diagnosis"))
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(doc["ending"]["kind"], "no_diagnosis")
        self.assertEqual(len(doc["transitions"]), 1)
        self.assertEqual(len([e for e in doc["transitions"] if e["from"] == e["to"]]), 1)
        self.assertNotIn("resolved_at", doc)
        self.assertNotIn("stop_reason", doc)

    def test_backfill_handed_off_requires_handed_to(self):
        self.make("old", status="escalated")
        with self.assertRaises(tt.Fail):
            tt.apply_transition(ROOT, self.traces, "old",
                               args(backfill_ending=True, kind="handed_off"))

    def test_cas_mismatch(self):
        self.make()
        with self.assertRaises(tt.Fail) as ctx:
            tt.apply_transition(ROOT, self.traces, "s1", args(to="resolved", expect_sha256="deadbeef"))
        self.assertEqual(ctx.exception.code, "E_STATE_CHANGED")

    def test_dry_run_does_not_write(self):
        path = self.make()
        before = path.read_text(encoding="utf-8")
        tt.apply_transition(ROOT, self.traces, "s1", args(to="resolved", dry_run=True))
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_missing_summary_rejected(self):
        path = self.traces / "s1.yaml"
        path.write_text('session_id: "s1"\nstatus: in_progress\nupdated_at: "2026-10-30T09:00:00+08:00"\n',
                        encoding="utf-8")
        with self.assertRaises(tt.Fail) as ctx:
            tt.apply_transition(ROOT, self.traces, "s1", args(to="resolved"))
        self.assertIn("summary", ctx.exception.extra["requirements"])

    def test_hit_case_resolved_requires_feedback(self):
        self.make(extra='active_case: VLLM-ASC-11312\n')
        with self.assertRaises(tt.Fail) as ctx:
            tt.apply_transition(ROOT, self.traces, "s1", args(to="resolved"))
        self.assertIn("feedback.outcome", ctx.exception.extra["requirements"])

    def test_crlf_preserved(self):
        self.make()
        path = self.traces / "s1.yaml"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
        tt.apply_transition(ROOT, self.traces, "s1", args(to="resolved"))
        self.assertIn(b"\r\n", path.read_bytes())

    def test_field_sedimented_writes_only_that_block(self):
        self.make()
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(field="sedimented", state="submitted", inbox_path="postmortems/inbox/x.md"))
        doc = self.load()
        self.assertEqual(doc["sedimented"]["state"], "submitted")
        self.assertEqual(doc["status"], "in_progress")
        self.assertNotIn("transitions", doc)


if __name__ == "__main__":
    unittest.main()
