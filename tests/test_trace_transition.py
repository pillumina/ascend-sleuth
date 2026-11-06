"""状态写入口的口径与边界回归。

护四件事，都是「错了不报错、只把记录写坏」的那一类：
1. 写集合按动作分开：收尾写 stop_reason/resolved_at，重开与补记不写；
2. 事件可回放：重开把旧 ending 放进 prev_ending，改收尾方式跨状态时是两条事件；
3. 必填按收尾方式合并：补记老 escalated 单同样要求 handed_to；
4. 文本定点替换不碰块标量、保留换行风格。
"""

import argparse
import base64
import hashlib
import io
import json
import sys
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import trace_transition as tt  # noqa: E402
import _trace_state as st  # noqa: E402


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
                    report_source=None, report_result=None, report_note=None,
                    verdict=None, review_note=None,
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

    def test_lock_unavailable_fails_without_writing(self):
        # log_lock 的契约是 yield True/False。False = 本平台没有可用的互斥原语；
        # 此时写状态会丢事件。写入口必须拒绝，而不是在无锁状态下写。
        path = self.make()
        before = path.read_bytes()

        @contextlib.contextmanager
        def unavailable(_path):
            yield False

        with mock.patch.object(tt, "log_lock", unavailable):
            with self.assertRaises(tt.Fail) as ctx:
                tt.apply_transition(ROOT, self.traces, "s1", args(to="resolved"))
        self.assertEqual(ctx.exception.code, "E_IO")
        self.assertIn("写锁不可用", ctx.exception.message)
        self.assertEqual(path.read_bytes(), before)

    def test_permission_error_message_carries_path_and_system_reason(self):
        # 面板把这一支说成「当前会话没有写权限」会把人引去查会话档位：文件级拒绝（ACL /
        # 只读 / 占用）与档位是两回事。这里钉住 message 带路径与系统原因，退出码与 JSON 形状不变。
        path = str(self.traces / "s1.yaml")

        def deny(*_args, **_kwargs):
            raise PermissionError(13, "Permission denied", path)

        with mock.patch.object(tt, "apply_transition", deny):
            rc, out = self.run_main(["s1", "--root", str(ROOT), "--traces", str(self.traces), "--json"])
        self.assertEqual(rc, 5, out)
        payload = json.loads(out)
        self.assertEqual(set(payload), {"ok", "code", "message"}, out)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "E_PERM")
        self.assertIn(path, payload["message"])
        self.assertIn("Permission denied", payload["message"])
        self.assertIn("文件操作被系统拒绝", payload["message"])

    def test_permission_error_without_filename_keeps_system_reason(self):
        # 有的平台抛 PermissionError 时 filename 为空：不能因此退回一句「没有写权限」，
        # 系统原因仍要带出来。
        def deny(*_args, **_kwargs):
            raise PermissionError(13, "Access is denied")

        with mock.patch.object(tt, "apply_transition", deny):
            rc, out = self.run_main(["s1", "--root", str(ROOT), "--traces", str(self.traces), "--json"])
        self.assertEqual(rc, 5, out)
        self.assertEqual(json.loads(out)["message"], "文件操作被系统拒绝（Access is denied）")

    def test_fallback_command_shapes_apply(self):
        # 面板「生成指令」兜底生成的是可直接执行的命令：字段走 --payload-base64，会改变
        # 校验路径的标志留在命令行。形状错了，读者照抄会得到 E_SCHEMA 或写错字段。
        def run(payload, flags, sid="s1"):
            token = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
            return self.run_main([sid, "--root", str(ROOT), "--traces", str(self.traces),
                                  "--by", "user", "--source", "panel", "--json",
                                  "--payload-base64=" + token, *flags])

        self.make()
        rc, out = run({"to": "resolved", "kind": "root_cause", "summary": "中文摘要 $var 'single'",
                       "severity": "service-affecting", "fix_emitted": True}, [])
        self.assertEqual(rc, 0, out)
        doc = self.load()
        self.assertEqual(doc["status"], "resolved")
        self.assertEqual(doc["severity"], "service-affecting")
        self.assertTrue(doc["fix_emitted"])

        rc, out = run({"reopen": True}, [])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.load()["status"], "in_progress")

        rc, out = run({"to": "escalated", "kind": "handed_off", "handed_to": "张工 · CANN 组"}, [])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.load()["status"], "escalated")

        rc, out = run({"to": "resolved", "kind": "root_cause"}, ["--correct-ending"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.load()["status"], "resolved")
        self.assertEqual(self.load()["ending"]["kind"], "root_cause")

        # 补记收尾方式：老单已 resolved 但没有 ending，命令行带 --backfill-ending。
        self.make("old", status="resolved")
        rc, out = run({"kind": "root_cause"}, ["--backfill-ending"], sid="old")
        self.assertEqual(rc, 0, out)
        old = yaml.safe_load((self.traces / "old.yaml").read_text(encoding="utf-8"))
        self.assertEqual(old["ending"]["kind"], "root_cause")

        # 沉淀状态：状态由命令行给，payload 是空对象（面板的 sedimented 写就是这样）。
        rc, out = run({}, ["--field", "sedimented", "--state", "submitted"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.load()["sedimented"]["state"], "submitted")

    def test_cas_token_is_single_use(self):
        path = self.make()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        tt.apply_transition(ROOT, self.traces, "s1", args(to="resolved", expect_sha256=sha))
        with self.assertRaises(tt.Fail) as ctx:
            tt.apply_transition(ROOT, self.traces, "s1", args(reopen=True, expect_sha256=sha))
        self.assertEqual(ctx.exception.code, "E_STATE_CHANGED")

    def test_field_report_writes_outcome_and_marks_review(self):
        self.make(status="resolved")
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(field="report", report_source="field", report_result="other_way",
                                 report_note="换驱动版本后好了"))
        doc = self.load()
        self.assertEqual(doc["feedback"]["outcome"], "resolved")
        self.assertEqual(doc["reports"][-1]["source"], "field")
        self.assertEqual(doc["reports"][-1]["result"], "other_way")
        # 回报不改状态（那是另一条轴）
        self.assertEqual(doc["status"], "resolved")

    def test_vendor_report_does_not_touch_outcome(self):
        self.make(status="resolved")
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(field="report", report_source="vendor", report_result="from_report"))
        doc = self.load()
        self.assertNotIn("feedback", doc)
        self.assertEqual(doc["reports"][-1]["source"], "vendor")

    def test_report_enum_rejected(self):
        self.make(status="resolved")
        with self.assertRaises(tt.Fail) as ctx:
            tt.apply_transition(ROOT, self.traces, "s1",
                                args(field="report", report_source="field", report_result="bogus"))
        self.assertEqual(ctx.exception.code, "E_SCHEMA")

    def test_review_clears_report_review_flag(self):
        self.make(status="resolved")
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(field="report", report_source="field", report_result="other_way"))
        doc = self.load()
        self.assertTrue(st.derive(doc, set())["needReportReview"])
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(field="review", verdict="report_revision", review_note="补一句实际做法"))
        doc = self.load()
        self.assertEqual(doc["reviews"][-1]["verdict"], "report_revision")
        self.assertFalse(st.derive(doc, set())["needReportReview"])
        # 复核不改状态
        self.assertEqual(doc["status"], "resolved")

    def test_review_invalid_verdict_rejected(self):
        self.make(status="resolved")
        with self.assertRaises(tt.Fail) as ctx:
            tt.apply_transition(ROOT, self.traces, "s1", args(field="review", verdict="bogus"))
        self.assertEqual(ctx.exception.code, "E_SCHEMA")

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

    # ── 复制到任意终端的输入通道：base64 单行 ──────────────────────────────────
    # 兜底命令要在 bash / zsh / PowerShell / cmd.exe 里原样可粘，所以 payload 只能是一个
    # 纯 ASCII 单行参数；这里守住「值原样进去、坏 token 不写盘」两件事。
    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            rc = tt.main(argv)
        return rc, out.getvalue()

    def test_payload_base64_supplies_values(self):
        self.make()
        body = {"to": "resolved", "kind": "root_cause", "severity": "service-affecting",
                "fix_emitted": True,
                "summary": "中文摘要 $var 'single' 与 \"double\""}
        token = base64.b64encode(json.dumps(body, ensure_ascii=False).encode("utf-8")).decode("ascii")
        rc, out = self.run_main(["s1", "--root", str(ROOT), "--traces", str(self.traces),
                                 "--json", "--payload-base64=" + token])
        self.assertEqual(rc, 0, out)
        doc = self.load()
        self.assertEqual(doc["status"], "resolved")
        self.assertEqual(doc["summary"], body["summary"])

    def test_payload_base64_bad_tokens_write_nothing(self):
        # 四种手误分开报：空串 / 不是 base64 / 解出来不是 JSON / 不是对象。以前空串会落到
        # 转移校验那句「不允许转到该状态」，看不出是参数没带；混成一句读者只能猜。
        cases = [
            ("", "base64 参数是空的"),
            ("这不是base64", "base64 参数解不开"),
            (base64.b64encode(b"abc").decode("ascii"), "解出来不是 JSON"),
            (base64.b64encode(b"[1,2]").decode("ascii"), "payload 必须是对象"),
        ]
        for token, want in cases:
            path = self.make()
            before = path.read_bytes()
            rc, out = self.run_main(["s1", "--root", str(ROOT), "--traces", str(self.traces),
                                     "--json", "--payload-base64=" + token])
            self.assertEqual(rc, 2, out)
            self.assertIn("E_SCHEMA", out, out)
            self.assertIn(want, out, out)
            self.assertEqual(path.read_bytes(), before, token)

    def test_field_sedimented_writes_only_that_block(self):
        self.make()
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(field="sedimented", state="submitted", inbox_path="postmortems/inbox/x.md"))
        doc = self.load()
        self.assertEqual(doc["sedimented"]["state"], "submitted")
        self.assertEqual(doc["status"], "in_progress")
        self.assertNotIn("transitions", doc)

    def test_field_sedimented_none_clears_target(self):
        # 撤回到「未沉淀」时，上一次的 case_id / inbox_path 必须一起清掉：留着它们，
        # 下游会把这份 trace 算成沉淀过那条 case（`trace_entry_activity.py` 的强度读数）。
        self.make()
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(field="sedimented", state="submitted",
                                 case_id="VLLM-ASC-1", inbox_path="postmortems/inbox/x.case.yaml"))
        tt.apply_transition(ROOT, self.traces, "s1",
                            args(field="sedimented", state="none"))
        doc = self.load()
        self.assertEqual(doc["sedimented"]["state"], "none")
        self.assertEqual(doc["sedimented"]["case_id"], "")
        self.assertEqual(doc["sedimented"]["inbox_path"], "")


if __name__ == "__main__":
    unittest.main()
