"""settle_trace_feedback 的口径回归测试。

护的是学习环的核心口径：**只有 feedback.resolved 计 hits**；来源 session 自己的
resolve 记 self_resolved、**不计入 hits**（同一份证据不能数两次）；not_resolved /
partial 计 misdiagnoses；同一 session 同序列只结算一次（幂等）；dry-run 不写盘。
这几条写错，case 置信度就会朝错的方向学习，而面板看不出来。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import settle_trace_feedback as stf  # noqa: E402

CASE_TMPL = """cases:
  - id: {cid}
    title: "结算测试"
    category: interrupt
{extra}    confidence:
      hits: {hits}
      misdiagnoses: {mis}
      score: 0.5
      last_hit: ""
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


class SettleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.kb = self.root / "knowledge"
        self.traces = self.root / "traces"
        self.kb.mkdir()
        self.traces.mkdir()
        self.state = self.root / ".settle-state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, cid="SETTLE-1", source_session=None, hits=0, mis=0):
        extra = f"    source_session: {source_session}\n" if source_session else ""
        p = self.kb / "inference" / "vllm-ascend" / "interrupt" / f"{cid}.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CASE_TMPL.format(cid=cid, extra=extra, hits=hits, mis=mis), encoding="utf-8")
        return p

    def write_trace(self, sid, cid="SETTLE-1", outcome="resolved", status="resolved",
                    ns="inference/vllm-ascend"):
        (self.traces / f"{sid}.yaml").write_text(
            TRACE_TMPL.format(sid=sid, cid=cid, outcome=outcome, status=status, ns=ns),
            encoding="utf-8")

    def read_case(self, p):
        import yaml
        return yaml.safe_load(p.read_text(encoding="utf-8"))["cases"][0]

    def run_settle(self, apply=False):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            stf.settle(self.traces, self.state, apply, kb_root=self.kb)
        return buf.getvalue()

    # ---------------------------------------------------------------- 正/负信号
    def test_resolved_from_consumer_counts_hits(self):
        """消费者环境报 resolve → hits += 1（这是 hits 的口径）。"""
        p = self.write_case()
        self.write_trace("2026-09-16-10000-consumer")
        self.run_settle(apply=True)
        c = self.read_case(p)
        self.assertEqual(c["confidence"]["hits"], 1)
        self.assertEqual(c["confidence"]["misdiagnoses"], 0)

    def test_not_resolved_counts_misdiagnoses(self):
        p = self.write_case()
        self.write_trace("2026-09-16-10001-consumer", outcome="not_resolved")
        self.run_settle(apply=True)
        c = self.read_case(p)
        self.assertEqual(c["confidence"]["hits"], 0)
        self.assertEqual(c["confidence"]["misdiagnoses"], 1)

    def test_partial_counts_misdiagnoses(self):
        p = self.write_case()
        self.write_trace("2026-09-16-10002-consumer", outcome="partial")
        self.run_settle(apply=True)
        self.assertEqual(self.read_case(p)["confidence"]["misdiagnoses"], 1)

    # ---------------------------------------------------------------- 自证口径
    def test_source_session_self_resolved_does_not_touch_hits(self):
        """来源 session 自己的 resolve = 自证：记 self_resolved，hits 保持不动。"""
        p = self.write_case(source_session="2026-09-16-10003-author")
        self.write_trace("2026-09-16-10003-author")
        self.run_settle(apply=True)
        c = self.read_case(p)
        self.assertEqual(c["confidence"]["hits"], 0, "自证不得计入 hits（同一证据不数两次）")
        self.assertEqual(c["confidence"]["self_resolved"]["count"], 1)

    def test_consumer_resolved_on_authored_case_still_counts_hits(self):
        """同一条 case 被别人消费并 resolve → 仍计 hits（自证只挡产地那一次）。"""
        p = self.write_case(source_session="2026-09-16-10004-author")
        self.write_trace("2026-09-16-10005-other")
        self.run_settle(apply=True)
        c = self.read_case(p)
        self.assertEqual(c["confidence"]["hits"], 1)
        self.assertNotIn("self_resolved", c["confidence"])

    # ---------------------------------------------------------------- 幂等
    def test_settle_is_idempotent(self):
        """同一 session 同序列只结算一次——重复跑不得把 hits 累加。"""
        p = self.write_case()
        self.write_trace("2026-09-16-10006-consumer")
        self.run_settle(apply=True)
        out2 = self.run_settle(apply=True)
        self.assertEqual(self.read_case(p)["confidence"]["hits"], 1)
        self.assertIn("已结算", out2)

    def test_incremental_settle_applies_only_new_events(self):
        """补一条新 feedback → 只结算新增的那条（EV-2026-109 修的就是这里）。

        改前（v1 游标）：幂等键是整段事件列表 hash，列表一变就整段重放 → 旧事件二次计入 hits
        （实测 1→3）。改后（v2 游标逐事件记落地）：1→2。
        """
        p = self.write_case()
        self.write_trace("2026-09-16-10007-consumer")
        self.run_settle(apply=True)
        self.assertEqual(self.read_case(p)["confidence"]["hits"], 1)
        with (self.traces / "2026-09-16-10007-consumer.yaml").open("a", encoding="utf-8") as fh:
            fh.write("  - role: agent\n    action: feedback\n    case: SETTLE-1\n    outcome: resolved\n")
        self.run_settle(apply=True)
        self.assertEqual(self.read_case(p)["confidence"]["hits"], 2)

    def test_rewritten_sequence_is_refused_not_guessed(self):
        """事件序列被改写（非追加）→ 拒绝结算并告警：重放会虚增、当作已落地会丢证据。"""
        p = self.write_case()
        self.write_trace("2026-09-16-10020-consumer")
        self.run_settle(apply=True)
        self.assertEqual(self.read_case(p)["confidence"]["hits"], 1)
        # 把同一条 feedback 改写成另一个 case（历史被重写，不是追加）
        self.write_trace("2026-09-16-10020-consumer", cid="SETTLE-OTHER")
        out = self.run_settle(apply=True)
        self.assertIn("序列被改写", out)
        self.assertEqual(self.read_case(p)["confidence"]["hits"], 1, "改写时不得重放")

    def test_unlanded_event_is_retried_until_case_exists(self):
        """case 还没落库 → 该事件不记落地、保持待结算；case 到位后重跑即补上。"""
        p = self.write_case(cid="SETTLE-1")
        self.write_trace("2026-09-16-10021-consumer", cid="LATER-1")   # 指向还不存在的 case
        out1 = self.run_settle(apply=True)
        self.assertIn("保持待结算", out1)
        self.assertEqual(self.read_case(p)["confidence"]["hits"], 0)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        entry = state["_trace_feedback"]["2026-09-16-10021-consumer"]
        self.assertEqual(entry["applied"], [], "未落地的事件不得被记成已落地")

        self.write_case(cid="LATER-1")                                  # case 落库
        self.run_settle(apply=True)
        import yaml
        later = self.kb / "inference" / "vllm-ascend" / "interrupt" / "LATER-1.yaml"
        self.assertEqual(yaml.safe_load(later.read_text(encoding="utf-8"))["cases"][0]
                         ["confidence"]["hits"], 1, "case 到位后应补结算")

    def test_write_verification_blocks_cursor_advance(self):
        """写回复核不通过（此处：case 没有 confidence: 块）→ 不推进游标，下次重试。"""
        p = self.kb / "inference" / "vllm-ascend" / "interrupt" / "NO-CONF.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('cases:\n  - id: NO-CONF\n    title: "无 confidence 块"\n'
                     "    category: interrupt\n", encoding="utf-8")
        self.write_trace("2026-09-16-10022-consumer", cid="NO-CONF")
        out = self.run_settle(apply=True)
        self.assertIn("复核不通过", out)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["_trace_feedback"]["2026-09-16-10022-consumer"]["applied"], [])

    def test_legacy_cursor_migrates_without_replay(self):
        """v1 游标（整段 hash）迁移：视为已落地，不重放（防二次计数）。"""
        p = self.write_case()
        self.write_trace("2026-09-16-10023-consumer")
        import hashlib
        legacy = hashlib.sha256(json.dumps(
            [{"case": "SETTLE-1", "outcome": "resolved"}], sort_keys=True).encode()).hexdigest()[:16]
        self.state.write_text(json.dumps({"_trace_feedback": {
            "2026-09-16-10023-consumer": {"events": legacy, "settled_at": "2026-W37"}}}),
            encoding="utf-8")
        out = self.run_settle(apply=True)
        self.assertIn("v1 游标 → v2", out)
        self.assertEqual(self.read_case(p)["confidence"]["hits"], 0, "迁移不得重放")

    # ---------------------------------------------------------------- 只读复核
    def test_audit_reports_settled_but_effect_missing(self):
        """--audit：游标说已结算、case 里没有痕迹 → 报出并非零退出（发现丢失的那条路）。"""
        p = self.write_case()
        self.write_trace("2026-09-16-10024-consumer")
        self.state.write_text(json.dumps({"_trace_feedback": {
            "2026-09-16-10024-consumer": {"schema": 2, "events": [], "applied": []}}}),
            encoding="utf-8")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = stf.audit(self.traces, self.state, self.kb)
        out = buf.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("未落地", out)
        self.assertEqual(self.read_case(p)["confidence"]["hits"], 0, "audit 是只读的")

    def test_audit_is_clean_after_a_real_settle(self):
        self.write_case()
        self.write_trace("2026-09-16-10025-consumer")
        self.run_settle(apply=True)
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = stf.audit(self.traces, self.state, self.kb)
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertIn("无「已结算但无效果」", buf.getvalue())

    # ---------------------------------------------------------------- dry-run
    def test_dry_run_writes_nothing(self):
        p = self.write_case()
        before = p.read_text(encoding="utf-8")
        self.write_trace("2026-09-16-10008-consumer")
        self.run_settle(apply=False)
        self.assertEqual(p.read_text(encoding="utf-8"), before, "dry-run 不得改 case 文件")
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
        p = self.write_case()
        (self.traces / "2026-09-16-10010-consumer.yaml").write_text(
            "session_id: s\nstatus: resolved\ntrace:\n"
            "  - role: agent\n    action: feedback\n    outcome: resolved\n", encoding="utf-8")
        out = self.run_settle(apply=True)
        self.assertIn("缺 case 字段", out)
        self.assertEqual(self.read_case(p)["confidence"]["hits"], 0)

    def test_unknown_case_is_skipped(self):
        self.write_case(cid="SETTLE-1")
        self.write_trace("2026-09-16-10011-consumer", cid="NOT-EXIST")
        out = self.run_settle(apply=True)
        self.assertIn("未在 knowledge/ 找到", out)

    def test_unparseable_trace_does_not_abort_others(self):
        """一条 trace 解析失败不得拖垮整批结算。"""
        p = self.write_case()
        (self.traces / "bad.yaml").write_text("trace: [\n", encoding="utf-8")
        self.write_trace("2026-09-16-10012-consumer")
        out = self.run_settle(apply=True)
        self.assertIn("解析失败", out)
        self.assertEqual(self.read_case(p)["confidence"]["hits"], 1)


if __name__ == "__main__":
    unittest.main()
