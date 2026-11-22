#!/usr/bin/env python3
"""select_unit_tests 的选择规则：改动 → 测试子集，条件不成立时回退全量。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import select_unit_tests as sut  # noqa: E402


class SelectUnitTestsTest(unittest.TestCase):
    """在临时仓库里造 scripts/tests 的引用关系，逐条验选择与回退。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def write(self, rel: str, text: str = "") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def select(self, changed, **kwargs):
        return sut.select(self.root, changed, **kwargs)

    # ---- 基本选择 ----

    def test_changed_script_selects_test_it_imports(self):
        self.write("scripts/build_foo.py")
        self.write("tests/test_build_foo.py", "import build_foo\n")
        result, _ = self.select(["scripts/build_foo.py"])
        self.assertEqual(result, ["tests.test_build_foo"])

    def test_dir_consumers_point_at_existing_scripts(self):
        """DIR_CONSUMERS 写错只会表现为少选；钉住每个键与消费方都落在真仓里。"""
        for prefix, consumers in sut.DIR_CONSUMERS.items():
            with self.subTest(prefix=prefix):
                self.assertTrue((ROOT / prefix).is_dir(), prefix)
                modules = {alias for alias, _ in sut._script_modules(ROOT)}
                for alias in consumers:
                    self.assertIn(alias, modules, f"{prefix} -> {alias}")

    def test_data_dir_change_selects_consumer_test(self):
        """数据目录改动要选中消费脚本的测试：数据文件不是脚本，静态扫描看不出归属。"""
        self.write("scripts/src_fetch.py")
        self.write("tests/test_src_fetch.py", "import src_fetch\n")
        self.write("scripts/source_catalog.py")
        self.write("tests/test_source_catalog.py", "import source_catalog\n")
        result, notes = self.select(["source-catalog.d/cann.yaml"])
        self.assertEqual(result, ["tests.test_source_catalog", "tests.test_src_fetch"])
        self.assertFalse(any("跳过" in note for note in notes))

    def test_shared_module_pulls_dependents_tests(self):
        self.write("scripts/_shared.py", "def helper():\n    return 1\n")
        self.write("scripts/build_foo.py", "from _shared import helper\n")
        self.write("tests/test_build_foo.py", "import build_foo\n")
        result, _ = self.select(["scripts/_shared.py"])
        self.assertEqual(result, ["tests.test_build_foo"])

    def test_transitive_dependents_are_included(self):
        self.write("scripts/_base.py")
        self.write("scripts/_middle.py", "import _base\n")
        self.write("scripts/build_foo.py", "import _middle\n")
        self.write("tests/test_build_foo.py", "import build_foo\n")
        result, _ = self.select(["scripts/_base.py"])
        self.assertEqual(result, ["tests.test_build_foo"])

    def test_nested_test_module_is_selected(self):
        self.write("scripts/cli.py")
        self.write("tests/self_evolution/test_cli.py", "import cli\n")
        result, _ = self.select(["tests/self_evolution/test_cli.py"])
        self.assertEqual(result, ["tests.self_evolution.test_cli"])

    def test_package_script_selects_test_by_dotted_import(self):
        """子包按点分模块名解析，不再一律全量：改 samples 只带出 import 它的测试。"""
        self.write("scripts/evolve/__init__.py")
        self.write("scripts/evolve/samples.py")
        self.write("scripts/evolve/other.py")
        self.write("tests/evolve/test_samples.py", "from evolve.samples import Sample\n")
        self.write("tests/evolve/test_other.py", "from evolve.other import Other\n")
        result, _ = self.select(["scripts/evolve/samples.py"])
        self.assertEqual(result, ["tests.evolve.test_samples"])

    def test_relative_import_links_package_modules(self):
        """包内 `from .decision import` 要连到同包模块，改被引用的那个能带出调用方。"""
        self.write("scripts/evolve/__init__.py")
        self.write("scripts/evolve/decision.py")
        self.write("scripts/evolve/runner.py", "from .decision import decide\n")
        self.write(
            "tests/self_evolution/test_runner.py",
            "from evolve.runner import decide\n",
        )
        result, _ = self.select(["scripts/evolve/decision.py"])
        self.assertEqual(result, ["tests.self_evolution.test_runner"])

    def test_nested_relative_import_resolves_to_parent_package(self):
        """`from ..adapters import x` 要按当前包层级回退两级。"""
        self.write("scripts/evolve/__init__.py")
        self.write("scripts/evolve/adapters/__init__.py")
        self.write("scripts/evolve/sources/__init__.py")
        self.write(
            "scripts/evolve/sources/github.py",
            "from ..adapters import AdapterError\n",
        )
        self.write(
            "tests/self_evolution/test_github.py",
            "from evolve.sources.github import GitHub\n",
        )
        result, _ = self.select(["scripts/evolve/adapters/__init__.py"])
        self.assertIn("tests.self_evolution.test_github", result)

    def test_package_init_change_pulls_member_tests(self):
        """改包 `__init__.py` 会让包内每个模块受影响：import 子模块先执行 init。"""
        self.write("scripts/evolve/__init__.py")
        self.write("scripts/evolve/samples.py")
        self.write("scripts/evolve/runner.py")
        self.write("tests/self_evolution/test_samples.py", "from evolve.samples import S\n")
        self.write("tests/self_evolution/test_runner.py", "from evolve.runner import R\n")
        result, _ = self.select(["scripts/evolve/__init__.py"])
        self.assertEqual(
            result,
            ["tests.self_evolution.test_runner", "tests.self_evolution.test_samples"],
        )

    def test_same_named_entry_does_not_expand_to_package(self):
        """`scripts/evolve.py` 与包 `evolve/` 同名：改入口不能把包内模块带出来。

        判据取「改入口文件本身」：只有包内模块引用的测试不该被选中。若实现按
        「这个名字有成员」展开，这里会多出 tests.test_runner。
        """
        self.write("scripts/evolve.py", "from evolve.cli import main\n")
        self.write("scripts/evolve/__init__.py")
        self.write("scripts/evolve/cli.py")
        self.write("scripts/evolve/runner.py")
        self.write("tests/test_cli.py", "from evolve.cli import main\n")
        self.write("tests/test_runner.py", "from evolve.runner import run\n")
        result, _ = self.select(["scripts/evolve.py"])
        self.assertEqual(result, [])

    def test_relative_import_in_package_init_uses_that_package(self):
        """包 `__init__.py` 里的 `from .base import` 指向包内，不是父包。"""
        self.write("scripts/evolve/__init__.py")
        self.write("scripts/evolve/sources/__init__.py", "from .base import Source\n")
        self.write("scripts/evolve/sources/base.py")
        self.write(
            "tests/self_evolution/test_sources.py",
            "from evolve.sources import Source\n",
        )
        result, _ = self.select(["scripts/evolve/sources/base.py"])
        self.assertEqual(result, ["tests.self_evolution.test_sources"])

    def test_relative_import_in_top_package_init_uses_package(self):
        """顶层包 `__init__.py` 的 `from .samples import` 指向 `evolve.samples`。"""
        self.write("scripts/evolve/__init__.py", "from .samples import S\n")
        self.write("scripts/evolve/samples.py")
        self.write("tests/test_samples.py", "from evolve import S\n")
        result, _ = self.select(["scripts/evolve/samples.py"])
        self.assertEqual(result, ["tests.test_samples"])

    def test_nested_dir_without_package_forces_all(self):
        """包内还有一层不是包的目录：点分名对不上，按全量（多跑，不漏跑）。"""
        self.write("scripts/evolve/__init__.py")
        self.write("scripts/evolve/plugins/tool.py")
        result, notes = self.select(["scripts/evolve/plugins/tool.py"])
        self.assertEqual(result, "ALL")
        self.assertTrue(any("登记消费方" in note for note in notes))

    def test_subpackage_path_string_reference_is_selected(self):
        """测试用 `scripts/<子目录>/<文件>` 字面量调脚本时也要选中。"""
        self.write("scripts/evolve/__init__.py")
        self.write("scripts/evolve/runner.py")
        self.write("tests/test_runner.py", 'CMD = ["python3", "scripts/evolve/runner.py"]\n')
        result, _ = self.select(["scripts/evolve/runner.py"])
        self.assertEqual(result, ["tests.test_runner"])

    def test_dynamic_dir_maps_to_consumer_test(self):
        """动态加载的目录没有 import 关系，靠登记的消费方选中它的测试。"""
        self.write("scripts/platforms/github.py")
        self.write("scripts/pr_status.py", "PLATFORMS_DIR = 1\n")
        self.write("tests/test_pr_status.py", "import pr_status\n")
        result, _ = self.select(["scripts/platforms/github.py"])
        self.assertEqual(result, ["tests.test_pr_status"])

    def test_unknown_subdir_without_package_forces_all(self):
        """未登记、也不在 Python 包里的子目录：静态扫描看不出谁用它，回退全量。"""
        self.write("scripts/newdir/tool.js")
        result, notes = self.select(["scripts/newdir/tool.js"])
        self.assertEqual(result, "ALL")
        self.assertTrue(any("登记消费方" in note for note in notes))

    def test_registered_dir_without_consumers_selects_nothing(self):
        """已登记且没有 Python 测试消费的目录：不跑单元测试，由别的 job 管。"""
        self.write("scripts/fixtures/make_root.py")
        result, notes = self.select(["scripts/fixtures/make_root.py"])
        self.assertEqual(result, [])
        self.assertTrue(any("没有单元测试引用" in note for note in notes))

    def test_all_test_modules_recurse(self):
        self.write("tests/test_a.py")
        self.write("tests/self_evolution/test_b.py")
        self.assertEqual(
            sut.all_test_modules(self.root),
            ["tests.self_evolution.test_b", "tests.test_a"],
        )

    def test_changed_test_file_is_selected_even_without_script_change(self):
        self.write("scripts/cli.py")
        self.write("tests/test_cli.py", "import subprocess\n")
        result, _ = self.select(["tests/test_cli.py"])
        self.assertEqual(result, ["tests.test_cli"])

    def test_script_filename_string_reference_is_selected(self):
        self.write("scripts/tool.mjs")
        self.write(
            "tests/test_tool.py",
            'CMD = ["node", "scripts/tool.mjs"]\n',
        )
        result, _ = self.select(["scripts/tool.mjs"])
        self.assertEqual(result, ["tests.test_tool"])

    def test_orphan_test_runs_on_any_script_change(self):
        self.write("scripts/cli.py")
        self.write("tests/test_orphan.py", "import subprocess\n")
        result, _ = self.select(["scripts/cli.py"])
        self.assertEqual(result, ["tests.test_orphan"])

    def test_multiple_tests_are_sorted(self):
        self.write("scripts/build_foo.py")
        self.write("tests/test_b.py", "import build_foo\n")
        self.write("tests/test_a.py", "import build_foo\n")
        result, _ = self.select(["scripts/build_foo.py"])
        self.assertEqual(result, ["tests.test_a", "tests.test_b"])

    # ---- 无对应测试 ----

    def test_untested_script_selects_nothing(self):
        self.write("scripts/cli.py")
        self.write("tests/test_other.py", "import other\n")
        self.write("scripts/other.py")
        result, notes = self.select(["scripts/cli.py"])
        self.assertEqual(result, [])
        self.assertTrue(any("没有单元测试引用" in note for note in notes))

    def test_unreferenced_js_script_selects_nothing(self):
        self.write("scripts/tool.mjs")
        result, _ = self.select(["scripts/tool.mjs"])
        self.assertEqual(result, [])

    # ---- 回退全量 ----

    def test_force_all(self):
        result, _ = self.select([], force_all=True)
        self.assertEqual(result, "ALL")

    def test_tests_helper_forces_all(self):
        self.write("tests/fixtures/case.yaml")
        result, _ = self.select(["tests/fixtures/case.yaml"])
        self.assertEqual(result, "ALL")

    def test_ci_change_forces_all(self):
        self.write(".github/workflows/kb-checks.yml")
        result, _ = self.select([".github/workflows/kb-checks.yml"])
        self.assertEqual(result, "ALL")

    def test_deleted_test_file_forces_all(self):
        """删测试文件时没有可跑的模块；不判全量就成了「删掉测试 = 绿」。"""
        result, notes = self.select(["tests/test_gone.py"])
        self.assertEqual(result, "ALL")
        self.assertTrue(any("删除" in note for note in notes))

    def test_deleted_script_forces_all(self):
        self.write("scripts/build_foo.py")
        result, _ = self.select(["scripts/gone.py"])
        self.assertEqual(result, "ALL")

    def test_unparsable_changed_script_forces_all(self):
        self.write("scripts/broken.py", "def broken(:\n")
        result, _ = self.select(["scripts/broken.py"])
        self.assertEqual(result, "ALL")

    def test_unparsable_test_file_forces_all(self):
        self.write("scripts/build_foo.py")
        self.write("tests/test_broken.py", "def broken(:\n")
        result, _ = self.select(["scripts/build_foo.py"])
        self.assertEqual(result, "ALL")

    def test_no_changes_selects_nothing(self):
        result, notes = self.select([])
        self.assertEqual(result, [])
        self.assertTrue(any("没有改动文件" in note for note in notes))

    # ---- CLI ----

    def test_cli_prints_module_per_line(self):
        self.write("scripts/build_foo.py")
        self.write("tests/test_build_foo.py", "import build_foo\n")
        stdin = sys.stdin
        stdout = sys.stdout
        try:
            sys.stdin = type("FakeStdin", (), {"read": lambda self: "scripts/build_foo.py\n"})()
            buf = []
            sys.stdout = type("FakeStdout", (), {"write": lambda self, s: buf.append(s)})()
            rc = sut.main(["--root", str(self.root)])
        finally:
            sys.stdin = stdin
            sys.stdout = stdout
        self.assertEqual(rc, 0)
        self.assertEqual("".join(buf).strip(), "tests.test_build_foo")


