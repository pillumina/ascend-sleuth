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

    # ------------------------------------------------------------------ 一张账：四个分项
    def test_views_carry_kind_and_cover_both_paths(self):
        """类视图与兜底视图两条读取路径都要进账，且带 `kind` 分得开。

        为什么：两条路径的判据是两条 dimension（"哪条路径越线"要看得出来），
        但共用同一把尺子（token）——`views` 是它们的并集。
        """
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.write_case("common/performance/C.yaml", cid="C-1", cat="performance")
        self.generate()
        data = IRC.cell_costs(self.root)
        self.assertEqual(sorted(v["kind"] for v in data["views"]), ["cell", "cell", "fallback", "fallback"])
        self.assertEqual(len(data["views"]), len(data["cells"]) + len(data["fallbacks"]))

    def test_fallback_over_cap_flags_exit_1(self):
        """兜底视图（category 未定才读）**同一条硬线**——此前它被明确写在线外。

        真实库里的反例：vllm-ascend 兜底视图 24270 tok 超硬线 20000，而 `--json` 退 0、
        体检报"所有格子均未触发"：全系统最贵的一次读不在任何判据里。本测试钉住越线即 1。
        """
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.generate()
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--cap", "1"]
        self.assertEqual(IRC.main(), 1)
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--cap", "1000000"]
        self.assertEqual(IRC.main(), 0)

    def test_reference_layer_measured_but_never_gated(self):
        """先验层进同一张账（整读成本 + 检索残量），但**不设线**：再贵也不影响退出码。

        判据：先验层是检索式读取（一次 grep + ≤5 行），token 不随库大小线性涨，
        它的退化形态是"翻不到"（残量）。给它配 token 硬线属假硬化——准入判据第三条
        （已复发 ≥2 次）没有证据，所以先有数（原则八），攒到期数够了再定线。
        """
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.generate()
        ref = self.root / "references"
        (ref / "_procedure-index").mkdir(parents=True)
        (ref / "errors").mkdir()
        (ref / "_summary-index.yaml").write_text(
            "entries:\n"
            "- {id: p1, type: platform-fact, title: t1, summary: s, applies_to: {platforms: [cross], categories: []}}\n"
            "- {id: p2, type: software-fact, title: t2, summary: s, applies_to: {platforms: [A3-910C], categories: [interrupt]}}\n",
            encoding="utf-8")
        (ref / "_procedure-index.yaml").write_text("procedures_total: 1\n", encoding="utf-8")
        (ref / "_procedure-index" / "interrupt.yaml").write_text("- {id: m1}\n", encoding="utf-8")
        (ref / "errors" / "cann-runtime.yaml").write_text("- {id: e1}\n", encoding="utf-8")

        views = [r["view"] for r in IRC.reference_costs(self.root)]
        self.assertTrue(any("背景索引" in v for v in views), views)
        self.assertTrue(any("流程分片" in v for v in views), views)
        self.assertTrue(any("错误族表" in v for v in views), views)

        residual = IRC.bg_residual(self.root)
        self.assertEqual(residual["entries"], 2)
        per = {(x["platform"], x["category"]): x["rows"] for x in residual["by_platform_category"]}
        self.assertEqual(per[("A3-910C", "interrupt")], 2)      # 跨平台行 + 本卡行
        self.assertEqual(per[("A3-910C", "performance")], 1)    # 只剩跨平台行
        self.assertEqual(residual["cross_only_by_category"]["interrupt"], 1)

        # 只量不判：先验层再贵也不进退出码（cap 放到无穷大 → 0）
        sys.argv = ["index_read_cost.py", "--root", str(self.root), "--cap", "1000000"]
        self.assertEqual(IRC.main(), 0)
        # references/ 不在（worktree 里被删/未挂）→ 空表，不是崩溃
        empty = tempfile.TemporaryDirectory()
        with empty:
            root = Path(empty.name)
            (root / "knowledge").mkdir()
            self.assertEqual(IRC.reference_costs(root), [])
            self.assertIsNone(IRC.bg_residual(root))
            self.assertIsNone(IRC.stage2_costs(root))

    def test_stage2_body_cost_is_measured(self):
        """阶段二候选全文（≤5 条）此前一笔账都没有——它和最贵的格子同量级。"""
        for i in range(3):
            self.write_case(f"inference/vllm-ascend/interrupt/A{i}.yaml", cid=f"A-{i}", sym="症状" * 40)
        self.generate()
        st = IRC.stage2_costs(self.root)
        self.assertEqual(st["cases"], 3)
        self.assertGreater(st["median"], 0)
        self.assertLessEqual(st["top5"], 5 * st["max"])
        self.assertGreaterEqual(st["top5"], 3 * st["median"] - st["max"] if st["max"] > st["median"] else st["median"])

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
