"""check_test_portability 的规则、豁免与退出码自检。

为什么单测：检查器本身是 CI 的硬门，规则一旦漏判，PR 会放行只在 Windows 上失败的用例；
误判则挡下本来正确的写法，维护者只能用豁免注释逐条绕开。两种错误都要用合成源码钉住。
夹具全部写在内存里的源码字符串，不落盘、不联网、不依赖本机平台。

覆盖边界同脚本头注：R1、R2 只看有没有 encoding；R3 只认字面量与命令位置；
R5 只在 read_bytes() 的同一表达式里判；R6 只认字面量导入与 os.<函数> 调用。
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_test_portability as ctp  # noqa: E402

SAMPLE = "tests/sample.py"


def scan(source):
    return ctp.scan_source(SAMPLE, source)


def codes(source):
    return [(violation.line, violation.code) for violation in scan(source)]


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ctp.main(argv)
    return code, out.getvalue(), err.getvalue()


class R1TextIoTest(unittest.TestCase):
    def test_text_io_without_encoding_is_reported(self):
        for source in (
            'open("a.txt")',
            'open("a.txt", "w")',
            'io.open("a.txt", "r")',
            'Path("a.txt").read_text()',
            'Path("a.txt").write_text("x")',
            'open("a.txt", encoding=None)',
        ):
            with self.subTest(source=source):
                self.assertEqual([(1, "R1")], codes(source))

    def test_binary_and_pinned_encoding_are_clean(self):
        for source in (
            'open("a.bin", "rb")',
            'open("a.bin", "wb")',
            'open("a.txt", encoding="utf-8")',
            'Path("a.txt").read_text(encoding="utf-8")',
            'Path("a.txt").write_text("x", encoding="utf-8")',
            'open(path, mode)',
            'os.open("a.txt", os.O_RDONLY)',
        ):
            with self.subTest(source=source):
                self.assertEqual([], codes(source))

    def test_fixture_string_contents_are_not_scanned(self):
        source = (
            'TEXT = """\n'
            'open("a.txt")\n'
            'subprocess.run(["python3", "scripts/x.py"], text=True)\n'
            '"""\n'
        )
        self.assertEqual([], codes(source))


class R2SubprocessTextModeTest(unittest.TestCase):
    def test_text_mode_without_encoding_is_reported(self):
        for source in (
            'subprocess.run(["git", "status"], text=True)',
            'subprocess.run(["git", "status"], universal_newlines=True)',
            'subprocess.Popen(["git", "status"], text=True)',
            'subprocess.run(["git"], text=True, encoding=None)',
        ):
            with self.subTest(source=source):
                self.assertEqual([(1, "R2")], codes(source))

    def test_multiline_call_with_encoding_is_clean(self):
        source = (
            "subprocess.run(\n"
            '    ["git", "status"],\n'
            "    text=True,\n"
            '    encoding="utf-8",\n'
            ")\n"
        )
        self.assertEqual([], codes(source))

    def test_multiline_call_without_encoding_reports_first_line(self):
        source = (
            "subprocess.run(\n"
            '    ["git", "status"],\n'
            "    text=True,\n"
            ")\n"
        )
        self.assertEqual([(1, "R2")], codes(source))

    def test_non_literal_text_flag_is_not_judged(self):
        self.assertEqual([], codes("subprocess.run([\"git\"], text=text_mode)"))


class R3InterpreterLiteralTest(unittest.TestCase):
    def test_literal_interpreters_are_reported(self):
        for source in (
            'subprocess.run(["python", "scripts/x.py"])',
            'subprocess.run(["python3", "scripts/x.py"])',
            'subprocess.run(["py", "scripts/x.py"])',
            'subprocess.run(["python.exe", "scripts/x.py"])',
        ):
            with self.subTest(source=source):
                self.assertEqual([(1, "R3")], codes(source))

    def test_wrapped_and_variable_argv_are_reported(self):
        cases = (
            'sh(repo, "python3", *args)',
            'cmd = ["python3", "scripts/x.py"]',
        )
        for source in cases:
            with self.subTest(source=source):
                self.assertEqual([(1, "R3")], codes(source))

    def test_absolute_interpreter_path_is_reported(self):
        source = r'subprocess.run(["C:\\Python39\\python.exe", "scripts/x.py"])'
        self.assertEqual([(1, "R3")], codes(source))

    def test_sys_executable_and_data_strings_are_clean(self):
        for source in (
            'subprocess.run([sys.executable, "scripts/x.py"])',
            'subprocess.run(["echo", "python3"])',
            'cmd = ["git", "status"]',
            'self.assertIn("python3", output)',
            'name = "python3"',
            'subprocess.run("python3 scripts/x.py", shell=True)',
        ):
            with self.subTest(source=source):
                self.assertEqual([], codes(source))


