"""metrics_health 拆分后的函数级回归测试。

`main` 原先整段串在一起：读配置、算容量、拼中文文案、判退出码。拆成
`_load_*` / `_compute_*` / `_render_*` 之后，这里直接调用这些函数，钉住三件事：

- 判据比较（哪条线命中、硬线怎么认、量不出时不当成没越界）；
- 退出码三态（0 全评过 / 1 有违反 / 2 有判据没评过）；
- 人读文案与机器读 payload 的字段来自同一份计算。

黑盒入口断言在 `test_metrics_health.py`，本文件只测拆分出来的函数。
"""

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import metrics_health as MH  # noqa: E402

GATES = [
    {"id": "cell_read_soft_tok", "dimension": "capacity_cell_read_tok",
     "op": ">", "value": 8000, "meaning": "soft", "action": "省"},
    {"id": "cell_read_hard_tok", "dimension": "capacity_cell_read_tok",
     "op": ">=", "value": 20000, "meaning": "hard", "action": "瘦身"},
    {"id": "fallback_read_soft_tok", "dimension": "capacity_fallback_read_tok",
     "op": ">", "value": 8000, "meaning": "fb soft", "action": "改两步法"},
    {"id": "fallback_read_hard_tok", "dimension": "capacity_fallback_read_tok",
     "op": ">=", "value": 20000, "meaning": "fb hard", "action": "切平台"},
]


def capacity(cells=(), fallbacks=(), hits=None, unmeasurable=(), fb_unmeasurable=(),
             structural_unavailable=False, live_ok=True, prev_cells=None, notes=None):
    """构造容量面结果，默认是"量出来了、没越界"的正常态。"""
    return MH._Capacity(list(cells), list(fallbacks), hits or {},
                        list(unmeasurable), list(fb_unmeasurable),
                        structural_unavailable, live_ok, prev_cells or {}, notes or [])


def inputs(gates=(), readability=(), periods=(), fresh=None, load_errors=None):
    """构造读侧结果。"""
    return MH._Inputs(list(gates), fresh or {}, list(readability), list(periods),
                      load_errors or [])


class SelectLatestTest(unittest.TestCase):
    def test_newer_recorded_at_wins(self):
        periods = [
            {"period": "old", "recorded_at": "2026-01-01", "kind": "live"},
            {"period": "new", "recorded_at": "2026-02-01", "kind": "live"},
        ]
        live, struct = MH._select_latest(periods)
        self.assertEqual(live["period"], "new")
        self.assertIsNone(struct)

    def test_same_date_falls_back_to_list_position(self):
        """同日期时位置靠后的更新（聚合按 recorded_at 升序生成）。"""
        periods = [
            {"period": "first", "recorded_at": "2026-02-01", "kind": "live"},
            {"period": "second", "recorded_at": "2026-02-01", "kind": "live"},
        ]
        live, _struct = MH._select_latest(periods)
        self.assertEqual(live["period"], "second")

    def test_structural_snapshot_needs_case_total(self):
        periods = [{"period": "s", "recorded_at": "2026-02-01",
                    "metrics": {"case_total": 10}}]
        _live, struct = MH._select_latest(periods)
        self.assertEqual(struct["period"], "s")


class CapacityHitsTest(unittest.TestCase):
    def test_soft_and_hard_lines_both_recorded(self):
        cells = [("inference/vllm-ascend", "interrupt", 97, 17343)]
        fallbacks = [("inference/vllm-ascend", None, 128, 25291)]
        hits = MH._compute_capacity_hits(GATES, cells, fallbacks)
        self.assertEqual(hits, {
            ("cell", "inference/vllm-ascend", "interrupt"): {
                "kind": "cell", "ns": "inference/vllm-ascend", "cat": "interrupt",
                "n": 97, "tok": 17343,
                "gates": [{"id": "cell_read_soft_tok", "meaning": "soft", "action": "省"}],
                "hard": False,
            },
            ("fallback", "inference/vllm-ascend", None): {
                "kind": "fallback", "ns": "inference/vllm-ascend", "cat": None,
                "n": 128, "tok": 25291,
                "gates": [{"id": "fallback_read_soft_tok", "meaning": "fb soft",
                           "action": "改两步法"},
                          {"id": "fallback_read_hard_tok", "meaning": "fb hard",
                           "action": "切平台"}],
                "hard": True,
            },
        })

    def test_missing_cost_and_unmet_thresholds_are_skipped(self):
        """成本 None 的格子不判；阈值边界严格按 op（`>` 等值不算，`>=` 等值算）。"""
        cells = [("ns", "cat", 1, None), ("ns", "cat", 1, 8000),
                 ("ns2", "cat2", 1, 20000)]
        hits = MH._compute_capacity_hits(GATES[:2], cells, [])
        self.assertEqual(list(hits), [("cell", "ns2", "cat2")])
        self.assertEqual(hits[("cell", "ns2", "cat2")]["gates"], [
            {"id": "cell_read_soft_tok", "meaning": "soft", "action": "省"},
            {"id": "cell_read_hard_tok", "meaning": "hard", "action": "瘦身"},
        ])
        self.assertTrue(hits[("cell", "ns2", "cat2")]["hard"])

    def test_no_matching_gates_means_no_hits(self):
        self.assertEqual(MH._compute_capacity_hits([], [("ns", "cat", 1, 99999)], []), {})


