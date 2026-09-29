"""容量判据链的口径回归测试（2026-09-29，EV-2026-162）。

为什么单开一个文件：容量线从"条数"迁到"阶段一实读 token"之后，**判定链有三段**
（读侧视图 → 现算成本 → 判据比较），任何一段拿不到数据都必须表现为"未评估（--check 退 2）"，
而不是"均未触发（绿）"。历史上这里吃过两次假绿：
  ① 读侧视图缺失 → 成本记 None 被跳过 → 输出「所有格子均未触发」；
  ② 结构侧整块拿不到（knowledge/ 不在）→ 同上。
两条都在这里钉住——判据可以"没数据"，但不能把"没数据"说成"没事"。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_index as BI  # noqa: E402
import index_read_cost as IRC  # noqa: E402

CASE = """cases:
  - id: {cid}
    title: "容量测试 {cid}"
    category: interrupt
    tags: [t]
    confidence: {{score: 0.5}}
    symptoms:
      - "症状 {cid}：error code 507014"
"""


class CapacityGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "knowledge").mkdir()
        (self.root / "metrics").mkdir()
        # 判据文件按真实仓库的形状给两条 token 线（体检脚本读它）
        (self.root / "metrics" / "gates.yaml").write_text(
            "gates:\n"
            "  - id: cell_read_soft_tok\n"
            "    dimension: capacity_cell_read_tok\n"
            "    op: \">\"\n"
            "    value: 8000\n"
            "    meaning: 超评估线\n"
            "    action: 看能否再省\n"
            "  - id: cell_read_hard_tok\n"
            "    dimension: capacity_cell_read_tok\n"
            "    op: \">=\"\n"
            "    value: 20000\n"
            "    meaning: 超硬线\n"
            "    action: 先瘦身\n",
            encoding="utf-8")
        (self.root / "metrics" / "timeline.yaml").write_text("periods: []\n", encoding="utf-8")
        (self.root / "references").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, rel, cid):
        p = self.root / "knowledge" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CASE.format(cid=cid), encoding="utf-8")

    def generate_views(self):
        ns = BI.collect(self.root)
        (self.root / "knowledge" / "_index").mkdir(parents=True, exist_ok=True)
        for nsk, cells in ns.items():
            BI.shard_path(self.root, nsk).write_text(BI.render_shard(nsk, cells), encoding="utf-8")
            for cat, cases in cells.items():
                BI.shard_path(self.root, f"{nsk}__{cat}").write_text(
                    BI.render_shard(f"{nsk}__{cat}", {cat: cases}), encoding="utf-8")

    def health(self):
        r = subprocess.run([sys.executable, "scripts/metrics_health.py", "--json", "--check",
                            "--root", str(self.root)], cwd=ROOT, capture_output=True, text=True)
        return r.returncode, json.loads(r.stdout)

    # ---------------------------------------------------------------- 判据身份
    def test_gate_ids_name_the_governed_quantity(self):
        """判据 id 要写明量是 token；条数不再是判据（它只作观察值）。"""
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", "A-1")
        self.generate_views()
        _rc, doc = self.health()
        ids = [g["id"] for g in doc["gates"]]
        self.assertIn("cell_read_soft_tok", ids)
        self.assertIn("cell_read_hard_tok", ids)
        self.assertFalse([i for i in ids if i.endswith("_cap")], ids)

    # ---------------------------------------------------------------- 量不出 ≠ 没事
    def test_missing_read_view_is_not_evaluated(self):
        """读侧视图缺失 → 该判据**未评估**（--check 退 2），不是"均未触发"。"""
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", "A-1")
        self.generate_views()
        BI.shard_path(self.root, "inference__vllm-ascend__interrupt").unlink()
        rc, doc = self.health()
        self.assertEqual(rc, 2, doc.get("check_verdict"))
        self.assertLess(doc["coverage"]["gates_evaluated"], doc["coverage"]["gates_total"])
        self.assertTrue(any("容量线未评估" in b for b in doc["broken"]), doc["broken"])

    def test_structural_side_unavailable_is_not_evaluated(self):
        """结构侧整块拿不到（knowledge/ 不在）→ 同样退 2，不许报"所有格子均未触发"。"""
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", "A-1")
        self.generate_views()
        import shutil
        shutil.rmtree(self.root / "knowledge")
        rc, doc = self.health()
        self.assertEqual(rc, 2, doc.get("check_verdict"))
        self.assertTrue(any("容量线未评估" in b for b in doc["broken"]), doc["broken"])

    # ---------------------------------------------------------------- 兜底视图也判线
    def add_fallback_gates(self, soft="1", hard="1"):
        """给 fixture 的 gates.yaml 追加兜底视图那两条线（值取 1：合成库很小，判的是接线）。"""
        g = self.root / "metrics" / "gates.yaml"
        g.write_text(g.read_text(encoding="utf-8")
                     + "  - id: fallback_read_soft_tok\n"
                       "    dimension: capacity_fallback_read_tok\n"
                       "    op: \">\"\n"
                       f"    value: {soft}\n"
                       "    meaning: 兜底视图超评估线\n"
                       "    action: 看能否改两步法\n"
                       "  - id: fallback_read_hard_tok\n"
                       "    dimension: capacity_fallback_read_tok\n"
                       "    op: \">=\"\n"
                       f"    value: {hard}\n"
                       "    meaning: 兜底视图超硬线\n"
                       "    action: 优先按平台轴切分或改两步法\n",
                     encoding="utf-8")

    def test_fallback_view_is_gated(self):
        """兜底视图（category 未判出才读）接上同一条线——此前它被明确写在线外。

        真实库里的形态：vllm-ascend 兜底视图 24270 tok 超硬线 20000，而体检报"所有格子均未
        触发"：全系统最贵的一次读不在任何判据里。这条钉住三个接线点：判据被实现、越线报出来、
        机器读的那份带上兜底视图的读数。
        """
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", "A-1")
        self.generate_views()
        self.add_fallback_gates()
        _rc, doc = self.health()
        # 不判 rc：本 fixture 的 references/ 是空的，结构侧会如实退 2（与容量无关）；
        # 容量的判定看这条 fail——没有别的 broken 时它就是把退出码推到 1 的那条。
        hits = [f for f in doc["findings"] if f["face"] == "容量" and f["level"] == "fail"]
        self.assertTrue(any("兜底视图" in f["text"] for f in hits), doc["findings"])
        self.assertGreaterEqual(doc["fail_count"], 1)
        fb = next(c for c in doc["capacity_fallbacks"] if c["namespace"] == "inference/vllm-ascend")
        self.assertTrue(fb["hard"])
        dims = {a["dimension"]: a["implemented"] for a in doc["coverage"]["gates"]}
        self.assertTrue(dims["capacity_fallback_read_tok"])

    def test_missing_fallback_view_is_not_evaluated(self):
        """兜底视图量不出（缺 `<ns>.list`）→ 未评估（退 2），不是"没越界"。"""
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", "A-1")
        self.generate_views()
        self.add_fallback_gates(soft="0", hard="0")
        BI.shard_path(self.root, "inference__vllm-ascend").unlink()
        rc, doc = self.health()
        self.assertEqual(rc, 2, doc.get("check_verdict"))
        self.assertTrue(any("容量线未评估" in b and "兜底视图" in b for b in doc["broken"]), doc["broken"])

    # ---------------------------------------------------------------- 读数与现算一致
    def test_reported_cost_equals_the_live_recomputation(self):
        """体检报的每格成本 == `index_read_cost` 现算的那个数（同一个量，不许两套）。"""
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", "A-1")
        self.generate_views()
        _rc, doc = self.health()
        live = {(c["namespace"], c["category"]): c["tok"] for c in IRC.cell_costs(self.root)["cells"]}
        got = {(c["namespace"], c["category"]): c["tok"] for c in doc["capacity_cells"]}
        self.assertEqual(got, live)
        soft = next(g["value"] for g in doc["gates"] if g["id"] == "cell_read_soft_tok")
        hard = next(g["value"] for g in doc["gates"] if g["id"] == "cell_read_hard_tok")
        for c in doc["capacity_cells"]:
            self.assertEqual(c["soft"], c["tok"] > soft)
            self.assertEqual(c["hard"], c["tok"] >= hard)

    def test_counts_alone_never_flag_a_cell(self):
        """条数多但成本低 → 不越线（这正是换量的意义：条数是代理，不是判据）。"""
        for i in range(40):
            self.write_case(f"inference/vllm-ascend/interrupt/A{i}.yaml", f"A-{i}")
        self.generate_views()
        _rc, doc = self.health()
        cell = next(c for c in doc["capacity_cells"] if c["category"] == "interrupt")
        self.assertEqual(cell["count"], 40)
        self.assertLess(cell["tok"], 8000)          # 合成 case 很小
        self.assertFalse(cell["soft"])
        self.assertFalse(cell["hard"])


if __name__ == "__main__":
    unittest.main()
