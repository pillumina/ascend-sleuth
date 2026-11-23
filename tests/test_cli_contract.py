# -*- coding: utf-8 -*-
"""命令行公共层：退出码归一与 JSON 输出。"""

import ast
import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import _cli  # noqa: E402


class MainEntryTest(unittest.TestCase):
    def test_return_value_becomes_exit_code(self):
        self.assertEqual(_cli.main_entry(lambda: 7), 7)
        self.assertEqual(_cli.main_entry(lambda: None), 0)

    def test_system_exit_is_normalized(self):
        def stop():
            raise SystemExit(2)
        self.assertEqual(_cli.main_entry(stop), 2)

    def test_system_exit_string_prints_and_returns_one(self):
        def stop():
            raise SystemExit("bad")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(_cli.main_entry(stop), _cli.EXIT_FINDINGS)
        self.assertIn("bad", err.getvalue())

    def test_broken_pipe_is_success(self):
        def closed():
            raise BrokenPipeError()
        self.assertEqual(_cli.main_entry(closed), _cli.EXIT_OK)

    def test_keyboard_interrupt_is_130(self):
        def interrupted():
            raise KeyboardInterrupt()
        self.assertEqual(_cli.main_entry(interrupted), 130)


class OutputTest(unittest.TestCase):
    def test_emit_is_utf8_json(self):
        out = io.StringIO()
        with redirect_stdout(out):
            _cli.emit({"title": "中文", "ok": True})
        self.assertEqual(json.loads(out.getvalue()), {"title": "中文", "ok": True})

    def test_fail_returns_code_and_writes_stderr(self):
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(_cli.fail("bad input", _cli.EXIT_USAGE), 2)
        self.assertIn("bad input", err.getvalue())


if __name__ == "__main__":
    unittest.main()


class EntryConsistencyTest(unittest.TestCase):
    """入口统一走 _cli.main_entry：钉 stdio、归一退出码的行为不靠自觉。

    扫描范围是 ``scripts/*.py``（顶层入口）。``scripts/fixtures/`` 是夹具构造脚本，
    不作为独立入口；``scripts/_stdio.py`` 只在注释里提到 ``__main__``。
    """

    @staticmethod
    def _guards(tree):
        for node in tree.body:
            if isinstance(node, ast.If):
                dumped = ast.dump(node.test)
                if "__name__" in dumped and "__main__" in dumped:
                    yield node

    @staticmethod
    def _wraps_main_entry(guard):
        for statement in guard.body:
            if not isinstance(statement, ast.Raise):
                continue
            exc = statement.exc
            if not (isinstance(exc, ast.Call) and getattr(exc.func, "id", "") == "SystemExit"):
                continue
            if not exc.args:
                continue
            inner = exc.args[0]
            if isinstance(inner, ast.Call) and getattr(inner.func, "id", "") == "main_entry":
                return True
        return False

    def test_every_entry_raises_through_main_entry(self):
        offenders = []
        for path in sorted((ROOT / "scripts").glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "__main__" not in text:
                continue
            tree = ast.parse(text, filename=str(path))
            guards = list(self._guards(tree))
            if not guards:
                if path.name != "_stdio.py":
                    offenders.append(f"{path.name}: no __main__ guard")
                continue
            for guard in guards:
                if not self._wraps_main_entry(guard):
                    offenders.append(f"{path.name}:{guard.lineno}: main() not wrapped by main_entry")
                elif len(guard.body) != 1:
                    offenders.append(
                        f"{path.name}:{guard.lineno}: __main__ block must be exactly one statement")
        self.assertEqual(offenders, [])
