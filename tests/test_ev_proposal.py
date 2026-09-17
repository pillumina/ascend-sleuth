"""ev_proposal 的合入指针回写与候选水位读数（本卡机制修正）。

护的是两件会直接把演进闭环的读数带偏的事：
① **回写指针**：判据「待合入积压」数的是"已验证但没有合入指针的卡"。指针只能写进卡文本，
   而从来没有机制保证它被写——实测一批 7 张卡随同一个 PR 合入 main、7 张全部无指针，判据读成
   "未合入"。回写因此必须是脚本（保留注释、只追加、可重复执行）。
② **水位读数**：设计处把「候选水位上限」标为蓝图态、启用条件是"积压真实发生（>20 在池）"；
   该条件早已满足，而 skill 正文那句"超限只记信号不产卡"既无数值也无读数。水位是一条读数 + 退出码。
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ev_proposal as ep  # noqa: E402

CARD = """\
# 一张带注释的卡（回写必须保留注释与既有内容）
id: EV-2026-900
layer: L2
title: 示例
status: validated
authorization: review
dimension: evolvability
created_at: 2026-09-17
source_signals:
  - signal: process_friction
    evidence: "示例"
    trajectory:
      - "traces/x.yaml"
hypothesis: 示例
predicted_effect:
  metric: m
  from: a
  to: b
  measure:
    command: "true"
    expect_exit: 0
validation:
  method: scan_review
  baseline: b
  success_criteria: s
  rollback: r
gate:
  condition: c
risk: low
principle_refs: [10]
decisions:
  - who: agent
    when: 2026-09-17
    type: proposal
    conclusion: "产卡"
"""


class MarkMergedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "proposals" / "ideas").mkdir(parents=True)
        self.card = self.root / "proposals" / "ideas" / "EV-2026-900.yaml"
        self.card.write_text(CARD, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_appends_pointer_and_preserves_everything(self):
        rc = ep.mark_merged(self.root, "242", [], all_pending=True, dry_run=False)
        self.assertEqual(rc, 0)
        text = self.card.read_text(encoding="utf-8")
        self.assertIn("PR #242", text)
        self.assertTrue(text.startswith("# 一张带注释的卡"))          # 注释保留
        self.assertIn('conclusion: "产卡"', text)                      # 既有内容保留
        doc = ep.load_yaml(self.card)
        self.assertEqual(doc["decisions"][-1]["type"], "action")       # 结构仍是合法卡
        self.assertEqual(doc["id"], "EV-2026-900")

    def test_idempotent(self):
        ep.mark_merged(self.root, "242", [], all_pending=True, dry_run=False)
        before = self.card.read_text(encoding="utf-8")
        ep.mark_merged(self.root, "242", [], all_pending=True, dry_run=False)
        self.assertEqual(before, self.card.read_text(encoding="utf-8"))

    def test_dry_run_writes_nothing(self):
        before = self.card.read_text(encoding="utf-8")
        rc = ep.mark_merged(self.root, "242", [], all_pending=True, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertEqual(before, self.card.read_text(encoding="utf-8"))

    def test_only_validated_cards_are_pending(self):
        """已 rejected / in_experiment 的卡不进 --all-pending（它们不是"待合入"）。"""
        d = ep.load_yaml(self.card)
        d["status"] = "rejected"
        ep.write_text_lf(self.card, __import__("yaml").safe_dump(d, allow_unicode=True, sort_keys=False),
                         encoding="utf-8")
        rc = ep.mark_merged(self.root, "242", [], all_pending=True, dry_run=False)
        self.assertEqual(rc, 0)
        self.assertNotIn("PR #242", self.card.read_text(encoding="utf-8"))

    def test_refuses_when_decisions_is_not_last(self):
        """顶层最后一段不是 decisions 时拒绝（追加会破坏结构），并给出非零退出。"""
        self.card.write_text(CARD + "extra_key: 1\n", encoding="utf-8")
        rc = ep.mark_merged(self.root, "242", [self.card.stem] if False else ["EV-2026-900"],
                            all_pending=False, dry_run=False)
        self.assertEqual(rc, 2)
        self.assertNotIn("PR #242", self.card.read_text(encoding="utf-8"))

    def test_unknown_card_is_an_error(self):
        self.assertEqual(ep.mark_merged(self.root, "242", ["EV-9999-999"], False, False), 2)


class WaterlineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "proposals" / "ideas").mkdir(parents=True)
        for i in range(3):
            p = self.root / "proposals" / "ideas" / f"EV-2026-90{i}.yaml"
            p.write_text(CARD.replace("EV-2026-900", f"EV-2026-90{i}"), encoding="utf-8")
        # 一张已带指针的卡：不应计入待回写
        p = self.root / "proposals" / "ideas" / "EV-2026-909.yaml"
        p.write_text(CARD.replace("EV-2026-900", "EV-2026-909").replace(
            'conclusion: "产卡"', 'conclusion: "随 PR #99 合入"'), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_pending_without_pointer(self):
        self.assertEqual(ep.waterline(self.root, 20), 0)   # 3 < 20 → 未超限
        self.assertEqual(ep.waterline(self.root, 3), 1)    # 3 >= 3 → 超限（退 1）
        self.assertEqual(ep.waterline(self.root, 4), 0)


if __name__ == "__main__":
    unittest.main()


class ImpactViewTest(unittest.TestCase):
    """同组件先例视图：按组件聚合尝试与结局（有否决/换方向的组件才让"先例咨询"有信息量）。"""

    def _card(self, cid, status, component):
        return (CARD.replace("EV-2026-900", cid)
                    .replace("layer: L2", f"layer: L2\ntarget_component: {component}")
                    .replace("status: validated", f"status: {status}"))

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        d = self.root / "proposals" / "ideas"
        d.mkdir(parents=True)
        (d / "EV-2026-901.yaml").write_text(self._card("EV-2026-901", "validated", "scripts/same.py"),
                                            encoding="utf-8")
        (d / "EV-2026-902.yaml").write_text(self._card("EV-2026-902", "rejected", "scripts/same.py"),
                                            encoding="utf-8")
        (d / "EV-2026-903.yaml").write_text(self._card("EV-2026-903", "validated", "scripts/other.py"),
                                            encoding="utf-8")

    def test_aggregates_by_target_component_and_flags_divergence(self):
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ep.impact(self.root)
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("scripts/same.py：2 次", out)
        self.assertIn("有结局分歧", out)
        self.assertIn("1 个有结局分歧", out)

    def test_unknown_component_exits_2(self):
        self.assertEqual(ep.impact(self.root, component="不存在的组件"), 2)
