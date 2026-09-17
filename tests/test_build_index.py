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

    # ---------------------------------------------------------------- 新鲜度口径
    def test_stale_entries_flags_changed_case(self):
        p = self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        ns = bi.collect(self.root)
        doc = {"namespaces": ns}
        (self.root / "knowledge" / "_index.yaml").write_text(
            __import__("yaml").safe_dump(doc, allow_unicode=True), encoding="utf-8")
        self.assertEqual(bi.stale_entries(self.root, ns), [])

        p.write_text(p.read_text(encoding="utf-8").replace("score: 0.6", "score: 0.9"),
                     encoding="utf-8")
        stale = bi.stale_entries(self.root, bi.collect(self.root))
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0][1], "S-1")

    def test_stale_entries_reports_index_only_case(self):
        """索引里有、库里没有（case 被删）→ 也要报，否则 --check 静默留旧条目。"""
        import copy
        import yaml
        self.write_case("inference/vllm-ascend/interrupt/S.yaml", cid="S-1")
        ns = bi.collect(self.root)
        doc = {"namespaces": copy.deepcopy(ns)}   # 深拷贝：只让索引多出这条，库侧仍没有
        doc["namespaces"]["inference/vllm-ascend"]["interrupt"].append(
            {"id": "GONE-1", "hash": "deadbeef", "file": "knowledge/x.yaml"})
        (self.root / "knowledge" / "_index.yaml").write_text(
            yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        stale = bi.stale_entries(self.root, ns)
        self.assertTrue(any(s[1] == "GONE-1" for s in stale))

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
