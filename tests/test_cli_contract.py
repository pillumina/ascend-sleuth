# -*- coding: utf-8 -*-
"""命令行公共层：退出码归一与 JSON 输出。"""

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
