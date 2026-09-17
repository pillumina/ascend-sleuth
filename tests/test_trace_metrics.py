"""trace_metrics 的口径回归测试。

`metrics/timeline.yaml` 的诊断侧读数（命中率、路由准确率、误诊率、reference 三态）
全部由本脚本从 trace 现算，然后被周批、面板与 EV 门控读走。这里用合成 trace 断死口径：
命中怎么算、路由对错怎么判、误诊率的分母是什么、`skipped` 为什么不能算作"查了没命中"。

做法：`--traces-dir` 指向 tmp 目录（该参数为本卡新增，默认行为不变——仍解析到主检出），
`--emit-yaml-only` 拿机器可读快照，断言打在字段值上。

用例引用的 case id 从生成的 `knowledge/_index.yaml` 里现取（不硬编码），case 增删不会让本测试腐烂。
"""

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


class TraceMetricsTest(unittest.TestCase):
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

    def metrics(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "trace_metrics.py"),
             "--root", str(ROOT), "--traces-dir", str(self.traces), "--emit-yaml-only"],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return (yaml.safe_load(r.stdout) or {}).get("metrics") or {}

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
            capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0)
        self.assertIn("未找到任何 traces", r.stdout)


if __name__ == "__main__":
    unittest.main()
