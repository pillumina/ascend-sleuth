"""trace_begin.py 的约定：派生字段机器填、取不到就留空并说明、不覆盖已有轨迹。

为什么单独测它：`harness_session` 漏写会让面板与侧栏挂不到会话上，而这类错误在运行时不报错——
只能靠"建 header 这一步本身可靠"来挡。测的是三条契约，不是实现细节。
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
            capture_output=True, text=True, encoding="utf-8", env=full_env, timeout=120,
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


def sync_result(**overrides):
    base = {
        "ok": True, "remote": "origin", "branch": "main",
        "local_rev": "aaa1111", "remote_rev": "bbb2222",
        "behind": 0, "ahead": 0,
        "surface": {"knowledge": 0, "routing": 0, "reference": 0, "methodology": 0, "other": 0},
        "merge": "none", "reason": "", "skipped": False, "offline": False,
        "config": "file", "same_repo": True,
        "local_rev_before": "aaa1111", "behind_before": "unknown",
        "last_ok_at": "", "attempted_at": "", "last_reason": "", "config_error": "",
    }
    base.update(overrides)
    return base


class SyncHeaderTest(unittest.TestCase):
    def test_header_carries_sync_fields_with_defaults(self):
        text = trace_begin.build_header(
            slug="2026-11-04-demo", harness_session="session-abc",
            created_at="2026-11-04T10:00:00+08:00", kb_rev="deadbee",
        )
        self.assertIn('kb_remote: ""', text)
        self.assertIn('kb_remote_rev: "unknown"', text)
        self.assertIn('kb_behind: "unknown"', text)
        self.assertIn('kb_sync: "off"', text)
        self.assertIn('kb_merge: "none"', text)

    def test_kb_fields_hides_stale_values_when_fetch_failed(self):
        fields = trace_begin.kb_fields(sync_result(
            ok=False, reason="timeout", remote_rev="bbb2222", behind=2))
        self.assertEqual(fields["kb_remote_rev"], "unknown")
        self.assertEqual(fields["kb_behind"], "unknown")
        self.assertEqual(fields["kb_sync_state"], "failed")

    def test_kb_fields_keeps_values_when_fetch_succeeded(self):
        fields = trace_begin.kb_fields(sync_result(
            ok=True, remote_rev="bbb2222", behind=2, reason="dirty"))
        self.assertEqual(fields["kb_remote_rev"], "bbb2222")
        self.assertEqual(fields["kb_behind"], 2)
        self.assertEqual(fields["kb_sync_state"], "ok")

    def test_header_writes_integer_behind_without_quotes(self):
        text = trace_begin.build_header(
            slug="2026-11-04-demo", harness_session="session-abc",
            created_at="2026-11-04T10:00:00+08:00", kb_rev="deadbee",
            kb_remote="origin/main", kb_remote_rev="aaa1111", kb_behind=3,
            kb_sync_state="ok", kb_merge="none",
        )
        self.assertIn('kb_remote: "origin/main"', text)
        self.assertIn("kb_behind: 3", text)
        self.assertIn('kb_sync: "ok"', text)


class SyncHintTest(unittest.TestCase):
    def test_merge_success(self):
        text = trace_begin.sync_hint(sync_result(
            merge="ff-only", local_rev="bbb2222", local_rev_before="aaa1111",
            behind=0, behind_before=2))
        self.assertEqual(
            text,
            "已同步知识库到 bbb2222（原 aaa1111，落后 2 个提交）。"
            "本会话的流程文件仍是旧版，下次会话生效。")

    def test_behind_without_merge(self):
        text = trace_begin.sync_hint(sync_result(
            behind=2, reason="dirty", local_rev="aaa1111"))
        self.assertIn("知识库落后 2 个提交（工作区有未提交改动）", text)
        self.assertIn("本单按 aaa1111 诊断", text)
        self.assertIn("git merge --ff-only origin/main", text)

    def test_fetch_failure(self):
        text = trace_begin.sync_hint(sync_result(
            ok=False, reason="timeout", local_rev="aaa1111", behind="unknown"))
        self.assertEqual(text, "无法确认知识库是否最新（fetch 超时），本单按 aaa1111 诊断。")

    def test_fetch_failure_exit_code_is_readable(self):
        text = trace_begin.sync_hint(sync_result(
            ok=False, reason="exit-128", local_rev="aaa1111", behind="unknown"))
        self.assertIn("fetch 退出码 128", text)

    def test_no_hint_when_up_to_date_skipped_or_off(self):
        self.assertEqual(trace_begin.sync_hint(sync_result(behind=0)), "")
        self.assertEqual(trace_begin.sync_hint(sync_result(
            ok=False, skipped=True, reason="timeout")), "")
        self.assertEqual(trace_begin.sync_hint(sync_result(
            ok=False, offline=True, reason="offline")), "")
        self.assertEqual(trace_begin.sync_hint(sync_result(
            ok=False, reason="no-sync")), "")


class SyncCliTest(unittest.TestCase):
    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.argv", ["trace_begin.py", *args]), \
                mock.patch.object(trace_begin, "harness_session_of",
                                  return_value=("session-abc", "")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = trace_begin.main()
        return code, out.getvalue(), err.getvalue()

    def test_no_sync_does_not_network(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(trace_begin.kb_sync, "sync",
                                   side_effect=AssertionError("--no-sync 不应 fetch")):
                code, out, _ = self.run_main(
                    "--slug", "2026-11-04-demo", "--repo", td, "--print-only", "--no-sync")
            self.assertEqual(code, 0)
            self.assertIn('kb_sync: "off"', out)
            # --print-only 优先于 --no-sync：两种都不联网，原因写更强的那个。
            self.assertIn('kb_sync_reason: "print-only"', out)

    def test_print_only_does_not_network_or_write(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(trace_begin.kb_sync, "sync",
                                   side_effect=AssertionError("--print-only 不应 fetch")):
                code, out, _ = self.run_main(
                    "--slug", "2026-11-04-demo", "--repo", td, "--print-only")
            self.assertEqual(code, 0)
            self.assertIn('kb_sync: "off"', out)
            self.assertIn('kb_sync_reason: "print-only"', out)
            self.assertFalse((Path(td) / "traces").exists())

    def test_same_name_check_runs_before_sync(self):
        with tempfile.TemporaryDirectory() as td:
            traces = Path(td) / "traces"
            traces.mkdir(parents=True)
            target = traces / "2026-11-04-demo.yaml"
            target.write_text("session_id: old\n", encoding="utf-8")
            with mock.patch.object(trace_begin, "sync_of") as sync_mock:
                code, _out, _err = self.run_main(
                    "--slug", "2026-11-04-demo", "--repo", td)
            self.assertEqual(code, 2)
            sync_mock.assert_not_called()
            self.assertEqual(target.read_text(encoding="utf-8"), "session_id: old\n")
            self.assertFalse((Path(td) / ".local").exists())

    def test_merge_hint_is_printed_once(self):
        result = sync_result(merge="ff-only", local_rev="bbb2222",
                             remote_rev="bbb2222", local_rev_before="aaa1111",
                             behind=0, behind_before=2)
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(trace_begin, "sync_of", return_value=result):
                code, out, _ = self.run_main(
                    "--slug", "2026-11-04-demo", "--repo", td)
            self.assertEqual(code, 0)
            self.assertIn(
                "已同步知识库到 bbb2222（原 aaa1111，落后 2 个提交）。"
                "本会话的流程文件仍是旧版，下次会话生效。", out)
