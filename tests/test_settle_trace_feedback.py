"""settle_trace_feedback 的口径回归测试。

护的是学习环的核心口径：**只有 feedback.resolved 计 resolved**；来源 session 自己的
resolve 记 self_resolved、**不计入 resolved**（同一份证据不能数两次）；not_resolved /
partial 计 misdiagnosed；同一 session 同序列只结算一次（幂等）；dry-run 不写盘。

**写哪里也是口径的一部分**：这些计数写进 `metrics/entry-activity.d/<周>.yaml` 的
`kind: case` 行，**不再写回案例文件**（案例里已没有 `confidence` 块）。写错地方不会报错——
它只是让计数落在一个没人读的字段上，而读数看起来一切正常。
"""

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import entry_activity as ea  # noqa: E402
import settle_trace_feedback as stf  # noqa: E402

CASE_TMPL = """cases:
  - id: {cid}
    title: "结算测试"
    category: interrupt
{extra}    investigation_quality: medium
    root_cause: x
    fix: y
"""

TRACE_TMPL = """session_id: {sid}
status: {status}
trace:
  - role: agent
    action: triage
    namespace: {ns}
  - role: agent
    action: hit
    case: {cid}
  - role: agent
    action: feedback
    case: {cid}
    outcome: {outcome}
"""

RUN = "2026-10-16-0920"


class SettleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.kb = self.root / "knowledge"
        self.traces = self.root / "traces"
        self.kb.mkdir()
        self.traces.mkdir()
        self.state = self.root / ".settle-state.json"
        self._env = os.environ.get("ASCEND_SLEUTH_DEPLOYMENT")
        os.environ["ASCEND_SLEUTH_DEPLOYMENT"] = "test-dep"
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._env is None:
            os.environ.pop("ASCEND_SLEUTH_DEPLOYMENT", None)
        else:
            os.environ["ASCEND_SLEUTH_DEPLOYMENT"] = self._env

    def write_case(self, cid="SETTLE-1", source_session=None):
        extra = f"    source_session: {source_session}\n" if source_session else ""
        p = self.kb / "inference" / "vllm-ascend" / "interrupt" / f"{cid}.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CASE_TMPL.format(cid=cid, extra=extra), encoding="utf-8")
        return p

    def write_trace(self, sid, cid="SETTLE-1", outcome="resolved", status="resolved",
                    ns="inference/vllm-ascend"):
        (self.traces / f"{sid}.yaml").write_text(
            TRACE_TMPL.format(sid=sid, cid=cid, outcome=outcome, status=status, ns=ns),
            encoding="utf-8")

    def rows(self):
        """记录源文件里的全部行（按文件名归周）。"""
        return ea.read_source(self.root)[0]

    def counts(self, cid):
        """某个 case 在记录里的计数之和。"""
        out = {"resolved": 0, "misdiagnosed": 0, "self_resolved": 0}
        for r in self.rows():
            if r.get("kind") == "case" and r.get("id") == cid:
                for k in out:
                    out[k] += int(r.get(k, 0) or 0)
        return out

    def run_settle(self, apply=False):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = stf.settle(self.traces, self.state, apply, self.root,
                              kb_root=self.kb, run=RUN)
        self.assertIn(code, (0, 2))
        return buf.getvalue()

    # ---------------------------------------------------------------- 正/负信号
    def test_resolved_from_consumer_counts_resolved(self):
        self.write_case()
        self.write_trace("2026-09-16-10000-consumer")
        self.run_settle(apply=True)
        self.assertEqual(self.counts("SETTLE-1")["resolved"], 1)
        self.assertEqual(self.counts("SETTLE-1")["misdiagnosed"], 0)

    def test_not_resolved_counts_misdiagnosed(self):
        self.write_case()
        self.write_trace("2026-09-16-10001-consumer", outcome="not_resolved")
        self.run_settle(apply=True)
        self.assertEqual(self.counts("SETTLE-1")["misdiagnosed"], 1)

    def test_partial_counts_misdiagnosed(self):
        self.write_case()
        self.write_trace("2026-09-16-10002-consumer", outcome="partial")
        self.run_settle(apply=True)
        self.assertEqual(self.counts("SETTLE-1")["misdiagnosed"], 1)

    # ---------------------------------------------------------------- 自证口径
    def test_source_session_self_resolved_does_not_touch_resolved(self):
        """来源 session 自己的 resolve = 自证：记 self_resolved，resolved 保持不动。"""
        self.write_case(source_session="2026-09-16-10003-author")
        self.write_trace("2026-09-16-10003-author")
        self.run_settle(apply=True)
        c = self.counts("SETTLE-1")
        self.assertEqual(c["resolved"], 0, "自证不得计入独立解决的计数（同一证据不数两次）")
        self.assertEqual(c["self_resolved"], 1)

    def test_consumer_resolved_on_authored_case_still_counts_resolved(self):
        """同一条 case 被别人消费并 resolve → 仍计 resolved（自证只挡产地那一次）。"""
        self.write_case(source_session="2026-09-16-10004-author")
        self.write_trace("2026-09-16-10005-other")
        self.run_settle(apply=True)
        c = self.counts("SETTLE-1")
        self.assertEqual(c["resolved"], 1)
        self.assertEqual(c["self_resolved"], 0)

    def test_case_file_is_not_touched(self):
        """结算不再改知识条目：案例文件在结算前后逐字节相同。"""
        p = self.write_case()
        before = p.read_text(encoding="utf-8")
        self.write_trace("2026-09-16-10030-consumer")
        self.run_settle(apply=True)
        self.assertEqual(p.read_text(encoding="utf-8"), before,
                         "计数写进使用记录，不写回案例")

    def test_row_carries_the_full_case_key_set(self):
        """行必须带齐 case 的全部计数键（含 0）：缺键会被读成「这轮没记」而不是 0。"""
        self.write_case()
        self.write_trace("2026-09-16-10031-consumer")
        self.run_settle(apply=True)
        row = [r for r in self.rows() if r.get("kind") == "case"][0]
        for k in ea.COUNT_KEYS["case"]:
            self.assertIn(k, row, f"结算写出的行缺 {k}")

    # ---------------------------------------------------------------- 幂等
    def test_settle_is_idempotent(self):
        self.write_case()
        self.write_trace("2026-09-16-10006-consumer")
        self.run_settle(apply=True)
        out2 = self.run_settle(apply=True)
        self.assertEqual(self.counts("SETTLE-1")["resolved"], 1)
        self.assertIn("已结算", out2)

    def test_incremental_settle_applies_only_new_events(self):
        """补一条新 feedback → 只结算新增的那条（EV-2026-109 修的就是这里）。"""
        self.write_case()
        self.write_trace("2026-09-16-10007-consumer")
        self.run_settle(apply=True)
        self.assertEqual(self.counts("SETTLE-1")["resolved"], 1)
        with (self.traces / "2026-09-16-10007-consumer.yaml").open("a", encoding="utf-8") as fh:
            fh.write("  - role: agent\n    action: feedback\n    case: SETTLE-1\n    outcome: resolved\n")
        self.run_settle(apply=True)
        self.assertEqual(self.counts("SETTLE-1")["resolved"], 2)

    def test_rewritten_sequence_is_refused_not_guessed(self):
        """事件序列被改写（非追加）→ 拒绝结算并告警：重放会虚增、当作已落地会丢证据。"""
        self.write_case()
        self.write_case(cid="SETTLE-OTHER")
        self.write_trace("2026-09-16-10020-consumer")
        self.run_settle(apply=True)
        self.assertEqual(self.counts("SETTLE-1")["resolved"], 1)
        self.write_trace("2026-09-16-10020-consumer", cid="SETTLE-OTHER")
        out = self.run_settle(apply=True)
        self.assertIn("序列被改写", out)
        self.assertEqual(self.counts("SETTLE-1")["resolved"], 1, "改写时不得重放")

    def test_unlanded_event_is_retried_until_case_exists(self):
        """case 还没落库 → 该事件不记落地、保持待结算；case 到位后重跑即补上。"""
        self.write_case(cid="SETTLE-1")
        self.write_trace("2026-09-16-10021-consumer", cid="LATER-1")
        out1 = self.run_settle(apply=True)
        self.assertIn("保持待结算", out1)
        self.assertEqual(self.counts("LATER-1")["resolved"], 0)
        entry = json.loads(self.state.read_text(encoding="utf-8"))["_trace_feedback"][
            "2026-09-16-10021-consumer"]
        self.assertEqual(entry["applied"], [], "未落地的事件不得被记成已落地")

        self.write_case(cid="LATER-1")
        self.run_settle(apply=True)
        self.assertEqual(self.counts("LATER-1")["resolved"], 1, "case 到位后应补结算")

    def test_legacy_cursor_migrates_without_replay(self):
        """v1 游标（整段 hash）迁移：视为已落地，不重放（防二次计数）。"""
        self.write_case()
        self.write_trace("2026-09-16-10023-consumer")
        legacy = hashlib.sha256(json.dumps(
            [{"case": "SETTLE-1", "outcome": "resolved"}], sort_keys=True).encode()).hexdigest()[:16]
        self.state.write_text(json.dumps({"_trace_feedback": {
            "2026-09-16-10023-consumer": {"events": legacy, "settled_at": "2026-W37"}}}),
            encoding="utf-8")
        out = self.run_settle(apply=True)
        self.assertIn("v1 游标 → v3", out)
        self.assertEqual(self.counts("SETTLE-1")["resolved"], 0, "迁移不得重放")

    # ---------------------------------------------------------------- 只读复核
    def test_audit_reports_settled_but_effect_missing(self):
        """--audit：游标说已结算、记录里没有痕迹 → 报出并非零退出（发现丢失的那条路）。"""
        self.write_case()
        self.write_trace("2026-09-16-10024-consumer")
        self.state.write_text(json.dumps({"_trace_feedback": {
            "2026-09-16-10024-consumer": {"schema": 3, "events": [], "applied": [],
                                          "landed": []}}}), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = stf.audit(self.traces, self.state, self.root)
        out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("未落地", out)

    def test_audit_is_clean_after_a_real_settle(self):
        self.write_case()
        self.write_trace("2026-09-16-10025-consumer")
        self.run_settle(apply=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = stf.audit(self.traces, self.state, self.root)
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertIn("无「已结算但无效果」", buf.getvalue())

    # ---------------------------------------------------------------- dry-run
    def test_dry_run_writes_nothing(self):
        self.write_case()
        self.write_trace("2026-09-16-10008-consumer")
        self.run_settle(apply=False)
        self.assertEqual(self.rows(), [], "dry-run 不得写记录")
        self.assertFalse(self.state.exists(), "dry-run 不得写游标")

    def test_apply_writes_cursor(self):
        self.write_case()
        self.write_trace("2026-09-16-10009-consumer")
        self.run_settle(apply=True)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn("2026-09-16-10009-consumer", state["_trace_feedback"])

    # ---------------------------------------------------------------- 无效输入
    def test_feedback_without_case_field_is_skipped(self):
        """feedback 缺 case → 跳过并告警，不得把它算到任何 case 上。"""
        self.write_case()
        (self.traces / "2026-09-16-10010-consumer.yaml").write_text(
            "session_id: s\nstatus: resolved\ntrace:\n"
            "  - role: agent\n    action: feedback\n    outcome: resolved\n", encoding="utf-8")
        out = self.run_settle(apply=True)
        self.assertIn("缺 case 字段", out)
        self.assertEqual(self.rows(), [])

    def test_unknown_case_is_skipped(self):
        self.write_case(cid="SETTLE-1")
        self.write_trace("2026-09-16-10011-consumer", cid="NOT-EXIST")
        out = self.run_settle(apply=True)
        self.assertIn("未在 knowledge/ 找到", out)

    def test_unparseable_trace_does_not_abort_others(self):
        """一条 trace 解析失败不得拖垮整批结算。"""
        self.write_case()
        (self.traces / "bad.yaml").write_text("trace: [\n", encoding="utf-8")
        self.write_trace("2026-09-16-10012-consumer")
        out = self.run_settle(apply=True)
        self.assertIn("解析失败", out)
        self.assertEqual(self.counts("SETTLE-1")["resolved"], 1)


if __name__ == "__main__":
    unittest.main()
