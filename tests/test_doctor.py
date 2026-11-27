"""doctor 的知识库同步检查：只读、不联网，判 ok / degraded / off 三态。

为什么单测：体检器把「这台机器能不能同步知识库」压成一行。落后、上次 fetch 失败、
部署声明离线三种情况的结论不同；判错时人看到的是一句"环境齐了"或一条假红。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import doctor  # noqa: E402


def git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", *args],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败：{proc.stderr}")
    return (proc.stdout or "").strip()


class KbSyncCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="doctor-kb-sync-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "README.md").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "init")
        self.first = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.first)
        self.write_settings()

    def write_settings(self, sync=None, identity=None):
        doc = {
            "schema": "ascend-sleuth-settings/1",
            "sync": {"remote": "origin", "branch": "main",
                     "enabled": True, "auto_merge": True},
        }
        if sync:
            doc["sync"].update(sync)
        if identity is not None:
            doc["identity"] = identity
        path = self.repo / ".local" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")

    def check(self):
        return doctor.check_kb_sync(self.repo)

    def test_ok_when_local_ref_matches_head(self):
        row = self.check()
        self.assertEqual(row["id"], "kb-sync")
        self.assertEqual(row["state"], doctor.OK)
        self.assertIn("一致", row["detail"])
        self.assertEqual(row["fix"], "")

    def test_degraded_when_behind(self):
        (self.repo / "next.txt").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "next.txt")
        git(self.repo, "commit", "-qm", "next")
        second = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/main", second)
        git(self.repo, "reset", "-q", "--hard", self.first)
        row = self.check()
        self.assertEqual(row["state"], doctor.DEGRADE)
        self.assertIn("落后 origin/main 1 个提交", row["detail"])
        self.assertEqual(row["fix"], "python3 scripts/kb_sync.py --show")

    def test_unconfigured_uses_defaults_without_degrading(self):
        (self.repo / ".local" / "settings.json").unlink()
        row = self.check()
        self.assertEqual(row["state"], doctor.OK)
        self.assertIn("按默认值算", row["detail"])
        self.assertIn("origin/main", row["detail"])
        self.assertEqual(row["fix"], "")

    def test_degraded_when_last_fetch_failed(self):
        state = {"schema": "ascend-sleuth-kb-sync-state/1",
                 "last_ok_at": "2026-11-01T10:00:00+08:00",
                 "attempted_at": "2026-11-04T10:00:00+08:00",
                 "reason": "timeout", "remote": "origin", "branch": "main"}
        path = self.repo / ".local" / "kb-sync-state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
        row = self.check()
        self.assertEqual(row["state"], doctor.DEGRADE)
        self.assertIn("上次 fetch 失败：fetch 超时", row["detail"])
        self.assertIn("2026-11-04T10:00:00+08:00", row["detail"])

    def test_off_when_deployment_declares_offline(self):
        (self.repo / "sleuth.config.yaml").write_text(
            'schema: sleuth-config-v1\nsync:\n  mode: "offline"\n', encoding="utf-8")
        row = self.check()
        self.assertEqual(row["state"], doctor.OK)
        self.assertIn("offline", row["detail"])
        self.assertIn("不联网", row["detail"])
        self.assertEqual(row["fix"], "")

    def test_degraded_when_no_remote_ref(self):
        git(self.repo, "update-ref", "-d", "refs/remotes/origin/main")
        row = self.check()
        self.assertEqual(row["state"], doctor.DEGRADE)
        self.assertIn("算不出落后", row["detail"])

    def test_identity_is_shown_with_default_marker(self):
        row = self.check()
        self.assertIn("归属仓 origin（默认）", row["detail"])

    def test_identity_unresolved_degrades(self):
        self.write_settings(identity={"remote": "gone"})
        row = self.check()
        self.assertEqual(row["state"], doctor.DEGRADE)
        self.assertIn("归属仓 gone", row["detail"])
        self.assertIn("解析不到", row["detail"])

    def test_same_repo_mismatch_degrades(self):
        git(self.repo, "remote", "add", "origin",
            "https://github.com/pillumina/ascend-sleuth.git")
        git(self.repo, "remote", "add", "mirror", "https://example.com/o/r.git")
        self.write_settings(sync={"remote": "mirror"})
        row = self.check()
        self.assertEqual(row["state"], doctor.DEGRADE)
        self.assertIn("同步源与归属仓不同源", row["detail"])


class RegistrationTest(unittest.TestCase):
    def test_kb_sync_is_in_capability_table(self):
        needs = {name for _label, items in doctor.CAPABILITIES for name in items}
        self.assertIn("kb-sync", needs)

    def test_capability_table_accepts_registered_checks(self):
        ids = {name for _label, items in doctor.CAPABILITIES for name in items}
        checks = [{"id": name, "state": doctor.OK} for name in ids]
        row = doctor.check_capability_table(checks)
        self.assertEqual(row["state"], doctor.OK)


class GitCodeCheckTest(unittest.TestCase):
    """GitCode 通道三态：环境 token > CLI 登录态；缺 CLI 给安装，未登录给网页登录。"""

    def tearDown(self):
        for name in ("GC_TOKEN", "GITCODE_TOKEN"):
            os.environ.pop(name, None)

    def test_env_token_without_cli_is_still_degraded(self):
        # 摄取脚本仍要 CLI 作 API 入口：env token 不能把能力判成可用
        os.environ["GITCODE_TOKEN"] = "x"
        with mock.patch.object(doctor, "tool_version", return_value=""):
            row = doctor.check_gitcode()
        self.assertEqual(row["state"], doctor.DEGRADE)
        self.assertIn("GITCODE_TOKEN", row["detail"])
        self.assertIn("GITCODE_TOKEN", row["note"])

    def test_env_token_with_logged_in_cli_is_ok(self):
        os.environ["GITCODE_TOKEN"] = "x"
        proc = mock.Mock(returncode=0, stdout=json.dumps({"source": "GITCODE_TOKEN"}), stderr="")
        with mock.patch.object(doctor, "tool_version", side_effect=lambda n: "1.2.3" if n == "gitcode" else ""), \
             mock.patch.object(doctor.subprocess, "run", return_value=proc):
            row = doctor.check_gitcode()
        self.assertEqual(row["state"], doctor.OK)
        self.assertIn("GITCODE_TOKEN", row["detail"])

    def test_missing_cli_gives_install_fix(self):
        with mock.patch.object(doctor, "tool_version", return_value=""):
            row = doctor.check_gitcode()
        self.assertEqual(row["state"], doctor.DEGRADE)
        self.assertEqual(row["fix_kind"], "install-cli")
        self.assertTrue(row["fix_auto"])
        self.assertIn("atomgit-cli", row["fix"])
        self.assertNotIn("auth login", row["fix"], "安装类 fix 不能带登录命令")

    def test_logged_in_is_ok(self):
        proc = mock.Mock(returncode=0, stdout=json.dumps({"source": "config"}), stderr="")
        with mock.patch.object(doctor, "tool_version", side_effect=lambda n: "1.2.3" if n == "gitcode" else ""), \
             mock.patch.object(doctor.subprocess, "run", return_value=proc):
            row = doctor.check_gitcode()
        self.assertEqual(row["state"], doctor.OK)
        self.assertIn("config", row["detail"])

    def test_not_logged_in_gives_web_login(self):
        proc = mock.Mock(returncode=4, stdout="{}", stderr="not logged in")
        with mock.patch.object(doctor, "tool_version", side_effect=lambda n: "1.2.3" if n == "gitcode" else ""), \
             mock.patch.object(doctor.subprocess, "run", return_value=proc):
            row = doctor.check_gitcode()
        self.assertEqual(row["state"], doctor.DEGRADE)
        self.assertEqual(row["fix_kind"], "login-web")
        self.assertFalse(row["fix_auto"])
        self.assertEqual(row["fix"], "gitcode auth login --web")

    def test_capability_rows_cover_gitcode(self):
        rows = dict(doctor.CAPABILITIES)
        self.assertIn("gitcode", rows["批量导入上游 issue（GitCode）"])
        self.assertIn("gh", rows["批量导入上游 issue（GitHub）"])


class LocalModuleTest(unittest.TestCase):
    """本仓模块不能报成缺失的第三方包。

    为什么单测：`bench_sediment_queue.py` 的 `import sediment_state` 指向插件 `lib/` 里的文件，
    不是待装的包。判成本仓以外的东西时，体检器会给一条装不上的修法，并把一条正常流程标成阻断。
    """

    def setUp(self):
        plugins = ROOT / "dsh-plugins"
        if not (plugins / "dsh-sleuth-copilot" / "lib" / "sediment_state.py").is_file():
            self.skipTest("本检出没有插件 lib（框架 fork 形态）")

    def test_plugin_lib_module_is_local(self):
        self.assertIn("sediment_state", doctor.local_module_names())
        self.assertIsNotNone(doctor.resolve_spec("sediment_state"))

    def test_plugin_lib_dirs_are_discovered(self):
        dirs = {p.resolve() for p in doctor.local_module_dirs()}
        for plugin in (ROOT / "dsh-plugins").iterdir():
            lib = plugin / "lib"
            if lib.is_dir():
                self.assertIn(lib.resolve(), dirs)

    def test_plugin_lib_module_not_reported_as_missing_package(self):
        rows = {row["id"]: row for row in doctor.check_third_party()}
        self.assertNotIn("sediment_state", rows)
        self.assertNotIn("_yaml", rows, "scripts/ 里的模块同样不算待装包")

    def test_absent_package_is_still_a_candidate(self):
        # 反向保证：本仓没有同名文件、解释器也解析不到的名字，仍走「缺包」这条路
        name = "doctor_probe_absent_pkg"
        self.assertNotIn(name, doctor.local_module_names())
        self.assertIsNone(doctor.resolve_spec(name))
        self.assertFalse(doctor.is_stdlib(name, doctor.resolve_spec(name)))

    def test_no_blocking_package_left_in_this_checkout(self):
        # 本检出自带 plugins 与 PyYAML 以外的依赖不保证装；这里只断言没有「本仓模块被报阻断」
        blocked = [row["id"] for row in doctor.check_third_party() if row["state"] == doctor.BLOCK]
        self.assertNotIn("sediment_state", blocked)


if __name__ == "__main__":
    unittest.main()
