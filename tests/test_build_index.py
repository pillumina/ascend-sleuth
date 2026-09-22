"""build_index 的口径回归测试。

索引是 Tier 2 阶段一唯一的检索面：格子分组错 → 候选集错；category 来源错 → 分片选错；
行宽压缩口径错 → 阶段一过滤拿不到判别信号；hash 口径错 → `--check` 永久红或永久绿。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_index as bi  # noqa: E402

CASE_TMPL = """cases:
  - id: {cid}
    title: "{title}"
    category: {cat}
    tags: [{tags}]
    compat:
      - framework: vllm-ascend
        ranges: ["0.23.0"]
    confidence:
      score: 0.6
    symptoms:
      - "{sym}"
"""


class BuildIndexTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "knowledge").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, rel, cid="TEST-1", cat="interrupt", title="t", tags="a, b", sym="s"):
        p = self.root / "knowledge" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CASE_TMPL.format(cid=cid, cat=cat, title=title, tags=tags, sym=sym),
                     encoding="utf-8")
        return p

    # ---------------------------------------------------------------- hash 口径
    def test_case_hash_normalizes_crlf(self):
        """LF 与 CRLF 同一份内容 → 同一 hash（否则 Windows 提交索引后 Linux CI 永久红）。"""
        a = self.root / "a.yaml"
        b = self.root / "b.yaml"
        a.write_bytes("x: 1\ny: 2\n".encode())
        b.write_bytes("x: 1\r\ny: 2\r\n".encode())
        self.assertEqual(bi.case_hash(a), bi.case_hash(b))

    def test_case_hash_changes_with_content(self):
        a = self.root / "a.yaml"
        b = self.root / "b.yaml"
        a.write_text("x: 1\n", encoding="utf-8")
        b.write_text("x: 2\n", encoding="utf-8")
        self.assertNotEqual(bi.case_hash(a), bi.case_hash(b))

    # ---------------------------------------------------------------- 收集口径
    def test_collect_skips_generated_and_archived(self):
        self.write_case("inference/vllm-ascend/interrupt/TEST-1.yaml", cid="TEST-1")
        self.write_case("_archive/inference/vllm-ascend/interrupt/OLD.yaml", cid="OLD-1")
        (self.root / "knowledge" / "_index").mkdir(parents=True)
        (self.root / "knowledge" / "_index" / "inference__vllm-ascend.yaml").write_text(
            "namespaces: {}\n", encoding="utf-8")
        (self.root / "knowledge" / "_index.yaml").write_text("namespaces: {}\n", encoding="utf-8")

        ns = bi.collect(self.root)
        ids = [c["id"] for cells in ns.values() for cs in cells.values() for c in cs]
        self.assertEqual(ids, ["TEST-1"])

    def test_category_comes_from_case_field_not_directory(self):
        """目录停在工作负载层，category 是正交轴、从 case 字段取（ADR-0004）。"""
        self.write_case("inference/vllm-ascend/interrupt/TEST-1.yaml", cid="TEST-1", cat="precision")
        ns = bi.collect(self.root)
        self.assertIn("precision", ns["inference/vllm-ascend"])
        self.assertNotIn("interrupt", ns["inference/vllm-ascend"])

    def test_framework_dir_folds_into_namespace(self):
        """inference/training 折叠到两级（三级会让面板渲染出重复 category）；common 停在 common。"""
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.write_case("training/verl/interrupt/B.yaml", cid="B-1")
        self.write_case("common/performance/C.yaml", cid="C-1", cat="performance")
        ns = bi.collect(self.root)
        self.assertEqual(sorted(ns), ["common", "inference/vllm-ascend", "training/verl"])

    def test_illegal_category_raises(self):
        """三分类强制：other/空值直接抛，不能变成不可达格子。"""
        self.write_case("inference/vllm-ascend/interrupt/X.yaml", cid="X-1", cat="other")
        with self.assertRaises(ValueError):
            bi.collect(self.root)

    # ---------------------------------------------------------------- 行宽口径
    def test_row_is_compressed_for_phase_one(self):
        """F2/F5：symptoms 只留首条 120 字、title 截 160、tags 截 6——阶段一拿这一行做过滤。"""
        long_title = "标" * 200
        long_sym = "症" * 200
        self.write_case("inference/vllm-ascend/interrupt/T.yaml", cid="T-1",
                        title=long_title, tags=",".join(f"t{i}" for i in range(9)), sym=long_sym)
        ns = bi.collect(self.root)
        row = ns["inference/vllm-ascend"]["interrupt"][0]
        self.assertEqual(len(row["title"]), 161)          # 160 + 省略号
        self.assertTrue(row["title"].endswith("…"))
        self.assertEqual(len(row["tags"]), 6)
        self.assertEqual(len(row["symptoms"]), 1)
        self.assertEqual(len(row["symptoms"][0]), 121)    # 120 + 省略号
        self.assertEqual(row["file"], "knowledge/inference/vllm-ascend/interrupt/T.yaml")

    # ---------------------------------------------------------------- 一致性门口径
    # 门是**覆盖检查**（每条 case 的索引行都在、与内容对得上），不是逐字节相同：
    # 生成物配了 merge=union，合并出来的文件内容对、顺序可能与重新生成不同。
    # 所以下面既测"五种漂移都红"，也测"union 合并的结果不许红"。
    def generate_all(self, ns=None):
        """分片 + 总表都写出来（模拟一次完整的"跑了一遍生成器"）。"""
        ns = bi.collect(self.root) if ns is None else ns
        (self.root / "knowledge" / "_index").mkdir(parents=True, exist_ok=True)
        for nsk, cells in ns.items():
            bi.shard_path(self.root, nsk).write_text(bi.render_shard(nsk, cells), encoding="utf-8")
            for cat, cases in cells.items():
                bi.shard_path(self.root, f"{nsk}__{cat}").write_text(
                    bi.render_shard(f"{nsk}__{cat}", {cat: cases}), encoding="utf-8")
        (self.root / "knowledge" / "_index.yaml").write_text(bi.render(ns), encoding="utf-8")
        return ns

    def problems(self):
        return bi.coverage_problems(self.root, bi.collect(self.root))

    def test_coverage_green_after_generate(self):
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        self.assertEqual(self.problems(), [])
        self.assertEqual(bi.canonical_dirty(self.root, bi.collect(self.root)), [])

    def test_coverage_flags_changed_case(self):
        p = self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        self.assertEqual(self.problems(), [])
        p.write_text(p.read_text(encoding="utf-8").replace("score: 0.6", "score: 0.9"),
                     encoding="utf-8")
        probs = self.problems()
        # 分片与总表各报一次（两处都存着这条 case 的旧行）——这正是"两层都得跟上"的意思
        self.assertEqual(len(probs), 2, probs)
        self.assertTrue(all("S-1" in p for p in probs), probs)
        self.assertTrue(any("过期" in p for p in probs), probs)

    def test_coverage_flags_added_case(self):
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.generate_all()
        self.write_case("inference/vllm-ascend/interrupt/B.yaml", cid="B-1")
        probs = self.problems()
        self.assertTrue(any("B-1" in p and "缺条目" in p for p in probs), probs)

    def test_coverage_flags_deleted_case(self):
        p = self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        p.unlink()
        probs = self.problems()
        self.assertTrue(any("S-1" in p and "库里没有" in p for p in probs), probs)

    def test_coverage_flags_hand_edited_row(self):
        """手改索引行（case 内容没动）→ 红。hash 查不出这种改动，行级比对能——这是覆盖检查比
        "只比 hash"强的地方。"""
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        p = bi.shard_path(self.root, "inference/vllm-ascend__interrupt")
        p.write_text(p.read_text(encoding="utf-8").replace("title: t", "title: 手改过的标题"),
                     encoding="utf-8")
        probs = self.problems()
        self.assertTrue(any("不一致" in x for x in probs), probs)

    def test_union_merged_index_is_green(self):
        """**关键一条**：两人同一天各加一条 case，union 合并出来的分片/总表（两条目都在、
        顺序可能与重新生成不同）必须是**绿的**——否则 union 换来的"不用任何人跑命令"就白拿了。
        内容出错（丢条目）仍然红，见上面几条。"""
        self.write_case("inference/vllm-ascend/interrupt/A.yaml", cid="A-1")
        self.write_case("inference/vllm-ascend/interrupt/B.yaml", cid="B-1")
        ns = bi.collect(self.root)
        self.generate_all(ns)
        # 模拟 union：把 B 的条目从分片里挪到 A 前面（顺序非规范，内容齐全）
        p = bi.shard_path(self.root, "inference/vllm-ascend__interrupt")
        text = p.read_text(encoding="utf-8")
        rows = text.split("\n    - id: ")
        self.assertEqual(len(rows), 3, rows)
        p.write_text(rows[0] + "\n    - id: " + rows[2] + "\n    - id: " + rows[1],
                     encoding="utf-8")
        self.assertEqual(self.problems(), [])                      # 门：绿（内容齐全）
        self.assertTrue(bi.canonical_dirty(self.root, ns))         # 逐字节自检：非规范（可选归一）

    def test_coverage_flags_duplicate_rows(self):
        """同一条 case 在索引里出现两次（行级合并/重复 rebase 的产物，内容完全相同 → git 不报冲突，
        hash 与行比对也一致）→ 必须报出来。只按 id 建字典的话第二份被静静吃掉（评审抓到的洞）。"""
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        p = bi.shard_path(self.root, "inference/vllm-ascend__interrupt")
        text = p.read_text(encoding="utf-8")
        i = text.index("    - id: ")
        p.write_text(text + text[i:], encoding="utf-8")      # 同一条目块再来一份（内容完全相同）
        probs = self.problems()
        self.assertTrue(any("出现 2 次" in x for x in probs), probs)

    def test_coverage_red_when_shard_missing(self):
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        bi.shard_path(self.root, "inference/vllm-ascend__interrupt").unlink()
        probs = self.problems()
        # 少了类分片：条目还在 ns 分片里（覆盖不破），但阶段一命中该类分片的路径读不到了 → 必须报
        self.assertTrue(any("分片缺失" in p and "inference__vllm-ascend__interrupt" in p for p in probs), probs)

    def test_shard_with_conflict_markers_is_reported_not_merged(self):
        """分片里出现冲突标记（不该有——本目录配了 union）→ 点名，动作是重跑生成器。"""
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        self.generate_all()
        p = bi.shard_path(self.root, "inference/vllm-ascend__interrupt")
        p.write_text("<<<<<<< HEAD\nnamespaces: {}\n=======\nnamespaces: {}\n>>>>>>> other\n",
                     encoding="utf-8")
        _rows, broken = bi.shard_hashes(self.root)
        self.assertTrue(broken and "冲突标记" in broken[0], broken)
        self.assertTrue(any("冲突标记" in x for x in self.problems()), self.problems())

    def test_header_has_no_numbers(self):
        """生成物头注里不留数字（条数/容量/日期）：数字一进 git，两人并发合并时要么撞同一行、
        要么漂移成错的数。数字改成现算（scripts/index_counts.py）。"""
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        text = bi.render(bi.collect(self.root))
        self.assertEqual(text, bi.render(bi.collect(self.root)))
        head = text.split("namespaces:")[0]
        self.assertNotIn("生成日期：", head)
        self.assertNotIn("case 总数：", head)
        self.assertNotIn("容量(", head)
        self.assertNotRegex(head, r"20\d\d-\d\d-\d\d")
        shard_head = bi.render_shard("inference/vllm-ascend__interrupt",
                                     {"interrupt": bi.collect(self.root)["inference/vllm-ascend"]["interrupt"]}
                                     ).split("namespaces:")[0]
        self.assertNotRegex(shard_head, r"（\d+ 条 case）")

    def test_sig_and_tok_fields_for_phase_one_ranking(self):
        """行内签名面字段（EV-2026-111）：sig 只收纯字面量、tok 覆盖全部症状且上限 12。"""
        p = self.root / "knowledge" / "inference" / "vllm-ascend" / "interrupt" / "S.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        # 用单引号 YAML 标量：双引号会处理反斜杠转义，把正则分支写坏
        p.write_text(
            "cases:\n"
            "  - id: S-1\n"
            "    title: 't'\n"
            "    category: interrupt\n"
            "    tags: [a]\n"
            "    confidence: {score: 0.5}\n"
            "    symptoms:\n"
            "      - '首条症状，无字面量'\n"
            "      - '第二条症状：error code 507014，kernel_name=MoeDistributeDispatchV2'\n"
            "    quickly_check:\n"
            "      primary:\n"
            "        expected: 'regex:507014|\\d+\\(\\)|aicore exception'\n",
            encoding="utf-8")
        row = bi.collect(self.root)["inference/vllm-ascend"]["interrupt"][0]
        self.assertIn("507014", row["sig"])
        self.assertIn("aicore exception", row["sig"])
        self.assertNotIn("\\d+", " ".join(row["sig"]))       # 正则元字符分支不入 sig
        self.assertIn("507014", row["tok"])                  # 判别信号在第二条症状 → tok 收得到
        self.assertLessEqual(len(row["tok"]), 12)

    def test_render_shard_carries_file_and_hash(self):
        """阶段二要靠 file 定位、靠 hash 判过期——分片里必须有这两列。"""
        self.write_case("inference/vllm-ascend/interrupt/R.yaml", cid="R-1")
        ns = bi.collect(self.root)
        text = bi.render_shard("inference/vllm-ascend", ns["inference/vllm-ascend"])
        self.assertIn("knowledge/inference/vllm-ascend/interrupt/R.yaml", text)
        self.assertIn("hash:", text)
        self.assertIn("R-1", text)


if __name__ == "__main__":
    unittest.main()
