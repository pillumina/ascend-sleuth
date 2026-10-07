"""rank_candidates 的排序口径回归测试（EV-2026-111）。

护的是三顺位与稳定性：签名字面量命中 > token 交集 > score > id。
排序错=候选顺序错=诊断先看错的 case；而排序是纯计算，出错没有任何别的信号会报。
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

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


class RankBaselineCompareTest(unittest.TestCase):
    """阶段一排序的前后对照（--write-baseline / --compare-baseline）。

    护三件事：同一份树前后对照报「无变差」并退 0；索引侧证据变了必须报变差并退 1；
    不可比时明确退化而不是给读数——没有基线文件、基线读不出来或不是合法 YAML、基线是空文件、
    基线里没有逐条名次、基线里的名次不是整数或 null、口径不符（排序键或 top_k 不同）、
    基线里的 fixture 名与现状一个都对不上、现状一条 fixture 都评不了，这些路径都退 2，
    且都不给出「无变差」这类肯定读数。
    夹具在临时目录现造（一格索引 + 一条 fixture），不复用真实知识库。
    """

    TEXT = "CUDA error 719 observed during inference"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "eval" / "golden").mkdir(parents=True, exist_ok=True)
        self.base = self.root / ".s2-replay" / "rank-baseline.yaml"
        self._write_index([row("VLLM-ASC-1", sig=["CUDA error 719"], tok=["cuda", "error"]),
                           row("VLLM-ASC-2", tok=["hang"]),
                           row("VLLM-ASC-3", tok=["timeout"])])
        self._write_fixture("fx-a.fixture.yaml", "VLLM-ASC-1")

    def _write_index(self, rows):
        doc = {"namespaces": {"inference/vllm-ascend": {"interrupt": rows}}}
        (self.root / "knowledge").mkdir(parents=True, exist_ok=True)
        (self.root / "knowledge" / "_index.yaml").write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _write_fixture(self, name, case_id):
        (self.root / "eval" / "golden" / name).write_text(
            yaml.safe_dump({"expected": {"case_id": case_id}, "input": {"symptoms": self.TEXT}},
                           allow_unicode=True), encoding="utf-8")

    def _run(self, fn, *a):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = fn(*a)
        return code, out.getvalue(), err.getvalue()

    def test_write_then_compare_no_change(self):
        code, _out, _err = self._run(rc.cmd_write_baseline, self.root, self.base, 5)
        self.assertEqual(code, 0)
        doc = yaml.safe_load(self.base.read_text(encoding="utf-8"))
        self.assertEqual(doc["key"], "lexical")
        self.assertEqual(doc["top_k"], 5)
        self.assertEqual(doc["fixtures"], {"fx-a.fixture.yaml": 1})

        code, out, _err = self._run(rc.cmd_compare_baseline, self.root, self.base, 5)
        self.assertEqual(code, 0)
        self.assertIn("无变差", out)

    def test_compare_reports_regression_and_exits_1(self):
        self._run(rc.cmd_write_baseline, self.root, self.base, 5)
        # 改动后：期望 case 丢了字面量分支，同格子多出 5 条更强的竞争者
        rows = [row("VLLM-ASC-1", tok=["cuda", "error"])]
        rows += [row(f"VLLM-ASC-{i}", sig=["CUDA error 719"]) for i in range(4, 9)]
        self._write_index(rows)

        code, out, _err = self._run(rc.cmd_compare_baseline, self.root, self.base, 5)
        self.assertEqual(code, 1)
        self.assertIn("变差", out)
        self.assertIn("fx-a.fixture.yaml", out)
        self.assertIn("未进候选", out)

    def test_compare_without_baseline_returns_2(self):
        code, _out, err = self._run(rc.cmd_compare_baseline, self.root, self.base, 5)
        self.assertEqual(code, 2)
        self.assertIn("--write-baseline", err)

    def test_top_k_mismatch_is_not_comparable(self):
        self._run(rc.cmd_write_baseline, self.root, self.base, 5)
        code, _out, err = self._run(rc.cmd_compare_baseline, self.root, self.base, 3)
        self.assertEqual(code, 2)
        self.assertIn("不可比", err)

    def test_fixture_with_unknown_case_is_skipped(self):
        self._write_fixture("fx-gone.fixture.yaml", "VLLM-ASC-999")
        code, out, _err = self._run(rc.cmd_write_baseline, self.root, self.base, 5)
        self.assertEqual(code, 0)
        self.assertIn("skip 1 条", out)
        doc = yaml.safe_load(self.base.read_text(encoding="utf-8"))
        self.assertEqual(list(doc["fixtures"]), ["fx-a.fixture.yaml"])

    def test_corrupt_baseline_is_not_comparable(self):
        """基线不是合法 YAML：退 2 并说清怎么重写，不能抛异常退 1（退 1 是「查出变差」）。"""
        self.base.parent.mkdir(parents=True, exist_ok=True)
        self.base.write_text("fixtures: [不是映射\n", encoding="utf-8")
        code, _out, err = self._run(rc.cmd_compare_baseline, self.root, self.base, 5)
        self.assertEqual(code, 2)
        self.assertIn("读不出来", err)
        self.assertIn("--write-baseline", err)

    def test_empty_baseline_reports_missing_readings_not_no_change(self):
        """0 字节基线：退 2，且原因必须是「没有逐条名次」，不是「无变差」或 top_k 不符。"""
        self.base.parent.mkdir(parents=True, exist_ok=True)
        self.base.write_text("", encoding="utf-8")
        code, out, err = self._run(rc.cmd_compare_baseline, self.root, self.base, 5)
        self.assertEqual(code, 2)
        self.assertIn("没有逐条名次", err)
        self.assertNotIn("无变差", out)

    def test_baseline_without_fixtures_is_not_comparable(self):
        """合法 YAML 但没有逐条名次（只有 top_k）：退 2——不能对一份不可比的基线说「无变差」。"""
        self.base.parent.mkdir(parents=True, exist_ok=True)
        self.base.write_text(yaml.safe_dump({"key": "lexical", "top_k": 5}), encoding="utf-8")
        code, out, err = self._run(rc.cmd_compare_baseline, self.root, self.base, 5)
        self.assertEqual(code, 2)
        self.assertIn("没有逐条名次", err)
        self.assertNotIn("无变差", out)

    def test_baseline_key_mismatch_is_not_comparable(self):
        """基线是别的排序键算的：退 2（换键后名次不是同一把尺子量的）。"""
        self._run(rc.cmd_write_baseline, self.root, self.base, 5)
        doc = yaml.safe_load(self.base.read_text(encoding="utf-8"))
        doc["key"] = "score"
        self.base.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                             encoding="utf-8")
        code, _out, err = self._run(rc.cmd_compare_baseline, self.root, self.base, 5)
        self.assertEqual(code, 2)
        self.assertIn("不可比", err)

    def test_renamed_fixture_is_not_counted_as_regression(self):
        """夹具改名：现状缺的是 fixture 文件本身，不是期望 case 掉出候选——不报成变差。"""
        self._write_fixture("fx-keep.fixture.yaml", "VLLM-ASC-2")
        self._run(rc.cmd_write_baseline, self.root, self.base, 5)
        (self.root / "eval" / "golden" / "fx-a.fixture.yaml").unlink()
        self._write_fixture("fx-b.fixture.yaml", "VLLM-ASC-1")
        code, out, _err = self._run(rc.cmd_compare_baseline, self.root, self.base, 5)
        self.assertEqual(code, 0)
        self.assertIn("不计入变差 fx-a.fixture.yaml", out)
        self.assertIn("新增 fixture 1 条", out)

    def test_all_fixtures_renamed_is_not_comparable(self):
        """基线里的名字与现状一个都对不上：没有任何一条真被对照过，不能报「无变差」退 0。"""
        self._run(rc.cmd_write_baseline, self.root, self.base, 5)
        (self.root / "eval" / "golden" / "fx-a.fixture.yaml").unlink()
        self._write_fixture("fx-b.fixture.yaml", "VLLM-ASC-1")
        self._write_fixture("fx-c.fixture.yaml", "VLLM-ASC-2")
        code, out, err = self._run(rc.cmd_compare_baseline, self.root, self.base, 5)
        self.assertEqual(code, 2)
        self.assertIn("一个都对不上", err)
        self.assertNotIn("无变差", out)

    def test_baseline_with_non_integer_rank_is_not_comparable(self):
        """基线里的名次必须是整数或 null：写成字符串会抛异常退 1（退 1 是「查出变差」），写成小数不能当名次用。"""
        self._run(rc.cmd_write_baseline, self.root, self.base, 5)
        for value in ("1", 1.5, True):
            with self.subTest(value=value):
                doc = yaml.safe_load(self.base.read_text(encoding="utf-8"))
                doc["fixtures"]["fx-a.fixture.yaml"] = value
                self.base.write_text(
                    yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
                code, out, err = self._run(rc.cmd_compare_baseline, self.root, self.base, 5)
                self.assertEqual(code, 2)
                self.assertIn("不是整数或 null", err)
                self.assertNotIn("无变差", out)

    def test_no_evaluable_fixture_reports_cause(self):
        """现状一条 fixture 都评不了（夹具改名/删除或知识库没重建）：说清原因并退 2，不给读数。"""
        self._run(rc.cmd_write_baseline, self.root, self.base, 5)
        (self.root / "eval" / "golden" / "fx-a.fixture.yaml").unlink()
        self._write_fixture("fx-gone.fixture.yaml", "VLLM-ASC-999")
        code, out, err = self._run(rc.cmd_compare_baseline, self.root, self.base, 5)
        self.assertEqual(code, 2)
        self.assertIn("一条 fixture 都评不了", err)
        self.assertIn("build_index.py", err)
        self.assertNotIn("无变差", out)


if __name__ == "__main__":
    unittest.main()
