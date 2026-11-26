"""trace_metrics 拆分后的函数级回归测试。

`main` 里原先是一整段读、算、渲染混在一起的代码。拆成 `_load_inputs` /
`_compute_metrics` / `_render_*` 之后，这里直接调用这些函数，把口径钉在值上：
命中率、路由准确率、reference 三态、停止原因、字段违规、切片是否进快照。

为什么单开一个文件：`test_trace_metrics.py` 走子进程黑盒断言（入口行为），
本文件走函数级断言（拆分后的计算与渲染）。两边同时红，说明改动既改了实现也改了行为。
"""

import json
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import trace_metrics as TM  # noqa: E402

# case id → (namespace, category, score)；分数只用于置信度分布。
BY_CASE = {
    "CASE-A": ("inference/vllm-ascend", "interrupt", 0.7),
    "CASE-B": ("training/verl", "performance", 0.3),
    "CASE-C": ("common", "precision", 0.4),
}

STATES = [
    {
        "session_id": "s1", "status": "resolved", "stop_reason": "resolved_confirmed",
        "kb_behind": 2, "kb_merge": "ff-only", "external_evidence": "on",
        "trace": [
            {"role": "user", "content": "推理拉起报错 error code 507014"},
            {"role": "agent", "action": "triage",
             "routed": ["inference/vllm-ascend"], "category": "interrupt"},
            {"role": "agent", "action": "quickly_check"},
            {"role": "agent", "action": "hit", "case": "CASE-A"},
            {"role": "agent", "action": "reference_lookup", "ref_id": "REF-A",
             "outcome": "hit", "purpose": "fix", "platform": "A2-910B"},
            {"role": "agent", "action": "source_analysis", "repo": "r/x", "ref": "v1",
             "fetch_exit": 0, "verify": "hit"},
            {"role": "agent", "action": "external_lookup",
             "capability": "versioned-code", "outcome": "hit"},
            {"role": "agent", "action": "attribution", "verdict": "case_error"},
            {"role": "agent", "action": "feedback", "outcome": "resolved"},
        ],
    },
    {
        "session_id": "s2", "status": "not_resolved", "stop_reason": "halted_ask_user",
        "kb_behind": 0, "kb_merge": "none", "external_evidence": "off",
        "trace": [
            {"role": "user", "content": "训练跑着跑着就变慢了，也说不上哪里不对"},
            {"role": "agent", "action": "triage", "routed": []},
            {"role": "agent", "action": "triage_semantic",
             "namespace": "common", "category": "performance"},
            {"role": "agent", "action": "hit", "case": "CASE-B"},
            {"role": "agent", "action": "reference_lookup", "ref_id": "REF-B",
             "outcome": "skipped", "purpose": "background"},
            {"role": "agent", "action": "source_analysis", "repo": "r/x", "ref": "v1",
             "fetch_exit": 3, "verify": "miss"},
            {"role": "agent", "action": "external_lookup", "capability": "manual-doc",
             "outcome": "skipped", "reason": "not-needed"},
            {"role": "agent", "action": "tier3"},
            {"role": "agent", "action": "attribution", "attribution_kind": "execution"},
            {"role": "agent", "action": "feedback", "outcome": "not_resolved"},
        ],
    },
    {
        "session_id": "s3", "status": "resolved", "kb_behind": "unknown",
        "trace": [
            {"role": "user", "content": "拉起时 warning PlatformNPU is registered but not available"},
            {"role": "agent", "action": "triage"},
            {"role": "agent", "action": "load_index"},
            {"role": "agent", "action": "quickly_check"},
            {"role": "agent", "action": "attribution", "verdict": "execution_error"},
        ],
    },
]

