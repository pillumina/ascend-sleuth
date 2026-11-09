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


def git(cwd, *args):
    proc = subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", *args],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败：{proc.stderr}")
    return (proc.stdout or "").strip()


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


def sync_result(**overrides):
    base = {
        "ok": True, "remote": "origin", "branch": "main",
        "local_rev": "aaa1111", "remote_rev": "bbb2222",
        "behind": 0, "ahead": 0,
        "surface": {"knowledge": 0, "routing": 0, "reference": 0, "methodology": 0,
                    "panel": 0, "other": 0},
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

    def test_kb_fields_marks_broken_config_without_changing_state(self):
        fields = trace_begin.kb_fields(sync_result(
            config_error="读不出 /repo/.local/settings.json：Expecting value"))
        self.assertEqual(fields["kb_sync_reason"], "config-broken")
        self.assertEqual(fields["kb_sync_state"], "ok")

    def test_kb_fields_keeps_the_sync_reason_when_config_is_readable(self):
        fields = trace_begin.kb_fields(sync_result(reason="dirty"))
        self.assertEqual(fields["kb_sync_reason"], "dirty")

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
    KNOWLEDGE_SURFACE = {"knowledge": 1, "routing": 0, "reference": 0,
                         "methodology": 0, "other": 0}

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
            behind=2, reason="dirty", local_rev="aaa1111",
            surface=self.KNOWLEDGE_SURFACE))
        self.assertIn("知识库落后 2 个提交（工作区有未提交改动）", text)
        self.assertIn("本单按 aaa1111 诊断", text)
        self.assertIn("git merge --ff-only origin/main", text)

    def test_behind_hint_is_silent_when_only_other_surface_changed(self):
        # 只改 docs/ 等 other 面：不影响本次诊断读的候选与路由，不打扰开单人。
        result = sync_result(behind=2, reason="dirty", surface={"other": 3})
        self.assertEqual(trace_begin.sync_hint(result), "")

    def test_behind_hint_fires_for_every_knowledge_surface(self):
        for key in trace_begin.HINT_SURFACES:
            with self.subTest(surface=key):
                text = trace_begin.sync_hint(sync_result(
                    behind=1, reason="dirty", surface={key: 1}))
                self.assertIn("知识库落后 1 个提交", text)

    def test_dirty_hint_offers_commit_or_stash(self):
        text = trace_begin.sync_hint(sync_result(
            behind=1, reason="dirty", surface=self.KNOWLEDGE_SURFACE))
        self.assertIn("先提交或 git stash", text)

    def test_non_dirty_hints_do_not_offer_stash(self):
        cases = {
            "branch-mismatch": "当前不在配置分支 main",
            "worktree": "当前检出是链接 worktree",
            "not-ancestor": "当前分支不是 origin/main 的祖先",
        }
        for reason, expected in cases.items():
            with self.subTest(reason=reason):
                text = trace_begin.sync_hint(sync_result(
                    behind=1, reason=reason, surface=self.KNOWLEDGE_SURFACE))
                self.assertIn(expected, text)
                self.assertNotIn("stash", text)

    def test_identity_hints_point_to_identity_setting(self):
        cases = {
            "same-repo": "同步源与归属仓不同源",
            "identity-unresolved": "归属仓解析不到",
        }
        for reason, expected in cases.items():
            with self.subTest(reason=reason):
                text = trace_begin.sync_hint(sync_result(
                    behind=1, reason=reason, surface=self.KNOWLEDGE_SURFACE))
                self.assertIn(expected, text)
                self.assertIn("设为归属仓", text)

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

    def test_broken_config_prints_one_line_and_marks_the_reason(self):
        result = sync_result(
            config_error="读不出 /repo/.local/settings.json：Expecting value")
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(trace_begin, "sync_of", return_value=result):
                code, out, _ = self.run_main(
                    "--slug", "2026-11-04-cfg", "--repo", td)
            self.assertEqual(code, 0)
            lines = [line for line in out.splitlines() if "知识库配置读不出" in line]
            self.assertEqual(len(lines), 1)
            self.assertIn("按默认值同步", lines[0])
            self.assertIn("Expecting value", lines[0])
            text = (Path(td) / "traces" / "2026-11-04-cfg.yaml").read_text(encoding="utf-8")
            self.assertIn('kb_sync_reason: "config-broken"', text)

    def test_unwritable_traces_exits_before_sync(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "traces").write_text("not a dir\n", encoding="utf-8")
            with mock.patch.object(trace_begin, "sync_of") as sync_mock:
                code, _out, err = self.run_main(
                    "--slug", "2026-11-04-fail", "--repo", td)
            self.assertEqual(code, 2)
            sync_mock.assert_not_called()
            self.assertIn("traces", err)


class LocalRepoHintTest(unittest.TestCase):
    """用本地裸仓跑真实 sync：不联网，验证 surface 与下一步命令来自真实结果。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="trace-begin-repo-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "knowledge").mkdir()
        (self.repo / "knowledge" / "base.yaml").write_text("cases: []\n", encoding="utf-8")
        (self.repo / "README.md").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "init")
        self.bare = self.base / "origin.git"
        git(self.base, "init", "--bare", "-q", str(self.bare))
        git(self.repo, "remote", "add", "origin", str(self.bare))
        git(self.repo, "push", "-q", "-u", "origin", "main")
        settings = self.repo / ".local" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(
            '{"schema": "ascend-sleuth-settings/1", "sync": '
            '{"remote": "origin", "branch": "main", "enabled": true, "auto_merge": true}}',
            encoding="utf-8")

    def upstream(self, rel: str, body: str):
        other = self.base / "other"
        if not other.exists():
            git(self.base, "clone", "-q", "-b", "main", str(self.bare), str(other))
        path = other / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        git(other, "add", "-A")
        git(other, "commit", "-qm", "upstream")
        git(other, "push", "-q", "origin", "main")

    def run_main(self, slug: str):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.argv", ["trace_begin.py", "--slug", slug,
                                     "--repo", str(self.repo)]), \
                mock.patch.object(trace_begin, "harness_session_of",
                                  return_value=("session-abc", "")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = trace_begin.main()
        return code, out.getvalue(), err.getvalue()

    def test_docs_only_surface_does_not_print_a_behind_hint(self):
        self.upstream("docs/note.md", "note\n")
        (self.repo / "README.md").write_text("dirty\n", encoding="utf-8")
        code, out, _ = self.run_main("2026-11-04-noise")
        self.assertEqual(code, 0)
        self.assertNotIn("知识库落后", out)

    def test_branch_mismatch_hint_names_the_branch_and_does_not_offer_stash(self):
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.upstream("knowledge/a.yaml", "cases: []\n")
        code, out, _ = self.run_main("2026-11-04-brhint")
        self.assertEqual(code, 0)
        self.assertIn("知识库落后 1 个提交", out)
        self.assertIn("当前不在配置分支 main", out)
        self.assertNotIn("stash", out)

    def test_merge_with_panel_changes_says_to_restart_dsh(self):
        self.upstream("dsh-plugins/dsh-sleuth-panels/package.json", "{}\n")
        code, out, _ = self.run_main("2026-11-04-panel")
        self.assertEqual(code, 0)
        self.assertIn("面板代码也更新了", out)
        self.assertIn("重启 DSH", out)


if __name__ == "__main__":
    unittest.main()
