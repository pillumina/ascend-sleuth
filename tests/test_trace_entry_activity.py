"""trace_entry_activity 的口径回归：轨迹 → 触达计数，会话日志 → 工具分布与账单。

三件事值得单测，因为它们的失效都不报错：
  ① **触达口径**：被选中（进候选集）、被加载（读了正文）、被排除是三种不同的触达，
     混成一个数就看不出「检索到了但每次都排除」这条信号；
  ② **增量**：轨迹是追加型的，同一会话跑第二次只能写新增的那部分——按「处理过一次就跳过」
     会让后来补上的事件永远进不了记录，按累计值直接写会重复计数；
  ③ **先验 id 归一**：schema 要求写词条 id，历史 trace 里有写文件路径的；不归一就会
     在记录里生出一条 id 是路径的假条目（面板上按 id 点不进任何词条）。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import entry_activity as ea  # noqa: E402
import trace_entry_activity as tea  # noqa: E402

TRACE = {
    "session_id": "2026-10-16-12000-demo",
    "harness_session": "demo-sid",
    "status": "resolved",
    "created_at": "2026-10-16T12:00:00+08:00",
    "updated_at": "2026-10-16T13:00:00+08:00",
    "detected_framework": "vllm-ascend",
    "detected_platform": "A2-910B",
    "detected_category": "interrupt",
    "excluded_cases": ["CASE-EX"],
    "feedback": {"case": "CASE-A", "outcome": "resolved", "confirmed_at": "2026-10-16"},
    "sedimented": {"state": "knowledge", "case_id": "CASE-A"},
    "trace": [
        {"role": "agent", "step": 1, "action": "triage", "routed": ["inference/vllm-ascend", "common"]},
        {"role": "agent", "step": 3, "action": "load_index", "namespaces": ["inference/vllm-ascend"],
         "n_cases": 85},
        {"role": "agent", "step": 3, "action": "hit", "case": "CASE-HIT"},
        {"role": "agent", "step": 3, "action": "load_full", "candidates": ["CASE-HIT", "CASE-B"]},
        {"role": "agent", "step": 3, "action": "quickly_check", "case": "CASE-HIT", "result": "match"},
        {"role": "agent", "step": 3, "action": "quickly_check", "case": "CASE-B", "result": "mismatch"},
        {"role": "agent", "step": 2, "action": "reference_lookup", "ref_id": "ref-one",
         "purpose": "signature", "outcome": "hit"},
        {"role": "agent", "step": 2, "action": "reference_lookup",
         "ref_ids": ["ref-two", "ref-three"], "purpose": "background", "outcome": "miss"},
        {"role": "agent", "step": 4, "action": "reference_lookup", "ref_id": "ref-no-outcome",
         "purpose": "fix"},
        {"role": "agent", "step": 6, "action": "feedback", "case": "CASE-A", "outcome": "resolved"},
    ],
}

SESSION_LOG = "\n".join([
    json.dumps({"type": "assistant/message", "data": {
        "turn": 1, "step": 1,
        "usage": {"inputTokens": 100, "cacheReadTokens": 10, "cacheWriteTokens": 5,
                  "outputTokens": 20}}}),
    json.dumps({"type": "tool/call", "time": 1000, "data": {
        "turn": 1, "step": 1, "callId": "c1", "name": "read", "arguments": '{"file_path": "/x/y.yaml"}'}}),
    json.dumps({"type": "tool/result", "time": 1100, "data": {"message": {
        "source": {"kind": "tool", "callId": "c1"},
        "content": [{"type": "tool-result", "content": [{"type": "text", "text": "ok"}]}]}}}),
    json.dumps({"type": "tool/call", "time": 2000, "data": {
        "turn": 1, "step": 1, "callId": "c2", "name": "grep", "arguments": '{"pattern": "507014"}'}}),
    json.dumps({"type": "tool/result", "time": 2300, "data": {
        "message": {"source": {"kind": "tool", "callId": "c2"},
                    "content": [{"type": "tool-result", "content": [{"type": "text", "text": "err"}],
                                 "isError": True}]},
        "error": {"name": "TimeoutError", "code": "TIMEOUT"}}}),
])


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.traces = self.root / "traces"
        self.traces.mkdir()
        self.sessions = self.root / "sessions"
        (self.sessions / "ws" / "demo-sid").mkdir(parents=True)
        (self.sessions / "ws" / "demo-sid" / "session.jsonl.zstd").write_text(
            SESSION_LOG, encoding="utf-8")
        self.local = self.root / "metrics" / "entry-activity.local"
        self.state = self.root / ".settle-state.json"
        os.environ["ASCEND_SLEUTH_DEPLOYMENT"] = "test-dep"
        self.addCleanup(lambda: os.environ.pop("ASCEND_SLEUTH_DEPLOYMENT", None))
        self.write_lib()

    def write_lib(self, cases=("CASE-A", "CASE-B", "CASE-HIT", "CASE-EX"),
                  refs=("ref-one", "ref-two", "ref-three", "ref-no-outcome")):
        for cid in cases:
            p = self.root / "knowledge" / "inference" / "vllm-ascend" / "interrupt" / f"{cid}.yaml"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"cases:\n  - id: {cid}\n    category: interrupt\n"
                         "    investigation_quality: medium\n", encoding="utf-8")
        for rid in refs:
            p = self.root / "references" / "errors" / f"{rid}.yaml"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"id: {rid}\ntype: error-code\nstatus: active\n", encoding="utf-8")

    def write_trace(self, doc=None):
        d = doc or TRACE
        (self.traces / f"{d['session_id']}.yaml").write_text(
            yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def run_summarize(self, apply=False, run="2026-10-16-1400", sessions_root=None,
                      use_log=True):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = tea.build_records(self.root, self.traces,
                                     sessions_root or self.sessions, None, apply, run,
                                     self.state, use_log=use_log, local_dir=self.local)
        self.assertEqual(code, 0)
        return buf.getvalue()

    def rows(self):
        return ea.read_source(self.root)[0]


class FactsTest(Fixture):
    def test_selected_loaded_excluded_are_three_different_things(self):
        facts = tea.trace_facts(TRACE)
        self.assertEqual(facts["cases"]["CASE-HIT"]["selected"], 3)
        self.assertEqual(facts["cases"]["CASE-HIT"]["loaded"], 2)
        self.assertEqual(facts["cases"]["CASE-B"]["selected"], 2)
        self.assertEqual(facts["cases"]["CASE-B"]["loaded"], 2)
        self.assertEqual(facts["cases"]["CASE-EX"]["excluded"], 1)
        self.assertEqual(facts["cases"]["CASE-EX"]["selected"], 0)

    def test_miss_event_excluded_cases_counted_once(self):
        """`miss` 事件带 `excluded_cases` 只计一次（同一事件曾被通用循环与 miss 分支各计一遍）。"""
        facts = tea.trace_facts({"trace": [
            {"role": "agent", "action": "miss", "excluded_cases": ["CASE-X", "CASE-Y"]}]})
        self.assertEqual(facts["cases"]["CASE-X"]["excluded"], 1)
        self.assertEqual(facts["cases"]["CASE-Y"]["excluded"], 1)

    def test_top_level_rollup_is_not_counted_twice(self):
        """顶层 `excluded_cases` 是这一单的汇总，与事件里的同名列表是同一个事实，只计一次。"""
        facts = tea.trace_facts({"excluded_cases": ["CASE-X"], "trace": [
            {"role": "agent", "action": "miss", "excluded_cases": ["CASE-X"]}]})
        self.assertEqual(facts["cases"]["CASE-X"]["excluded"], 1)

    def test_two_separate_exclusions_count_twice(self):
        """两次各自排除同一个候选 = 两次触达，计 2。"""
        facts = tea.trace_facts({"trace": [
            {"role": "agent", "action": "miss", "excluded_cases": ["CASE-X"]},
            {"role": "agent", "action": "miss", "excluded_cases": ["CASE-X"]}]})
        self.assertEqual(facts["cases"]["CASE-X"]["excluded"], 2)

    def test_one_event_counting_both_candidate_fields_counts_once(self):
        """同一事件同时写 `candidates` 与 `considered_candidates` 时按集合算（后者是超集）。"""
        facts = tea.trace_facts({"trace": [{"role": "agent", "action": "load_full",
                                           "candidates": ["C"], "considered_candidates": ["C", "D"]}]})
        self.assertEqual(facts["cases"]["C"]["selected"], 1)
        self.assertEqual(facts["cases"]["C"]["loaded"], 1)
        self.assertEqual(facts["cases"]["D"]["selected"], 1)
        self.assertEqual(facts["cases"]["D"]["loaded"], 0, "D 只是被看过，没取全文")

    def test_route_and_hit_case(self):
        facts = tea.trace_facts(TRACE)
        self.assertEqual(facts["routed"], "inference/vllm-ascend", "common 不是路由目标")
        self.assertEqual(facts["hit_case"], "CASE-HIT")

    def test_reference_three_states_and_unrecorded_outcome(self):
        facts = tea.trace_facts(TRACE)
        self.assertEqual(facts["refs"]["ref-one"], {"lookups": 1, "hit": 1, "miss": 0, "skipped": 0,
                                                    "purpose": {"signature": 1}})
        self.assertEqual(facts["refs"]["ref-two"]["lookups"], 1)
        self.assertEqual(facts["refs"]["ref-two"]["miss"], 1)
        # 没写 outcome 的事件：算查过，但不落进三态——差值就是记账缺口的读数
        self.assertEqual(facts["refs"]["ref-no-outcome"]["lookups"], 1)
        self.assertEqual(sum(facts["refs"]["ref-no-outcome"][k] for k in ("hit", "miss", "skipped")), 0)

    def test_strength_self_report_when_source_session_settled_it(self):
        facts = tea.trace_facts(TRACE)
        facts["case_verification_source"] = None
        self.assertTrue(tea.is_self_resolve(TRACE["session_id"], facts))
        self.assertEqual(tea.strength_of(facts, True), "self-report")

    def test_strength_falls_back_to_investigation(self):
        facts = tea.trace_facts(TRACE)
        self.assertEqual(tea.strength_of(facts, False), "investigation")


class SessionLogTest(Fixture):
    def test_tokens_are_summed_by_turn_step(self):
        log, why = tea.read_session_log(
            self.sessions / "ws" / "demo-sid" / "session.jsonl.zstd")
        self.assertIsNone(why)
        self.assertEqual(log["tokens"], {"uncached": 100, "cache_read": 10,
                                         "cache_write": 5, "out": 20})

    def test_tool_latency_and_error_are_recorded(self):
        log, _ = tea.read_session_log(
            self.sessions / "ws" / "demo-sid" / "session.jsonl.zstd")
        by = {c["tool"]: c for c in log["tool_calls"]}
        self.assertEqual(by["read"]["ms"], 100)
        self.assertTrue(by["read"]["ok"])
        self.assertEqual(by["grep"]["ms"], 300)
        self.assertFalse(by["grep"]["ok"])
        self.assertEqual(by["grep"]["error"], "TimeoutError")
        self.assertEqual(log["tools"]["grep"]["timeouts"], 1, "错误名带 timeout 的另计超时")

    def test_tool_errors_are_counted_once_across_runs(self):
        """会话日志增长后第二轮只写新增的调用与错误（按差写，不按整份快照写）。"""
        self.write_trace()
        self.run_summarize(apply=True, run="2026-10-17-0900")
        first = [r for r in self.rows() if r["kind"] == "tool" and r["id"] == "grep"][0]
        self.assertEqual((first["calls"], first["errors"]), (1, 1))
        # 追加一次无错误的调用：日志变了，错误数没变
        log = self.root / "sessions" / "ws" / "demo-sid" / "session.jsonl.zstd"
        log.write_text(SESSION_LOG + "\n" + "\n".join([
            json.dumps({"type": "tool/call", "time": 5000,
                        "data": {"turn": 1, "step": 3, "callId": "c4", "name": "grep",
                                 "arguments": '{"pattern": "x"}'}}),
            json.dumps({"type": "tool/result", "time": 5100,
                        "data": {"message": {"source": {"kind": "tool", "callId": "c4"},
                                             "content": [{"type": "tool-result",
                                                          "content": [{"type": "text", "text": "ok"}]}]}}}),
        ]), encoding="utf-8")
        self.run_summarize(apply=True, run="2026-10-17-0910")
        rows = [r for r in self.rows() if r["kind"] == "tool" and r["id"] == "grep"]
        self.assertEqual(len(rows), 2, "两轮各一行")
        self.assertEqual(sum(r["calls"] for r in rows), 2)
        self.assertEqual(sum(r["errors"] for r in rows), 1, "错误只记一次")
        self.assertEqual(sum(r["timeouts"] for r in rows), 1)

    def test_args_summary_keeps_only_the_identifying_bit(self):
        log, _ = tea.read_session_log(
            self.sessions / "ws" / "demo-sid" / "session.jsonl.zstd")
        by = {c["tool"]: c for c in log["tool_calls"]}
        self.assertEqual(by["read"]["args"], "/x/y.yaml")
        self.assertEqual(by["grep"]["args"], "507014")


class StepCostTest(Fixture):
    """每步成本：靠 `ts` 切窗口把会话日志折进诊断步。"""

    def test_no_ts_means_no_guess(self):
        """轨迹没有 ts → 返回 None（面板显示「本次没记」），不按顺序猜。"""
        log, _ = tea.read_session_log(self.sessions / "ws" / "demo-sid" / "session.jsonl.zstd")
        self.assertIsNone(tea.step_cost([{"step": 1}, {"step": 2}], log))

    def test_one_timestamped_step_is_not_enough(self):
        log, _ = tea.read_session_log(self.sessions / "ws" / "demo-sid" / "session.jsonl.zstd")
        self.assertIsNone(tea.step_cost([{"step": 1, "ts": 1000}], log))

    def test_calls_and_tokens_are_folded_into_their_window(self):
        log = {
            "tool_calls": [
                {"tool": "read", "t": 1000, "ms": 100, "step": 1},
                {"tool": "grep", "t": 2500, "ms": 300, "step": 1},
                {"tool": "bash", "t": 4000, "ms": 50, "step": 2},
            ],
            "usage_points": [
                {"t": 1100, "uncached": 10, "cache_read": 5, "cache_write": 0, "out": 2},
                {"t": 2600, "uncached": 7, "cache_read": 3, "cache_write": 0, "out": 1},
                {"t": 4100, "uncached": 1, "cache_read": 0, "cache_write": 0, "out": 9},
            ],
        }
        trace = [{"step": 1, "ts": 900}, {"step": 2, "ts": 3000}]
        out = {r["step"]: r for r in tea.step_cost(trace, log)}
        self.assertEqual((out[1]["calls"], out[1]["ms"]), (2, 400))
        self.assertEqual((out[2]["calls"], out[2]["ms"]), (1, 50))
        self.assertEqual(out[1]["tokens"]["uncached"], 17)
        self.assertEqual(out[2]["tokens"]["out"], 9)
        self.assertEqual(out[1]["tools"], ["grep", "read"])

    def test_ts_accepts_epoch_ms_seconds_and_iso(self):
        self.assertEqual(tea._epoch_ms(1792222333444), 1792222333444)
        self.assertEqual(tea._epoch_ms(1792222333.444), 1792222333444)
        self.assertEqual(tea._epoch_ms("1970-01-01T00:00:01+00:00"), 1000)
        self.assertIsNone(tea._epoch_ms("刚刚"))

    def test_real_row_shape_survives_the_join(self):
        """每步成本只留本机明细，不进记录行（明细含命令摘要与现场信息）。"""
        log, _ = tea.read_session_log(self.sessions / "ws" / "demo-sid" / "session.jsonl.zstd")
        self.assertIn("usage_points", log)
        self.assertTrue(all("t" in c for c in log["tool_calls"]))


class SessionLogDiscoveryTest(unittest.TestCase):
    """会话日志根不止一个：面板调子进程时环境里不一定有 DSH_HOME。"""

    def test_finds_the_session_under_any_candidate_root(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty" / "sessions"
            empty.mkdir(parents=True)
            real = Path(tmp) / "real" / "sessions"
            d = real / "ws" / "sid-x"
            d.mkdir(parents=True)
            (d / "session.v4.jsonl.zstd").write_text("x", encoding="utf-8")
            path, why = tea.find_session_log("sid-x", [empty, real])
            self.assertIsNone(why)
            self.assertEqual(path.parent, d, "第二个候选根里有这一单，也要找得到")

    def test_finds_bare_and_prefixed_session_dirs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sessions"
            bare = root / "ws" / "41b83c2c-a23d-46c0-91d0-ef717f5d3611"
            prefixed = root / "ws" / "session-79ddff11-219d-4fa7-a68f-76144ebacdca"
            bare.mkdir(parents=True)
            prefixed.mkdir(parents=True)
            (bare / "session.v4.jsonl.zstd").write_text("x", encoding="utf-8")
            (prefixed / "session.v4.jsonl.zstd").write_text("x", encoding="utf-8")
            # 带前缀的 id 要找到裸目录，裸 id 要找到带前缀目录。
            path, why = tea.find_session_log("session-41b83c2c-a23d-46c0-91d0-ef717f5d3611",
                                             [root])
            self.assertIsNone(why)
            self.assertEqual(path.parent, bare)
            path, why = tea.find_session_log("79ddff11-219d-4fa7-a68f-76144ebacdca", [root])
            self.assertIsNone(why)
            self.assertEqual(path.parent, prefixed)

    def test_miss_lists_the_roots_it_tried(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a"
            b = Path(tmp) / "b"
            a.mkdir(); b.mkdir()
            path, why = tea.find_session_log("nope", [a, b])
            self.assertIsNone(path)
            self.assertIn(str(a), why)
            self.assertIn(str(b), why)

    def test_env_root_comes_first(self):
        old = os.environ.get("DSH_HOME")
        os.environ["DSH_HOME"] = "/tmp/dsh-home-x"
        try:
            self.assertEqual(tea.harness_homes()[0], Path("/tmp/dsh-home-x"))
        finally:
            if old is None:
                os.environ.pop("DSH_HOME", None)
            else:
                os.environ["DSH_HOME"] = old

    def test_default_lookup_walks_harness_homes(self):
        """不传 sessions_root 时真的按 harness_homes() 逐个找（面板调子进程的路径）。"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "dsh-home"
            d = home / "sessions" / "ws" / "sid-env"
            d.mkdir(parents=True)
            (d / "session.v4.jsonl.zstd").write_text("x", encoding="utf-8")
            old = os.environ.get("DSH_HOME")
            os.environ["DSH_HOME"] = str(home)
            try:
                path, why = tea.find_session_log("sid-env")
            finally:
                if old is None:
                    os.environ.pop("DSH_HOME", None)
                else:
                    os.environ["DSH_HOME"] = old
            self.assertIsNone(why)
            self.assertEqual(path.parent, d)

    def test_desktop_app_dirs_are_scanned_one_level(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            good = base / "dsh-desktop" / "harness" / "sessions"
            good.mkdir(parents=True)
            (base / "other-app" / "harness").mkdir(parents=True)
            homes = tea.app_harness_roots(base)
            self.assertEqual([h.parent.name for h in homes], ["dsh-desktop"],
                             "只收 sessions/ 存在的应用目录")


class WindowCostTest(Fixture):
    """诊断窗口内的成本：同一条会话里做过两单时，两单的读数必须分开。

    会话日志记的是整条会话的账。窗口切错时不会报错：两行读数一模一样，读者会读成
    「两次诊断一样贵」——这正是这组用例要钉住的那类失效。
    """

    def trace_doc(self, **kw):
        d = {"created_at": "2026-10-16T12:00:00+08:00",
             "updated_at": "2026-10-16T13:00:00+08:00"}
        d.update(kw)
        return d

    def ms(self, iso):
        return tea._epoch_ms(iso)

    def log(self):
        inside = self.ms("2026-10-16T12:30:00+08:00")
        before = self.ms("2026-10-16T11:00:00+08:00")
        after = self.ms("2026-10-16T14:00:00+08:00")
        return {
            "tool_calls": [
                {"tool": "read", "t": before, "ms": 1000, "step": 1},
                {"tool": "read", "t": inside, "ms": 120, "step": 1},
                {"tool": "grep", "t": inside + 500, "ms": 300, "step": 2},
                {"tool": "bash", "t": after, "ms": 5000, "step": 9},
            ],
            "usage_points": [
                {"t": before, "uncached": 999, "cache_read": 0, "cache_write": 0, "out": 0},
                {"t": inside, "uncached": 100, "cache_read": 10, "cache_write": 5, "out": 20},
                {"t": after, "uncached": 777, "cache_read": 0, "cache_write": 0, "out": 0},
            ],
        }

    def test_calls_and_tokens_outside_the_window_are_not_counted(self):
        w = tea.window_cost(self.trace_doc(), self.log())
        self.assertEqual(w["calls"], 2)
        self.assertEqual(w["ms"], 420)
        self.assertEqual(w["tokens"], {"uncached": 100, "cache_read": 10,
                                       "cache_write": 5, "out": 20})
        self.assertEqual((w["outside_calls"], w["outside_ms"]), (2, 6000),
                         "窗口外的调用只计数，不进这一单的成本")

    def test_updated_at_marks_the_window_truncated(self):
        w = tea.window_cost(self.trace_doc(), self.log())
        self.assertEqual(w["bound_to"], "updated_at")
        self.assertTrue(w["truncated"], "没有 ended_at 时后段可能混进诊断之外的活，要标出来")
        w2 = tea.window_cost(self.trace_doc(ended_at="2026-10-16T12:45:00+08:00"), self.log())
        self.assertEqual(w2["bound_to"], "ended_at")
        self.assertFalse(w2["truncated"])

    def test_missing_endpoints_are_not_guessed(self):
        self.assertIsNone(tea.window_cost({"created_at": "2026-10-16T12:00:00+08:00"}, self.log()),
                          "缺右边界时不给数，不拿整份日志顶替")
        self.assertIsNone(tea.window_cost({"updated_at": "2026-10-16T13:00:00+08:00"}, self.log()))
        self.assertIsNone(tea.window_cost(self.trace_doc(), None))

    def test_end_before_start_is_not_a_window(self):
        """结束早于开始（或相等）时切不出区间：返回 None，不拿它去统计。"""
        self.assertIsNone(tea.window_cost(self.trace_doc(ended_at="2026-10-16T11:00:00+08:00"),
                                          self.log()))
        self.assertIsNone(tea.window_cost(self.trace_doc(ended_at="2026-10-16T12:00:00+08:00"),
                                          self.log()))

    def test_long_calls_are_counted_separately(self):
        """机器休眠会让一次调用的墙钟时长到小时级：合计里标出来，不从合计里扣。"""
        inside = self.ms("2026-10-16T12:30:00+08:00")
        log = {"tool_calls": [
            {"tool": "read", "t": inside, "ms": tea.LONG_CALL_MS + 1, "step": 1},
            {"tool": "bash", "t": inside + 10, "ms": 40, "step": 1},
        ], "usage_points": []}
        w = tea.window_cost(self.trace_doc(), log)
        self.assertEqual((w["long_calls"], w["long_ms"]), (1, tea.LONG_CALL_MS + 1))
        self.assertEqual(w["long_threshold_ms"], tea.LONG_CALL_MS)
        self.assertEqual(w["ms"], tea.LONG_CALL_MS + 41, "长调用仍计入合计")
        # 阈值口径：文案写「超过 10 分钟」，恰好 10 分钟不算
        edge = {"tool_calls": [{"tool": "read", "t": inside, "ms": tea.LONG_CALL_MS, "step": 1}],
                "usage_points": []}
        self.assertEqual(tea.window_cost(self.trace_doc(), edge)["long_calls"], 0)

    def test_pending_calls_are_reported_not_counted_as_zero_ms(self):
        inside = self.ms("2026-10-16T12:30:00+08:00")
        log = {"tool_calls": [{"tool": "bash", "t": inside, "ms": None, "step": 1}],
               "usage_points": []}
        w = tea.window_cost(self.trace_doc(), log)
        self.assertEqual((w["calls"], w["pending"], w["ms_complete"]), (1, 1, False))

    def test_detail_record_carries_the_window(self):
        """本机明细里必须有 cost.window：面板的耗时与 token 两列读它。"""
        self.write_trace()
        self.run_summarize(apply=True)
        doc = ea.read_local_record(self.local, TRACE["session_id"])
        w = doc["cost"]["window"]
        self.assertIsNotNone(w)
        self.assertEqual(w["calls"], 0, "夹具日志的时间戳在 1970 年，落在窗口外")
        self.assertEqual(w["outside_calls"], 2)
        self.assertEqual(doc["cost"]["tokens"]["out"], 20, "本会话累计仍原样保留")

    def test_local_only_writes_detail_without_rows_or_cursor(self):
        """面板自动重建走这一档：只写 gitignored 的本机明细，不写源行、不动游标。

        为什么单钉：游标更新没有锁、且按「上次游标之后」计增量；面板若走 --apply 自动重建，
        会把用户聊天里的工具调用记进诊断指标，并与其他 session 抢游标。
        """
        self.write_trace()
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = tea.build_records(self.root, self.traces, self.sessions, None, True,
                                   "2026-10-16-1500", self.state, use_log=True,
                                   local_dir=self.local, local_only=True)
        self.assertEqual(rc, 0)
        self.assertIn("只写本机明细", buf.getvalue())
        doc = ea.read_local_record(self.local, TRACE["session_id"])
        self.assertIsNotNone(doc, "本机明细要写出来")
        self.assertIn("window", doc["cost"])
        self.assertEqual(self.rows(), [], "不得写 metrics/entry-activity.d/ 的增量行")
        self.assertFalse(self.state.exists(), "不得落下共享游标")

    def test_local_only_reports_even_when_no_new_rows(self):
        """第二轮没有新行时也要打印「只写本机明细」，不能打印成「不写任何行」——明细确实写了。"""
        self.write_trace()
        self.run_summarize(apply=True)          # 第一轮把增量行与游标写掉
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = tea.build_records(self.root, self.traces, self.sessions, None, True,
                                   "2026-10-17-0900", self.state, use_log=True,
                                   local_dir=self.local, local_only=True)
        self.assertEqual(rc, 0)
        self.assertIn("只写本机明细", buf.getvalue())
        self.assertNotIn("不写任何行", buf.getvalue())

    def test_detail_record_counts_calls_inside_the_window(self):
        """窗口内的调用与用量进 cost.window；与 cost.tokens（本会话累计）分开写。"""
        doc = dict(TRACE)
        doc["created_at"] = "1970-01-01T00:00:00+00:00"
        doc["updated_at"] = "1970-01-01T00:00:10+00:00"
        self.write_trace(doc)
        self.run_summarize(apply=True)
        rec = ea.read_local_record(self.local, TRACE["session_id"])
        w = rec["cost"]["window"]
        self.assertEqual((w["calls"], w["ms"]), (2, 400), "夹具里的两次调用都落在窗口内")
        self.assertEqual(w["tokens"]["uncached"], 100)
        self.assertEqual(w["outside_calls"], 0)
        self.assertEqual(rec["cost"]["tokens"]["out"], 20, "本会话累计同时保留")


class NoDegradationTest(Fixture):
    """会话日志没了的那一轮，不得把已有的好明细覆盖成空。"""

    def test_existing_detail_is_kept_when_session_log_disappears(self):
        self.write_trace()
        self.run_summarize(apply=True)          # 第一轮：日志在，明细里成本齐全
        good = ea.read_local_record(self.local, TRACE["session_id"])
        self.assertTrue(good["cost"]["tokens"], "前置：第一轮明细里有四类 token")
        # 模拟面板子进程拿不到 DSH_HOME：日志目录找不到
        shutil.rmtree(self.sessions / "ws" / "demo-sid")
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = tea.build_records(self.root, self.traces, self.sessions, None, True,
                                   "2026-10-16-1600", self.state, use_log=True,
                                   local_dir=self.local, local_only=True)
        self.assertEqual(rc, 2, "没找到日志时要非零退出，面板据此报失败")
        after = ea.read_local_record(self.local, TRACE["session_id"])
        self.assertEqual(after["cost"]["tokens"], good["cost"]["tokens"], "旧明细不被空记录覆盖")
        self.assertIn("保留已有明细", buf.getvalue())

    def test_offline_mode_is_not_treated_as_degraded(self):
        """`--no-session-log` 是文档化的离线模式：不读日志不是"日志缺席"，不该拦。"""
        self.write_trace()
        self.run_summarize(apply=True)
        good = ea.read_local_record(self.local, TRACE["session_id"])
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = tea.build_records(self.root, self.traces, self.sessions, None, True,
                                   "2026-10-16-1700", self.state, use_log=False,
                                   local_dir=self.local, local_only=True)
        self.assertEqual(rc, 0, "离线模式不该按失败退出")
        after = ea.read_local_record(self.local, TRACE["session_id"])
        self.assertIsNone(after["cost"]["tokens"], "离线那一轮本来就该写空的成本字段")
        self.assertNotIn("保留已有明细", buf.getvalue())


class DeltaTest(Fixture):
    def test_first_run_writes_rows_for_every_touched_entry(self):
        self.write_trace()
        self.run_summarize(apply=True)
        kinds = {(r["kind"], r["id"]) for r in self.rows()}
        self.assertIn(("case", "CASE-HIT"), kinds)
        self.assertIn(("ref", "ref-one"), kinds)
        self.assertIn(("tool", "read"), kinds)

    def test_second_run_without_changes_writes_nothing(self):
        self.write_trace()
        self.run_summarize(apply=True)
        before = len(self.rows())
        out = self.run_summarize(apply=True, run="2026-10-16-1500")
        self.assertEqual(len(self.rows()), before, "没有新事实时不写行")
        self.assertIn("没有新的条目使用增量", out)

    def test_newly_appended_events_are_folded_incrementally(self):
        """轨迹追加事件后重跑：只写新增的那部分（不按累计值重写）。"""
        self.write_trace()
        self.run_summarize(apply=True)
        doc = dict(TRACE)
        doc["trace"] = TRACE["trace"] + [
            {"role": "agent", "step": 5, "action": "hit", "case": "CASE-NEW"}]
        self.write_lib(cases=("CASE-A", "CASE-B", "CASE-HIT", "CASE-EX", "CASE-NEW"))
        self.write_trace(doc)
        self.run_summarize(apply=True, run="2026-10-16-1500")
        rows = [r for r in self.rows() if r["id"] == "CASE-NEW"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["selected"], 1)

    def test_local_detail_is_written_with_tool_calls(self):
        self.write_trace()
        self.run_summarize(apply=True)
        doc = ea.read_local_record(self.local, TRACE["session_id"])
        self.assertEqual(doc["session_id"], TRACE["session_id"])
        self.assertEqual(doc["detected"]["framework"], "vllm-ascend")
        self.assertEqual(len(doc["tool_calls"]), 2)
        self.assertEqual(doc["cost"]["tokens"]["out"], 20)
        self.assertEqual(doc["strength"], "self-report")

    def test_missing_session_log_is_reported_not_estimated(self):
        self.write_trace(dict(TRACE, harness_session="nonexistent"))
        out = self.run_summarize(apply=True)
        self.assertIn("会话成本与工具分布缺席", out)
        self.assertEqual([r for r in self.rows() if r["kind"] == "tool"], [])
        doc = ea.read_local_record(self.local, TRACE["session_id"])
        self.assertIsNone(doc["cost"]["tokens"])

    def test_tool_snapshot_survives_a_run_without_logs(self):
        """日志读不到的一轮不清零工具快照，否则下一轮可读时会把整段调用重算一次。"""
        self.write_trace()
        self.run_summarize(apply=True)
        first = [r for r in self.rows() if r["kind"] == "tool"]
        self.assertEqual(len(first), 2, "read 与 grep 各一行")
        # 这一轮不读日志（模拟 node 不可用）：不得把工具快照清零
        self.run_summarize(apply=True, run="2026-10-16-1500", use_log=False)
        self.run_summarize(apply=True, run="2026-10-16-1600")
        again = [r for r in self.rows() if r["kind"] == "tool"]
        self.assertEqual(len(again), 2, "日志恢复可读后不得把已经记过的调用重算一遍")


class RefNormalisationTest(Fixture):
    def test_path_shaped_ref_id_is_normalised_to_entry_id(self):
        self.write_lib(refs=("cann-runtime-error-codes",))
        doc = dict(TRACE)
        doc["trace"] = [{"role": "agent", "step": 2, "action": "reference_lookup",
                         "ref_id": "references/errors/cann-runtime-error-codes.yaml",
                         "purpose": "signature", "outcome": "hit"}]
        self.write_trace(doc)
        self.run_summarize(apply=True)
        ids = [r["id"] for r in self.rows() if r["kind"] == "ref"]
        self.assertEqual(ids, ["cann-runtime-error-codes"], "记录按词条 id 建键，不按文件路径")

    def test_unresolvable_ref_value_is_reported_and_not_recorded(self):
        """归不到词条的写法（如指向索引生成物）不写进记录，但要在输出里报出来。"""
        doc = dict(TRACE)
        doc["trace"] = [{"role": "agent", "step": 2, "action": "reference_lookup",
                         "ref_id": "references/_procedure-index.yaml",
                         "purpose": "procedure", "outcome": "skipped"}]
        self.write_trace(doc)
        out = self.run_summarize(apply=True)
        self.assertIn("归不到任何词条 id", out)
        self.assertEqual([r["id"] for r in self.rows() if r["kind"] == "ref"],
                         [], "归不到词条的值不写进记录（不造 id 是路径的假条目）")


class IndexReadAccountTest(Fixture):
    def test_four_components_are_reported_or_none(self):
        self.write_lib(refs=("ref-one",))
        (self.root / "knowledge" / "_index").mkdir(parents=True, exist_ok=True)
        (self.root / "knowledge" / "_index" / "inference__vllm-ascend__interrupt.list").write_text(
            "id: CASE-A | title: x\n", encoding="utf-8")
        facts = tea.trace_facts(TRACE)
        facts["_ref_paths"] = tea.ref_index(self.root)[0]
        acc = tea.index_read_account(self.root, facts, tea.case_index(self.root)[0],
                                     category="interrupt")
        self.assertIsNotNone(acc["class_view"])
        self.assertIsNotNone(acc["reference_layer"])
        self.assertIsNotNone(acc["candidates_full"])
        self.assertIsNone(acc["fallback_view"], "没读兜底视图就是 None，不是 0")


if __name__ == "__main__":
    unittest.main()
