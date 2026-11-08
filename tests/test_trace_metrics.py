"""trace_metrics 的口径回归测试。

`metrics/timeline.yaml` 的诊断侧读数（命中率、路由准确率、误诊率、reference 三态）
全部由本脚本从 trace 现算，然后被周批、面板与 EV 门控读走。这里用合成 trace 断死口径：
命中怎么算、路由对错怎么判、误诊率的分母是什么、`skipped` 为什么不能算作"查了没命中"。

做法：`--traces-dir` 指向 tmp 目录（该参数为本卡新增，默认行为不变——仍解析到主检出），
`--emit-yaml-only` 拿机器可读快照，断言打在字段值上。

用例引用的 case id 从生成的 `knowledge/_index.yaml` 里现取（不硬编码），case 增删不会让本测试腐烂。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

SESSION_TMPL = """session_id: {sid}
status: {status}
trace:
  - role: user
    content: "报错：测试输入"
  - role: agent
    action: triage
    routed: [{routed}]
    category: {cat}
  - role: agent
    action: hit
    case: {case}
{extra}"""


def pick_cases():
    """从索引里取两个不同 namespace 的真实 case id。"""
    doc = yaml.safe_load((ROOT / "knowledge" / "_index.yaml").read_text(encoding="utf-8"))
    first = second = None
    for ns, cells in (doc.get("namespaces") or {}).items():
        for entries in cells.values():
            for e in entries or []:
                if not first:
                    first = (ns, e["id"])
                elif ns != first[0] and not second:
                    second = (ns, e["id"])
    assert first and second, "索引里至少要有两个不同 namespace 的 case"
    return first, second


class _MetricsHarness(unittest.TestCase):
    """合成 trace + 跑 `trace_metrics.py` 的公共装置（本文件两个测试类共用）。"""

    @classmethod
    def setUpClass(cls):
        # pick_cases() 返回 ((ns, id), (ns2, id2))——两组不同 namespace
        (cls.ns_a, cls.case_a), (cls.ns_b, cls.case_b) = pick_cases()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.traces = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write_session(self, sid, status="resolved", routed=None, cat="interrupt",
                      case=None, extra="", hit=True):
        ns_list = [self.ns_a] if routed is None else routed   # [] = 显式"没有路由信息"
        case_val = case or self.case_a
        text = SESSION_TMPL.format(sid=sid, status=status, cat=cat,
                                   routed=", ".join(ns_list), case=case_val, extra=extra)
        if not hit:   # 模拟"路由到了但没命中"：去掉 hit 行
            text = text.replace("  - role: agent\n    action: hit\n    case: %s\n" % case_val, "")
        (self.traces / f"{sid}.yaml").write_text(text, encoding="utf-8")

    def run_metrics(self, *extra_args):
        # `encoding="utf-8"` 必须显式给：脚本侧把 stdout 钉成 UTF-8（scripts/_stdio.py），
        # 而 Windows 上的父进程按 locale（中文系统 = GBK）解码，读线程会抛 UnicodeDecodeError、
        # `r.stdout` 留 None——本地看到的是"空输出"，Linux CI 不暴露。
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "trace_metrics.py"),
             "--root", str(ROOT), "--traces-dir", str(self.traces), *extra_args],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def metrics(self):
        return (yaml.safe_load(self.run_metrics("--emit-yaml-only")) or {}).get("metrics") or {}

    def metrics_json(self, *extra_args):
        return json.loads(self.run_metrics("--json", *extra_args))


class TraceMetricsTest(_MetricsHarness):
    # ---------------------------------------------------------------- 命中口径
    def test_hit_requires_a_hit_event(self):
        """tier2_hit 只数有 hit 事件的 session——「路由到了」不等于「命中了」。"""
        self.write_session("s1-hit", case=self.case_a)
        self.write_session("s2-no-hit", routed=[self.ns_a], hit=False)
        m = self.metrics()
        self.assertEqual(m["sessions_total"], 2)
        self.assertEqual(m["tier2_hit"], 1)

    # ---------------------------------------------------------------- 路由准确率
    def test_routing_accuracy_compares_routed_ns_with_hit_case_ns(self):
        """分母 = 有 hit 且带路由且 case 在索引里的 session；分子 = 路由与 case 归属一致。"""
        self.write_session("s1-ok", routed=[self.ns_a], case=self.case_a)
        self.write_session("s2-wrong", routed=[self.ns_b], case=self.case_a)
        m = self.metrics()
        self.assertEqual(m["routed_accuracy"], {"ok": 1, "total": 2})

    def test_routing_needs_a_routed_namespace(self):
        """没有路由信息的命中 session 不进分母（不猜）。"""
        self.write_session("s1-ok", routed=[self.ns_a], case=self.case_a)
        self.write_session("s2-noroute", routed=[], case=self.case_a)
        m = self.metrics()
        self.assertEqual(m["routed_accuracy"], {"ok": 1, "total": 1})

    # ---------------------------------------------------------------- 误诊率
    def test_misdiagnosis_denominator_is_tier2_hit(self):
        """误诊率 = 反馈 not_resolved/partial 的命中 session / 命中 session 总数。"""
        self.write_session(
            "s1-bad", case=self.case_a,
            extra="  - role: agent\n    action: feedback\n    case: %s\n    outcome: not_resolved\n" % self.case_a)
        self.write_session(
            "s2-good", case=self.case_a,
            extra="  - role: agent\n    action: feedback\n    case: %s\n    outcome: resolved\n" % self.case_a)
        self.write_session("s3-nofeedback", case=self.case_a)
        m = self.metrics()
        self.assertEqual(m["tier2_hit"], 3)
        self.assertEqual(m["misdiagnosis_rate"], {"ok": 1, "total": 3})
        self.assertEqual(m["feedback_capture"], {"resolved": 1, "not_resolved": 1, "partial": 0})

    # ---------------------------------------------------------------- reference 三态
    def test_reference_skipped_is_not_counted_as_a_hit(self):
        """`skipped` = 本触发点没查：不得计入引用次数，也不得读成「查了没命中」。"""
        self.write_session(
            "s1-ref", case=self.case_a,
            extra=("  - role: agent\n    action: reference_lookup\n    ref_id: some-ref\n"
                   "    outcome: hit\n    purpose: signature\n"
                   "  - role: agent\n    action: reference_lookup\n    ref_id: skipped-ref\n"
                   "    outcome: skipped\n    purpose: background\n"))
        m = self.metrics()
        self.assertEqual(m["reference"]["hits"], 1, "skipped 不得计入引用次数")
        self.assertEqual(m["reference_outcomes"], {"hit": 1, "skipped": 1})

    def test_triage_miss_classes_split_three_ways(self):
        """triage 未命中要分三类记（EV-2026-110）：真缺陷 / 级联换挡 / 记录缺口。

        - lexical_gap：有语义兜底（或显式空 routed），且输入里有 token 类信号 → 词法层该接住却没接住
        - semantic_path：有语义兜底，但输入是纯自由语言、没有任何 token → 级联按设计换挡
        - routed_unrecorded：有 triage 事件但 routed 字段没记 → E2 错例池的取数字段缺口
        分支命中的 session 不计入任何一类。
        """
        import shutil
        fx = ROOT / "tests" / "fixtures" / "traces_ev110"
        for f in fx.glob("*.yaml"):
            shutil.copy(f, self.traces / f.name)
        m = self.metrics()
        self.assertEqual(m["triage_miss_classes"],
                         {"lexical_gap": 1, "semantic_path": 1,
                          "routed_unrecorded": 1, "no_triage_event": 0})
        self.assertEqual(m["triage_miss_sessions"]["lexical_gap"], ["ev110-lexical"])
        self.assertEqual(m["triage_miss_sessions"]["routed_unrecorded"], ["ev110-unrecorded"])

    def test_missing_traces_reports_instead_of_faking(self):
        """空 traces 目录 → 如实说明，不产出假读数。"""
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "trace_metrics.py"),
             "--root", str(ROOT), "--traces-dir", str(self.traces)],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0)
        self.assertIn("未找到任何 traces", r.stdout)


class OfflineReplayRecordsTest(_MetricsHarness):
    """零执行评估所需的三项记录：停止原因 / 同批并发标记 / 候选全集。

    三项都是换一个策略在这段历史上走一遍的前提：不知道当时在哪停、哪些动作是同一批并发、
    筛候选时看过哪些，重放只能按人回忆重讲。记录缺了就按未记录计数，不回填，也不猜：
    所以这里断的是记录了怎么算与没记录怎么算两件事，而不是逼旧 trace 补字段。
    """

    def test_stop_reason_counted_and_missing_counted_separately(self):
        """顶层 stop_reason：记了的进分布，没记的进未记录数——两者不混算。"""
        self.write_session("s1-stop", extra="stop_reason: halted_ask_user\n")
        self.write_session("s2-nostop")
        m = self.metrics()
        self.assertEqual(m["stop_reasons"], {"halted_ask_user": 1})
        self.assertEqual(m["stop_reason_unrecorded"], 1)

    def test_out_of_vocabulary_stop_reason_is_reported(self):
        """词表外的停止原因照样进分布，同时按字段违规报出来（不静默收下）。"""
        self.write_session("s1-badstop", extra="stop_reason: guessed\n")
        m = self.metrics()
        self.assertEqual(m["stop_reasons"], {"guessed": 1})
        self.assertEqual(m["trace_record_violations"], ["s1-badstop: stop_reason='guessed'"])

    def test_parallel_group_and_considered_candidates_counted(self):
        """两项事件记录各自计数；候选全集包含实际取全文的候选时不报违规。"""
        self.write_session(
            "s1-records",
            extra=("  - role: agent\n"
                   "    action: load_full\n"
                   "    parallel_group: g1\n"
                   '    candidates: ["VLLM-ASC-0001", "VLLM-ASC-0002"]\n'
                   '    considered_candidates: ["VLLM-ASC-0001", "VLLM-ASC-0002", "VLLM-ASC-0003"]\n'),
        )
        m = self.metrics()
        self.assertEqual(m["parallel_group_events"], 1)
        self.assertEqual(m["considered_candidates_events"], 1)
        self.assertNotIn("trace_record_violations", m)

    def test_full_text_candidate_outside_considered_is_a_violation(self):
        """取全文的候选不在候选全集里 = 两次记录对不上，按违规报出来。"""
        self.write_session(
            "s1-lack",
            extra=("  - role: agent\n"
                   "    action: load_full\n"
                   '    candidates: ["VLLM-ASC-0001"]\n'
                   '    considered_candidates: ["VLLM-ASC-0002"]\n'),
        )
        m = self.metrics()
        self.assertEqual(
            m["trace_record_violations"],
            ["s1-lack: 取全文的候选不在 considered_candidates 里 ['VLLM-ASC-0001']"])

    def test_non_string_stop_reason_is_a_violation_not_a_crash(self):
        """stop_reason 写成列表/字典：报违规并继续出读数，不会让整个脚本中断。"""
        self.write_session("s1-liststop", extra="stop_reason: [budget_exhausted, abandoned]\n")
        m = self.metrics()
        self.assertEqual(
            m["trace_record_violations"],
            ["s1-liststop: stop_reason 应为字符串（['budget_exhausted', 'abandoned']）"])
        self.assertEqual(m["stop_reason_unrecorded"], 0)
        self.assertNotIn("stop_reasons", m)

    def test_non_list_candidates_is_a_violation(self):
        """取全文的候选写成字符串：与 considered_candidates 的类型检查对齐，按违规报出来。

        候选全集在不在都要报：全集缺了不等于这条记录没问题。
        """
        self.write_session(
            "s1-strcand",
            extra=("  - role: agent\n"
                   "    action: load_full\n"
                   '    candidates: "VLLM-ASC-0001"\n'
                   '    considered_candidates: ["VLLM-ASC-0002"]\n'),
        )
        self.write_session(
            "s1-strcand-nocc",
            extra=("  - role: agent\n"
                   "    action: load_full\n"
                   '    candidates: "VLLM-ASC-0001"\n'),
        )
        m = self.metrics()
        self.assertEqual(
            sorted(m["trace_record_violations"]),
            sorted(["s1-strcand: candidates 应为候选 id 列表（'VLLM-ASC-0001'）",
                    "s1-strcand-nocc: candidates 应为候选 id 列表（'VLLM-ASC-0001'）"]))

    def test_violation_total_counts_past_the_listed_five(self):
        """违规超过 5 处时列表只留前 5 条，总数另记——否则看不出是 5 处还是 50 处。"""
        for i in (1, 2, 3):
            self.write_session(
                f"s{i}-two",
                extra=("  - role: agent\n"
                       "    action: load_full\n"
                       "    parallel_group: ''\n"
                       "stop_reason: guessed\n"),
            )
        m = self.metrics()
        self.assertEqual(len(m["trace_record_violations"]), 5)
        self.assertEqual(m["trace_record_violations_total"], 6)


class KbBaselineSliceTest(_MetricsHarness):
    """知识基线切片（RFC #432）：kb_behind 三组解决率 + kb_merge 触发率。

    解决率的分母是组内 session 数，判据沿用脚本内 `status == "resolved"`——与 reference
    引用后 resolve、Tier 3 挽救同一处，不另立一套。字段缺失（旧 trace）计入 unknown 组，
    不回填、不猜。
    """

    def test_old_trace_without_fields_goes_to_unknown(self):
        """旧 trace 两个字段都没有：只进 unknown 组，其余两组无样本。"""
        self.write_session("s1-old")
        kb = self.metrics_json("--kb-baseline")["kb_baseline"]
        self.assertEqual(kb["resolution"]["unknown"], {"ok": 1, "total": 1})
        self.assertEqual(kb["resolution"]["behind"], {"ok": 0, "total": 0})
        self.assertEqual(kb["resolution"]["current"], {"ok": 0, "total": 0})
        self.assertEqual(kb["merge"], {"ff_only": 0, "total": 0})

    def test_behind_zero_and_positive_split_into_two_groups(self):
        """kb_behind = 0 进「最新」，> 0 进「落后」；解决与否按 status 判。"""
        self.write_session("s1-current", status="resolved", extra="kb_behind: 0\n")
        self.write_session("s2-behind", status="not_resolved", extra="kb_behind: 7\n")
        self.write_session("s3-behind", status="resolved", extra="kb_behind: 3\n")
        kb = self.metrics_json("--kb-baseline")["kb_baseline"]
        self.assertEqual(kb["resolution"]["current"], {"ok": 1, "total": 1})
        self.assertEqual(kb["resolution"]["behind"], {"ok": 1, "total": 2})
        self.assertEqual(kb["resolution"]["unknown"], {"ok": 0, "total": 0})

    def test_unknown_literal_and_missing_share_one_group(self):
        """`kb_behind: "unknown"` 与字段缺失同列 unknown，不与数字组混算。"""
        self.write_session("s1-unknown", extra='kb_behind: "unknown"\n')
        self.write_session("s2-missing")
        self.write_session("s3-behind", status="not_resolved", extra="kb_behind: 2\n")
        kb = self.metrics_json("--kb-baseline")["kb_baseline"]
        self.assertEqual(kb["resolution"]["unknown"], {"ok": 2, "total": 2})
        self.assertEqual(kb["resolution"]["behind"], {"ok": 0, "total": 1})
        self.assertEqual(kb["resolution"]["current"], {"ok": 0, "total": 0})

    def test_merge_rate_counts_only_sessions_with_the_field(self):
        """触发率的分母 = 有 kb_merge 字段的单；ff-only 记触发，none 记未触发。"""
        self.write_session("s1-ff", extra="kb_merge: ff-only\n")
        self.write_session("s2-ff", extra="kb_merge: ff-only\n")
        self.write_session("s3-none", extra="kb_merge: none\n")
        self.write_session("s4-missing")
        kb = self.metrics_json("--kb-baseline")["kb_baseline"]
        self.assertEqual(kb["merge"], {"ff_only": 2, "total": 3})

    def test_slice_is_opt_in_and_stays_out_of_the_snapshot(self):
        """默认输出不含切片；--emit-yaml 即使带开关也不产出该字段（live 白名单）。"""
        self.write_session("s1-kb", extra="kb_behind: 5\nkb_merge: ff-only\n")
        self.assertNotIn("KB 基线切片", self.run_metrics())
        human = self.run_metrics("--kb-baseline")
        self.assertIn("落后 1/1 (100%)", human)
        self.assertIn("ff-only 1/1 (100%)", human)
        snap = yaml.safe_load(self.run_metrics("--emit-yaml-only", "--kb-baseline"))["metrics"]
        self.assertNotIn("kb_baseline", snap)

    def test_invalid_kb_fields_are_reported(self):
        """kb_behind 非整数、kb_merge 词表外：计入 unknown / 分母，同时按字段违规报出来。"""
        self.write_session("s1-bad", extra="kb_behind: many\nkb_merge: fast-forward\n")
        m = self.metrics_json("--kb-baseline")
        self.assertEqual(m["kb_baseline"]["resolution"]["unknown"]["total"], 1)
        self.assertEqual(m["kb_baseline"]["merge"], {"ff_only": 0, "total": 1})
        self.assertEqual(
            m["trace_record_violations"],
            ["s1-bad: kb_behind 应为整数或 'unknown'（'many'）",
             "s1-bad: kb_merge 应为 'ff-only' 或 'none'（'fast-forward'）"])

    def test_unhashable_kb_values_do_not_crash(self):
        """两个字段写成列表：按违规报出，读数照常产出（字段坏了不中断整张表）。"""
        self.write_session("s1-list", extra="kb_behind: [3]\nkb_merge: [ff-only]\n")
        m = self.metrics_json("--kb-baseline")
        self.assertEqual(m["kb_baseline"]["resolution"]["unknown"]["total"], 1)
        self.assertEqual(m["kb_baseline"]["merge"], {"ff_only": 0, "total": 1})
        self.assertEqual(len(m["trace_record_violations"]), 2)


if __name__ == "__main__":
    unittest.main()


class SourceUsageTest(_MetricsHarness):
    """源码取用切片（--source-usage）：仓 / 版本 / 取用退出码 / 验证结果的聚合口径。"""

    def test_counts_repo_ref_exit_and_verify(self):
        extra = (
            "  - role: agent\n    action: source_analysis\n"
            "    repo: vllm-project/vllm-ascend\n    ref: v0.23.0\n"
            "    fetch_exit: 0\n    verify: hit\n"
            "  - role: agent\n    action: source_analysis\n"
            "    repo: vllm-project/vllm-ascend\n    ref: v0.23.0\n"
            "    fetch_exit: 3\n    verify: skipped\n"
            "  - role: agent\n    action: source_analysis\n    tool_calls: []\n"
        )
        self.write_session("s1-src", extra=extra)
        su = self.metrics_json("--source-usage")["source_usage"]
        self.assertEqual(su["events"], 3)
        self.assertEqual(su["repos"], {"vllm-project/vllm-ascend": 2})
        self.assertEqual(su["refs"], {"v0.23.0": 2})
        self.assertEqual(su["fetch_exits"], {"0": 1, "3": 1})
        self.assertEqual(su["verify"], {"hit": 1, "skipped": 1})
        self.assertEqual(su["unrecorded"], 1)
        self.assertIsNone(su["violations"])

    def test_violations_are_reported(self):
        extra = (
            "  - role: agent\n    action: source_analysis\n    repo: r/x\n"
            "    fetch_exit: \"zero\"\n    verify: maybe\n"
        )
        self.write_session("s1-badsrc", extra=extra)
        su = self.metrics_json("--source-usage")["source_usage"]
        self.assertEqual(su["violations_total"], 2)
        self.assertTrue(any("fetch_exit" in v for v in su["violations"]))
        self.assertTrue(any("verify" in v for v in su["violations"]))

    def test_slice_not_in_emit_yaml_and_absent_without_flag(self):
        self.write_session("s1-plain")
        self.assertNotIn("source_usage", self.metrics())
        self.assertNotIn("source_usage", self.metrics_json())
        with_flag = self.metrics_json("--source-usage")
        self.assertIn("source_usage", with_flag)
        self.assertIn("源码取用", self.run_metrics("--source-usage"))
