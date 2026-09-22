"""结构数字（条数 / 逐格容量）的口径回归测试。

这些数字原先写在生成物 `knowledge/_index.yaml` 的头注里，是**共享热点**：两人并发改不同框架
时会撞同一段文本，或各自写出漂移的数（后来真实值 +2，文件里还是旧数）。现在改成从 case 文件
现算（`scripts/index_counts.py`）——本文件钉住三件事：数字确实来自文件、格子口径没变、
以及体检脚本的结构侧用的是这条现算路径（不再有第二份副本）。
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import index_counts as IC  # noqa: E402
import metrics_snapshot as MS  # noqa: E402

CASE = """cases:
  - id: {cid}
    title: "数字口径测试 {cid}"
    category: {cat}
    tags: [t]
    confidence:
      score: 0.5
    symptoms:
      - "症状 {cid}"
"""


class CountsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "knowledge").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, ns_dir, cat, cid):
        p = self.root / "knowledge" / ns_dir / f"{cid}.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CASE.format(cid=cid, cat=cat), encoding="utf-8")

    def test_counts_come_from_files(self):
        for i in range(3):
            self.write_case("inference/vllm-ascend/interrupt", "interrupt", f"A-{i}")
        self.write_case("training/verl/precision", "precision", "B-0")
        data = IC.counts(self.root)
        self.assertEqual(data["total"], 4)
        by = {(c["namespace"], c["category"]): c for c in data["cells"]}
        self.assertEqual(by[("inference/vllm-ascend", "interrupt")]["count"], 3)
        self.assertEqual(by[("training/verl", "precision")]["count"], 1)

    def test_caps_and_flags(self):
        """soft/hard cap 是**算出来的标志**，不是文件里写死的数字。"""
        for i in range(IC.BI.SOFT_CAP + 1):
            self.write_case("inference/vllm-ascend/interrupt", "interrupt", f"A-{i}")
        cell = {(c["namespace"], c["category"]): c for c in IC.counts(self.root)["cells"]}[
            ("inference/vllm-ascend", "interrupt")]
        self.assertEqual(cell["soft_cap"], IC.BI.SOFT_CAP)
        self.assertEqual(cell["hard_cap"], IC.BI.HARD_CAP)
        self.assertTrue(cell["over_soft"])
        self.assertFalse(cell["over_hard"])
        for i in range(IC.BI.HARD_CAP - IC.BI.SOFT_CAP + 1):
            self.write_case("inference/vllm-ascend/interrupt", "interrupt", f"B-{i}")
        cell = {(c["namespace"], c["category"]): c for c in IC.counts(self.root)["cells"]}[
            ("inference/vllm-ascend", "interrupt")]
        self.assertTrue(cell["over_hard"])

    def test_no_number_is_stored_in_the_index(self):
        """生成物里不留数字：这是 union 合并能用的前提（数字一进去，两人并发非撞即漂）。"""
        self.write_case("inference/vllm-ascend/interrupt", "interrupt", "A-0")
        import build_index as BI
        head = BI.render(BI.collect(self.root)).split("namespaces:")[0]
        for bad in ("case 总数：", "容量(", "生成日期："):
            self.assertNotIn(bad, head)

    def test_metrics_snapshot_structural_side_uses_computed_counts(self):
        """体检脚本的结构侧走现算：case_total 与 capacity_by_ns 都来自文件。
        （这条替代了原先"面板/体检读索引头注"的路径——那份副本已删除。）"""
        for i in range(2):
            self.write_case("inference/vllm-ascend/interrupt", "interrupt", f"A-{i}")
        out, notes = MS.collect_structural(self.root)
        self.assertEqual(out["case_total"], 2)
        self.assertEqual(out["capacity_by_ns"]["inference/vllm-ascend"]["interrupt"]["count"], 2)
        self.assertEqual(out["capacity_by_ns"]["inference/vllm-ascend"]["interrupt"]["cap"], IC.BI.SOFT_CAP)


if __name__ == "__main__":
    unittest.main()
