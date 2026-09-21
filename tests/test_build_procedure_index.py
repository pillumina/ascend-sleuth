"""build_procedure_index 的分片口径回归测试。

分片最危险的失败模式是**静默消失**：某条流程既不在这片也不在那片，`--check` 全绿，
而读侧从此看不到它——索引本身没错，错的是它与词条集合的对应关系。本文件把三条
对应关系钉住：①每条 active methodology 在它声明的每个分片里；②选择器声明的分片集合
与磁盘上的分片文件一致；③选择器自己始终是小文件（它每次都要整读，涨回去就等于没分片）。
"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_procedure_index as bp  # noqa: E402

ENTRY_TMPL = """id: {rid}
type: methodology
title: "{title}"
summary: "{summary}"
sources:
- type: official-doc
  url: https://example.invalid/{rid}
status: active
last_verified: '2026-09-01'
applies_to:
  categories: [{cats}]
  platforms: [cross]
content:
  flow:
  - step: 1
    action: a
    check: c
"""


class ProcedureShardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "references").mkdir()
        (self.root / "scripts").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_ref(self, rid, cats, title="t", summary="s"):
        p = self.root / "references" / "methodologies" / f"{rid}.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ENTRY_TMPL.format(rid=rid, cats=", ".join(cats), title=title, summary=summary),
                     encoding="utf-8")
        return p

    def build(self):
        outs, entries, keys = bp.expected_outputs(self.root)
        (self.root / "references" / bp.SHARD_DIR_NAME).mkdir(parents=True, exist_ok=True)
        for rel, text in outs.items():
            (self.root / "references" / rel).write_text(text, encoding="utf-8")
        return outs, entries, keys

    def entries_of(self, outs, key):
        return {e["id"] for e in yaml.safe_load(outs[f"{bp.SHARD_DIR_NAME}/{key}.yaml"])["entries"]}

    # ------------------------------------------------------------ 分片归属
    def test_every_active_methodology_lands_in_its_categories(self):
        self.write_ref("proc-a", ["interrupt"])
        self.write_ref("proc-b", ["precision", "interrupt"])
        outs, entries, keys = self.build()
        self.assertEqual(sorted(keys), ["interrupt", "precision"])
        self.assertEqual(self.entries_of(outs, "interrupt"), {"proc-a", "proc-b"})
        self.assertEqual(self.entries_of(outs, "precision"), {"proc-b"})

    def test_cross_procedure_gets_its_own_shard(self):
        """applies_to.categories 为空 = 不限定类别——必须有 `_cross` 片，否则它谁也看不到。"""
        self.write_ref("proc-a", ["interrupt"])
        self.write_ref("proc-any", [])
        outs, entries, keys = self.build()
        self.assertIn(bp.CROSS_KEY, keys)
        self.assertEqual(self.entries_of(outs, bp.CROSS_KEY), {"proc-any"})

    def test_non_active_and_non_methodology_excluded(self):
        self.write_ref("proc-a", ["interrupt"])
        p = self.write_ref("proc-draft", ["interrupt"])
        p.write_text(p.read_text(encoding="utf-8").replace("status: active", "status: deprecated"),
                     encoding="utf-8")
        outs, entries, keys = self.build()
        self.assertEqual([e["id"] for e in entries], ["proc-a"])

    # ------------------------------------------------------------ 选择器与分片一致
    def test_selector_lists_every_shard(self):
        self.write_ref("proc-a", ["interrupt"])
        self.write_ref("proc-b", ["performance"])
        outs, entries, keys = self.build()
        sel = yaml.safe_load(outs[bp.OUT_NAME])
        self.assertEqual([s["category"] for s in sel["shards"]], keys)
        self.assertEqual(sel["procedures_total"], 2)
        for s in sel["shards"]:
            # 选择器里的路径是仓库相对（人要照着它开文件），outs 的键是 references/ 相对
            self.assertTrue(s["shard"].startswith("references/"))
            self.assertIn(s["shard"][len("references/"):], outs)

    def test_selector_stays_small(self):
        """选择器每次都要整读——它涨回去，分片就白分了。"""
        for i in range(12):
            self.write_ref(f"proc-{i}", ["interrupt"], summary="x" * 200)
        outs, entries, keys = self.build()
        self.assertLess(bp._tokens(outs[bp.OUT_NAME]), bp.SELECTOR_CAP_TOKENS)

    def test_shard_carries_full_selector_row(self):
        """分片行必须带 title/summary——它们是选择的依据，截掉就没法选（与 case 索引同一纪律）。"""
        long_summary = "y" * 400
        self.write_ref("proc-a", ["interrupt"], summary=long_summary)
        outs, entries, keys = self.build()
        row = yaml.safe_load(outs[f"{bp.SHARD_DIR_NAME}/interrupt.yaml"])["entries"][0]
        self.assertEqual(sorted(row), ["categories", "file", "id", "platforms", "summary", "title"])
        self.assertLessEqual(len(row["summary"]), bp.SUMMARY_CAP)
        self.assertTrue(row["file"].startswith("references/"))

    # ------------------------------------------------------------ --check 的牙齿
    def run_check(self):
        """跑真实的 --check 入口（判据在 main 里，直接调它才算测到牙齿）。"""
        import contextlib
        import io
        from unittest import mock
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["build_procedure_index.py", "--check", "--root", str(self.root)]):
            with contextlib.redirect_stdout(buf):
                code = bp.main()
        return code, buf.getvalue()

    def test_check_passes_on_fresh_index(self):
        self.write_ref("proc-a", ["interrupt"])
        self.write_ref("proc-b", [])
        self.build()
        code, out = self.run_check()
        self.assertEqual(code, 0, out)

    def test_check_detects_stale_shard(self):
        """分片过期（词条改了没重建）必须红——否则读侧按旧 title 选错过时的流程。"""
        self.write_ref("proc-a", ["interrupt"])
        self.build()
        self.write_ref("proc-a", ["interrupt"], title="renamed")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("过期", out)

    def test_check_flags_orphan_shard(self):
        """categories 改过之后旧分片会留下——读侧会把它当成"本 category 有专用分片"，是静默误导。"""
        self.write_ref("proc-a", ["interrupt"])
        self.write_ref("proc-b", ["precision"])
        self.build()
        (self.root / "references" / bp.SHARD_DIR_NAME / "oldcat.yaml").write_text(
            "entries: []\n", encoding="utf-8")
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("残留分片", out)

    def test_check_flags_missing_shard_file(self):
        """选择器指向的分片被删掉 → 红（否则读侧打开一个不存在的文件）。"""
        self.write_ref("proc-a", ["interrupt"])
        self.build()
        (self.root / "references" / bp.SHARD_DIR_NAME / "interrupt.yaml").unlink()
        code, out = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("不存在", out)

    def test_parsers_reject_wrong_shape(self):
        """选择器与分片不同形——只判"能解析"的话，两者互换也全绿，而读侧拿不到 shards 字段。"""
        self.write_ref("proc-a", ["interrupt"])
        outs, entries, keys = self.build()
        shard_text = outs[f"{bp.SHARD_DIR_NAME}/interrupt.yaml"]
        self.assertEqual(bp.parses_shard(shard_text), "")
        self.assertNotEqual(bp.parses_selector(shard_text), "")


if __name__ == "__main__":
    unittest.main()
