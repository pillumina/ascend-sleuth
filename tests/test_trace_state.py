"""状态投影与派生判据的回归。

护三件事：
1. 派生量与既有实现同口径（闭环、待沉淀、未收尾、价值序）——它们此前写在面板 JS 里，
   搬进 Python 时最容易「看起来一样、边界差一个」；
2. 动作只给当前状态合法的（终态不给收尾、缺收尾方式只给补记、有收尾方式只给改）；
3. 状态列颜色由库算（反向回报不用绿、待回报用空心琥珀），面板不再自己判。
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _trace_state as st  # noqa: E402


def doc(**kw):
    base = {"status": "in_progress", "active_case": "pending-investigation",
            "summary": "训练挂起", "trace": [{"role": "user"}], "updated_at": "2026-10-30T09:00:00+08:00"}
    base.update(kw)
    return base


class VocabTest(unittest.TestCase):
    def test_vocab_self_check(self):
        vocab = st.load_vocab(ROOT)
        self.assertEqual(st.check_vocab(vocab), [])
        self.assertEqual([s["value"] for s in vocab["statuses"]],
                         ["in_progress", "resolved", "escalated", "archived", "unknown"])

    def test_severity_from_yaml(self):
        vocab = st.load_vocab(ROOT)
        self.assertEqual([s["value"] for s in vocab["severities"]],
                         ["benign", "service-affecting", "data-loss-risk"])


class DeriveTest(unittest.TestCase):
    def test_hit_case_closed_only_with_outcome(self):
        d = st.derive(doc(status="resolved", active_case="VLLM-ASC-11312",
                          feedback={"outcome": "pending"}), set())
        self.assertFalse(d["closed"])
        self.assertTrue(d["needConfirm"])
        d2 = st.derive(doc(status="resolved", active_case="VLLM-ASC-11312",
                           feedback={"outcome": "resolved"}), set())
        self.assertTrue(d2["closed"])
        self.assertFalse(d2["needConfirm"])

    def test_no_hit_closed_by_status(self):
        d = st.derive(doc(status="resolved", active_case="pending-investigation", feedback={}), set())
        self.assertTrue(d["closed"])

    def test_need_work_excludes_sed_and_skeleton(self):
        cand = [{"kind": "case", "summary": "x"}]
        self.assertTrue(st.derive(doc(sediment_candidates=cand), set())["needSed"])
        self.assertFalse(st.derive(doc(sediment_candidates=cand), set())["needWork"])
        self.assertTrue(st.derive(doc(), set())["needWork"])
        self.assertTrue(st.derive(doc(trace=[], summary=None), set())["skeleton"])

    def test_value_rank(self):
        self.assertEqual(st.derive(doc(sedimented={"state": "knowledge"}), set())["valueRank"], 5)
        self.assertEqual(st.derive(doc(active_case="VLLM-ASC-1"), {"VLLM-ASC-1"})["valueRank"], 4)
        self.assertEqual(st.derive(doc(active_case="VLLM-ASC-1"), set())["valueRank"], 3)
        self.assertEqual(st.derive(doc(status="resolved", feedback={"outcome": "resolved"}, active_case=None),
                                   set())["valueRank"], 2)
        self.assertEqual(st.derive(doc(status="resolved", active_case=None), set())["valueRank"], 1)

    def test_case_kind_placeholder_is_not_case(self):
        self.assertEqual(st.case_kind("pending-investigation"), "placeholder")
        self.assertEqual(st.case_kind("VLLM-ASC-11312"), "case")
        self.assertEqual(st.case_kind(None), "none")

    # ---- 等什么 / 等谁：派生量，不写盘 ----
    def test_waiting_for_prefers_last_action_then_latest_missing(self):
        d = st.derive(doc(trace=[{"role": "user", "evidence": {"missing": "缺日志"}},
                                 {"role": "agent"}], last_action="等用户确认路径"), set())
        self.assertEqual(d["waitingFor"], "等用户确认路径")
        self.assertEqual(d["waitingOn"], "user_material")
        self.assertTrue(d["needsInput"])
        # 旧 trace 没写 last_action：退到最近一条 missing
        d2 = st.derive(doc(trace=[{"role": "user", "evidence": {"missing": "缺日志"}}]), set())
        self.assertEqual(d2["waitingFor"], "缺日志")
        self.assertEqual(d2["waitingOn"], "user_material")
        # 多行提问折叠成一行，面板一行显示
        d3 = st.derive(doc(trace=[{"role": "user"}], last_action="等用户确认\n  三条路径"), set())
        self.assertEqual(d3["waitingFor"], "等用户确认 三条路径")

    def test_terminal_trace_does_not_still_wait_for_old_missing(self):
        d = st.derive(doc(status="resolved",
                          trace=[{"role": "user", "evidence": {"missing": "缺日志"}}]), set())
        self.assertEqual(d["waitingFor"], "")
        self.assertEqual(d["waitingOn"], "ended")
        self.assertFalse(d["needsInput"])

    def test_waiting_on_feedback_and_sediment(self):
        d = st.derive(doc(status="resolved", active_case="VLLM-ASC-1",
                          feedback={"case": "VLLM-ASC-1", "outcome": "pending"}), set())
        self.assertEqual(d["waitingOn"], "user_feedback")
        # 在途、有 case 候选、没有当前提问 → 等沉淀
        d2 = st.derive(doc(sediment_candidates=[{"kind": "case"}]), set())
        self.assertEqual(d2["waitingOn"], "sediment")
        # 在途、有 case 候选、但 last_action 在等材料 → 先答「等什么」
        d3 = st.derive(doc(sediment_candidates=[{"kind": "case"}], last_action="等现场补 plog"), set())
        self.assertEqual(d3["waitingOn"], "user_material")
        self.assertTrue(d3["needsInput"])
        # 已收尾、带 case 候选、还没沉淀 → 待沉淀（不是 ended）
        d4 = st.derive(doc(status="resolved", sediment_candidates=[{"kind": "case"}]), set())
        self.assertEqual(d4["waitingOn"], "sediment")

    def test_waiting_on_upstream(self):
        cases = self._upstream_case()
        d = st.derive(doc(status="resolved", active_case="VLLM-ASC-1", fix_emitted=False),
                      {"VLLM-ASC-1"}, cases)
        self.assertEqual(d["waitingOn"], "upstream")
        self.assertEqual(d["waitingFor"], "")

    # ---- 等上游：四个已有事实的现算组合（收尾 + 没给 fix + 有锚点 + 依据在上游）----
    def _upstream_case(self, source="upstream-maintainer-confirmed", last="2026-W42"):
        return {"VLLM-ASC-1": {"anchors": ["vllm-ascend#10834"], "lastVerified": last,
                               "verificationSource": source}}

    def test_upstream_pending_needs_closed_no_fix_anchor_and_upstream_grounding(self):
        cases = self._upstream_case()
        d = st.derive(doc(status="resolved", active_case="VLLM-ASC-1", fix_emitted=False),
                      {"VLLM-ASC-1"}, cases)
        self.assertTrue(d["upstreamPending"])
        self.assertEqual(d["upstream"]["anchors"], ["vllm-ascend#10834"])
        self.assertEqual(d["upstream"]["lastVerified"], "2026-W42")

    def test_upstream_pending_false_when_any_leg_is_missing(self):
        cases = self._upstream_case()
        hit = {"VLLM-ASC-1"}
        # 给了 fix → 不是在等上游
        self.assertFalse(st.derive(doc(status="resolved", active_case="VLLM-ASC-1",
                                       fix_emitted=True), hit, cases)["upstreamPending"])
        # 还没收尾 → 那是"在查"，不是等上游
        self.assertFalse(st.derive(doc(status="in_progress", active_case="VLLM-ASC-1",
                                       fix_emitted=False), hit, cases)["upstreamPending"])
        # 没记 fix_emitted → 不猜（缺键不等于没给 fix）。三种"未记"的写法都要算未记：
        # 缺键 / `fix_emitted: null`（`trace_begin.py` 给每条新 trace 写的就是这个）/ 空串。
        for label, extra in (("缺键", {}), ("null", {"fix_emitted": None}), ("空串", {"fix_emitted": ""})):
            self.assertFalse(st.derive(doc(status="resolved", active_case="VLLM-ASC-1", **extra),
                                       hit, cases)["upstreamPending"], label)
        # 平铺写 null、但 `outcome.fix_emitted: true` 记了真值 → 不能同时挂「已给 fix」与「等上游」
        self.assertFalse(st.derive(doc(status="resolved", active_case="VLLM-ASC-1",
                                       fix_emitted=None, outcome={"fix_emitted": True}),
                                   hit, cases)["upstreamPending"])
        # 案例在库里但没有上游锚点 → 查不了上游，不挂这个徽标
        no_anchor = {"VLLM-ASC-1": {"anchors": [], "lastVerified": "",
                                    "verificationSource": "upstream-fix-merged"}}
        self.assertFalse(st.derive(doc(status="resolved", active_case="VLLM-ASC-1",
                                       fix_emitted=False), hit, no_anchor)["upstreamPending"])
        # 不传 KB 附加事实（老调用点）→ 两个字段都按不可判处理
        d2 = st.derive(doc(status="resolved", active_case="VLLM-ASC-1", fix_emitted=False), hit)
        self.assertFalse(d2["upstreamPending"])
        self.assertIsNone(d2["upstream"])

    def test_upstream_pending_excludes_stop_cards_and_non_upstream_sources(self):
        # 这两条是评审构造出的误标反例，必须红：
        # ① data-loss-risk 按 severity gate 就不该给 fix（先停、保留现场、通知 owner），
        #    它不是"在等上游"；
        cards = self._upstream_case()
        d = st.derive(doc(status="resolved", active_case="VLLM-ASC-1", fix_emitted=False,
                          severity="data-loss-risk"), {"VLLM-ASC-1"}, cards)
        self.assertFalse(d["upstreamPending"], "数据风险单必须不进等上游")
        # ② 案例依据不在上游（investigation / engineer-report）→ 没给 fix 只说明"只定位到根因"
        for source in ("investigation", "engineer-report", "self-report", ""):
            cases = self._upstream_case(source=source)
            d2 = st.derive(doc(status="resolved", active_case="VLLM-ASC-1", fix_emitted=False),
                           {"VLLM-ASC-1"}, cases)
            self.assertFalse(d2["upstreamPending"], f"source={source} 不该被判成等上游")

    def test_upstream_pending_accepts_outcome_fix_emitted(self):
        # 两种写法都认，与面板 flat 字段同条：`outcome.fix_emitted` 侧也判得出「没给 fix」
        cases = self._upstream_case()
        d = st.derive(doc(status="resolved", active_case="VLLM-ASC-1",
                          outcome={"fix_emitted": "false"}), {"VLLM-ASC-1"}, cases)
        self.assertTrue(d["upstreamPending"])
        d2 = st.derive(doc(status="resolved", active_case="VLLM-ASC-1",
                           outcome={"fix_emitted": True}), {"VLLM-ASC-1"}, cases)
        self.assertFalse(d2["upstreamPending"])


class KbCaseMetaTest(unittest.TestCase):
    def test_reads_anchors_and_last_verified_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            kdir = Path(tmp) / "knowledge" / "inference"
            kdir.mkdir(parents=True)
            (kdir / "C-1.yaml").write_text(
                "cases:\n"
                "  - id: C-1\n"
                "    validation_record:\n"
                "      consistent: 1\n"
                "      last_verified: 2026-W42\n"
                "    upstream:\n"
                "      - repo: vllm-project/vllm-ascend\n"
                "        issue: 10834\n"
                "        url: https://example.invalid/10834\n",
                encoding="utf-8")
            (kdir / "C-2.yaml").write_text("cases:\n  - id: C-2\n", encoding="utf-8")
            # 生成物与归档不该进这张表：文件名以 _ 开头的跳过；`_archive/` 下的退休案例
            # 与 build_index / verify_upstream_outcomes 同一条（不进检索、不查证）。
            (Path(tmp) / "knowledge" / "_index.yaml").write_text(
                "cases:\n  - id: C-IDX\n", encoding="utf-8")
            archived = Path(tmp) / "knowledge" / "_archive" / "old"
            archived.mkdir(parents=True)
            (archived / "OLD-1.yaml").write_text(
                "cases:\n  - id: OLD-1\n    upstream:\n      - {repo: a/b, issue: 1}\n",
                encoding="utf-8")
            meta = st.kb_case_meta(Path(tmp))
            self.assertEqual(sorted(meta), ["C-1", "C-2"])
            self.assertEqual(meta["C-1"]["anchors"], ["vllm-ascend#10834"])
            self.assertEqual(meta["C-1"]["lastVerified"], "2026-W42")
            self.assertEqual(meta["C-1"]["verificationSource"], "")
            self.assertEqual(meta["C-2"],
                             {"anchors": [], "lastVerified": "", "verificationSource": ""})

    def test_missing_knowledge_dir_is_empty_not_an_error(self):
        self.assertEqual(st.kb_case_meta(Path("/nonexistent-kb")), {})

    def test_pr_anchor_and_broken_anchor(self):
        # `issue` 与 `pr` 二选一；两者都缺的锚点跳过，不猜编号
        case = {"upstream": [{"repo": "a/b", "pr": 7},
                             {"repo": "a/b"},
                             "not-a-mapping"]}
        self.assertEqual(st._upstream_anchor_labels(case), ["b#7"])


class LoadTracesTest(unittest.TestCase):
    def test_bad_entries_leave_other_rows_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "good.yaml").write_text('session_id: "good"\nstatus: in_progress\n',
                                            encoding="utf-8")
            (root / "bad.yaml").write_text("status: [unclosed\n", encoding="utf-8")
            # 目录也能匹配 `*.yaml`；read_bytes 抛 IsADirectoryError，只该标记这一行。
            (root / "blocked.yaml").mkdir()
            rows = {row["file"]: row for row in st.load_traces(root)}
            self.assertEqual(sorted(rows), ["bad.yaml", "blocked.yaml", "good.yaml"])
            good = rows["good.yaml"]
            self.assertIsNone(good["error"])
            self.assertEqual(good["sessionId"], "good")
            self.assertEqual(len(good["contentSha256"]), 64)
            self.assertIsNone(rows["bad.yaml"]["doc"])
            self.assertTrue(rows["bad.yaml"]["error"])
            self.assertIsNone(rows["blocked.yaml"]["doc"])
            self.assertTrue(rows["blocked.yaml"]["error"])
            self.assertEqual(rows["blocked.yaml"]["contentSha256"], "")


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "trace-status.yaml").write_bytes((ROOT / "trace-status.yaml").read_bytes())
        kdir = self.base / "knowledge" / "inference"
        kdir.mkdir(parents=True)
        (kdir / "C-1.yaml").write_text(
            "cases:\n  - id: VLLM-ASC-1\n"
            "    upstream:\n      - {repo: vllm-project/vllm-ascend, issue: 10834}\n",
            encoding="utf-8")
        self.traces = self.base / "traces"
        self.traces.mkdir()
        (self.traces / "s1.yaml").write_text(
            'session_id: "s1"\nstatus: resolved\nupdated_at: "2026-10-30T09:00:00+08:00"\n'
            "transitions:\n"
            '  - {"at": "2026-10-29T09:00:00+08:00", "from": "in_progress", "to": "resolved",'
            ' "folded": 3, "note": "更早的 3 次转移已折叠"}\n'
            '  - {"action": "reopen", "at": "2026-10-30T09:00:00+08:00", "from": "resolved",'
            ' "to": "in_progress", "ending": null, "prev_ending": null, "by": "user",'
            ' "source": "panel", "note": ""}\n',
            encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_transitions_carry_action_note_and_folded(self):
        row = st.project(self.traces, self.base)["sessions"][0]
        first, second = row["transitions"]
        self.assertEqual(first["folded"], 3)
        self.assertEqual(first["note"], "更早的 3 次转移已折叠")
        self.assertIsNone(first["action"])
        self.assertEqual(second["action"], "reopen")
        self.assertEqual(second["note"], "")
        self.assertEqual(second["folded"], 0)
        self.assertEqual((second["by"], second["source"]), ("user", "panel"))

    def test_vocab_endings_carry_target_statuses(self):
        endings = {e["value"]: e for e in st.project(self.traces, self.base)["vocab"]["endings"]}
        self.assertEqual(endings["handed_off"]["statuses"], ["escalated"])
        self.assertEqual(endings["root_cause"]["statuses"], ["resolved"])
        # 原有三字段不动
        self.assertEqual(endings["handed_off"]["requires"], ["ending.handed_to"])

    def test_preloaded_rows_give_same_projection(self):
        rows = st.load_traces(self.traces)
        with_rows = st.project(self.traces, self.base, rows=rows)
        from_disk = st.project(self.traces, self.base)
        self.assertEqual(with_rows["sessions"], from_disk["sessions"])
        # 传了 rows 就不再重读：文件在传入后被改，投影仍按传入的那份算
        (self.traces / "s1.yaml").write_text('session_id: "s1"\nstatus: archived\n',
                                             encoding="utf-8")
        self.assertEqual(st.project(self.traces, self.base, rows=rows)["sessions"][0]["status"],
                         "resolved")


class ActionsTest(unittest.TestCase):
    def setUp(self):
        self.vocab = st.load_vocab(ROOT)

    def ids(self, d):
        return [a["id"] for a in st.actions_for(d, self.vocab, st.derive(d, set()))]

    def test_in_progress_has_three_closings(self):
        self.assertEqual(self.ids(doc()), ["close-resolved", "close-escalated", "close-archived"])

    def test_terminal_with_ending_has_correct_and_reopen(self):
        ids = self.ids(doc(status="escalated", ending={"kind": "handed_off", "handed_to": "张工"}))
        self.assertIn("correct-ending", ids)
        self.assertIn("reopen", ids)
        self.assertNotIn("backfill-ending", ids)
        self.assertFalse([i for i in ids if i.startswith("close-")])

    def test_terminal_without_ending_has_backfill_only(self):
        ids = self.ids(doc(status="archived", active_case=None))
        self.assertIn("backfill-ending", ids)
        self.assertIn("reopen", ids)
        self.assertNotIn("correct-ending", ids)

    def test_hit_case_close_needs_feedback(self):
        actions = st.actions_for(doc(active_case="VLLM-ASC-11312"), self.vocab,
                                 st.derive(doc(active_case="VLLM-ASC-11312"), set()))
        resolved = [a for a in actions if a["id"] == "close-resolved"][0]
        self.assertIn("feedback.outcome", resolved["mustExist"])

    def test_ending_choices_carry_required_fields(self):
        actions = st.actions_for(doc(), self.vocab, st.derive(doc(), set()))
        archived = [a for a in actions if a["id"] == "close-archived"][0]
        dup = [c for c in archived["endingChoices"] if c["value"] == "duplicate"][0]
        self.assertIn("ending.duplicate_of", dup["requires"])


class ToneTest(unittest.TestCase):
    def test_negative_outcome_not_green(self):
        vocab = st.load_vocab(ROOT)
        tone = st.display_tone("resolved", "not_resolved", st.status_meta(vocab, "resolved"))
        self.assertEqual(tone["color"], "var(--c-gray)")

    def test_pending_is_hollow_amber(self):
        vocab = st.load_vocab(ROOT)
        tone = st.display_tone("resolved", "pending", st.status_meta(vocab, "resolved"))
        self.assertTrue(tone["hollow"])
        self.assertEqual(tone["color"], "var(--c-amber)")

    def test_normal_resolved_green(self):
        vocab = st.load_vocab(ROOT)
        self.assertEqual(st.display_tone("resolved", None, st.status_meta(vocab, "resolved"))["color"],
                         "var(--c-green)")


if __name__ == "__main__":
    unittest.main()
