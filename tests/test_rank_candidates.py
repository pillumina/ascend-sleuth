"""rank_candidates 的排序口径回归测试（EV-2026-111）。

护的是三顺位与稳定性：签名字面量命中 > token 交集 > score > id。
排序错=候选顺序错=诊断先看错的 case；而排序是纯计算，出错没有任何别的信号会报。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import rank_candidates as rc  # noqa: E402


def row(cid, sig=(), tok=(), score=None, title="", symptoms=()):
    return {"id": cid, "ns": "inference/vllm-ascend", "category": "interrupt",
            "sig": list(sig), "tok": list(tok), "title": title, "symptoms": list(symptoms),
            "confidence": {"score": score}}


class RankCandidatesTest(unittest.TestCase):
    def ids(self, rows, text):
        return [r["id"] for r, _h, _o in rc.rank_rows(rows, text)]

    def test_signature_literal_beats_token_overlap(self):
        """报错原文命中是最强信号：字面量命中数优先于 token 交集数。"""
        text = "error code 507014 aicore exception"
        a = row("A", sig=["aicore exception"], tok=[])              # 1 条字面量命中
        b = row("B", sig=[], tok=["507014", "0x1234", "v1.2.3"])     # 无字面量，token 交集多
        self.assertEqual(self.ids([b, a], text), ["A", "B"])

    def test_token_overlap_beats_score(self):
        """token 交集优先于 score——score 不是相关性信号（实测依据见卡）。"""
        text = "报错 error code 507014"
        a = row("A", tok=["507014"], score=0.1)
        b = row("B", tok=[], score=0.9)
        self.assertEqual(self.ids([b, a], text), ["A", "B"])

    def test_score_breaks_ties(self):
        a = row("A", score=0.3)
        b = row("B", score=0.7)
        self.assertEqual(self.ids([a, b], "无 token 无字面量"), ["B", "A"])

    def test_id_breaks_final_tie_for_stability(self):
        """全平局时按 id 稳定排序——同一输入两次跑必须同序（可复算的前提）。"""
        rows = [row("C"), row("A"), row("B")]
        self.assertEqual(self.ids(rows, "无信号"), ["A", "B", "C"])
        self.assertEqual(self.ids(list(reversed(rows)), "无信号"), ["A", "B", "C"])

    def test_falls_back_to_row_text_when_tok_absent(self):
        """索引未重建（行内没有 tok）时退回按行内 title+symptoms 现算，不能崩。"""
        a = row("A", title="aclnnMoeDistributeDispatchV4 failed", score=0.1)
        b = row("B", title="别的现象", score=0.9)
        self.assertEqual(self.ids([b, a], "报错 aclnnMoeDistributeDispatchV4 failed"), ["A", "B"])

    def test_empty_text_does_not_crash(self):
        rows = [row("A", sig=["x"]), row("B")]
        self.assertEqual(len(self.ids(rows, "")), 2)

    def test_case_insensitive_literal_match(self):
        a = row("A", sig=["Address already in use"], score=0.1)
        b = row("B", score=0.9)
        self.assertEqual(self.ids([b, a], "报错：address already in use"), ["A", "B"])


    def test_pipeline_isomorphic_eval_counts_recall_and_rank_separately(self):
        """管线同构量尺：筛漏（recall@5）与排后（top3|≤5）必须分开数——两件事的修法不同。"""
        rows = [row("HIT", tok=["507014"], score=0.1),
                row("N1", score=0.9), row("N2", score=0.8), row("N3", score=0.7),
                row("N4", score=0.6), row("N5", score=0.5), row("N6", score=0.4)]
        fixtures = [("HIT", "error code 507014")]
        by_score = rc.evaluate(rows, fixtures, rc._key_score, top_k=5)
        self.assertEqual(by_score["recall_at_k"], 0, "只按 score 时 HIT 排在第 7，筛不进前 5")
        by_lex = rc.evaluate(rows, fixtures, rc._key_lexical, top_k=5)
        self.assertEqual(by_lex["recall_at_k"], 1)
        self.assertEqual(by_lex["top3_given"], 1)
        self.assertEqual(by_lex["median_rank_in_loaded"], 1.0)

    def test_eval_unknown_case_is_skipped_not_counted_as_miss(self):
        """expected 指向未入库 case（构造示例）→ 不计入分母，否则成功率被凭空拉低。"""
        rows = [row("A", score=0.5)]
        e = rc.evaluate(rows, [("A", "x"), ("NOT-IN-KB", "x")], rc._key_score)
        self.assertEqual(e["n"], 1)


if __name__ == "__main__":
    unittest.main()
