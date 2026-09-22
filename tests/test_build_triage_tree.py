"""Tier 1 路由层「源 → 生成物」的口径回归测试。

这一层存在的理由是可验证的：路由数据原先放在一个 141 行的文件里，谁加词都得改它，
两个人撞在同一段文本上就要人判断"留哪一份"。拆成一族一文件 + 生成物之后，
**读侧完全不变**（diagnose / verify_references / kb-explorer 读的还是 triage-tree.yaml），
所以本测试要钉住的正是"生成物与源一致、且拼接不丢内容、不改顺序"这三件事。
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_triage_tree as btt  # noqa: E402

BRANCH = """  - id: {bid}
    category: {cat}
    symptoms:
      - ["{sym}"]
    search_namespaces:
      - {ns}
    fallback: Tier 3
"""


def run_main(*argv):
    """跑生成器的 main()，返回 (exit_code, stdout)。"""
    buf = io.StringIO()
    old = sys.argv
    sys.argv = ["build_triage_tree.py", *argv]
    try:
        with contextlib.redirect_stdout(buf):
            rc = btt.main()
    finally:
        sys.argv = old
    return rc, buf.getvalue()


class TriageTreeSplitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "triage-tree.d").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_family(self, name, bid, cat="interrupt", sym="boom", ns="common/", syms=None):
        groups = syms if syms is not None else [sym]
        body = (
            f"  - id: {bid}\n"
            f"    category: {cat}\n"
            "    symptoms:\n"
            + "".join(f'      - ["{s}"]\n' for s in groups)
            + "    search_namespaces:\n"
            f"      - {ns}\n"
            "    fallback: Tier 3\n"
        )
        (self.root / "triage-tree.d" / name).write_text(
            f"# 一族：{bid}\n\nbranches:\n" + body, encoding="utf-8")

    def write_protocol(self, text="路由说明第一行\n\n第二行\n"):
        (self.root / "triage-tree.d" / btt.PROTOCOL_NAME).write_text(text, encoding="utf-8")

    def build(self):
        return run_main("--root", str(self.root))

    # ---------------------------------------------------------------- 源 → 生成物
    def test_generate_then_check_is_green(self):
        self.write_protocol()
        self.write_family("10-a.yaml", "a_branch")
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        rc, out = run_main("--check", "--root", str(self.root))
        self.assertEqual(rc, 0, out)
        self.assertIn("逐字节相同", out)

    def test_check_red_and_says_rerun_when_source_changed(self):
        """改了源没重建 → 红，且给的动作是"重跑一次"，不是让人去比对生成物。"""
        self.write_protocol()
        self.write_family("10-a.yaml", "a_branch")
        self.build()
        self.write_family("10-a.yaml", "a_branch", sym="boom2")
        rc, out = run_main("--check", "--root", str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("build_triage_tree.py", out)

    # ---------------------------------------------------------------- 覆盖检查（门）
    def test_coverage_green_and_red_on_missing_word(self):
        """门是覆盖检查：源里每条症状组都在聚合里。缺一条 → 红（改名/改词/手改聚合都落这条）。"""
        self.write_protocol()
        self.write_family("10-a.yaml", "a_branch", syms=["boom", "bang"])
        self.build()
        rc, out = run_main("--check-coverage", "--root", str(self.root))
        self.assertEqual(rc, 0, out)
        agg = self.root / "triage-tree.yaml"
        agg.write_text(agg.read_text(encoding="utf-8").replace('      - ["bang"]\n', ""),
                       encoding="utf-8")
        rc, out = run_main("--check-coverage", "--root", str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("缺症状组", out)

    def test_union_merged_aggregate_is_green(self):
        """**关键一条**：两人同一天给同一族加词，union 合并出来的聚合（两句都在、顺序可能不是
        重新拼接的顺序）必须是**绿的**——否则 union 换来的"谁都不用跑命令"就白拿了。
        逐字节自检（--check）此时会红，那是可选的归一化提示，不作门。"""
        self.write_protocol()
        self.write_family("10-a.yaml", "a_branch", syms=["boom", "mine", "theirs"])
        self.build()
        agg = self.root / "triage-tree.yaml"
        lines = agg.read_text(encoding="utf-8").split("\n")
        i_mine = next(i for i, l in enumerate(lines) if '"mine"' in l)
        i_theirs = next(i for i, l in enumerate(lines) if '"theirs"' in l)
        lines[i_mine], lines[i_theirs] = lines[i_theirs], lines[i_mine]   # 顺序被 union 换过
        agg.write_text("\n".join(lines), encoding="utf-8")
        rc, out = run_main("--check-coverage", "--root", str(self.root))
        self.assertEqual(rc, 0, out)
        rc, _out = run_main("--check", "--root", str(self.root))
        self.assertEqual(rc, 1, "逐字节自检应当报非规范（这是可选的归一化提示）")

    def test_coverage_reports_branch_missing_from_aggregate(self):
        self.write_protocol()
        self.write_family("10-a.yaml", "a_branch")
        self.write_family("20-b.yaml", "b_branch")
        self.build()
        agg = self.root / "triage-tree.yaml"
        text = agg.read_text(encoding="utf-8")
        agg.write_text(text[:text.index("  - id: b_branch")], encoding="utf-8")
        rc, out = run_main("--check-coverage", "--root", str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("缺分支", out)

    def test_branch_order_follows_filename(self):
        """diagnose 按顺序匹配分支 → 顺序是语义的一部分，必须由文件名（序号前缀）决定。"""
        self.write_protocol()
        self.write_family("20-second.yaml", "second")
        self.write_family("10-first.yaml", "first")
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        doc = yaml.safe_load((self.root / "triage-tree.yaml").read_text(encoding="utf-8"))
        self.assertEqual([b["id"] for b in doc["branches"]], ["first", "second"])

    def test_protocol_becomes_comment_header(self):
        """说明与入场判据（prose）进生成物的注释头，不在正文里——正文只有 branches。"""
        self.write_protocol("第一行\n\n第三行\n")
        self.write_family("10-a.yaml", "a_branch")
        self.build()
        text = (self.root / "triage-tree.yaml").read_text(encoding="utf-8")
        head = text[:text.index("branches:")]
        self.assertIn("# 第一行", head)
        self.assertIn("#\n", head)          # 空行 → 裸 '#'
        self.assertNotIn("第一行", text[text.index("branches:"):])

    def test_body_is_verbatim_splice_of_sources(self):
        """拼接逐字保留（含行内注释与对齐）：迁移那一次 body 字节不变，路由行为不变的证据是 diff。"""
        self.write_protocol()
        (self.root / "triage-tree.d" / "10-a.yaml").write_text(
            "# 注释不进正文\n\nbranches:\n"
            '  - id: a_branch\n'
            "    category: interrupt\n"
            "    symptoms:\n"
            '      - ["boom"]    # 这条的来历（VERL-1）\n'
            "    search_namespaces: [common/]   # 按顺序搜\n"
            "    fallback: Tier 3\n",
            encoding="utf-8")
        self.build()
        text = (self.root / "triage-tree.yaml").read_text(encoding="utf-8")
        body = text[text.index("branches:"):]
        self.assertIn('# 这条的来历（VERL-1）', body)
        self.assertIn("search_namespaces: [common/]   # 按顺序搜", body)
        self.assertNotIn("注释不进正文", body)

    # ---------------------------------------------------------------- 源文件校验
    def test_two_branches_in_one_file_is_rejected(self):
        """一族一文件是 union 合并能自动留住两边改动的前提，破了它就回到判断题。"""
        self.write_protocol()
        self.write_family("10-a.yaml", "a_branch")
        self.write_family("20-b.yaml", "b_branch")
        p = self.root / "triage-tree.d" / "30-both.yaml"
        p.write_text("branches:\n" + BRANCH.format(bid="c1", cat="interrupt", sym="x", ns="common/")
                     + BRANCH.format(bid="c2", cat="interrupt", sym="y", ns="common/"),
                     encoding="utf-8")
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("一族一文件", out)

    def test_duplicate_branch_id_is_rejected(self):
        self.write_protocol()
        self.write_family("10-a.yaml", "same_id")
        self.write_family("20-b.yaml", "same_id")
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("重复", out)

    def test_illegal_category_is_rejected(self):
        self.write_protocol()
        self.write_family("10-a.yaml", "a_branch", cat="other")
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("category", out)

    def test_conflict_marker_is_reported_with_union_explanation(self):
        """源文件里出现冲突标记：报错必须说清"两份都留"这个动作，而不是只报 YAML 解析失败。"""
        self.write_protocol()
        (self.root / "triage-tree.d" / "10-a.yaml").write_text(
            "branches:\n<<<<<<< HEAD\n  - id: a\n=======\n  - id: b\n>>>>>>> other\n",
            encoding="utf-8")
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("冲突标记", out)
        self.assertIn("union", out)

    def test_duplicated_group_warns_but_does_not_fail(self):
        """union 合并会把两人加的同一行都留下：重复整条只告警（删一行即可），不拦下整次提交——
        拦下就等于把自动合并的收益又还回去了。"""
        self.write_protocol()
        self.write_family("10-a.yaml", "a_branch", syms=["boom", "boom"])
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        self.assertIn("WARN", out)

    def test_missing_protocol_or_empty_dir_is_rejected(self):
        self.write_family("10-a.yaml", "a_branch")
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn(btt.PROTOCOL_NAME, out)

    def test_branch_cap_is_enforced(self):
        self.write_protocol()
        for i in range(btt.BRANCH_CAP + 1):
            self.write_family(f"{i:02d}-f.yaml", f"b{i}")
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("上限", out)


class RealRepoTest(unittest.TestCase):
    """真实仓库上的断言：读侧不变、生成物与源一致、路由面就是那 7 个分支。"""

    def test_check_green_on_repo(self):
        for flag in ("--check", "--check-coverage", "--check-sources"):
            rc, out = run_main(flag, "--root", str(ROOT))
            self.assertEqual(rc, 0, f"{flag}: {out}")

    def test_aggregate_is_parseable_and_covers_expected_branches(self):
        doc = yaml.safe_load((ROOT / "triage-tree.yaml").read_text(encoding="utf-8"))
        ids = [b["id"] for b in doc["branches"]]
        self.assertEqual(ids, ["training_interrupt", "training_precision", "training_performance",
                               "inference_interrupt", "inference_precision", "inference_performance",
                               "uncategorized"])
        for b in doc["branches"]:
            self.assertIn(b["category"], ("interrupt", "precision", "performance", None))
            self.assertTrue(b["search_namespaces"])

    def test_sources_and_aggregate_agree_on_every_symptom(self):
        """逐条比对：源里每条症状组都在生成物里出现，数量一致（拼接不丢内容）。"""
        doc = yaml.safe_load((ROOT / "triage-tree.yaml").read_text(encoding="utf-8"))
        src_groups = 0
        for f in sorted((ROOT / "triage-tree.d").glob("*.yaml")):
            src_groups += len(yaml.safe_load(f.read_text(encoding="utf-8"))["branches"][0]["symptoms"])
        out_groups = sum(len(b["symptoms"]) for b in doc["branches"])
        self.assertEqual(src_groups, out_groups)
        self.assertGreater(out_groups, 50)


if __name__ == "__main__":
    unittest.main()
