"""confidence 搬运的文本手术回归。

搬运脚本做两件不可逆的事：把案例里的历史累计值写成 `kind: baseline` 行、把 `confidence`
块从案例文件里删掉。删块是**文本级**手术（案例文件里有关键注释，不能整篇重新 dump），
所以边界判错会删掉邻字段或留下半截块——两种都不会报错，只会让案例少一个字段或解析失败。
"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import migrate_confidence_baseline as mcb  # noqa: E402

CASE_WITH_CONF = """# 头部注释：说清这条 case 的来历
cases:
  - id: CASE-1
    title: "t"
    category: interrupt
    confidence:
      hits: 4
      misdiagnoses: 1
      last_hit: "2026-W35"
      self_resolved:
        count: 2
        last: "2026-W35"
        examples: [s1, s2]
    symptoms:
      - "s"
    # 说明：confidence/validation_record 由 groom 写入
    root_cause: rc
    fix: f
"""

CASE_NO_CONF = """cases:
  - id: CASE-2
    title: "t"
    category: interrupt
    symptoms:
      - "s"
"""


class StripBlockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.kb = self.root / "knowledge" / "inference" / "vllm-ascend" / "interrupt"
        self.kb.mkdir(parents=True)

    def write(self, name, text):
        p = self.kb / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_block_boundary_keeps_neighbouring_fields(self):
        self.write("CASE-1.yaml", CASE_WITH_CONF)
        items = mcb.scan(self.root)
        self.assertEqual(len(items), 1)
        after = mcb.strip_block(items[0])
        doc = yaml.safe_load(after)
        c = doc["cases"][0]
        self.assertNotIn("confidence", c)
        self.assertEqual(c["symptoms"], ["s"])
        self.assertEqual(c["root_cause"], "rc")
        self.assertIn("# 头部注释：说清这条 case 的来历", after, "案例头部的注释要留住")
        self.assertIn("# 说明：confidence/validation_record 由 groom 写入", after,
                      "紧跟其后的注释不属于该块，不能一起删掉")

    def test_baseline_row_carries_counts_and_week(self):
        self.write("CASE-1.yaml", CASE_WITH_CONF)
        item = mcb.scan(self.root)[0]
        row = mcb.baseline_row(item, "baseline-2026-10-17", "d1")
        self.assertEqual(row["resolved"], 4)
        self.assertEqual(row["misdiagnosed"], 1)
        self.assertEqual(row["self_resolved"], 2)
        self.assertEqual(row["last_hit"], "2026-W35")
        self.assertEqual(row["kind"], "baseline")

    def test_zero_counts_write_no_row(self):
        self.write("CASE-2.yaml", CASE_NO_CONF.replace(
            '    category: interrupt\n',
            '    category: interrupt\n    confidence:\n      hits: 0\n      misdiagnoses: 0\n'))
        item = mcb.scan(self.root)[0]
        self.assertIsNone(mcb.baseline_row(item, "baseline-2026-10-17", "d1"),
                          "计数全为 0 且没有 last_hit：只删块，不写行")

    def test_case_without_confidence_is_untouched(self):
        self.write("CASE-2.yaml", CASE_NO_CONF)
        self.assertEqual(mcb.scan(self.root), [], "没有该块的案例不进搬运清单")

    def test_nested_confidence_scalar_is_not_the_block(self):
        """嵌套的 `confidence: 0.9`（如 notes 下）不能被当成 case 级块删掉。"""
        text = ("cases:\n"
                "  - id: CASE-1\n"
                "    notes:\n"
                "      confidence: 0.9\n"
                "    confidence:\n"
                "      hits: 2\n"
                "    title: t\n")
        lines = text.split("\n")
        start, end, inline = mcb.find_conf_block(lines)
        self.assertFalse(inline)
        self.assertEqual(lines[start].strip(), "confidence:", "找到的应是 case 级那块")
        after = yaml.safe_load(mcb.strip_block(
            {"lines": lines, "start": start, "end": end, "text": text}))
        c = after["cases"][0]
        self.assertNotIn("confidence", c)
        self.assertEqual(c["notes"], {"confidence": 0.9}, "嵌套的那个值要留着")

    def test_comment_between_key_and_children_is_removed_with_the_block(self):
        """`confidence:` 后紧跟同缩进注释时，连同子键一起删（否则留下孤儿子键、YAML 解析失败）。"""
        text = ("cases:\n"
                "  - id: CASE-1\n"
                "    confidence:\n"
                "    # 历史累计\n"
                "      hits: 2\n"
                "    title: t\n")
        lines = text.split("\n")
        start, end, _ = mcb.find_conf_block(lines)
        after = mcb.strip_block({"lines": lines, "start": start, "end": end, "text": text})
        doc = yaml.safe_load(after)   # 解析不过会抛
        self.assertNotIn("confidence", doc["cases"][0])
        self.assertEqual(doc["cases"][0]["title"], "t")

    def test_migration_is_idempotent(self):
        p = self.write("CASE-1.yaml", CASE_WITH_CONF)
        item = mcb.scan(self.root)[0]
        p.write_text(mcb.strip_block(item), encoding="utf-8")
        self.assertEqual(mcb.scan(self.root), [], "删过一次之后不该再被扫出来")


if __name__ == "__main__":
    unittest.main()
