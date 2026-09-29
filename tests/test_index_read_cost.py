"""阶段一实读成本（每格 token）的口径回归测试。

为什么钉住它（2026-09-29）：容量上限原先用"条数 × 70 token/条"估，实测是 252 token/条（现行
分片）/ 152 token/条（紧凑行）——估小了 3.4 倍，于是一个 93 条的格子看起来"贴着线"，实际
23.4K token，比整个诊断会话的常驻指令面还大。上限要按 token 定，所以这把尺子本身要有测试：
估算口径、紧凑行字段与截断、`--cell` 选择、以及越界时的退出码。
"""

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
    title: "{title}"
    category: {cat}
    tags: [hccl, comm-init]
    compat:
      - framework: vllm-ascend
        ranges: ["0.23.0"]
    confidence:
      score: 0.5
    symptoms:
      - "{sym}"
    quickly_check:
      primary:
        command_template: "grep -n '507014' log"
        expected: "regex:507014|error code 5"
"""


class ReadCostTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "knowledge").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, rel, cid="TEST-1", cat="interrupt", title="标题", sym="症状"):
        p = self.root / "knowledge" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CASE.format(cid=cid, cat=cat, title=title, sym=sym), encoding="utf-8")
        return p

    def generate(self):
        ns = BI.collect(self.root)
        (self.root / "knowledge" / "_index").mkdir(parents=True, exist_ok=True)
        for nsk, cells in ns.items():
            for cat, cases in cells.items():
                BI.shard_path(self.root, f"{nsk}__{cat}").write_text(
                    BI.render_shard(f"{nsk}__{cat}", {cat: cases}), encoding="utf-8")
        return ns

    # ------------------------------------------------------------------ 估算口径
    def test_token_estimate_counts_cjk_per_char(self):
        """中文按 1 token/字、ASCII 按 3.6 字符/token——不用字节折算（中文 3 字节/token 会偏）。"""
        self.assertEqual(IRC.tok("昇腾"), 2)
        self.assertEqual(IRC.tok("error"), 1)          # 5 / 3.6 → 1
        self.assertEqual(IRC.tok(""), 0)

    def test_estimate_is_positive_and_monotone(self):
        self.assertLess(IRC.tok("昇腾 vllm-ascend 507014"), IRC.tok("昇腾 vllm-ascend 507014 " * 3))

    # ------------------------------------------------------------------ 紧凑行形态
    def test_compact_line_carries_the_judgement_evidence(self):
        """一行要带：id / 标题 / 症状首条 / sig 字面量 / tok / compat / tags（少了任一项就是证据缺失）。"""
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        row = BI.collect(self.root)["inference/vllm-ascend"]["interrupt"][0]
        line = IRC.compact_line(row)
        for want in ("A-1", "标题", "症状", "507014", "vllm-ascend 0.23.0", "hccl"):
            self.assertIn(want, line)
        self.assertNotIn("\n", line)                   # 一行一条：折行就等于 grep 拿不到整条
        self.assertNotIn("hash", line)                 # hash 只服务新鲜度门，读侧不需要
        self.assertNotIn("knowledge/inference", line)  # file 可由 id 推出，也不进读侧

    def test_compact_line_truncates_like_the_shard_row(self):
        self.write_case("inference/vllm-ascend/interrupt/L.yaml", cid="L-1",
                        title="标" * 200, sym="症" * 200)
        row = BI.collect(self.root)["inference/vllm-ascend"]["interrupt"][0]
        line = IRC.compact_line(row)
        self.assertIn("标" * 160 + "…", line)
        self.assertIn("症" * 120 + "…", line)

    def test_compact_line_skips_empty_optional_fields(self):
        p = self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        p.write_text("cases:\n  - id: S-1\n    title: t\n    category: interrupt\n    symptoms:\n      - s\n",
                     encoding="utf-8")
        row = BI.collect(self.root)["inference/vllm-ascend"]["interrupt"][0]
        self.assertEqual(IRC.compact_line(row), "S-1 | t | s")

    # ------------------------------------------------------------------ 逐格成本
    def test_cell_costs_reports_both_formats_and_saving(self):
        for i in range(3):
            self.write_case("inference/vllm-ascend/interrupt/A.yaml" if i == 0
                            else f"inference/vllm-ascend/interrupt/A{i}.yaml", cid=f"A-{i}")
        self.generate()
        data = IRC.cell_costs(self.root)
        cell = next(c for c in data["cells"] if c["category"] == "interrupt")
        self.assertEqual(cell["rows"], 3)
        self.assertGreater(cell["yaml_tok"], cell["compact_tok"])   # 现行分片的结构开销是真实的
        self.assertLess(data["total"]["compact_tok"], data["total"]["yaml_tok"])
        self.assertGreater(data["total"]["saving_pct"], 0)

    def test_missing_shard_reports_zero_not_crash(self):
        """分片还没生成时（只跑过 collect）：yaml 成本记 0，不抛——尺子不能因为缺文件就崩。"""
        self.write_case("common/performance/C.yaml", cid="C-1", cat="performance")
        data = IRC.cell_costs(self.root)
        self.assertEqual(data["cells"][0]["yaml_tok"], 0)
        self.assertGreater(data["cells"][0]["compact_tok"], 0)

    # ------------------------------------------------------------------ 退出码契约
    def test_exit_code_flags_cell_over_cap(self):
        """越硬线 = 退出码 1（给体检脚本判），不越 = 0；这是脚本对外的契约。"""
        for i in range(40):
            self.write_case(f"inference/vllm-ascend/interrupt/A{i}.yaml", cid=f"A-{i}")
        self.generate()
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--cell",
                    "inference/vllm-ascend/interrupt", "--cap", "100"]
        self.assertEqual(IRC.main(), 1)
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--cell",
                    "inference/vllm-ascend/interrupt", "--cap", "100000"]
        self.assertEqual(IRC.main(), 0)

    def test_unknown_cell_is_usage_error(self):
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.generate()
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--cell", "no/such"]
        self.assertEqual(IRC.main(), 2)


if __name__ == "__main__":
    unittest.main()