class ShardTest(unittest.TestCase):
    """`--shard I/N`：把选中列表（或全量）切成不重不漏的 N 片，供 CI 并行。"""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "tests").mkdir()
        (self.root / "scripts").mkdir()

    def write(self, rel: str, text: str = "") -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_round_robin_partitions_without_overlap(self):
        items = [f"tests.test_{name}" for name in "abcde"]
        parts = [sut.shard(items, f"{i}/2") for i in (1, 2)]
        self.assertEqual(
            parts,
            [["tests.test_a", "tests.test_c", "tests.test_e"], ["tests.test_b", "tests.test_d"]],
        )
        self.assertEqual(sorted(sum(parts, [])), sorted(items))

    def test_all_expands_full_test_dir(self):
        for name in "bdac":
            self.write(f"tests/test_{name}.py", "x = 1\n")
        self.write("tests/groom_fixtures.py", "x = 1\n")   # 非 test_*.py 不进全量
        parts = []
        for shard_id in (1, 2):
            rc, out, err = self.run_main(
                ["--root", str(self.root), "--all", "--shard", f"{shard_id}/2"]
            )
            self.assertEqual(rc, 0, err)
            parts.extend(out.splitlines())
        self.assertEqual(parts, ["tests.test_a", "tests.test_c", "tests.test_b", "tests.test_d"])

    def test_shard_does_not_pull_in_unselected_modules(self):
        self.write("scripts/build.py", "x = 1\n")
        self.write("scripts/other.py", "x = 1\n")
        for name in "abcd":
            self.write(f"tests/test_{name}.py", "import other\n")
        self.write("tests/test_a.py", "import build\n")
        self.write("tests/test_c.py", "import build\n")
        rc, out, err = self.run_main(
            ["--root", str(self.root), "--shard", "1/1"], stdin_text="scripts/build.py\n"
        )
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.splitlines(), ["tests.test_a", "tests.test_c"])

    def test_empty_shard_prints_nothing(self):
        self.write("tests/test_a.py", "x = 1\n")
        rc, out, err = self.run_main(["--root", str(self.root), "--all", "--shard", "2/2"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "")

    def test_invalid_or_out_of_range_shard_is_usage_error(self):
        for spec in ("2", "", "0/2", "3/2", "a/b"):
            with self.subTest(spec=spec):
                rc, out, err = self.run_main(["--root", str(self.root), "--all", "--shard", spec])
                self.assertEqual(rc, 2)
                self.assertEqual(out, "")
                self.assertIn("--shard", err)

    def test_all_matches_discover_pattern_not_only_test_underscore(self):
        """discover 默认 pattern 是 test*.py；testfoo.py 也要进全量，不能静默漏掉。"""
        self.write("tests/testfoo.py", "x = 1\n")
        rc, out, err = self.run_main(["--root", str(self.root), "--all", "--shard", "1/1"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out.splitlines(), ["tests.testfoo"])

    def test_main_pins_lf_on_stdout_for_machine_consumers(self):
        """Windows 上 Python 文本 stdout 会把 \n 翻成 \r\n，模块名会被 CI 读成带 \r。

        用 `TextIOWrapper(newline="\\r\\n")` 模拟那个翻译；断言输出字节里没有 `\r`。
        只断言「调用过 reconfigure」抓不住「调用位置在 print 之后」这类回退。
        """
        self.write("tests/test_a.py", "x = 1\n")
        import contextlib
        import io

        raw = io.BytesIO()
        fake = io.TextIOWrapper(raw, encoding="utf-8", newline="\r\n")
        err = io.StringIO()
        stdin = sys.stdin
        try:
            sys.stdin = type("FakeStdin", (), {"read": lambda self: ""})()
            with contextlib.redirect_stdout(fake), contextlib.redirect_stderr(err):
                rc = sut.main(["--root", str(self.root), "--all", "--shard", "1/1"])
        finally:
            sys.stdin = stdin
            fake.flush()
        self.assertEqual(rc, 0, err.getvalue())
        self.assertEqual(raw.getvalue(), b"tests.test_a\n")

    def run_main(self, argv, stdin_text=""):
        import contextlib
        import io

        out, err = io.StringIO(), io.StringIO()
        stdin = sys.stdin
        try:
            sys.stdin = type("FakeStdin", (), {"read": lambda self: stdin_text})()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = sut.main(argv)
        finally:
            sys.stdin = stdin
        return rc, out.getvalue().strip(), err.getvalue()


if __name__ == "__main__":
    unittest.main()
