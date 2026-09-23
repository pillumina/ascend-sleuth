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
    def test_check_red_on_any_gap(self):
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        r = self.run_cli("--check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("training / interrupt", r.stdout)

    def test_check_green_when_every_cell_has_a_fixture(self):
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        self.write_fixture("T-1.fixture.yaml", "T-1", "training/mindspeed-llm/interrupt/")
        r = self.run_cli("--check")
        self.assertEqual(r.returncode, 0)
        self.assertIn("每个含 case 的 (侧 × 性质) 格子都有真实夹具", r.stdout)

    def test_require_side_red_when_that_side_has_nothing(self):
        """`--require-side` 是钉住本次补齐的那一档：整侧没有夹具时，即使其它格子都满也要报。"""
        self.write_case("inference/vllm-ascend/interrupt/I-1.yaml", "I-1")
        self.write_fixture("I-1.fixture.yaml", "I-1", "inference/vllm-ascend/interrupt/")
        self.assertEqual(self.run_cli("--check").returncode, 0)
        self.write_case("training/mindspeed-llm/interrupt/T-1.yaml", "T-1")
        # 训练侧此刻有 case、无夹具——普通 --check 报缺口，--require-side 也报
        self.assertEqual(self.run_cli("--check", "--require-side", "training").returncode, 1)

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
        self.assertIn("性质证据（夹具的输入在词法上命中期望性质的有 1/2 条）", r.stdout)
        self.assertIn("仅语义兜底", r.stdout)

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


if __name__ == "__main__":
    unittest.main()
