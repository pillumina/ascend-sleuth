"""阶段一实读成本（每格 token）的口径回归测试。

为什么钉住它（2026-09-29）：容量上限原先用"条数 × 70 token/条"估，实测是 252 token/条（旧 YAML 分片）
与 173 token/条（现行读侧视图）——估小了 3.4 倍。上限要按 token 定，所以这把尺子本身要有测试：
估算口径、量的是**实际落盘的那份视图**、两类视图分开报、以及退出码契约。

上一条独立预核的反例（已回修，见"缺数据不能读成免费"与"退出码"两节）：`--json` 恒 0、缺视图静默报 0——
机器读的那条路看不出越线，"量不出"被读成"免费"。
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
        """按生成器的口径把读侧视图写出来（本文件量的是"落盘那份"）。"""
        ns = BI.collect(self.root)
        (self.root / "knowledge" / "_index").mkdir(parents=True, exist_ok=True)
        for nsk, cells in ns.items():
            BI.shard_path(self.root, nsk).write_text(BI.render_shard(nsk, cells), encoding="utf-8")
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

    # ------------------------------------------------------------------ 量的是落盘的那份视图
    def test_cost_comes_from_the_shipped_view_not_a_recomputation(self):
        """成本取自分片文件本身（含头注）：手写一份更长的视图 → 成本随之变大。

        为什么钉这条：成本若改成"按字段现算"，尺子就会与阶段一真正读到的字节脱钩——
        头注、字段名、分隔符这些"真会占字"的东西会从账上消失。
        """
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.generate()
        base = IRC.cell_costs(self.root)["cells"][0]["tok"]
        self.assertGreater(base, 0)
        p = BI.shard_path(self.root, "inference/vllm-ascend__interrupt")
        p.write_text(p.read_text(encoding="utf-8") + "# 多出来的一行注释\n" * 20, encoding="utf-8")
        self.assertGreater(IRC.cell_costs(self.root)["cells"][0]["tok"], base)

    def test_read_view_is_cheaper_than_the_old_yaml_shape(self):
        """同信息的读侧视图必须比旧 YAML 分片省——这是换形态的全部理由。

        比较**正文**（去掉两边头注）：头注是固定成本，条目少时它会让总量比不出来（3 条时反而更贵）。
        真实规模（百余条）下头注被摊掉，两种比法都成立。
        """
        import yaml as _yaml
        for i in range(20):
            self.write_case(f"inference/vllm-ascend/interrupt/A{i}.yaml", cid=f"A-{i}",
                            title="标题" * 20, sym="症状" * 30)
        ns = BI.collect(self.root)
        rows = ns["inference/vllm-ascend"]["interrupt"]
        body = lambda text: "\n".join(l for l in text.splitlines() if not l.startswith("#"))
        compact = IRC.tok(body(BI.render_shard("inference/vllm-ascend__interrupt", {"interrupt": rows})))
        legacy = IRC.tok(body(_yaml.safe_dump(
            {"namespaces": {"inference/vllm-ascend__interrupt": {"interrupt": rows}}},
            allow_unicode=True, sort_keys=False)))
        self.assertLess(compact, legacy)
        self.assertGreater(100 - 100 * compact / legacy, 15)      # 实测约 25–35%

    def test_fallback_view_is_reported_separately(self):
        """ns 兜底视图（category 未定才读）单独一节报，不混进类视图的分母。

        为什么：兜底视图更贵（真实库里 vllm-ascend 单文件 3 万余 token），混在一起会让"哪条读取
        路径越线"看不出来。
        """
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.write_case("inference/vllm-ascend/precision/B.yaml", cid="B-1", cat="precision")
        self.generate()
        data = IRC.cell_costs(self.root)
        self.assertEqual(len(data["cells"]), 2)
        self.assertEqual(len(data["fallbacks"]), 1)
        fb = data["fallbacks"][0]
        self.assertEqual((fb["namespace"], fb["rows"]), ("inference/vllm-ascend", 2))
        self.assertGreater(fb["tok"], max(c["tok"] for c in data["cells"]))   # 兜底更贵

    def test_total_counts_only_cell_views(self):
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.write_case("common/performance/C.yaml", cid="C-1", cat="performance")
        self.generate()
        data = IRC.cell_costs(self.root)
        self.assertEqual(data["total"]["rows"], 2)
        self.assertEqual(data["total"]["tok"], sum(c["tok"] for c in data["cells"]))

    # ------------------------------------------------------------------ 缺数据不能读成免费
    def test_missing_view_is_reported_not_counted_as_free(self):
        self.write_case("common/performance/C.yaml", cid="C-1", cat="performance")
        data = IRC.cell_costs(self.root)          # 没跑 generate：视图不存在
        self.assertIn("common__performance.list", data["missing_views"])
        sys.argv = ["index_read_cost.py", "--root", str(self.root)]
        self.assertEqual(IRC.main(), 2)

    def test_bad_root_is_usage_error_not_empty_library(self):
        self.generate()
        sys.argv = ["index_read_cost.py", "--root", str(self.root)]
        self.assertEqual(IRC.main(), 0)                              # 空库是真 0：knowledge/ 在
        sys.argv = ["index_read_cost.py", "--root", str(self.root / "nope")]
        self.assertEqual(IRC.main(), 2)

    def test_unknown_cell_is_usage_error(self):
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.generate()
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--cell", "no/such"]
        self.assertEqual(IRC.main(), 2)

    # ------------------------------------------------------------------ 退出码契约
    def test_exit_code_flags_cell_over_cap(self):
        """越硬线 = 1（给体检脚本判），不越 = 0；这是脚本对外的契约。"""
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
        于是机器读的那条路永远看不出越线）。"""
        for i in range(40):
            self.write_case(f"inference/vllm-ascend/interrupt/A{i}.yaml", cid=f"A-{i}")
        self.generate()
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--json",
                    "--cell", "inference/vllm-ascend/interrupt", "--cap", "100"]
        self.assertEqual(IRC.main(), 1)
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--json",
                    "--cell", "inference/vllm-ascend/interrupt", "--cap", "100000"]
        self.assertEqual(IRC.main(), 0)


if __name__ == "__main__":
    unittest.main()
