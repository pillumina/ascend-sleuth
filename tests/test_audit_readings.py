"""三处「读数口径」回归：死引用不过报、信号口径统一、归因通道两套词表都认。

为什么值得单测：这三处都是**判据/面板的分子**，错了不会崩、只会给出一个看起来正常的数——
本轮实测代价分别是：死引用 6 个里 4 个是假红（真腐烂只有 2 个）；同一面板里同一概念两个数
（40 vs 35）；"硬归因"这条腿从未有过数据（4 条归因事件、0 条被计）。读数错 = 决策错。
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import component_tally as ct  # noqa: E402
import ev_board_data as ebd  # noqa: E402


class DeadRefsTest(unittest.TestCase):
    """scan_dead_refs：只报"真腐烂"，不报相对路径 / 仓外路径 / 否定语境的路径。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "alive.md").write_text("x", encoding="utf-8")
        (self.root / "skills" / "diagnose" / "references").mkdir(parents=True)
        (self.root / "skills" / "diagnose" / "references" / "trace.md").write_text("x", encoding="utf-8")

    def dead(self, text):
        return ebd.scan_dead_refs(self.root, {"text": text})

    def test_real_rot_is_reported(self):
        self.assertEqual(self.dead("见 `docs/removed.md` 的说明"), ["docs/removed.md"])

    def test_relative_path_reference_is_not_rot(self):
        """`references/trace.md` 的真身在 skills/diagnose/references/ —— 按那个 skill 视角写的。"""
        self.assertEqual(self.dead("新增 `references/trace.md`"), [])

    def test_out_of_repo_path_is_not_rot(self):
        """父目录不在检出里 → 不是"被删"，是仓外/上游路径。"""
        self.assertEqual(self.dead("上游仓 `vendor/foo/bar.md`"), [])

    def test_negation_context_is_not_rot(self):
        """卡在陈述"该路径不存在"时，不能读成死指针。"""
        self.assertEqual(self.dead("真实生成物是 `_summary-index.yaml`，与 `references/_index.yaml` 均不存在"),
                         [])

    def test_existing_path_is_not_rot(self):
        self.assertEqual(self.dead("见 `docs/alive.md`"), [])


class SignalShareTest(unittest.TestCase):
    """by_signal 必须用全量信号，与体检判决（signals_all）同口径。"""

    def test_by_signal_counts_all_signals_not_first_three(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "proposals" / "ideas").mkdir(parents=True)
        card = """\
id: EV-2026-901
layer: L2
title: t
status: validated
authorization: review
dimension: evolvability
created_at: 2026-09-17
source_signals:
  - {signal: process_friction, evidence: a, trajectory: [x]}
  - {signal: process_friction, evidence: b, trajectory: [x]}
  - {signal: process_friction, evidence: c, trajectory: [x]}
  - {signal: process_friction, evidence: d, trajectory: [x]}
hypothesis: h
predicted_effect:
  metric: m
  from: a
  to: b
  measure: {command: "true", expect_exit: 0}
validation: {method: scan_review, baseline: b, success_criteria: s, rollback: r}
gate: {condition: c}
risk: low
principle_refs: [10]
decisions:
  - {who: agent, when: 2026-09-17, type: decision, conclusion: "随 PR #1 合入"}
"""
        (root / "proposals" / "ideas" / "EV-2026-901.yaml").write_text(card, encoding="utf-8")
        st = ebd.collect_stats(ebd.collect_ideas(root))
        # 一张卡、4 条同族信号 → 按卡去重记 1（不是 4，也不是被 [:3] 截断后的 3）
        self.assertEqual(st["by_signal"].get("process_friction"), 1)
        self.assertEqual(st["top_signal_share"], 1.0)


class AttributionVocabularyTest(unittest.TestCase):
    """component_tally：生产端写 attribution_kind，消费端必须认，否则硬归因恒为 0。"""

    def test_execution_kind_counts_as_hard(self):
        self.assertTrue(ct.is_hard({"source": "trace", "attribution_kind": "execution"}))
        self.assertFalse(ct.is_hard({"source": "trace", "attribution_kind": "improvement"}))
        self.assertFalse(ct.is_hard({"source": "trace", "attribution_kind": "design"}))

    def test_legacy_verdict_still_counts(self):
        self.assertTrue(ct.is_hard({"source": "trace", "verdict": "execution_error"}))

    def test_aggregate_puts_execution_kind_in_failure_cluster(self):
        entries = [
            {"source": "trace", "trace": "t1.yaml", "component": "skill:diagnose",
             "attribution_kind": "execution", "verdict": None},
            {"source": "trace", "trace": "t1.yaml", "component": "skill:diagnose",
             "attribution_kind": "design", "verdict": None},
        ]
        agg = ct.aggregate(entries)
        self.assertEqual(agg["skill:diagnose"]["trace_mis"], 1)
        self.assertEqual(agg["skill:diagnose"]["s2_candidate"], 0)


if __name__ == "__main__":
    unittest.main()
