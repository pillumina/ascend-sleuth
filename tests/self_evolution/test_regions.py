"""归因组件到可变异区的自动推荐。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.regions import REGIONS, recommend  # noqa: E402

# marker 决定一条补丁的 old_text 能否落在该区；值被改动会让对应区不可用，
# 所以在这里钉住。新增区必须同时登记期望值。
EXPECTED_MARKERS = {
    "diagnose.routing_hints": ("triage", "路由", "追问", "routing"),
    "diagnose.verification_checklist": ("quickly_check", "验证", "候选", "排除"),
    "diagnose.trace_evidence": ("trace", "evidence", "证据"),
    "diagnose.source_usage": ("源码分析", "src_fetch", "grep 定位", "source_analysis"),
    "diagnose.knowledge_usage": ("知识", "reference", "索引", "全文", "候选数"),
    "knowledge.case_content": ("症状", "symptoms", "quickly_check", "判别"),
    "knowledge.reference_content": ("词条", "适用范围", "来源", "scope"),
    "tooling.source_fetch": ("src_fetch", "cache", "缓存", "retry", "重试", "ref"),
    "tooling.source_catalog": ("catalog", "repo", "仓", "签名", "signature"),
    "harness.scheduler": ("scheduler", "调度", "budget", "预算", "stop", "停止"),
}


class RegionsTest(unittest.TestCase):
    def test_hard_components_rank_regions(self):
        result = recommend({
            "routing": {"events": 3, "hard": 2},
            "case_content": {"events": 1, "hard": 1},
        })
        self.assertEqual(result[0]["region"], "diagnose.routing_hints")
        self.assertEqual(result[0]["hard"], 2)

    def test_knowledge_usage_component_maps_to_usage_region(self):
        result = recommend({"case_retrieval": {"events": 2, "hard": 1}})
        self.assertEqual(result[0]["region"], "diagnose.knowledge_usage")

    def test_source_usage_component_maps_to_source_region(self):
        result = recommend({"source_usage": {"events": 2, "hard": 1}})
        self.assertEqual(result[0]["region"], "diagnose.source_usage")

    def test_region_markers_are_pinned(self):
        """没有 marker 的 region 无法校验 old_text，等于不可改。"""
        self.assertEqual(sorted(REGIONS), sorted(EXPECTED_MARKERS))
        for region_id, markers in EXPECTED_MARKERS.items():
            self.assertEqual(tuple(REGIONS[region_id].markers), markers, region_id)

    def test_unknown_components_return_empty(self):
        self.assertEqual(recommend({"unknown": {"events": 1, "hard": 1}}), [])


if __name__ == "__main__":
    unittest.main()