class R4PathPrefixTest(unittest.TestCase):
    def test_slash_literal_prefix_is_reported(self):
        for source in (
            'self.assertTrue(line.endswith("/v1.0"))',
            'self.assertTrue(line.startswith("/tmp"))',
        ):
            with self.subTest(source=source):
                self.assertEqual([(1, "R4")], codes(source))

    def test_portable_prefix_forms_are_clean(self):
        for source in (
            'self.assertTrue(line.endswith("v1.0"))',
            r'self.assertTrue(line.startswith("\\"))',
            'self.assertTrue(line.startswith(("/", "\\\\")))',
            'self.assertTrue(line.endswith(os.sep))',
            'self.assertTrue(line.endswith(name))',
        ):
            with self.subTest(source=source):
                self.assertEqual([], codes(source))


class R5ByteNewlineTest(unittest.TestCase):
    def test_read_bytes_then_crlf_replace_is_reported(self):
        source = r'path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))'
        self.assertEqual([(1, "R5")], codes(source))

    def test_normalized_chain_is_clean(self):
        source = (
            r'path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n")'
            r'.replace(b"\n", b"\r\n"))'
        )
        self.assertEqual([], codes(source))

    def test_separate_normalization_step_is_clean(self):
        source = (
            r'raw = path.read_bytes().replace(b"\r\n", b"\n")' "\n"
            r'path.write_bytes(raw.replace(b"\n", b"\r\n"))' "\n"
        )
        self.assertEqual([], codes(source))

    def test_replace_without_read_bytes_is_clean(self):
        for source in (
            r'payload.replace(b"\n", b"\r\n")',
            r'path.write_bytes(b"a\r\nb")',
        ):
            with self.subTest(source=source):
                self.assertEqual([], codes(source))


class R6PlatformApiTest(unittest.TestCase):
    def test_platform_imports_are_reported(self):
        for module in ("fcntl", "pwd", "grp", "termios", "posix", "msvcrt", "winreg"):
            with self.subTest(module=module):
                self.assertEqual([(1, "R6")], codes(f"import {module}"))

    def test_from_import_is_reported(self):
        self.assertEqual([(1, "R6")], codes("from pwd import getpwuid"))

    def test_platform_calls_are_reported(self):
        for call in ("os.fork()", "os.symlink(a, b)", "os.chmod(path, 0o644)"):
            with self.subTest(call=call):
                self.assertEqual([(2, "R6")], codes(f"import os\n{call}"))

    def test_other_os_calls_are_clean(self):
        for source in ("import os\nos.remove(path)", "import os", "import pathlib"):
            with self.subTest(source=source):
                self.assertEqual([], codes(source))

    def test_skip_decorator_covers_enclosing_function(self):
        source = (
            "import unittest\n"
            '@unittest.skipUnless(os.name == "posix", "fcntl 只在 POSIX 可用")\n'
            "def test_lock():\n"
            "    import fcntl\n"
        )
        self.assertEqual([], codes(source))

    def test_skip_decorator_on_class_covers_methods(self):
        source = (
            "import unittest\n"
            '@unittest.skipUnless(os.name == "posix", "POSIX 文件锁")\n'
            "class LockTest(unittest.TestCase):\n"
            "    def test_lock(self):\n"
            "        import fcntl\n"
        )
        self.assertEqual([], codes(source))

    def test_platform_branch_covers_import_and_call(self):
        for source in (
            'import os\nif os.name == "nt":\n    import winreg\n',
            'import os\nif os.name == "posix":\n    os.fork()\n',
            'import sys\nif sys.platform.startswith("win"):\n    import msvcrt\n',
        ):
            with self.subTest(source=source):
                self.assertEqual([], codes(source))

    def test_skip_is_scoped_to_the_decorated_function(self):
        source = (
            "import unittest\n"
            '@unittest.skip("暂不跑")\n'
            "def test_other():\n"
            "    pass\n"
            "import pwd\n"
        )
        self.assertEqual([(5, "R6")], codes(source))

    def test_try_import_fallback_is_still_reported(self):
        source = "try:\n    import fcntl\nexcept ImportError:\n    fcntl = None\n"
        self.assertEqual([(2, "R6")], codes(source))


class ExemptionTest(unittest.TestCase):
    def test_valid_inline_exemption_suppresses_violation(self):
        source = 'open("a.txt")  # portability-check: allow 该文件固定是 ASCII 配置'
        self.assertEqual([], codes(source))

    def test_empty_reason_is_not_an_exemption(self):
        for source in (
            'open("a.txt")  # portability-check: allow',
            'open("a.txt")  # portability-check: allow   ',
        ):
            with self.subTest(source=source):
                self.assertEqual([(1, "R1")], codes(source))

    def test_marker_in_string_is_not_an_exemption(self):
        source = 'open("a.txt"); note = "# portability-check: allow 这不是注释"'
        self.assertEqual([(1, "R1")], codes(source))

    def test_marker_on_previous_line_does_not_apply(self):
        source = (
            "# portability-check: allow 上一行的豁免不生效\n"
            'open("a.txt")\n'
        )
        self.assertEqual([(2, "R1")], codes(source))

    def test_exemption_on_multiline_call_first_line_applies(self):
        source = (
            "subprocess.run(  # portability-check: allow 输出只有 ASCII\n"
            '    ["git", "status"],\n'
            "    text=True,\n"
            ")\n"
        )
        self.assertEqual([], codes(source))

    def test_exemption_covers_platform_api(self):
        source = "import fcntl  # portability-check: allow POSIX 文件锁由被测脚本自己处理"
        self.assertEqual([], codes(source))

    def test_exemption_applies_per_rule_and_line(self):
        source = (
            'open("a.txt")  # portability-check: allow 该文件固定是 ASCII 配置\n'
            'Path("b.txt").read_text()\n'
        )
        self.assertEqual([(2, "R1")], codes(source))


