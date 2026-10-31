"""状态投影与派生判据的回归。

护三件事：
1. 派生量与既有实现同口径（闭环、待沉淀、未收尾、价值序）——它们此前写在面板 JS 里，
   搬进 Python 时最容易「看起来一样、边界差一个」；
2. 动作只给当前状态合法的（终态不给收尾、缺收尾方式只给补记、有收尾方式只给改）；
3. 状态列颜色由库算（反向回报不用绿、待回报用空心琥珀），面板不再自己判。
"""

import sys
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
        tone = st.display_tone("resolved", "not_resolved")
        self.assertEqual(tone["color"], "var(--c-gray)")

    def test_pending_is_hollow_amber(self):
        tone = st.display_tone("resolved", "pending")
        self.assertTrue(tone["hollow"])
        self.assertEqual(tone["color"], "var(--c-amber)")

    def test_normal_resolved_green(self):
        self.assertEqual(st.display_tone("resolved", None)["color"], "var(--c-green)")


if __name__ == "__main__":
    unittest.main()