class LineTokTest(unittest.TestCase):
    def test_gate_value_wins(self):
        gates = [{"id": "cell_read_soft_tok", "value": 9000}]
        self.assertEqual(MH._line_tok(gates, "cell", "soft"), 9000)

    def test_missing_gate_falls_back_to_constant(self):
        self.assertEqual(MH._line_tok([], "cell", "soft"), MH.SOFT_TOK_FALLBACK)
        self.assertEqual(MH._line_tok([], "fallback", "hard"), MH.HARD_TOK_FALLBACK)


class PrevCellsTest(unittest.TestCase):
    def test_reads_counts_from_last_structural_snapshot(self):
        last = {"metrics": {"capacity_by_ns": {
            "inference/vllm-ascend": {"interrupt": {"count": 97}},
            "common": {"performance": {"count": None}},
        }}}
        self.assertEqual(MH._compute_prev_cells(last), {
            ("inference/vllm-ascend", "interrupt"): 97,
            ("common", "performance"): None,
        })

    def test_no_snapshot_gives_empty_map(self):
        self.assertEqual(MH._compute_prev_cells(None), {})
        self.assertEqual(MH._compute_prev_cells({}), {})


class CapacityRenderTest(unittest.TestCase):
    def test_soft_hit_names_the_crossed_gate_and_plain_text(self):
        hits = MH._compute_capacity_hits(
            GATES[:2], [("inference/vllm-ascend", "interrupt", 97, 17343)], [])
        findings = MH._render_capacity_findings(
            GATES[:2], capacity(cells=[("inference/vllm-ascend", "interrupt", 97, 17343)],
                               hits=hits,
                               prev_cells={("inference/vllm-ascend", "interrupt"): 100}))
        self.assertEqual(findings, [(
            "fail", "容量",
            "inference/vllm-ascend · interrupt = 17343 tok（97 条）（上次快照 100 条）"
            " —— 越过 cell_read_soft_tok（soft）",
            "省",
            "推理 · vllm-ascend 的「中断类报错」共 97 条，查一次问题要读进来约 17343 字。"
            "已过评估线，值得看看还能不能再省",
        )])

    def test_hard_fallback_hit_names_the_same_cell_once(self):
        fallbacks = [("inference/vllm-ascend", None, 128, 25291)]
        hits = MH._compute_capacity_hits(GATES[2:], [], fallbacks)
        findings = MH._render_capacity_findings(
            GATES[2:], capacity(fallbacks=fallbacks, hits=hits))
        self.assertEqual(len(findings), 1, "一个格子只报一条")
        _level, _face, text, action, plain = findings[0]
        self.assertIn("兜底视图（category 未判出） = 25291 tok（128 条）", text)
        self.assertIn("fallback_read_soft_tok、fallback_read_hard_tok", text)
        self.assertEqual(action, "切平台")
        self.assertIn("是硬线 20000 的 1.3 倍", plain)

    def test_unmeasurable_is_warned_not_silently_green(self):
        findings = MH._render_capacity_findings(
            GATES, capacity(unmeasurable=[("ns", "cat")], fb_unmeasurable=["ns"]))
        self.assertEqual(findings[0][:4], (
            "warn", "容量",
            "容量线未评估：读侧视图缺失：ns · cat；ns 兜底视图",
            "python3 scripts/build_index.py",
        ))
        whole = MH._render_capacity_findings(
            GATES, capacity(structural_unavailable=True,
                            unmeasurable=[("（整个结构侧）", "拿不到")]))
        self.assertIn("结构侧整块拿不到", whole[0][2])

    def test_recompute_failure_and_clean_result_are_distinct(self):
        failed = MH._render_capacity_findings(GATES, capacity(live_ok=False))
        self.assertEqual(failed[0][2],
                         "容量线未评估：读入成本现算失败（结构侧拿到了，现算抛错）")
        clean = MH._render_capacity_findings(GATES, capacity())
        self.assertEqual(clean, [(
            "ok", "容量",
            "两类读入视图均未触发 (cell_read_soft_tok、cell_read_hard_tok、"
            "fallback_read_soft_tok、fallback_read_hard_tok)",
            None, None)])