EXPECTED_METRICS = {
    "sessions_total": 3,
    "tier2_hit": 2,
    "routed_accuracy": {"ok": 1, "total": 2},
    "misdiagnosis_rate": {"ok": 1, "total": 2},
    "by_category_hit": {"interrupt": {"hit": 1, "total": 1},
                        "performance": {"hit": 1, "total": 1}},
    "attribution_ratio": {"case_error": 1, "execution_error": 2},
    "confidence_distribution": {"low": 2, "total": 3},
    "feedback_capture": {"resolved": 1, "not_resolved": 1, "partial": 0},
    "trace_completeness": {"ok": 3, "total": 3},
    "vocab_compliance": {"ok": 21, "total": 21},
    "tier3": {"used": 1, "saved": 0},
    "triage_miss_classes": {"lexical_gap": 0, "semantic_path": 1,
                            "routed_unrecorded": 1, "no_triage_event": 0},
    "triage_miss_sessions": {"lexical_gap": [], "semantic_path": ["s2"],
                             "routed_unrecorded": ["s3"]},
    "reference": {"hits": 1, "refs": 1},
    "reference_outcomes": {"hit": 1, "skipped": 1},
    "reference_purposes": {"fix": 1, "background": 1},
    "reference_detail": {"REF-A": {"hits": 1, "resolved": 1}},
    "stop_reasons": {"resolved_confirmed": 1, "halted_ask_user": 1},
    "stop_reason_unrecorded": 1,
    "parallel_group_events": 0,
    "considered_candidates_events": 0,
    "trace_record_violations": None,
    "trace_record_violations_total": 0,
    "external_evidence": {"on": 1, "off": 1},
    "external_lookups": {"manual-doc": 1, "versioned-code": 1},
    "external_record_violations": None,
    "external_record_violations_total": 0,
}

EXPECTED_ROWS = [
    "| 指标 | 值 |",
    "|---|---|",
    "| 诊断 session 数 | 3（活跃 + 历史） |",
    "| Tier 2 命中 session | 2 |",
    "| 误诊率（命中但反馈 not_resolved/partial） | 1/2 (50%)",
    "| 按类命中（hit session / 该 category session） | interrupt 1/1；performance 1/1",
    "| 执行-误诊归因比（case 错 / 执行错） | case 1 / execution 2",
    "| 置信度分布 | 2/3 低置信（score<0.5）；中高置信 1",
    "| 路由准确率 | 1/2 (50%)",
    "| 结果反馈捕获 | 2/2（resolved 1 / not_resolved 1 / partial 0）",
    "| trace 完整性（proxy：含 triage + 过滤步） | 3/3 (100%)",
    "| trace 词表合规（词表外 action） | 21/21",
    "| Tier 3 兜底使用 / 其中挽救（resolved 且无 Tier 2 命中） | 1 / 0 |",
    "| triage miss 归类 | lexical_gap 0（token 在场却没接住→进 E2 错例池）；"
    "semantic_path 1（本来无 token，级联正常换挡）；routed 未记录 1（E2 取数字段缺口）",
    "| 零执行评估所需的记录 | 停止原因已记 2/3（未记录 1）；同批并发标记（parallel_group）事件 0；"
    "候选全集（considered_candidates）事件 0 |",
    "| reference 引用次数（去重 ref） | 1（1 个 ref） |",
    "| reference 触发三态（hit/miss/skipped） | hit 1、skipped 1（合计 2） |",
    "| reference 消费点分布（collect/signature/background/fix/procedure） | fix 1、background 1 |",
    "|   REF-A | hits 1，引用后 resolved 1/1 (100%) |",
    "| reference 平台分布 | A2-910B 1 |",
]


class _Computed(unittest.TestCase):
    """正常夹具的一次计算，供本文件多个用例共用。"""

    @classmethod
    def setUpClass(cls):
        cls.m, cls.detail = TM._compute_metrics(STATES, BY_CASE)
        cls.kb = TM._compute_kb_baseline(cls.detail["kb_groups"],
                                         cls.detail["kb_merge_ff"],
                                         cls.detail["kb_merge_total"])


