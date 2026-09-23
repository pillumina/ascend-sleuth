"""Tier 1 路由层「源 → 生成物」的口径回归测试。

这一层存在的理由是可验证的：路由数据原先放在一个文件里，谁加词都得改它，两个人撞在同一段文本上
就要人判断"留哪一份"。拆成一性质一文件 + 生成物之后，**读侧完全不变**（diagnose /
verify_references / kb-explorer 读的还是 triage-tree.yaml），所以本测试要钉住的正是
"生成物与源一致、拼接不丢内容、不改顺序"这三件事。

分层（先分侧、再分性质）加进来之后，还要钉住两件**只有分层才有**的事：
  ① 性质文件里的 `search_namespaces` 必须带 `<side>/` 占位——写死某一侧等于把侧又塞回症状层，
     跨侧碰撞会随这一行回来；
  ② `00-protocol.md` 的 `sources:` 是拼接口径的唯一写点——目录里存在但没登记的文件不会被拼进
     生成物，等于加了词却没生效，必须红。
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
      - <side>/<detected_framework>/
      - common/
    fallback: Tier 3
"""

PROTOCOL = """路由说明第一行

第二行

sources:
{manifest}
sides:
  - id: training
    label: 训练
    namespaces:
      - training/<detected_framework>/
      - common/
    fallback: Tier 3
  - id: inference
    label: 推理
    namespaces:
      - inference/<detected_framework>/
      - common/
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
        self.files = []

    def tearDown(self):
        self.tmp.cleanup()

    def write_family(self, name, bid, cat="interrupt", sym="boom", syms=None,
                     ns_side="<side>/<detected_framework>/", extra_ns=None):
        """写一个性质源文件；登记用的 manifest 条目留在 self.files 里。"""
        groups = syms if syms is not None else [sym]
        nss = [ns_side] + list(extra_ns or ["common/"])
        body = (
            f"  - id: {bid}\n"
            f"    category: {cat}\n"
            "    symptoms:\n"
            + "".join(f'      - ["{s}"]\n' for s in groups)
            + "    search_namespaces:\n"
            + "".join(f"      - {n}\n" for n in nss)
            + "    fallback: Tier 3\n"
        )
        (self.root / "triage-tree.d" / name).write_text(
            f"# 一性质：{bid}\n\nnatures:\n" + body, encoding="utf-8")
        self.files.append({"file": name, "nature": bid})
        return name

    def write_protocol(self, text=None, manifest=None, sides=2):
        if text is not None:
            (self.root / "triage-tree.d" / btt.PROTOCOL_NAME).write_text(text, encoding="utf-8")
            return
        items = manifest if manifest is not None else self.files
        m = ("".join(f"  - file: {it['file']}\n    nature: {it['nature']}\n" for it in items)
             or "  []\n")
        block = PROTOCOL.format(manifest=m)
        if sides == 1:
            block = block.split("  - id: inference")[0].rstrip("\n") + "\n"
        (self.root / "triage-tree.d" / btt.PROTOCOL_NAME).write_text(block, encoding="utf-8")

    def build(self):
        return run_main("--root", str(self.root))

    # ---------------------------------------------------------------- 源 → 生成物
    def test_generate_then_check_is_green(self):
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        rc, out = run_main("--check", "--root", str(self.root))
        self.assertEqual(rc, 0, out)
        self.assertIn("逐字节相同", out)

    def test_check_red_and_says_rerun_when_source_changed(self):
        """改了源没重建 → 红，且给的动作是"重跑一次"，不是让人去比对生成物。"""
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_protocol()
        self.build()
        self.write_family("10-interrupt.yaml", "interrupt", sym="boom2")
        rc, out = run_main("--check", "--root", str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("build_triage_tree.py", out)

    # ---------------------------------------------------------------- 覆盖检查（门）
    def test_coverage_green_and_red_on_missing_word(self):
        """门是覆盖检查：源里每条症状组都在聚合里。缺一条 → 红（改名/改词/手改聚合都落这条）。"""
        self.write_family("10-interrupt.yaml", "interrupt", syms=["boom", "bang"])
        self.write_protocol()
        self.build()
        rc, out = run_main("--check-coverage", "--root", str(self.root))
        self.assertEqual(rc, 0, out)
        agg = self.root / "triage-tree.yaml"
        agg.write_text(agg.read_text(encoding="utf-8").replace('      - ["bang"]\n', ""),
                       encoding="utf-8")
        rc, out = run_main("--check-coverage", "--root", str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("缺症状组", out)

    def test_coverage_flags_side_layer_drift(self):
        """侧层也进覆盖检查：`sides:` 是分层的一半，掉了它"先分侧"就无从落地。"""
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_protocol()
        self.build()
        agg = self.root / "triage-tree.yaml"
        text = agg.read_text(encoding="utf-8")
        agg.write_text(text.replace("  - inference/<detected_framework>/",
                                    "  - inference-serve/<detected_framework>/", 1),
                       encoding="utf-8")
        rc, out = run_main("--check-coverage", "--root", str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("侧 inference 的 namespaces 与源不一致", out)

    def test_retired_branches_key_is_flagged(self):
        """`branches:` 桶随分层退休：留着它读的人会以为有两套结构（一份还会漂移）。"""
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_protocol()
        self.build()
        agg = self.root / "triage-tree.yaml"
        agg.write_text(agg.read_text(encoding="utf-8")
                       + "branches:\n  - {id: bogus, category: null}\n", encoding="utf-8")
        rc, out = run_main("--check-coverage", "--root", str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("branches", out)

    def test_union_merged_aggregate_is_green(self):
        """**关键一条**：两人同一天给同一性质加词，union 合并出来的聚合（两句都在、顺序可能不是
        重新拼接的顺序）必须是**绿的**——否则 union 换来的"谁都不用跑命令"就白拿了。
        逐字节自检（--check）此时会红，那是可选的归一化提示，不作门。"""
        self.write_family("10-interrupt.yaml", "interrupt", syms=["boom", "mine", "theirs"])
        self.write_protocol()
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

    def test_coverage_flags_reordered_natures(self):
        """**顺序也是判据**：diagnose 按性质顺序匹配、先命中先归类——把两个性质块对调就是改了
        路由优先级，而集合相等的检查看不出来。"""
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_family("20-performance.yaml", "performance")
        self.write_protocol()
        self.build()
        agg = self.root / "triage-tree.yaml"
        lines = agg.read_text(encoding="utf-8").split("\n")
        i_a = lines.index("  - id: interrupt")
        i_b = lines.index("  - id: performance")
        # 只对调两个 `- id:` 行：整块对调会把 `branches:` 别名挤到中间、把 YAML 拼坏，
        # 那时报的是解析失败而不是顺序问题，测的东西就变了（实测踩过）。
        lines[i_a], lines[i_b] = lines[i_b], lines[i_a]
        agg.write_text("\n".join(lines), encoding="utf-8")
        rc, out = run_main("--check-coverage", "--root", str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("顺序与源不一致", out)

    def test_coverage_reports_nature_missing_from_aggregate(self):
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_family("20-performance.yaml", "performance")
        self.write_protocol()
        self.build()
        agg = self.root / "triage-tree.yaml"
        text = agg.read_text(encoding="utf-8")
        agg.write_text(text[:text.index("  - id: performance\n")], encoding="utf-8")
        rc, out = run_main("--check-coverage", "--root", str(self.root))
        self.assertEqual(rc, 1)
        self.assertIn("缺性质", out)

    def test_nature_order_follows_manifest(self):
        """顺序由 protocol 的 `sources:` 决定（序号前缀是给人找文件的索引，不直接参与排序）。"""
        self.write_family("20-performance.yaml", "performance")
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_protocol(manifest=[{"file": "20-performance.yaml", "nature": "performance"},
                                      {"file": "10-interrupt.yaml", "nature": "interrupt"}])
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        doc = yaml.safe_load((self.root / "triage-tree.yaml").read_text(encoding="utf-8"))
        self.assertEqual([b["id"] for b in doc["natures"]], ["performance", "interrupt"])

    def test_protocol_becomes_comment_header(self):
        """说明与入场判据（散文）进生成物的注释头，正文只有 sides / natures。"""
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_protocol()
        self.build()
        text = (self.root / "triage-tree.yaml").read_text(encoding="utf-8")
        head = text[:text.index("sides:")]
        self.assertIn("# 路由说明第一行", head)
        self.assertIn("#\n", head)          # 空行 → 裸 '#'
        self.assertNotIn("路由说明第一行", text[text.index("sides:"):])

    def test_body_is_verbatim_splice_of_sources(self):
        """拼接逐字保留（含行内注释与对齐）：路由行为不变的证据是 diff，不是"应该没变"。"""
        (self.root / "triage-tree.d" / "10-interrupt.yaml").write_text(
            "# 注释不进正文\n\nnatures:\n"
            "  - id: interrupt\n"
            "    category: interrupt\n"
            "    symptoms:\n"
            '      - ["boom"]    # 这条的来历（VERL-1）\n'
            "    search_namespaces: [<side>/<detected_framework>/, common/]   # 按顺序搜\n"
            "    fallback: Tier 3\n",
            encoding="utf-8")
        self.files.append({"file": "10-interrupt.yaml", "nature": "interrupt"})
        self.write_protocol()
        self.build()
        text = (self.root / "triage-tree.yaml").read_text(encoding="utf-8")
        body = text[text.index("natures:"):]
        self.assertIn('# 这条的来历（VERL-1）', body)
        self.assertIn("search_namespaces: [<side>/<detected_framework>/, common/]   # 按顺序搜", body)
        self.assertNotIn("注释不进正文", body)

    # ---------------------------------------------------------------- 源文件校验
    def test_two_natures_in_one_file_is_rejected(self):
        """一性质一文件是 union 合并能自动留住两边改动的前提，破了它就回到判断题。"""
        self.write_family("10-interrupt.yaml", "interrupt")
        p = self.root / "triage-tree.d" / "30-both.yaml"
        p.write_text("natures:\n" + BRANCH.format(bid="interrupt", cat="interrupt", sym="x")
                     + BRANCH.format(bid="precision", cat="precision", sym="y"),
                     encoding="utf-8")
        self.files.append({"file": "30-both.yaml", "nature": "interrupt"})   # 登记了也要按"一性质一文件"拦
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("一性质一文件", out)

    def test_unregistered_source_file_is_rejected(self):
        """目录里有、`sources:` 里没有 → 不会被拼进生成物（加了词却没生效），必须红。"""
        self.write_family("10-interrupt.yaml", "interrupt")
        (self.root / "triage-tree.d" / "90-precision.yaml").write_text(
            "natures:\n" + BRANCH.format(bid="precision", cat="precision", sym="y"),
            encoding="utf-8")
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("sources", out)
        self.assertIn("90-precision.yaml", out)

    def test_manifest_nature_mismatch_is_rejected(self):
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_protocol(manifest=[{"file": "10-interrupt.yaml", "nature": "performance"}])
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("对不上", out)

    def test_missing_side_placeholder_is_rejected(self):
        """**分层之后最要紧的一条**：性质层的检索面写死某一侧 = 把侧塞回症状层。"""
        self.write_family("10-interrupt.yaml", "interrupt", ns_side="training/<detected_framework>/")
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("<side>", out)

    def test_one_pinned_namespace_among_placeholder_ones_is_rejected(self):
        """**逐条判**，不是"有一条带 `<side>` 就算过"。独立预核实测的绕过口：列表里混一条写死侧的
        目录 + 一条带 `<side>` 的项，只判存在就放行，而推理侧展开后会去查训练目录——
        这一层要防的机制原样回来，且全套门都是绿的。"""
        self.write_family("10-interrupt.yaml", "interrupt",
                          ns_side="training/<detected_framework>/", extra_ns=["<side>/common/"])
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 1, out)
        self.assertIn("写死某一侧", out)

    def test_side_agnostic_namespace_must_be_in_the_side_layer(self):
        """公共目录由 `sides:` 派生（各侧 namespaces 的交集），不是写死一份 `common/`：
        协议里没进过任何侧目录面的项，性质层也不许用。"""
        self.write_family("10-interrupt.yaml", "interrupt", extra_ns=["shared/"])
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 1, out)
        self.assertIn("shared/", out)

    def test_missing_side_layer_is_rejected(self):
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_protocol(sides=1)
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("侧少于", out)

    def test_side_namespace_outside_its_own_dir_is_rejected(self):
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_protocol(text=PROTOCOL.format(
            manifest="  - file: 10-interrupt.yaml\n    nature: interrupt\n").replace(
            "      - inference/<detected_framework>/", "      - training/<detected_framework>/"))
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("inference/", out)

    def test_duplicate_nature_id_is_rejected(self):
        self.write_family("10-interrupt.yaml", "interrupt")
        self.write_family("20-interrupt.yaml", "interrupt")
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("重复", out)

    def test_nature_id_must_match_filename(self):
        self.write_family("10-interrupt.yaml", "precision", cat="precision")
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("两处必须同名", out)

    def test_illegal_category_is_rejected(self):
        self.write_family("10-interrupt.yaml", "interrupt", cat="other")
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("category", out)

    def test_conflict_marker_is_reported_with_union_explanation(self):
        """源文件里出现冲突标记：报错必须说清"两份都留"这个动作，而不是只报 YAML 解析失败。"""
        (self.root / "triage-tree.d" / "10-interrupt.yaml").write_text(
            "natures:\n<<<<<<< HEAD\n  - id: a\n=======\n  - id: b\n>>>>>>> other\n",
            encoding="utf-8")
        self.files.append({"file": "10-interrupt.yaml", "nature": "interrupt"})
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("冲突标记", out)
        self.assertIn("union", out)

    def test_duplicated_group_warns_but_does_not_fail(self):
        """union 合并会把两人加的同一行都留下：重复整条只告警（删一行即可），不拦下整次提交——
        拦下就等于把自动合并的收益又还回去了。"""
        self.write_family("10-interrupt.yaml", "interrupt", syms=["boom", "boom"])
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        self.assertIn("WARN", out)

    def test_missing_protocol_or_empty_dir_is_rejected(self):
        self.write_family("10-interrupt.yaml", "interrupt")
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn(btt.PROTOCOL_NAME, out)

    def test_nature_cap_is_enforced(self):
        self.write_protocol()
        for i in range(btt.NATURE_CAP + 1):
            self.write_family(f"{i:02d}-f{i}.yaml", f"nature{i}")
        self.write_protocol()
        rc, out = self.build()
        self.assertEqual(rc, 1)
        self.assertIn("上限", out)


class RealRepoTest(unittest.TestCase):
    """真实仓库上的断言：读侧不变、生成物与源一致、路由面就是那三个性质 × 两个侧。"""

    def test_check_green_on_repo(self):
        for flag in ("--check", "--check-coverage", "--check-sources"):
            rc, out = run_main(flag, "--root", str(ROOT))
            self.assertEqual(rc, 0, f"{flag}: {out}")

    def test_aggregate_has_only_two_top_level_keys(self):
        """生成物只有侧层与性质层两个顶层键——`branches:` 桶已退休，不留别名。"""
        doc = yaml.safe_load((ROOT / "triage-tree.yaml").read_text(encoding="utf-8"))
        self.assertEqual(sorted(doc), ["natures", "sides"])

    def test_aggregate_has_side_layer_and_three_natures(self):
        doc = yaml.safe_load((ROOT / "triage-tree.yaml").read_text(encoding="utf-8"))
        self.assertEqual([s["id"] for s in doc["sides"]], ["training", "inference"])
        for s in doc["sides"]:
            self.assertTrue(s["namespaces"])
            self.assertTrue(any(str(n).startswith(s["id"] + "/") for n in s["namespaces"]))
        self.assertEqual([b["id"] for b in doc["natures"]],
                         ["interrupt", "precision", "performance"])
        for b in doc["natures"]:
            self.assertIn(b["category"], ("interrupt", "precision", "performance"))
            self.assertTrue(b["search_namespaces"])
            self.assertTrue(any("<side>" in n for n in b["search_namespaces"]),
                            f"{b['id']} 的检索面缺 <side> 占位")

    def test_no_nature_id_carries_a_side(self):
        """分层之后分支名就是性质名——带 `training_` / `inference_` 前缀等于把侧记两遍。"""
        doc = yaml.safe_load((ROOT / "triage-tree.yaml").read_text(encoding="utf-8"))
        for b in doc["natures"]:
            self.assertNotIn(str(b["id"]).split("_")[0], ("training", "inference"),
                             f"{b['id']} 的分支名里带着侧")

    def test_sources_and_aggregate_agree_on_every_symptom(self):
        """逐条比对：源里每条症状组都在生成物里出现，数量一致（拼接不丢内容）。"""
        doc = yaml.safe_load((ROOT / "triage-tree.yaml").read_text(encoding="utf-8"))
        src_groups = 0
        for f in sorted((ROOT / "triage-tree.d").glob("*.yaml")):
            src_groups += len(yaml.safe_load(f.read_text(encoding="utf-8"))["natures"][0]["symptoms"])
        out_groups = sum(len(b["symptoms"]) for b in doc["natures"])
        self.assertEqual(src_groups, out_groups)
        self.assertGreater(out_groups, 40)


if __name__ == "__main__":
    unittest.main()
