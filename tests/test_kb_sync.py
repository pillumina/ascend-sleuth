"""kb_sync 的口径测试：默认配置、fetch、落后计算、改动面、合并四条条件、降级与缓存。

为什么不联网：远端一律用本地裸仓。超时用 mock 掉 `run_git` 的 fetch 调用，避免依赖真实网络。
断言打在 JSON 结果字段上，不打私有实现。
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kb_sync  # noqa: E402


def git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", *args],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败：{proc.stderr}")
    return (proc.stdout or "").strip()


class RepoCase(unittest.TestCase):
    """一个本地仓库 + 一个本地裸仓（origin），两者用 git 远端连接。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="kb-sync-")
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

    def write_settings(self, sync=None, target=None):
        doc = {
            "schema": "ascend-sleuth-settings/1",
            "sync": {"remote": "origin", "branch": "main", "enabled": True, "auto_merge": True},
        }
        if sync:
            doc["sync"].update(sync)
        if target is not None:
            doc["target"] = target
        path = self.repo / ".local" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")

    def upstream(self, files: dict) -> str:
        """在另一个克隆里提交并推送，返回新提交的短 sha；本机 origin ref 保持旧值。"""
        other = self.base / "other"
        if not other.exists():
            git(self.base, "clone", "-q", "-b", "main", str(self.bare), str(other))
        for rel, body in files.items():
            path = other / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        git(other, "add", "-A")
        git(other, "commit", "-qm", "upstream")
        git(other, "push", "-q", "origin", "main")
        return git(other, "rev-parse", "--short", "HEAD")

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = kb_sync.main(["--root", str(self.repo), *args])
        return code, json.loads(out.getvalue())


class ConfiguredCase(RepoCase):
    """写入最小 settings：默认配置本身不再触发联网。"""

    def setUp(self):
        super().setUp()
        self.write_settings()


