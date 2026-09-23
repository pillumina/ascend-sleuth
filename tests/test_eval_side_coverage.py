"""eval_side_coverage（回放夹具的按侧覆盖报告）的口径回归测试。

为什么值得测：这份报告要支撑的结论是"某一侧没有量尺"——它一旦算错，两个方向都不轻：
把构造示例算成覆盖 → 缺口被掩盖（本次要修的就是这个误读）；把真实夹具漏算 →
报了不存在的缺口，人就去补已经有的东西。所以钉四件事：真实夹具怎么算、
构造示例与指向未入库 case 的夹具怎么排除、`--check` 的两档（任一缺口 / 指定侧必须有）、
以及"按侧覆盖"这个数与格子表对得上。
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import eval_side_coverage as ESC  # noqa: E402

CASE = """cases:
  - id: {cid}
    title: "{title}"
    category: {cat}
    tags: [t]
    confidence: {{score: 0.5}}
    symptoms:
      - "{sym}"
"""

FIXTURE = """# eval/golden/{name}
case_id: {cid}

input:
  symptoms: "s"
  framework: {fw}

expected:
  namespace: {ns}
  case_id: {cid}
  assertion: top-3
"""


class EvalSideCoverageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "eval" / "golden").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_case(self, rel, cid, cat="interrupt", title="t", sym="s"):
        p = self.root / "knowledge" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(CASE.format(cid=cid, title=title, cat=cat, sym=sym), encoding="utf-8")
        return p

    def write_fixture(self, name, cid, ns, fw="mindspeed-llm"):
        (self.root / "eval" / "golden" / name).write_text(
            FIXTURE.format(name=name, cid=cid, ns=ns, fw=fw), encoding="utf-8")

    def seed_both_sides_covered(self):
        """两侧各一条 case + 一条夹具——`--check` 判**全部已声明侧**，所以格层用例要先满足侧层。"""
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_fixture("T-1.fixture.yaml", "T-1", "training/mindspeed-llm/interrupt/")
        self.write_case("inference/vllm-ascend/interrupt/I-1.yaml", "I-1")
        self.write_fixture("I-1.fixture.yaml", "I-1", "inference/vllm-ascend/interrupt/")

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "eval_side_coverage.py"),
             "--root", str(self.root), *args],
            capture_output=True, text=True)

    # ---------------------------------------------------------------- 库侧口径
    def test_library_cases_bucket_by_side_and_nature(self):
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_case("training/verl/precision/T-2.yaml", "T-2", cat="precision")
        self.write_case("inference/vllm-ascend/interrupt/I-1.yaml", "I-1")
        lib, common = ESC.library_cases(self.root)
        self.assertEqual(lib[("training", "interrupt")], ["T-1"])
        self.assertEqual(lib[("training", "precision")], ["T-2"])
        self.assertEqual(lib[("inference", "interrupt")], ["I-1"])
        self.assertEqual(common, [])

    def test_common_pool_is_not_a_side(self):
        """common/ 是框架无关的共享池——它不判侧，所以既不算进某一侧，也不算缺口。"""
        self.write_case("common/performance/C-1.yaml", "C-1", cat="performance")
        lib, common = ESC.library_cases(self.root)
        self.assertEqual(lib, {})
        self.assertEqual(common, ["C-1"])

    # ---------------------------------------------------------------- 夹具侧口径
    def test_real_fixture_covers_its_cell(self):
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_fixture("T-1.fixture.yaml", "T-1", "training/mindspeed-llm/interrupt/")
        R = ESC.report(self.root)
        self.assertEqual(len(R["real"]), 1)
        self.assertIn("T-1", R["covered"][("training", "interrupt")])

    def test_constructed_example_does_not_count_as_coverage(self):
        """构造示例（example.*）是格式演示，不算覆盖——把它算进去正是本次要修的误读。"""
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_fixture("example.fixture.yaml", "T-1", "training/mindspeed-llm/interrupt/")
        R = ESC.report(self.root)
        self.assertEqual(R["real"], [])
        self.assertEqual(R["covered"], {})

    def test_fixture_pointing_at_unseeded_case_does_not_count(self):
        """指向未入库 case 的夹具（`case_id` 不在索引里）不是可运行回归，同样不算覆盖。"""
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_fixture("GHOST.fixture.yaml", "GHOST-1", "training/mindspeed-llm/interrupt/")
        R = ESC.report(self.root)
        self.assertEqual(R["real"], [])
        self.assertEqual([r["fixture"] for r in R["dead"]], ["GHOST.fixture.yaml"])

    def test_side_and_nature_parsed_from_namespace(self):
        self.write_fixture("T-9.fixture.yaml", "T-9", "inference/vllm-ascend/precision/")
        row = ESC.fixture_rows(self.root)[0]
        self.assertEqual((row["side"], row["nature"]), ("inference", "precision"))

    # ---------------------------------------------------------------- 门的两档
    # ------------------------------------------- 两层判据的分界（这是本脚本最容易做错的地方）
    # 侧层（`--check`）管"某一侧一条真实夹具都不剩"；格层（`--check-cells`）管"某个
    # (侧 × 性质) 格子有 case 没夹具"。**两层必须能各自独立触发**——本脚本第一版把两层
    # 压在一个 `--check` 里，于是文档写的门与实际跑的门不是同一个，下面四条钉住这个分界。
    def test_side_layer_red_when_a_side_has_no_fixture(self):
        """某个侧有 case 却一条夹具都没有 → 侧层红。"""
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        r = self.run_cli("--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("侧层", r.stdout)

    def test_cell_layer_is_report_only_by_default(self):
        """**默认只报不拦**：格子缺夹具但每个侧都有别的夹具时，`--check` 放行。

        这是刻意的取舍（补夹具需要真实来源、凭空造不出来，同 holdout 的空缺格子）——
        所以"某个格子缺夹具"不该让一次无关 PR 变红。放行的同时必须仍然**报出来**。
        """
        self.seed_both_sides_covered()
        self.write_case("training/verl/performance/T-2.yaml", "T-2", cat="performance")
        r = self.run_cli("--check")
        self.assertEqual(r.returncode, 0)
        self.assertIn("默认只报不拦", r.stdout)
        self.assertIn("--check-cells", r.stdout)

    def test_cell_layer_red_when_explicitly_requested(self):
        """同一个状态加 `--check-cells` 就红——格层门随时可开，只是默认不开。"""
        self.seed_both_sides_covered()
        self.write_case("training/verl/performance/T-2.yaml", "T-2", cat="performance")
        self.assertEqual(self.run_cli("--check").returncode, 0)
        self.assertEqual(self.run_cli("--check-cells").returncode, 1)
        self.assertEqual(self.run_cli("--check", "--check-cells").returncode, 1)

    def test_side_layer_ignores_sides_without_cases(self):
        """侧层只对**库里有 case 的侧**要求量尺。

        "新侧先在后端声明、下一条 PR 才补 case 与夹具"是正常顺序（路由协议文件的侧列表可扩张），
        那时拦下来是拦错了对象——判据是"这一侧没有回归保护"，没有 case 就没有需要保护的东西。
        """
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_fixture("T-1.fixture.yaml", "T-1", "training/mindspeed-llm/interrupt/")
        # inference 侧此时既无 case 也无夹具：不该被侧层当成缺口
        self.assertEqual(self.run_cli("--check").returncode, 0)
        # 但一旦落了 case，就必须有夹具
        self.write_case("inference/vllm-ascend/interrupt/I-1.yaml", "I-1")
        self.assertEqual(self.run_cli("--check").returncode, 1)

    def test_check_green_when_both_layers_are_clean(self):
        self.seed_both_sides_covered()
        r = self.run_cli("--check", "--check-cells")
        self.assertEqual(r.returncode, 0)
        self.assertIn("侧层：每个已声明的侧都有真实夹具", r.stdout)
        self.assertNotIn("默认只报不拦", r.stdout)

    def test_require_side_limits_the_side_layer(self):
        """`--require-side` 把侧层判据限定到点名的侧——没点名的侧就算归零也不拦。"""
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_fixture("T-1.fixture.yaml", "T-1", "training/mindspeed-llm/interrupt/")
        # inference 侧这时**有 case、无夹具**：这才是"归零"该判的场景（没 case 的侧已被跳过）
        self.write_case("inference/vllm-ascend/interrupt/I-1.yaml", "I-1")
        self.assertEqual(self.run_cli("--check").returncode, 1)
        self.assertEqual(self.run_cli("--check", "--require-side", "training").returncode, 0)
        self.assertEqual(self.run_cli("--check", "--require-side", "training",
                                      "--require-side", "inference").returncode, 1)

    def test_require_side_rejects_unknown_side(self):
        """写错的侧名要报出来，不能静默当成"通过了"——那是这个脚本最容易骗自己的地方。"""
        r = self.run_cli("--check", "--require-side", "trainig")
        self.assertEqual(r.returncode, 2)
        self.assertIn("trainig", r.stderr)

    def test_require_side_green_when_that_side_is_covered(self):
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_fixture("T-1.fixture.yaml", "T-1", "training/mindspeed-llm/interrupt/")
        r = self.run_cli("--check", "--require-side", "training")
        self.assertEqual(r.returncode, 0)

    # ---------------------------------------------------------------- 读取错误的两种形态必须同形
    def test_missing_root_is_read_error_not_green(self):
        """`--root` 指错地方不能静默报绿。

        `glob` 对不存在的根返回空，报告会把"根够不着"印成"库里没有 case、每侧 0/0"加一句 ✓——
        那正是这个脚本要消灭的那类误读（读起来像事实、实际是够不着）。所以根不存在必须与
        "case 文件读不动"同一个退出码契约（2），不能与"没有缺口"（0）同形。
        """
        r = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "eval_side_coverage.py"),
             "--root", str(self.root / "nope")],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--root", r.stderr)

    def test_example_fixture_is_named_in_the_exclusion_list(self):
        """被排除的两种夹具都要**点名**——只印一个数字，读者看不出谁被剔了。"""
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_fixture("example.fixture.yaml", "T-1", "training/mindspeed-llm/interrupt/")
        self.write_fixture("GHOST.fixture.yaml", "GHOST", "training/mindspeed-llm/interrupt/")
        r = self.run_cli()
        self.assertIn("example.fixture.yaml", r.stdout)
        self.assertIn("GHOST.fixture.yaml", r.stdout)

    # ---------------------------------------------------------------- 性质证据（读出"钉住词表"的夹具）
    def test_nature_evidence_flags_lexical_vs_semantic_only(self):
        """词法命中与仅靠语义兜底是两种强度，报告要能分开——这是这套夹具唯一的强度读数。"""
        tree = """sides:
  - id: training
    label: 训练
    namespaces: [training/<detected_framework>/, common/]
    fallback: Tier 3
