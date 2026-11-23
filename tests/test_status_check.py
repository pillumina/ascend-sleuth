"""status_check：把 status.md 的确认方式解析成可执行检查。"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import status_check  # noqa: E402

TABLE = """\
| 机制 | 定义在哪 | 现状 | 确认方式 |
|---|---|---|---|
| 甲 | x.md 1 | 已落地 | `python3 scripts/a.py --help`；`ls scripts/a.py` |
| 乙 | y.md 2 | 已落地 | `node scripts/b.js --check` |
| 丙 | z.md 3 | 已落地 | `ls scripts/c.py` |
| 丁 | w.md 4 | 蓝图 | `node scripts/d.js --check` |
| 戊 | v.md 5 | 已落地 | `python3 scripts/e.py <卡号>` |
"""


class ParseTest(unittest.TestCase):
    def test_commands_and_skips_are_split(self):
        checks = {c.mechanism: c for c in status_check.parse_checks(TABLE)}
        self.assertEqual(list(checks), ["甲", "乙", "丙", "丁", "戊"])
        self.assertEqual(checks["甲"].commands, ("python3 scripts/a.py --help",))
        self.assertEqual(checks["甲"].skipped, ("ls scripts/a.py",))
        self.assertEqual(checks["乙"].commands, ("node scripts/b.js --check",))
        self.assertEqual(checks["丙"].commands, ())
        self.assertEqual(checks["丙"].skipped, ("ls scripts/c.py",))
        # 蓝图行与含占位符的命令不作为可执行项。
        self.assertEqual(checks["丁"].commands, ())
        self.assertEqual(checks["丁"].skipped, ("node scripts/d.js --check",))
        self.assertEqual(checks["戊"].commands, ())
        self.assertEqual(checks["戊"].skipped, ("python3 scripts/e.py <卡号>",))

    def test_header_and_separator_are_ignored(self):
        self.assertEqual(len(status_check.parse_checks("| 机制 | a | b | c |\n|--|--|--|--|\n")), 0)


class RunTest(unittest.TestCase):
    def test_runner_receives_python_as_current_interpreter(self):
        checks = status_check.parse_checks(TABLE)
        calls = []

        def runner(argv, cwd, timeout):
            calls.append((argv, cwd, timeout))
            return 0

        results = status_check.run_checks(checks, Path("/tmp"), runner=runner, timeout=7)
        self.assertEqual(len(results), 2)
        self.assertEqual(calls[0][0][0], sys.executable)
        self.assertEqual(calls[0][0][1:], ["scripts/a.py", "--help"])
        self.assertEqual(calls[0][2], 7)
        self.assertTrue(all(row["ok"] for row in results))

    def test_failure_and_only_filter(self):
        checks = status_check.parse_checks(TABLE)

        def runner(argv, cwd, timeout):
            return 0 if any("a.py" in part for part in argv) else 3

        results = status_check.run_checks(checks, Path("/tmp"), runner=runner, only="乙")
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertEqual(results[0]["exit"], 3)


class SkillProbeTest(unittest.TestCase):
    def _root(self, td, body):
        root = Path(td)
        (root / "skills" / "demo").mkdir(parents=True)
        (root / "skills" / "demo" / "SKILL.md").write_text(body, encoding="utf-8")
        return root

    def test_valid_skill_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, "---\nname: demo\ndescription: 演示 skill\n---\n\n正文\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = status_check.main(["--root", str(root), "--skill", "demo"])
            self.assertEqual(code, 0, out.getvalue())

    def test_missing_frontmatter_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, "正文\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = status_check.main(["--root", str(root), "--skill", "demo"])
            self.assertEqual(code, 1)
            self.assertIn("frontmatter", out.getvalue())


if __name__ == "__main__":
    unittest.main()
