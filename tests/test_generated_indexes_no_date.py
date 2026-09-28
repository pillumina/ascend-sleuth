"""三个索引生成物都不写日期——这条不变量原先只有知识索引有。

为什么值得一条测试：日期是「每次重建都变」的字段。一进 git，它就产生一处与内容无关的改动，
并发合并时又是一行必撞的同一行（`build_index.py` 去掉日期就是这个理由，见其头注）。
另外三个索引原先的做法是「写日期 + `--check` 归一化掉再比」：归一化让 `--check` 绿了，
却把合并时的撞行留了下来。本文件钉住两件事：
  ① 三个生成器的渲染结果头注里不出现日期——**防回归的主力**：谁把日期写回生成器，
     它当场红（生成物有没有跟着重生都红）；
  ② 生成物里多一行日期 → `--check` 报过期，钉的是「比较不再容忍额外行」。
     **它不能用来断言「归一化回不来」**：归一化只替换日期值、消不掉多出来的那一行，
     所以单独把归一化加回 `--check` 时 ② 不响（实测过），那一侧靠 ① 守。
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_error_gap_index as beg  # noqa: E402
import build_procedure_index as bp  # noqa: E402
import build_ref_summary_index as brs  # noqa: E402

DATE_RE = r"\d{4}-\d{2}-\d{2}"

METHODOLOGY = """id: proc-a
type: methodology
title: "t"
summary: "s"
sources:
- type: official-doc
  url: https://example.invalid/proc-a
status: active
last_verified: '2026-09-01'
applies_to:
  categories: [interrupt]
  platforms: [cross]
content:
  flow:
  - step: 1
    action: a
    check: c
"""

BACKGROUND = """id: fact-a
type: software-fact
title: "t"
summary: "s"
sources:
- type: official-doc
  url: https://example.invalid/fact-a
status: active
last_verified: '2026-09-01'
content:
  claim: c
  evidence: e
"""

FAULT_PATTERN = """id: fp-a
type: fault-pattern
title: "t"
summary: "s"
sources:
- type: official-doc
  url: https://example.invalid/fp-a
status: active
last_verified: '2026-09-01'
patterns:
- symptom: "报 507014"
  cause: c
  fix: f
"""


class RenderedHeadHasNoDateTest(unittest.TestCase):
    """① 渲染结果的头注里不许有日期（头注之外允许出现日期：词条正文可以提到时间）。"""

    def assert_head_date_free(self, text, head_marker, label):
        head = text.split(head_marker)[0]
        # 形态先自检：marker 一旦被改名，split 会退化成整篇，断言随之静默失效
        self.assertLess(len(head), len(text), f"{label} 的切分点 {head_marker} 没找到")
        self.assertNotRegex(head, DATE_RE, f"{label} 头注里出现了日期")
        # 只拦「生成日期：」这种真的在写日期的行——头注里那句「不写生成日期」的说明不算
        self.assertNotRegex(head, r"(?m)^#\s*生成日期", f"{label} 头注里出现了「生成日期：」行")

    def test_procedure_selector_and_shards(self):
        outs, _, keys = bp.expected_outputs(ROOT)
        self.assert_head_date_free(outs[bp.OUT_NAME], "procedures_total:", "流程选择器")
        for key in keys:
            self.assert_head_date_free(outs[f"{bp.SHARD_DIR_NAME}/{key}.yaml"], "entries:", f"分片 {key}")

    def test_reference_summary_index(self):
        text = brs.render(brs.collect(ROOT / "references"))
        self.assert_head_date_free(text, "entries:", "背景类 summary 索引")

    def test_error_gap_index(self):
        text = beg.render(ROOT / "references")
        self.assert_head_date_free(text, "code_gaps:", "错误码缺口索引")


class CheckRejectsExtraLinesTest(unittest.TestCase):
    """② 生成物里塞一行日期 → `--check` 报过期（比较不再容忍额外行）。

    适用范围窄于直觉：**不能**用它断言「归一化回不来」——归一化只替换日期值、
    消不掉多出来的那一行，它可以一边存在一边让本条通过。防那条回归靠 ①。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir()
        (self.root / "references" / "methodologies").mkdir(parents=True)
        (self.root / "references" / "software-facts").mkdir(parents=True)
        (self.root / "references" / "fault-patterns").mkdir(parents=True)
        (self.root / "references" / "errors").mkdir(parents=True)
        (self.root / "references" / "methodologies" / "proc-a.yaml").write_text(METHODOLOGY, encoding="utf-8")
        (self.root / "references" / "software-facts" / "fact-a.yaml").write_text(BACKGROUND, encoding="utf-8")
        (self.root / "references" / "fault-patterns" / "fp-a.yaml").write_text(FAULT_PATTERN, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self, module, argv):
        """跑真实的 main() 入口——判据在 main 里，绕开它等于没测到牙齿。
        三个 main 的退出方式不一致（两个 return 码、一个 sys.exit），两种都接住。"""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with mock.patch.object(sys, "argv", argv):
                try:
                    code = module.main()
                except SystemExit as e:
                    code = e.code
        return (0 if code is None else code), buf.getvalue()

    def write_all(self, outs):
        for rel, text in outs.items():
            p = self.root / "references" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")

    def test_procedure_index(self):
        outs, _, _ = bp.expected_outputs(self.root)
        self.write_all(outs)
        code, _ = self.run_check(bp, ["build_procedure_index.py", "--check", "--root", str(self.root)])
        self.assertEqual(code, 0)
        shard = self.root / "references" / bp.SHARD_DIR_NAME / "interrupt.yaml"
        shard.write_text(shard.read_text(encoding="utf-8") + "# 生成日期：2026-09-28\n", encoding="utf-8")
        code, out = self.run_check(bp, ["build_procedure_index.py", "--check", "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("过期", out)

    def test_reference_summary_index(self):
        text = brs.render(brs.collect(self.root / "references"))
        out_path = self.root / "references" / brs.OUT_NAME
        out_path.write_text(text, encoding="utf-8")
        code, _ = self.run_check(brs, ["build_ref_summary_index.py", "--check", "--root", str(self.root)])
        self.assertEqual(code, 0)
        out_path.write_text(text.replace("entries:", "# 生成日期：2026-09-28\nentries:"), encoding="utf-8")
        code, out = self.run_check(brs, ["build_ref_summary_index.py", "--check", "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("过期", out)

    def test_error_gap_index(self):
        text = beg.render(self.root / "references")
        out_path = self.root / "references" / beg.OUT_REL
        out_path.write_text(text, encoding="utf-8")
        code, _ = self.run_check(beg, ["build_error_gap_index.py", "--check", "--root", str(self.root)])
        self.assertEqual(code, 0)
        out_path.write_text("generated_at: 2026-09-28\n" + text, encoding="utf-8")
        code, out = self.run_check(beg, ["build_error_gap_index.py", "--check", "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("过期", out)


if __name__ == "__main__":
    unittest.main()
