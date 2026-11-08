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


if __name__ == "__main__":
    unittest.main()