class ComputeMetricsTest(_Computed):
    def test_normal_values(self):
        """正常 trace：每项指标按定义算出来，值与口径一起钉住。"""
        self.assertEqual(self.m, EXPECTED_METRICS)

    def test_empty_states_are_all_zero_or_none(self):
        """没有 session：计数为 0、比例字段为 None，不产出假读数。"""
        m, _detail = TM._compute_metrics([], {})
        self.assertEqual(m["sessions_total"], 0)
        self.assertEqual(m["tier2_hit"], 0)
        for key in ("routed_accuracy", "misdiagnosis_rate", "by_category_hit",
                    "confidence_distribution", "triage_miss_classes",
                    "triage_miss_sessions", "reference", "reference_outcomes",
                    "reference_purposes", "reference_detail", "stop_reasons",
                    "external_evidence", "external_lookups",
                    "trace_record_violations", "external_record_violations"):
            self.assertIsNone(m[key], key)
        self.assertEqual(m["trace_completeness"], {"ok": 0, "total": 0})
        self.assertEqual(m["vocab_compliance"], {"ok": 0, "total": 0})
        self.assertEqual(m["trace_record_violations_total"], 0)

    def test_broken_fields_are_reported_not_crashing(self):
        """字段缺失/类型错：照样出读数，违规按条报到 trace_record_violations。"""
        state = {
            "session_id": "b1", "stop_reason": ["abandoned"], "kb_behind": "many",
            "kb_merge": "fast-forward", "external_evidence": "maybe",
            "trace": [
                {"action": "triage"},
                {"action": "bogus"},
                {"action": "feedback", "outcome": "weird"},
                {"action": "source_analysis", "repo": " ", "fetch_exit": "1", "verify": "maybe"},
                {"action": "external_lookup", "capability": "nope", "outcome": "weird"},
                {"action": "reference_lookup", "ref_id": "R", "outcome": "weird",
                 "purpose": "bogus"},
                {"action": "considered_candidates", "considered_candidates": 5},
                {"action": "load_full", "candidates": "X"},
            ],
        }
        m, detail = TM._compute_metrics([state], {})
        self.assertEqual(m["trace_record_violations_total"], 6)
        self.assertEqual(m["trace_record_violations"][:2], [
            "b1: stop_reason 应为字符串（['abandoned']）",
            "b1: external_evidence='maybe'",
        ])
        self.assertEqual(m["vocab_compliance"], {"ok": 6, "total": 8})
        self.assertEqual(m["external_record_violations_total"], 2)
        self.assertEqual(m["triage_miss_classes"]["routed_unrecorded"], 1)
        self.assertEqual(detail["source_bad"], [
            "b1: fetch_exit 应为整数（'1'）",
            "b1: verify 应为 hit/miss/skipped（'maybe'）",
        ])


class SliceComputeTest(_Computed):
    def test_fix_basis_not_counted_in_attribution_ratio(self):
        states = [{
            "session_id": "s", "status": "resolved",
            "trace": [
                {"role": "agent", "action": "attribution", "verdict": "case_error", "component": "case:x"},
                {"role": "agent", "action": "attribution", "verdict": "execution_error", "component": "skill:diagnose"},
                {"role": "agent", "action": "attribution", "attribution_scope": "fix_basis",
                 "verdict": "case_error", "component": "reference:ref-r"},
            ],
        }]
        m, detail = TM._compute_metrics(states, {})
        self.assertEqual(m["attribution_ratio"], {"case_error": 1, "execution_error": 1})
        self.assertEqual(detail["fix_basis_attribs"], 1)

    def test_kb_baseline_counts_groups_and_merge_rate(self):
        """kb_behind 三组各算解决数；merge 分母只算有该字段的单。"""
        self.assertEqual(self.kb, {
            "resolution": {"behind": {"ok": 1, "total": 1},
                           "current": {"ok": 0, "total": 1},
                           "unknown": {"ok": 1, "total": 1}},
            "merge": {"ff_only": 1, "total": 2},
        })

    def test_kb_baseline_without_samples_is_zero_not_missing(self):
        """一组样本也没有：三组都是 0/0，不拿空 dict 或 None 冒充。"""
        groups = {g: {"ok": 0, "total": 0} for g in ("behind", "current", "unknown")}
        self.assertEqual(TM._compute_kb_baseline(groups, 0, 0), {
            "resolution": {"behind": {"ok": 0, "total": 0},
                           "current": {"ok": 0, "total": 0},
                           "unknown": {"ok": 0, "total": 0}},
            "merge": {"ff_only": 0, "total": 0},
        })

    def test_source_usage_aggregates_repo_ref_exit_and_verify(self):
        """源码取用：仓/版本按原值计数，退出码转字符串键，按仓失败单列。"""
        self.assertEqual(TM._compute_source_usage(self.detail), {
            "events": 2,
            "repos": {"r/x": 2},
            "refs": {"v1": 2},
            "fetch_exits": {"0": 1, "3": 1},
            "verify": {"hit": 1, "miss": 1},
            "unrecorded": None,
            "fail_by_repo": {"r/x": {"fetch_nonzero": 1, "verify_miss": 1}},
            "violations": None,
            "violations_total": 0,
        })

    def test_source_usage_of_empty_detail_has_no_slices(self):
        """没有 source_analysis 事件：事件数为 0，其余字段为 None（不编造空表）。"""
        su = TM._compute_source_usage(TM._compute_metrics([], {})[1])
        self.assertEqual(su["events"], 0)
        for key in ("repos", "refs", "fetch_exits", "verify", "unrecorded",
                    "fail_by_repo", "violations"):
            self.assertIsNone(su[key], key)
        self.assertEqual(su["violations_total"], 0)