class OutputContractTest(unittest.TestCase):
    def test_violation_format_and_rule_codes(self):
        violation = scan('Path("a.txt").read_text()')[0]
        text = violation.format()
        self.assertTrue(text.startswith("tests/sample.py:1: [R1] "))
        self.assertIn("；修法：", text)
        self.assertEqual("tests/sample.py", violation.path)

    def test_violations_sorted_by_line_then_rule(self):
        source = 'import fcntl\nopen("a.txt")\n'
        self.assertEqual([(1, "R6"), (2, "R1")], codes(source))

    def test_scan_source_rejects_syntax_errors(self):
        with self.assertRaises(ctp.ScanError):
            scan("def broken(:")


class CliTest(unittest.TestCase):
    def make_repo(self):
        tmp = tempfile.TemporaryDirectory(prefix="check-test-portability-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "tests").mkdir()
        return root

    def write_fixture(self, root, name, source):
        path = root / "tests" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def test_clean_tree_returns_zero(self):
        root = self.make_repo()
        self.write_fixture(root, "test_ok.py", 'Path("a.txt").read_text(encoding="utf-8")\n')
        code, out, _ = run_main(["--root", str(root)])
        self.assertEqual(0, code)
        self.assertIn("未发现可移植性违规", out)

    def test_violation_returns_one(self):
        root = self.make_repo()
        self.write_fixture(root, "test_bad.py", 'open("a.txt")\n')
        code, out, err = run_main(["--root", str(root)])
        self.assertEqual(1, code)
        self.assertIn("tests/test_bad.py:1: [R1] ", out)
        self.assertIn("；修法：", out)
        self.assertIn("1 处违规", err)

    def test_scan_tree_is_deterministic_across_files(self):
        root = self.make_repo()
        self.write_fixture(root, "test_b.py", 'open("b.txt")\n')
        self.write_fixture(root, "test_a.py", 'open("a.txt")\n')
        self.write_fixture(root, "test_nested/test_c.py", 'import fcntl\n')
        first = [(v.path, v.line, v.code) for v in ctp.scan_tree(root)]
        second = [(v.path, v.line, v.code) for v in ctp.scan_tree(root)]
        self.assertEqual(first, second)
        self.assertEqual(
            [
                ("tests/test_a.py", 1, "R1"),
                ("tests/test_b.py", 1, "R1"),
                ("tests/test_nested/test_c.py", 1, "R6"),
            ],
            first,
        )

    def test_scan_tree_ignores_non_python_files(self):
        root = self.make_repo()
        (root / "tests" / "notes.txt").write_text('open("a.txt")\n', encoding="utf-8")
        self.write_fixture(root, "test_ok.py", "x = 1\n")
        self.assertEqual([], ctp.scan_tree(root))

    def test_missing_tests_directory_returns_two(self):
        tmp = tempfile.TemporaryDirectory(prefix="check-test-portability-")
        self.addCleanup(tmp.cleanup)
        code, _, err = run_main(["--root", str(Path(tmp.name))])
        self.assertEqual(2, code)
        self.assertIn("扫描失败", err)

    def test_missing_root_returns_two(self):
        code, _, err = run_main(["--root", str(ROOT / "no-such-dir")])
        self.assertEqual(2, code)
        self.assertIn("扫描失败", err)

    def test_syntax_error_returns_two(self):
        root = self.make_repo()
        self.write_fixture(root, "test_broken.py", "def broken(:\n")
        code, _, err = run_main(["--root", str(root)])
        self.assertEqual(2, code)
        self.assertIn("扫描失败", err)

    def test_non_utf8_file_returns_two(self):
        root = self.make_repo()
        (root / "tests" / "test_gbk.py").write_bytes(b'# \xff\xfe\nx = 1\n')
        code, _, err = run_main(["--root", str(root)])
        self.assertEqual(2, code)
        self.assertIn("扫描失败", err)

    def test_empty_tests_directory_returns_two(self):
        root = self.make_repo()
        code, _, err = run_main(["--root", str(root)])
        self.assertEqual(2, code)
        self.assertIn("没有 .py 文件", err)


class ThisFileTest(unittest.TestCase):
    def test_this_test_file_is_clean(self):
        path = Path(__file__).resolve()
        source = path.read_text(encoding="utf-8")
        violations = ctp.scan_source("tests/test_check_test_portability.py", source)
        self.assertEqual([], [violation.format() for violation in violations])


if __name__ == "__main__":
    unittest.main()