class ConfigTest(RepoCase):
    def test_missing_settings_uses_defaults(self):
        data, config, problem = kb_sync.load_settings(self.repo)
        self.assertEqual(config, "default")
        self.assertEqual(problem, "")
        self.assertEqual(data["sync"],
                         {"remote": "origin", "branch": "main",
                          "enabled": True, "auto_merge": True})
        self.assertIsNone(data["target"])

    def test_broken_settings_falls_back_without_raising(self):
        path = self.repo / ".local" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        data, config, problem = kb_sync.load_settings(self.repo)
        self.assertEqual(config, "default")
        self.assertIn("读不出", problem)
        self.assertEqual(data["sync"]["remote"], "origin")
        code, doc = self.run_cli("--show", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(doc["config"], "default")

    def test_missing_settings_syncs_with_defaults(self):
        real = kb_sync.run_git
        calls = []

        def spy(args, cwd, timeout):
            calls.append(list(args))
            return real(args, cwd, timeout)

        with mock.patch.object(kb_sync, "run_git", side_effect=spy):
            code, doc = self.run_cli("--sync", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(doc["config"], "default")
        self.assertEqual(doc["remote"], "origin")
        self.assertTrue(doc["ok"])
        self.assertTrue(any("fetch" in call for call in calls))

    def test_settings_are_read_from_main_checkout(self):
        # worktree 里读 settings 也要落到主检出那一份：这里只验证路径解析与文件位置。
        self.write_settings()
        self.assertEqual(kb_sync.settings_path(self.repo),
                         (self.repo / ".local" / "settings.json").resolve())


class FetchTest(ConfiguredCase):
    def test_fetch_success_and_behind(self):
        upstream = self.upstream({"knowledge/new.yaml": "cases: []\n"})
        code, doc = self.run_cli("--sync", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["reason"], "")
        self.assertEqual(doc["remote"], "origin")
        self.assertEqual(doc["branch"], "main")
        self.assertEqual(doc["remote_rev"], upstream)
        self.assertEqual(doc["behind"], 1)
        self.assertEqual(doc["ahead"], 0)
        self.assertEqual(doc["merge"], "none")
        self.assertEqual(doc["config"], "file")

    def test_ahead_counts_local_commits(self):
        (self.repo / "local.txt").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "local")
        code, doc = self.run_cli("--sync", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["behind"], 0)
        self.assertEqual(doc["ahead"], 1)

    def test_surface_classification(self):
        self.upstream({
            "knowledge/a.yaml": "cases: []\n",
            "triage-tree.d/interrupt.yaml": "natures: []\n",
            "triage-tree.yaml": "natures: []\n",
            "references/facts.yaml": "items: []\n",
            "skills/demo/SKILL.md": "# demo\n",
            "docs/note.md": "# note\n",
        })
        _code, doc = self.run_cli("--sync", "--json")
        self.assertEqual(doc["surface"], {"knowledge": 1, "routing": 2, "reference": 1,
                                          "methodology": 1, "other": 1})

    def test_timeout_degrades_to_zero_exit(self):
        self.upstream({"knowledge/a.yaml": "cases: []\n"})
        real = kb_sync.run_git

        def fake(args, cwd, timeout):
            if "fetch" in args:
                raise subprocess.TimeoutExpired("git", timeout)
            return real(args, cwd, timeout)

        with mock.patch.object(kb_sync, "run_git", side_effect=fake):
            code, doc = self.run_cli("--sync", "--json")
        self.assertEqual(code, 0)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["reason"], "timeout")
        self.assertFalse(doc["skipped"])
        state = json.loads((self.repo / ".local" / "kb-sync-state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["reason"], "timeout")
        self.assertTrue(state["attempted_at"])

    def test_no_remote_degrades(self):
        git(self.repo, "remote", "remove", "origin")
        code, doc = self.run_cli("--sync", "--json")
        self.assertEqual(code, 0)
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["reason"], "no-remote")

    def test_failure_cache_skips_within_ten_minutes(self):
        state = {"schema": "ascend-sleuth-kb-sync-state/1", "last_ok_at": "",
                 "attempted_at": kb_sync.now_iso(), "reason": "timeout",
                 "remote": "origin", "branch": "main"}
        path = self.repo / ".local" / "kb-sync-state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
        real = kb_sync.run_git
        calls = []

        def spy(args, cwd, timeout):
            calls.append(list(args))
            if "fetch" in args:
                raise AssertionError("10 分钟内不应再 fetch")
            return real(args, cwd, timeout)

        with mock.patch.object(kb_sync, "run_git", side_effect=spy):
            code, doc = self.run_cli("--sync", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(doc["skipped"])
        self.assertEqual(doc["reason"], "timeout")
        self.assertFalse(any("fetch" in call for call in calls))

    def test_offline_declaration_does_not_fetch(self):
        (self.repo / "deployment.yaml").write_text(
            'evolution:\n  mode: "full"\nsync:\n  mode: "offline"\n', encoding="utf-8")
        real = kb_sync.run_git
        calls = []

        def spy(args, cwd, timeout):
            calls.append(list(args))
            if "fetch" in args:
                raise AssertionError("offline 不应 fetch")
            return real(args, cwd, timeout)

        with mock.patch.object(kb_sync, "run_git", side_effect=spy):
            code, doc = self.run_cli("--sync", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(doc["offline"])
        self.assertFalse(doc["ok"])
        self.assertEqual(doc["reason"], "offline")
        self.assertFalse(any("fetch" in call for call in calls))

    def test_show_is_read_only_and_does_not_fetch(self):
        local = git(self.repo, "rev-parse", "--short", "HEAD")
        upstream = self.upstream({"knowledge/a.yaml": "cases: []\n"})
        real = kb_sync.run_git
        calls = []

        def spy(args, cwd, timeout):
            calls.append(list(args))
            if "fetch" in args:
                raise AssertionError("--show 不应 fetch")
            return real(args, cwd, timeout)

        with mock.patch.object(kb_sync, "run_git", side_effect=spy):
            code, doc = self.run_cli("--show", "--json")
        self.assertEqual(code, 0)
        # 不 fetch 时本机 origin ref 停在旧值：落后 0，远端 sha 也还是旧的。
        self.assertEqual(doc["behind"], 0)
        self.assertEqual(doc["remote_rev"], local)
        self.assertNotEqual(doc["remote_rev"], upstream)
        self.assertFalse(any("fetch" in call for call in calls))

    def test_same_repo_compares_host_and_path(self):
        self.write_settings()
        _code, doc = self.run_cli("--show", "--json")
        self.assertTrue(doc["same_repo"])
        other = self.base / "other.git"
        git(self.base, "init", "--bare", "-q", str(other))
        git(self.repo, "remote", "add", "mirror", str(other))
        self.write_settings({"remote": "mirror"})
        _code, doc = self.run_cli("--show", "--json")
        self.assertFalse(doc["same_repo"])


class MergeTest(ConfiguredCase):
    def test_merges_when_four_conditions_hold(self):
        upstream = self.upstream({"knowledge/a.yaml": "cases: []\n"})
        code, doc = self.run_cli("--merge", "--json")
        self.assertEqual(code, 0)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["merge"], "ff-only")
        self.assertEqual(doc["behind"], 0)
        self.assertEqual(doc["local_rev"], upstream)
        self.assertEqual(doc["behind_before"], 1)
        self.assertTrue((self.repo / "knowledge" / "a.yaml").is_file())

    def test_branch_mismatch_blocks_merge(self):
        self.upstream({"knowledge/a.yaml": "cases: []\n"})
        git(self.repo, "checkout", "-q", "-b", "feature")
        _code, doc = self.run_cli("--merge", "--json")
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["merge"], "none")
        self.assertEqual(doc["reason"], "branch-mismatch")
        self.assertEqual(doc["behind"], 1)

    def test_not_ancestor_blocks_merge(self):
        self.upstream({"knowledge/a.yaml": "cases: []\n"})
        (self.repo / "local.txt").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "local")
        _code, doc = self.run_cli("--merge", "--json")
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["merge"], "none")
        self.assertEqual(doc["reason"], "not-ancestor")

    def test_dirty_working_tree_blocks_merge(self):
        self.upstream({"knowledge/a.yaml": "cases: []\n"})
        (self.repo / "README.md").write_text("dirty\n", encoding="utf-8")
        _code, doc = self.run_cli("--merge", "--json")
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["merge"], "none")
        self.assertEqual(doc["reason"], "dirty")

    def test_merge_in_progress_blocks_merge(self):
        self.upstream({"knowledge/a.yaml": "cases: []\n"})
        (self.repo / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n", encoding="utf-8")
        _code, doc = self.run_cli("--merge", "--json")
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["merge"], "none")
        self.assertEqual(doc["reason"], "merge-in-progress")

    def test_linked_worktree_blocks_merge(self):
        self.upstream({"knowledge/a.yaml": "cases: []\n"})
        wt = self.base / "wt"
        git(self.repo, "worktree", "add", "-q", "--detach", str(wt), "main")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = kb_sync.main(["--root", str(wt), "--merge", "--json"])
        doc = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["merge"], "none")
        self.assertEqual(doc["reason"], "worktree")
        self.assertEqual(doc["behind"], 1)

    def test_auto_merge_off_skips_merge(self):
        self.write_settings({"auto_merge": False})
        self.upstream({"knowledge/a.yaml": "cases: []\n"})
        result = kb_sync.sync(self.repo, do_merge=True, honor_auto_merge=True)
        self.assertEqual(result["merge"], "none")
        self.assertEqual(result["reason"], "auto-merge-off")
        self.assertEqual(result["behind"], 1)


class CliTest(RepoCase):
    def test_bad_timeout_is_arg_error(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "kb_sync.py"),
             "--root", str(self.repo), "--show", "--timeout", "0"],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(proc.returncode, 2)

    def test_human_show_reports_config_and_ref(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = kb_sync.main(["--root", str(self.repo), "--show"])
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("知识库同步", text)
        self.assertIn("origin/main", text)
        self.assertIn("本机 HEAD", text)


if __name__ == "__main__":
    unittest.main()