class ReadabilityTest(unittest.TestCase):
    def test_readable_and_unreadable_marked_apart(self):
        rules = [
            {"metric": "misdiagnosis_rate", "rule": "source_nonzero",
             "source": "feedback_capture", "why": "反馈为 0"},
            {"metric": "attribution_ratio", "rule": "any_gt_0", "why": "没有归因"},
        ]
        live_m = {"misdiagnosis_rate": {"ok": 0, "total": 3},
                  "feedback_capture": {"resolved": 0},
                  "attribution_ratio": {"case_error": 1}}
        findings, state = MH._render_readability_findings(rules, live_m)
        self.assertEqual(findings[0][0], "fail")
        self.assertIn("不可解读——反馈为 0（来源指标 feedback_capture 计数 0）",
                      findings[0][2])
        self.assertEqual(findings[1][0], "ok")
        self.assertEqual(state["misdiagnosis_rate"], {
            "readable": False,
            "why": "反馈为 0（来源指标 feedback_capture 计数 0）",
            "label": "误诊率",
        })
        self.assertTrue(state["attribution_ratio"]["readable"])

    def test_missing_field_and_unknown_rule_are_warned(self):
        rules = [
            {"metric": "attribution_ratio", "rule": "any_gt_0", "why": "没有归因"},
            {"metric": "x", "rule": "unknown_rule", "why": "w"},
        ]
        findings, state = MH._render_readability_findings(
            rules, {"x": {"v": 1}})
        self.assertEqual(findings[0][2],
                         "attribution_ratio：最新 live 快照没有该字段（没有归因）")
        self.assertEqual(findings[1][2], "x：rules 里的 rule 'unknown_rule' 没有对应实现")
        self.assertNotIn("attribution_ratio", state)
        self.assertNotIn("x", state)


class TextRenderTest(unittest.TestCase):
    PAYLOAD = {
        "coverage": {"gates_evaluated": 2, "gates_total": 2,
                     "readability_evaluated": 1, "readability_total": 1},
        "check_verdict": "violations",
        "fail_count": 2,
    }
    FINDINGS = [
        ("ok", "数据底座", "live 快照：1 期", None, None),
        ("fail", "容量", "超线", "跑 build_index", "读得太多了"),
    ]

    def test_violations_text_and_counts(self):
        text = MH._render_text(self.PAYLOAD, self.FINDINGS, [])
        self.assertEqual(text, "\n".join([
            "metrics 闭环体检（判据：metrics/gates.yaml）",
            "\n[数据底座]",
            "  ✓ live 快照：1 期",
            "\n[容量]",
            "  ✗ 超线",
            "      说人话：读得太多了",
            "      → 跑 build_index",
            "\n[判据覆盖面] 闸门 2/2 条已评估 · 数字可信度规则 1/1 条已评估",
            "\n结论：闭环未闭合（2 项 ✗）",
            "  ✗ = 有判据被违反但没人处理；行动列即下一步（判据数值在 metrics/gates.yaml）",
            "  退出码：0 判据全部评过且无越界 · 1 有判据被违反 · 2 有判据未被评估（不可判定）",
        ]))

    def test_broken_verdict_prints_the_unchecked_gates(self):
        payload = dict(self.PAYLOAD, check_verdict="broken", fail_count=1)
        text = MH._render_text(payload, [("ok", "数据底座", "live 快照：0 期", None, None)],
                               ["容量线未评估：读侧视图缺失"])
        self.assertIn("[体检器自身] 下列判据**未被评估**——这不是'通过'，是检测腿断了：",
                      text)
        self.assertIn("  ✗ 容量线未评估：读侧视图缺失", text)
        self.assertIn("结论：体检器不完整：有判据未被评估，结论不可用（1 项 ✗ 仅供参考）",
                      text)


