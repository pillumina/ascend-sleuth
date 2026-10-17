"""score_entries 的算分口径回归。

分数是候选排序的输入，算错不会崩、只会让**排序**悄悄偏向。三处口径值得钉住：
  ① 没有记录时分数就等于冷启动先验（「先验」这个词的全部含义）；
  ② 计数按记录里最新一次运行所处的周衰减——锚点必须取自数据，不能取当天日期，
     否则生成物会在没有任何知识变更时随日期变，`build_index --check` 会恒红；
  ③ 自证权重 0.5：它是弱证据，不是零信息，也不是整条独立确认。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import entry_activity as ea  # noqa: E402
import score_entries as se  # noqa: E402


def case_file(root, cid, verification=None, quality="medium", override=None):
    p = root / "knowledge" / "inference" / "vllm-ascend" / "interrupt" / f"{cid}.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"cases:", f"  - id: {cid}", "    category: interrupt"]
    if quality:
        lines.append(f"    investigation_quality: {quality}")
    if verification:
        lines.append(f"    verification: {{source: {verification}}}")
    if override:
        lines.append(f"    score_override: {override}")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        os.environ["ASCEND_SLEUTH_DEPLOYMENT"] = "d1"
        self.addCleanup(lambda: os.environ.pop("ASCEND_SLEUTH_DEPLOYMENT", None))

    def write_records(self, dep, cases):
        """cases = {id: {week: {resolved, misdiagnosed, self_resolved}}}"""
        doc = {"covered": {"deployment": dep, "runs": 1, "weeks": [], "checkouts": []},
               "cases": {}, "references": {}, "tools": {}, "cold": {"cases": 0},
               "cold_never_looked_up": []}
        for cid, weeks in cases.items():
            tot = {"selected": 0, "loaded": 0, "resolved": 0, "misdiagnosed": 0,
                   "self_resolved": 0, "excluded": 0}
            by = {}
            for wk, c in weeks.items():
                by[wk] = {**{k: 0 for k in ea.COUNT_KEYS["case"]}}
                for k, v in c.items():
                    by[wk][k] = v
                    tot[k] += v
                doc["covered"]["weeks"].append(wk)
            doc["cases"][cid] = {"totals": tot, "by_week": by, "recent": []}
        doc["covered"]["weeks"] = sorted(set(doc["covered"]["weeks"]))
        d = ea.generated_dir(self.root)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{dep}.yaml").write_text(ea.render(doc), encoding="utf-8")

    def test_no_records_falls_back_to_prior(self):
        case_file(self.root, "C-1", verification="engineer-report", quality="high")
        res = se.compute(self.root)
        self.assertEqual(res["meta"]["score_source"], "prior")
        self.assertEqual(res["cases"]["C-1"]["score"], 0.85)
        self.assertEqual(res["cases"]["C-1"]["source"], "prior")

    def test_resolved_raises_and_misdiagnosed_lowers(self):
        case_file(self.root, "C-1", verification="investigation", quality="medium")  # 先验 0.3
        self.write_records("d1", {"C-1": {"2026-W42": {"resolved": 4}}})
        good = se.compute(self.root)["cases"]["C-1"]
        self.assertEqual(good["source"], "records")
        self.assertGreater(good["score"], 0.3)

        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        case_file(self.root, "C-1", verification="investigation", quality="medium")
        self.write_records("d1", {"C-1": {"2026-W42": {"misdiagnosed": 4}}})
        bad = se.compute(self.root)["cases"]["C-1"]
        self.assertLess(bad["score"], 0.3)

    def test_self_report_weighs_half(self):
        case_file(self.root, "C-1", verification="investigation", quality="medium")
        self.write_records("d1", {"C-1": {"2026-W42": {"self_resolved": 4}}})
        only_self = se.compute(self.root)["cases"]["C-1"]["score"]

        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        case_file(self.root, "C-1", verification="investigation", quality="medium")
        self.write_records("d1", {"C-1": {"2026-W42": {"resolved": 4}}})
        full = se.compute(self.root)["cases"]["C-1"]["score"]
        self.assertLess(only_self, full, "自证是弱证据，权重低于独立确认")

    def test_decay_anchor_is_data_not_wall_clock(self):
        """同样的记录文件，隔多久算都是同一个分——生成物不随日期变。"""
        case_file(self.root, "C-1", verification="investigation", quality="medium")
        self.write_records("d1", {"C-1": {"2026-W30": {"resolved": 3}, "2026-W42": {"resolved": 1}}})
        a = se.compute(self.root)
        b = se.compute(self.root)
        self.assertEqual(a["cases"]["C-1"]["score"], b["cases"]["C-1"]["score"])
        self.assertEqual(a["meta"]["anchor_week"], "2026-W42")
        # 12 周半衰期：W30 的那 3 条到 W42 恰好减半
        self.assertAlmostEqual(a["cases"]["C-1"]["resolved"], 1 + 3 * 0.5, places=2)

    def test_override_wins(self):
        case_file(self.root, "C-1", verification="investigation", quality="low",
                  override="{score: 0.9, reason: 现场三次确认, by: owner}")
        self.write_records("d1", {"C-1": {"2026-W42": {"misdiagnosed": 3}}})
        c = se.compute(self.root)["cases"]["C-1"]
        self.assertEqual(c["source"], "override")
        self.assertEqual(c["score"], 0.9)

    def test_records_are_merged_across_deployments(self):
        """索引是全仓共享的生成物：算分读仓里全部部署的记录（确定性，与谁在哪台机器上算无关）。"""
        case_file(self.root, "C-1", verification="investigation", quality="low")
        self.write_records("d1", {"C-1": {"2026-W42": {"resolved": 2}}})
        self.write_records("d2", {"C-1": {"2026-W42": {"resolved": 2}}})
        c = se.compute(self.root)["cases"]["C-1"]
        self.assertAlmostEqual(c["resolved"], 4.0, places=2)

    def test_unknown_quality_is_reported_and_treated_as_low(self):
        case_file(self.root, "C-1", verification="engineer-report", quality="low-medium")
        res = se.compute(self.root)
        self.assertTrue(any("C-1" in x for x in res["meta"]["unrecognized_quality"]),
                        res["meta"]["unrecognized_quality"])
        self.assertEqual(res["cases"]["C-1"]["score"], se.PRIORS["engineer-report"]["low"])

    def test_baseline_counts_are_not_decayed(self):
        """搬运行没有运行周，按原样进入后验。"""
        case_file(self.root, "C-1", verification="investigation", quality="low")
        d = ea.generated_dir(self.root)
        d.mkdir(parents=True, exist_ok=True)
        doc = {"covered": {"deployment": "d1", "runs": 1, "weeks": ["2026-W42"],
                           "checkouts": []},
               "cases": {"C-1": {"totals": {"selected": 0, "loaded": 0, "resolved": 4,
                                            "misdiagnosed": 0, "self_resolved": 0,
                                            "excluded": 0, "baseline": True},
                                 "by_week": {"2026-W42": {"selected": 0, "loaded": 0, "resolved": 0,
                                                          "misdiagnosed": 0, "self_resolved": 0,
                                                          "excluded": 0}},
                                 "recent": []}},
               "references": {}, "tools": {}, "cold": {"cases": 0}, "cold_never_looked_up": []}
        (d / "d1.yaml").write_text(ea.render(doc), encoding="utf-8")
        self.assertAlmostEqual(se.compute(self.root)["cases"]["C-1"]["resolved"], 4.0, places=2)

    def test_baseline_rows_are_summed_across_deployments(self):
        """两份部署各有一条搬运行 → 计数求和，不是后一份覆盖前一份。"""
        case_file(self.root, "C-1", verification="investigation", quality="low")
        for dep in ("d1", "d2"):
            d = ea.generated_dir(self.root)
            d.mkdir(parents=True, exist_ok=True)
            doc = {"covered": {"deployment": dep, "runs": 1, "weeks": [], "checkouts": []},
                   "cases": {"C-1": {"totals": {"selected": 0, "loaded": 0, "resolved": 1,
                                                "misdiagnosed": 0, "self_resolved": 0,
                                                "excluded": 0, "baseline": True},
                                     "by_week": {}, "recent": []}},
                   "references": {}, "tools": {}, "cold": {"cases": 0},
                   "cold_never_looked_up": []}
            (d / f"{dep}.yaml").write_text(ea.render(doc), encoding="utf-8")
        self.assertAlmostEqual(se.compute(self.root)["cases"]["C-1"]["resolved"], 2.0, places=2)

    def test_source_without_records_leaves_score_at_prior(self):
        """只有「被选中」而没有结局的条目仍停在先验：选中不是有效性的证据。"""
        case_file(self.root, "C-1", verification="investigation", quality="low")
        self.write_records("d1", {"C-1": {"2026-W42": {}}})
        c = se.compute(self.root)["cases"]["C-1"]
        self.assertEqual(c["source"], "prior")
        self.assertEqual(c["score"], se.PRIORS["investigation"]["low"])


class OverrideCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_valid_override_passes(self):
        case_file(self.root, "C-1", override="{score: 0.5, reason: x, by: y}")
        self.assertEqual(se.check_overrides(self.root), [])

    def test_missing_reason_is_reported(self):
        case_file(self.root, "C-1", override="{score: 0.5, by: y}")
        self.assertTrue(any("reason" in p for p in se.check_overrides(self.root)))

    def test_out_of_range_score_is_reported(self):
        case_file(self.root, "C-1", override="{score: 1.5, reason: x, by: y}")
        self.assertTrue(any("[0, 1]" in p for p in se.check_overrides(self.root)))


if __name__ == "__main__":
    unittest.main()
