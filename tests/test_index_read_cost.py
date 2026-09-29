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
      - "第二条症状带 token：error code 507014，kernel_name=QuantBatchMatMulV3"
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
    def test_compact_line_field_set_is_exactly_the_read_protocol(self):
        """字段集合要**逐个钉住**，不能只查症状子串。

        为什么（独立预核 2026-09-29 的反例）：早先只断言"串里有 507014 / 症状"这类子串，
        于是把 `tok` 段整段删掉、测试仍 9 passed、卡里的 measure 仍通过——"静默砍掉判断证据"
        能一路绿灯。这里改成断言字段名集合：少一个字段就红。
        """
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        row = BI.collect(self.root)["inference/vllm-ascend"]["interrupt"][0]
        names = [part.split(": ", 1)[0] for part in IRC.compact_line(row).split(IRC.SEP)]
        self.assertEqual(names, list(IRC.READ_FIELDS))
        for want in ("A-1", "interrupt", "标题", "症状", "507014", "vllm-ascend 0.23.0", "hccl", "0.5"):
            self.assertIn(want, IRC.compact_line(row))
        self.assertNotIn("\n", IRC.compact_line(row))           # 一行一条：折行等于 grep 拿不到整条
        self.assertNotIn("hash:", IRC.compact_line(row))        # hash 只服务新鲜度门，读侧不需要
        self.assertNotIn("knowledge/inference", IRC.compact_line(row))   # file 可由 id 推出，不进读侧

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
        # 没有 sig/tok/compat/tags/score → 那几段整段省略（省行宽），其余按序保留
        self.assertEqual(IRC.compact_line(row), "id: S-1 | category: interrupt | title: t | symptoms: s")

    def test_compact_line_pipe_in_value_cannot_split_the_fields(self):
        """值里的 `|` 折成 `¦`：否则一条会被切成两截，解析与"grep 命中即整条"都失效。"""
        self.write_case("inference/vllm-ascend/interrupt/P.yaml", cid="P-1", title="a | b")
        row = BI.collect(self.root)["inference/vllm-ascend"]["interrupt"][0]
        names = [part.split(": ", 1)[0] for part in IRC.compact_line(row).split(IRC.SEP)]
        self.assertEqual(names, list(IRC.READ_FIELDS))
        self.assertIn("a ¦ b", IRC.compact_line(row))

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

    def test_missing_view_is_reported_not_counted_as_free(self):
        """缺读侧视图时：`cell_costs` 记 0（不崩），但 `missing_views` 要点名、`main` 返回 2。

        为什么（独立预核 2026-09-29）：静默 0 会被读成"这一格免费"——"残缺"与"量不出"必须不同形。
        """
        self.write_case("common/performance/C.yaml", cid="C-1", cat="performance")
        data = IRC.cell_costs(self.root)
        self.assertEqual(data["cells"][0]["yaml_tok"], 0)
        self.assertGreater(data["cells"][0]["compact_tok"], 0)
        self.assertIn("common__performance.yaml", data["missing_views"])
        sys.argv = ["index_read_cost.py", "--root", str(self.root)]
        self.assertEqual(IRC.main(), 2)

    def test_bad_root_is_usage_error_not_empty_library(self):
        """`--root` 传错（下面没有 knowledge/）→ 2，不能静默报"0 条、exit 0"。"""
        sys.argv = ["index_read_cost.py", "--root", str(self.root)]   # setUp 只建了 knowledge/，没有 case
        self.assertEqual(IRC.main(), 0)                               # 空库是真 0：knowledge/ 在
        sys.argv = ["index_read_cost.py", "--root", str(self.root / "nope")]
        self.assertEqual(IRC.main(), 2)

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

    def test_json_obeys_the_same_exit_code(self):
        """`--json` 也要按 cap 判（独立预核 2026-09-29 的反例：早先 `--json` 恒 0，
        于是机器读的那条路永远看不出越线，而卡里的 measure 恰好走的就是 `--json`）。"""
        for i in range(40):
            self.write_case(f"inference/vllm-ascend/interrupt/A{i}.yaml", cid=f"A-{i}")
        self.generate()
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--json",
                    "--cell", "inference/vllm-ascend/interrupt", "--cap", "100"]
        self.assertEqual(IRC.main(), 1)
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--json",
                    "--cell", "inference/vllm-ascend/interrupt", "--cap", "100000"]
        self.assertEqual(IRC.main(), 0)

    def test_unknown_cell_is_usage_error(self):
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.generate()
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--cell", "no/such"]
        self.assertEqual(IRC.main(), 2)


if __name__ == "__main__":
    unittest.main()