class AuditTest(unittest.TestCase):
    def test_clean_audit_is_zero(self):
        audit = MH._compute_audit(
            inputs(gates=[{"id": "g1", "dimension": "feedback_capture_total"}],
                   readability=[{"metric": "misdiagnosis_rate", "rule": "total_gt_0"}]),
            capacity(), {"misdiagnosis_rate": {"total": 1}}, [])
        self.assertEqual(audit.broken, [])
        self.assertEqual(audit.exit_code, 0)
        self.assertTrue(audit.gate_audit[0]["implemented"])
        self.assertTrue(audit.readability_audit[0]["present_in_snapshot"])

    def test_violation_is_one_and_unevaluated_is_two(self):
        args = (inputs(gates=[{"id": "g1", "dimension": "feedback_capture_total"}]),
                capacity(), {"misdiagnosis_rate": {"total": 1}})
        self.assertEqual(MH._compute_audit(*args, [("fail", "x", "y", None, None)]).exit_code, 1)

        uneven = MH._compute_audit(*args, [])
        self.assertEqual(uneven.exit_code, 0)
        with_missing = MH._compute_audit(
            inputs(gates=[{"id": "g2", "dimension": "capacity_cell_read_tok"}]),
            capacity(unmeasurable=[("ns", "cat")]),
            {}, [("fail", "x", "y", None, None)])
        self.assertEqual(with_missing.exit_code, 2, "判据没评过时 2 优先于 1")
        self.assertIn("闸门 g2：数据缺失（读侧视图量不出），本轮**未被评估**——不等于通过",
                      with_missing.broken)
        self.assertTrue(any("容量线未评估：读侧视图缺失（ns×cat）" in b
                            for b in with_missing.broken), with_missing.broken)

    def test_load_errors_and_unimplemented_gate_stay_visible(self):
        audit = MH._compute_audit(
            inputs(gates=[{"id": "g3", "dimension": "not_implemented"}],
                   load_errors=["gates.yaml 读取/解析失败"]),
            capacity(), {}, [])
        self.assertEqual(audit.exit_code, 2)
        self.assertIn("gates.yaml 读取/解析失败", audit.broken)
        self.assertIn("闸门 g3（dimension=not_implemented）没有评估实现——这条判据不会被检查",
                      audit.broken)


class LoadInputsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "metrics").mkdir()

    def write_gates(self, text):
        (self.root / "metrics" / "gates.yaml").write_text(text, encoding="utf-8")

    def test_reads_gates_freshness_readability_and_periods(self):
        self.write_gates(
            "gates:\n"
            "  - id: g1\n"
            "    dimension: feedback_capture_total\n"
            "    op: \"<=\"\n"
            "    value: 0\n"
            "freshness:\n"
            "  live_snapshot_max_age_days: 7\n"
            "readability:\n"
            "  - metric: misdiagnosis_rate\n"
            "    rule: total_gt_0\n"
            "    why: w\n")
        (self.root / "metrics" / "timeline.yaml").write_text(
            "periods:\n  - period: P\n    kind: live\n", encoding="utf-8")
        got = MH._load_inputs(self.root)
        self.assertEqual(got.gates, [{"id": "g1", "dimension": "feedback_capture_total",
                                      "op": "<=", "value": 0}])
        self.assertEqual(got.fresh, {"live_snapshot_max_age_days": 7})
        self.assertEqual(got.readability, [{"metric": "misdiagnosis_rate",
                                            "rule": "total_gt_0", "why": "w"}])
        self.assertEqual(got.periods, [{"period": "P", "kind": "live"}])
        self.assertEqual(got.load_errors, [])

    def test_duplicate_ids_are_reported(self):
        self.write_gates(
            "gates:\n"
            "  - id: dup\n"
            "    dimension: feedback_capture_total\n"
            "  - id: dup\n"
            "    dimension: feedback_capture_total\n")
        got = MH._load_inputs(self.root)
        self.assertTrue(any("判据 id 重复：dup" in e for e in got.load_errors),
                        got.load_errors)

    def test_missing_config_is_reported_as_load_error(self):
        """配置文件不存在与解析失败同样进 load_errors（不静默当成空文档）。"""
        missing = MH._load_inputs(self.root)
        self.assertEqual(missing.gates, [])
        self.assertTrue(any("gates.yaml 读取/解析失败" in e for e in missing.load_errors),
                        missing.load_errors)


class FreshnessRenderTest(unittest.TestCase):
    def test_fresh_and_missing_snapshots(self):
        today = date.today().isoformat()
        findings = MH._render_freshness_findings(
            {"period": "P", "recorded_at": today}, None,
            {"live_snapshot_max_age_days": 7, "structural_max_age_days": 7})
        self.assertEqual(findings[0][:3], (
            "ok", "数据新鲜度", "诊断侧 live 快照：最后 P（0 天前，阈值 7 天）"))
        self.assertEqual(findings[1][:3], (
            "fail", "数据新鲜度", "结构侧（容量/条数）：一期都没有"))

    def test_unparseable_recorded_at_is_a_warning(self):
        findings = MH._render_freshness_findings(
            {"period": "P", "recorded_at": "not-a-date"}, None,
            {"live_snapshot_max_age_days": 7})
        self.assertEqual(findings[0][:3], (
            "warn", "数据新鲜度", "诊断侧 live 快照：recorded_at 不可解析（'not-a-date'）"))


if __name__ == "__main__":
    unittest.main()