natures:
  - id: interrupt
    category: interrupt
    symptoms:
      - ["RuntimeError"]
    search_namespaces: [<side>/<detected_framework>/, common/]
    fallback: Tier 3
  - id: precision
    category: precision
    symptoms:
      - ["nan"]
    search_namespaces: [<side>/<detected_framework>/, common/]
    fallback: Tier 3
"""
        (self.root / "triage-tree.yaml").write_text(tree, encoding="utf-8")
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_case("training/mindspeed-llm/precision/T-2.yaml", "T-2", cat="precision")
        # T-1 的输入里带 RuntimeError（词法命中）；T-2 的输入不带 nan（仅语义兜底）
        (self.root / "eval" / "golden" / "T-1.fixture.yaml").write_text(
            "case_id: T-1\ninput:\n  symptoms: \"崩了 RuntimeError\"\n  framework: mindspeed-llm\n"
            "expected:\n  namespace: training/mindspeed-llm/interrupt/\n  case_id: T-1\n"
            "  assertion: top-3\n", encoding="utf-8")
        (self.root / "eval" / "golden" / "T-2.fixture.yaml").write_text(
            "case_id: T-2\ninput:\n  symptoms: \"数值看着不对\"\n  framework: mindspeed-llm\n"
            "expected:\n  namespace: training/mindspeed-llm/precision/\n  case_id: T-2\n"
            "  assertion: top-3\n", encoding="utf-8")
        r = self.run_cli("--nature-evidence")
        self.assertEqual(r.returncode, 0)
        self.assertIn("分母 = 2 条", r.stdout)
        self.assertIn("词法上命中期望性质的有 1 条", r.stdout)
        self.assertIn("仅语义兜底", r.stdout)
        # 证据行必须带**命中的正则**，不能只印性质名：读者要回答的是"这条夹具钉住了哪几个词"，
        # 而同一个词可能出现在多个症状组里（只挪一处，夹具会照样显示为"词法命中"）。
        self.assertIn("interrupt←RuntimeError", r.stdout)

    def test_nature_evidence_denominator_excludes_natureless_namespaces(self):
        """分母只算 `expected.namespace` 带性质段的夹具——这条直接给函数喂一条无性质段的 row。

        为什么不走 CLI：无性质段的夹具（`inference/sglang/`，与仓里 SGL 那条同形）在
        `library_cases` 阶段就进不了任何 (侧 × 性质) 桶，于是连 `real` 都进不去、根本到不了这一栏。
        而 CLI 输出的 `不参与本栏的 N 条` 是兜底防线（防的是"进了 real、但性质段读不出来"）。
        """
        import yaml as _yaml
        (self.root / "triage-tree.yaml").write_text(
            "sides:\n  - id: training\n    namespaces: [training/<detected_framework>/]\n"
            "natures:\n  - id: interrupt\n    symptoms: [[\"RuntimeError\"]]\n"
            "    search_namespaces: [<side>/<detected_framework>/]\n", encoding="utf-8")
        self.write_fixture("I-1.fixture.yaml", "I-1", "inference/sglang/")
        rows = ESC.fixture_rows(self.root)
        self.assertEqual(rows[0]["side"], "inference")
        self.assertEqual(rows[0]["nature"], "")      # 没有性质段
        self.assertEqual(ESC.nature_evidence(self.root, rows), [])

    def test_nature_evidence_survives_unparsable_tree(self):
        """路由表读不动时，性质证据是**可选读数**——不该把整份报告带崩、也不该伪装成"有缺口"。"""
        (self.root / "triage-tree.yaml").write_text("natures: [{id: interrupt", encoding="utf-8")
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        r = self.run_cli("--nature-evidence")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.returncode, 0)

    # ---------------------------------------------------------------- 覆盖记在错的格子上要报出来
    def test_fixture_declaring_the_wrong_cell_is_surfaced(self):
        """夹具声明的期望格与它指向的 case 实际所在格不一致 → 单列一行。

        不报的后果是双向误导：声明的那一格看起来"有覆盖"，而 case 真正的格子看起来是缺口。
        """
        self.write_case("training/mindspeed-llm/precision/T-1.yaml", "T-1", cat="precision")
        self.write_fixture("T-1.fixture.yaml", "T-1", "training/mindspeed-llm/interrupt/")
        R = ESC.report(self.root)
        self.assertEqual([r["fixture"] for r in R["mismatched"]], ["T-1.fixture.yaml"])
        self.assertIn("不在这一格", self.run_cli().stdout)

    def test_fixture_with_unreadable_side_is_surfaced(self):
        """namespace 首段读不出侧（写错一个词）也要报，不能静默混进「共享池」那一栏。"""
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_fixture("T-1.fixture.yaml", "T-1", "trainig/mindspeed-llm/interrupt/")
        R = ESC.report(self.root)
        self.assertEqual([r["fixture"] for r in R["mismatched"]], ["T-1.fixture.yaml"])
        self.assertIn("首段读不出侧", self.run_cli().stdout)

    def test_consistent_fixture_is_not_flagged(self):
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_fixture("T-1.fixture.yaml", "T-1", "training/mindspeed-llm/interrupt/")
        self.assertEqual(ESC.report(self.root)["mismatched"], [])

    def test_common_pool_fixture_is_not_flagged_as_mismatch(self):
        """共享池的 case 不进任何侧桶——报告不判共享池，所以它也不该被当成「格不一致」。"""
        self.write_case("common/performance/C-1.yaml", "C-1", cat="performance")
        self.write_fixture("C-1.fixture.yaml", "C-1", "common/performance/")
        self.assertEqual(ESC.report(self.root)["mismatched"], [])

    # ---------------------------------------------------------------- 本仓实况：缺口不再被掩盖
    def test_repo_reports_training_side_as_covered(self):
        """在本仓上跑：训练侧两个性质面都该有真实夹具了。

        这条钉的是"本次补齐真的生效"——它对仓库内容敏感，夹具被删或改指向就会红。
        """
        R = ESC.report(ROOT)
        self.assertTrue(R["covered"].get(("training", "interrupt")), "训练侧 interrupt 面无夹具")
        self.assertTrue(R["covered"].get(("training", "precision")), "训练侧 precision 面无夹具")

    def test_repo_training_fixtures_are_lexically_anchored(self):
        """本仓两条训练侧夹具的输入必须**词法上**就命中期望性质。

        这是它们与多数推理侧夹具的区别：推理侧 16/26 条靠语义兜底，改坏词表也照样过；
        训练侧这两条是词法锚定的，所以它们真能报出"性质词表被改坏"。
        （实测：把 `RuntimeError` 从 interrupt 挪到别的性质 → MSLLM-1655 当场报。）
        """
        ev = ESC.nature_evidence(ROOT, ESC.fixture_rows(ROOT))
        train = {e["fixture"]: e for e in ev if e["side"] == "training"}
        self.assertTrue(train, "训练侧没有任何夹具")
        for name, e in train.items():
            self.assertTrue(e["lexical"], f"{name} 的输入没有词法命中期望性质 {e['expected']}")

    def test_repo_nature_evidence_report_is_self_explanatory(self):
        """本仓实跑：这一栏要自带分母说明、点名不参与的夹具、并印出命中的正则。

        注意要走**本仓 root**（run_cli 默认把 --root 指向临时目录，那里没有 knowledge/）。
        """
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "eval_side_coverage.py"),
                            "--nature-evidence"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("带性质段的夹具", r.stdout)
        self.assertIn("不参与本栏的", r.stdout)
        self.assertIn("←", r.stdout)          # 命中的正则与性质一起印（性质←正则）


if __name__ == "__main__":
    unittest.main()