class RenderTest(_Computed):
    def test_markdown_rows_are_byte_stable(self):
        """人读表的每一行都钉住：改口径、改措辞、改顺序都会红。"""
        text = TM._render_markdown(self.m, self.detail, self.kb)
        self.assertEqual(text.split("\n\n<!--")[0].splitlines(), EXPECTED_ROWS)
        self.assertIn("机器可读快照：python3 scripts/trace_metrics.py --emit-yaml -->", text)

    def test_optional_slices_are_opt_in(self):
        """默认不含切片行；显式打开才多出 KB 基线与源码取用两段。"""
        default = TM._render_markdown(self.m, self.detail, self.kb)
        self.assertNotIn("KB 基线切片", default)
        self.assertNotIn("源码取用", default)

        with_slices = TM._render_markdown(self.m, self.detail, self.kb,
                                          show_kb_baseline=True, show_source_usage=True)
        lines = with_slices.splitlines()
        self.assertIn("| KB 基线切片·解决率（kb_behind 落后 / 最新 / unknown） | "
                      "落后 1/1 (100%)；最新 0/1 (0%)；unknown 1/1 (100%)；"
                      "落后与最新之差 +100 个百分点 |", lines)
        self.assertIn("| KB 基线切片·自动合并触发率 | ff-only 1/2 (50%)（有 kb_merge 字段的单） |",
                      lines)
        self.assertIn("| 源码取用（source_analysis） | 2 条；仓写法 1 种、版本写法 1 种"
                      "（两种都按原值计，别名不合并）；按仓 r/x 2 |", lines)
        self.assertIn("|   按仓失败（T12 判据） | r/x（fetch_exit 非零 1 次、verify 未命中 1 次） |",
                      lines)

    def test_json_keeps_key_order_and_drops_none(self):
        """`--json` 的键顺序来自 m 的插入顺序，None 字段不出现。"""
        doc = json.loads(TM._render_json(self.m))
        self.assertEqual(list(doc), [k for k in EXPECTED_METRICS
                                     if EXPECTED_METRICS[k] is not None])
        self.assertNotIn("trace_record_violations", doc)
        self.assertNotIn("external_record_violations", doc)

    def test_snapshot_excludes_optional_slices(self):
        """切片字段不进 `--emit-yaml` 快照（live 白名单会拦）。"""
        m = dict(self.m)
        m["kb_baseline"] = self.kb
        m["source_usage"] = TM._compute_source_usage(self.detail)
        snap = TM._build_snapshot(m)
        self.assertEqual(list(snap), ["period", "kind", "title", "recorded_at",
                                      "source", "metrics"])
        self.assertNotIn("kb_baseline", snap["metrics"])
        self.assertNotIn("source_usage", snap["metrics"])
        self.assertNotIn("trace_record_violations", snap["metrics"])

    def test_yaml_render_has_both_shapes(self):
        """`--emit-yaml-only` 只吐 metrics；`--emit-yaml` 多一层 periods。"""
        snap = TM._build_snapshot(self.m)
        only = yaml.safe_load(TM._render_yaml(snap, metrics_only=True))
        self.assertEqual(only, {"metrics": snap["metrics"]})
        full = TM._render_yaml(snap)
        self.assertTrue(full.startswith("\n--- metrics yaml 快照（复核后 append 进 "
                                        "metrics/timeline.yaml）---\n"))
        self.assertIn("periods:", full)
        self.assertIn("recorded_at:", full)


class ExternalCapabilityRegistryTest(unittest.TestCase):
    """capability 枚举只有一份数据（_types.yaml），代码从那里读，不在两处维护同一份名单。"""

    def test_known_capabilities_match_registry(self):
        doc = yaml.safe_load((ROOT / "references" / "_types.yaml").read_text(encoding="utf-8"))
        self.assertEqual(TM.KNOWN_CAPABILITIES, set(doc["external_capabilities"]))
        self.assertTrue(TM.KNOWN_CAPABILITIES)



if __name__ == "__main__":
    unittest.main()
