"""trace_begin.py 的约定：派生字段机器填、取不到就留空并说明、不覆盖已有轨迹。

为什么单独测它：`harness_session` 漏写会让面板与侧栏挂不到会话上，而这类错误在运行时不报错——
只能靠"建 header 这一步本身可靠"来挡。测的是三条契约，不是实现细节。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import trace_begin  # noqa: E402


class HarnessSessionTest(unittest.TestCase):
    def test_takes_the_env_value(self):
        sid, why = trace_begin.harness_session_of({"DSH_SESSION_ID": "session-abc"})
        self.assertEqual(sid, "session-abc")
        self.assertEqual(why, "")

    def test_absent_env_leaves_it_empty_and_says_why(self):
        sid, why = trace_begin.harness_session_of({})
        self.assertEqual(sid, "")
        self.assertIn("DSH_SESSION_ID", why)

    def test_wrong_shape_is_not_taken(self):
        # 不是 session-<uuid> 的值一律不收：猜一个号会把账单与面板记号挂到别的会话上
        sid, why = trace_begin.harness_session_of({"DSH_SESSION_ID": "2026-10-30-welink"})
        self.assertEqual(sid, "")
        self.assertIn("session-", why)


class HeaderTest(unittest.TestCase):
    def test_header_carries_derived_fields_and_empty_trace(self):
        text = trace_begin.build_header(
            slug="2026-10-30-demo", harness_session="session-abc",
            created_at="2026-10-30T10:00:00+08:00", kb_rev="deadbee",
        )
        self.assertIn('session_id: "2026-10-30-demo"', text)
        self.assertIn('harness_session: "session-abc"', text)
        self.assertIn('kb_rev: "deadbee"', text)
        self.assertIn('created_at: "2026-10-30T10:00:00+08:00"', text)
        self.assertIn("trace: []", text)

    def test_header_marks_dirty_working_tree(self):
        text = trace_begin.build_header(
            slug="2026-10-30-demo", harness_session="session-abc",
            created_at="2026-10-30T10:00:00+08:00", kb_rev="deadbee", kb_rev_dirty=True,
        )
        self.assertIn("kb_rev_dirty: true", text)
        clean = trace_begin.build_header(
            slug="2026-10-30-demo", harness_session="session-abc",
            created_at="2026-10-30T10:00:00+08:00", kb_rev="deadbee", kb_rev_dirty=False,
        )
        self.assertIn("kb_rev_dirty: false", clean)

    def test_header_marks_missing_session_rather_than_inventing_one(self):
        text = trace_begin.build_header(
            slug="2026-10-30-demo", harness_session="",
            created_at="2026-10-30T10:00:00+08:00", kb_rev="unknown",
        )
        self.assertIn('harness_session: ""', text)
        self.assertIn("缺！", text)


class CliTest(unittest.TestCase):
    def run_cli(self, *args, env=None):
        full_env = {"PATH": "/usr/bin:/bin"}
        if env:
            full_env.update(env)
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "trace_begin.py"), *args],
            capture_output=True, text=True, env=full_env, timeout=120,
        )

    def test_print_only_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            r = self.run_cli("--slug", "2026-10-30-demo", "--print-only", "--repo", td,
                             env={"DSH_SESSION_ID": "session-abc"})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('harness_session: "session-abc"', r.stdout)
            self.assertFalse((Path(td) / "traces").exists())

    def test_refuses_to_overwrite_an_existing_trace(self):
        with tempfile.TemporaryDirectory() as td:
            traces = Path(td) / "traces"
            traces.mkdir(parents=True)
            target = traces / "2026-10-30-demo.yaml"
            target.write_text("session_id: old\n", encoding="utf-8")
            r = self.run_cli("--slug", "2026-10-30-demo", "--repo", td)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(target.read_text(encoding="utf-8"), "session_id: old\n")

    def test_bad_slug_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            r = self.run_cli("--slug", "乱七八糟", "--repo", td)
            self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
