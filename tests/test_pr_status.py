"""pr_status 的口径回归测试。

护四件「错了不报错、只让状态静默失真」的事：

1. **台账 CAS**：两个写者同时写 `.groom/pr-state.json` 时，后写者不能覆盖先写者；
   写后校验落盘字节与本次序列化一致。
2. **目标推荐**：已保存目标 → 当前分支上游 → 唯一远端 → 不猜，顺序与理由都固定。
3. **平台适配器**：清单坏不抛、缺 token 标 available:false；YAML 适配器的 map/normalize
   用内置样例自检；exec 适配器 import 时不跑子进程。
4. **查询失败也留痕**：无适配器/无 token 时写 `state: unknown`、`source: platform`、
   `checked_at`，不删旧 PR；错误码与退出码符合契约。

不联网：HTTP 只在 monkeypatch 掉 `urlopen` 的用例里走一次，其余只测 map/normalize。
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pr_status as pr  # noqa: E402


# ---------------------------------------------------------------- 临时仓库与 CLI 工具

def git(repo: Path, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败：{proc.stderr}")
    return proc


def init_repo(base: Path, remotes=(("origin", "https://github.com/pillumina/ascend-sleuth.git"),)):
    repo = base / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "pr-status@example.com")
    git(repo, "config", "user.name", "PR Status Test")
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    for name, url in remotes:
        git(repo, "remote", "add", name, url)
    return repo


def run_cli(*args):
    out = io.StringIO()
    with redirect_stdout(out):
        code = pr.main(list(args))
    return code, json.loads(out.getvalue())


def run_cli_lines(*args):
    """跑一次 CLI，返回原始 stdout（--json-lines 是多行输出，不能整份 json.loads）。"""
    out = io.StringIO()
    with redirect_stdout(out):
        code = pr.main(list(args))
    return code, out.getvalue()


def parse_json_lines(text):
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def clean_env(**overrides):
    env = {key: value for key, value in os.environ.items() if key != "GITCODE_TOKEN"}
    env.update(overrides)
    return env


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RefusedLock:
    """模拟开锁文件被系统拒绝（Windows 上是 `[Errno 13]`）：一进上下文就抛。"""

    def __init__(self, filename):
        self.filename = filename

    def __enter__(self):
        raise PermissionError(13, "Permission denied", self.filename)

    def __exit__(self, *exc):
        return False


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="pr-status-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base)


# ---------------------------------------------------------------- 台账

class LedgerTest(RepoCase):
    def test_ledger_lives_in_shared_inbox(self):
        self.assertEqual(pr.ledger_path(self.repo).resolve(),
                         (self.repo / "postmortems" / "inbox" / ".groom" / "pr-state.json").resolve())

    def test_missing_ledger_is_empty_not_error(self):
        data = pr.load_ledger(self.repo)
        self.assertEqual(data["schema"], pr.SCHEMA)
        self.assertIsNone(data["target"])
        self.assertEqual(data["prs"], {})

    def test_save_then_load_roundtrip(self):
        data = pr.empty_ledger()
        data["target"] = {"remote": "origin", "base": "main", "platform": "github",
                          "url": "https://github.com/o/r.git", "note": "", "labels": {},
                          "source": "user", "chosen_at": "2026-11-01T10:00:00+08:00"}
        digest = pr.save_ledger(self.repo, data)
        self.assertEqual(digest, pr.file_sha256(pr.ledger_path(self.repo)))
        loaded = pr.load_ledger(self.repo)
        self.assertEqual(loaded["target"]["remote"], "origin")
        self.assertTrue(loaded["updated_at"])

    def test_save_ledger_folds_file_refusal(self):
        # 开锁文件被拒绝不是「写失败」：必须折成 LedgerError（调用方给 E_LEDGER），
        # 消息带真实路径与系统原因，不能落成 E_INTERNAL 的裸 PermissionError。
        refused = RefusedLock("/tmp/r/.groom/pr-state.json.lock")
        with mock.patch.object(pr, "log_lock", return_value=refused):
            with self.assertRaises(pr.LedgerError) as ctx:
                pr.save_ledger(self.repo, pr.empty_ledger())
        message = str(ctx.exception)
        self.assertIn("台账写不进去", message)
        self.assertIn("pr-state.json.lock", message)
        self.assertIn("Permission denied", message)

    def test_cas_rejects_stale_writer(self):
        pr.save_ledger(self.repo, pr.empty_ledger())
        stale_digest = pr.ledger_sha256(self.repo)
        data = pr.load_ledger(self.repo)
        data["target"] = {"remote": "origin", "base": "main", "platform": "github",
                          "url": "", "note": "", "labels": {}, "source": "user",
                          "chosen_at": ""}
        pr.save_ledger(self.repo, data)          # 另一个写者先写
        with self.assertRaises(pr.CasConflict):
            pr.save_ledger(self.repo, pr.empty_ledger(), expect_sha=stale_digest)
        self.assertEqual(pr.load_ledger(self.repo)["target"]["remote"], "origin")

    def test_cas_accepts_matching_digest(self):
        digest = pr.save_ledger(self.repo, pr.empty_ledger())
        data = pr.empty_ledger()
        data["prs"]["draft-a"] = {"platform": "github", "repo": "o/r", "number": 1,
                                  "url": "https://github.com/o/r/pull/1", "state": "open",
                                  "source": "ledger", "created_at": "2026-11-01T10:00:00+08:00"}
        pr.save_ledger(self.repo, data, expect_sha=digest)
        self.assertIn("draft-a", pr.load_ledger(self.repo)["prs"])

    def test_broken_ledger_raises_but_soft_read_degrades(self):
        path = pr.ledger_path(self.repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(pr.LedgerError):
            pr.load_ledger(self.repo)
        # 列目标只读：坏台账退化成空目标，远端照列。
        targets = pr.list_targets(self.repo)
        self.assertIsNone(targets["target"])
        self.assertEqual(targets["remotes"][0]["name"], "origin")

    def test_list_targets_sha256_tokens_the_ledger_bytes(self):
        # 不存在给 null；存在给文件字节哈希（与 --status / save_ledger 同一算法）。
        self.assertIsNone(pr.list_targets(self.repo)["sha256"])
        digest = pr.save_ledger(self.repo, pr.empty_ledger())
        self.assertEqual(pr.list_targets(self.repo)["sha256"], digest)
        code, payload = run_cli("--root", str(self.repo), "--list-targets")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["sha256"], digest)
        # 另一个写者改台账后，旧令牌与新给的 sha 不一致（面板据此判断自己的队列过期）。
        data = pr.load_ledger(self.repo)
        data["target"] = {"remote": "origin"}
        pr.save_ledger(self.repo, data)
        self.assertNotEqual(pr.list_targets(self.repo)["sha256"], digest)


# ---------------------------------------------------------------- settings 写点的文件指纹 CAS

def legacy_target(remote="origin", base="main"):
    return {"remote": remote, "base": base, "platform": "github",
            "url": "https://github.com/pillumina/ascend-sleuth.git", "note": "",
            "labels": {}, "source": "user", "chosen_at": "2026-11-01T10:00:00+08:00"}


class SettingsCasTest(RepoCase):
    """settings 的四个写点（--set-sync / --set-target / --migrate / 迁移写回）同一套 CAS。"""

    def test_load_target_migration_keeps_sync_section(self):
        # settings 已有 sync 段但没有 target；旧台账里有 target → 迁移写回时 sync 不能丢。
        pr.kb_sync.save_settings(self.repo, {"sync": {"remote": "origin", "branch": "main",
                                                      "enabled": False, "auto_merge": False}})
        data = pr.empty_ledger()
        data["target"] = legacy_target()
        pr.save_ledger(self.repo, data)

        target = pr.load_target(self.repo)
        self.assertEqual(target["remote"], "origin")
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertEqual(settings["target"]["remote"], "origin")
        self.assertFalse(settings["sync"]["enabled"])
        self.assertFalse(settings["sync"]["auto_merge"])

    def test_migrate_cli_keeps_sync_section(self):
        pr.kb_sync.save_settings(self.repo, {"sync": {"remote": "origin", "branch": "main",
                                                      "enabled": True, "auto_merge": False}})
        data = pr.empty_ledger()
        data["target"] = legacy_target(base="develop")
        pr.save_ledger(self.repo, data)

        code, payload = run_cli("--root", str(self.repo), "--migrate")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["migrated"])
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertEqual(settings["target"]["base"], "develop")
        self.assertTrue(settings["sync"]["enabled"])
        self.assertFalse(settings["sync"]["auto_merge"])

    def test_migrate_rejects_stale_settings_fingerprint(self):
        pr.kb_sync.save_settings(self.repo, {"sync": {"remote": "origin", "branch": "main",
                                                      "enabled": True, "auto_merge": True}})
        stale = pr.kb_sync.settings_sha256(self.repo)
        # 另一个写者（面板的 --set-sync）在读完指纹之后改了配置。
        pr.kb_sync.save_settings(self.repo, {"sync": {"remote": "origin", "branch": "main",
                                                      "enabled": False, "auto_merge": True}})
        before = pr.kb_sync.settings_path(self.repo).read_bytes()
        data = pr.empty_ledger()
        data["target"] = legacy_target()
        pr.save_ledger(self.repo, data)

        code, payload = run_cli("--root", str(self.repo), "--migrate",
                                "--expect-sha256", stale)
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_CAS")
        # 被拒绝的写没有落盘：文件还是另一个写者那一版，target 仍为空。
        self.assertEqual(pr.kb_sync.settings_path(self.repo).read_bytes(), before)
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertIsNone(settings["target"])
        self.assertFalse(settings["sync"]["enabled"])

    def test_set_target_rejects_stale_settings_fingerprint(self):
        pr.kb_sync.save_settings(self.repo, {"sync": {"remote": "origin", "branch": "main",
                                                      "enabled": True, "auto_merge": True}})
        stale = pr.kb_sync.settings_sha256(self.repo)
        real_save_ledger = pr.save_ledger
        after_race = {}

        def racing_save(root, data, expect_sha=None):
            # --set-target 先写台账、再写 settings；模拟两个写点之间另一个写者改了配置。
            digest = real_save_ledger(root, data, expect_sha=expect_sha)
            pr.kb_sync.save_settings(self.repo, {"sync": {"remote": "origin", "branch": "main",
                                                          "enabled": False, "auto_merge": True}})
            after_race["bytes"] = pr.kb_sync.settings_path(self.repo).read_bytes()
            return digest

        with mock.patch.object(pr, "save_ledger", side_effect=racing_save):
            code, payload = run_cli("--root", str(self.repo), "--set-target",
                                    "--remote", "origin")
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_CAS")
        # 写被拒绝：文件停在另一个写者那一版（sync 生效、target 仍为空）。
        self.assertEqual(pr.kb_sync.settings_path(self.repo).read_bytes(), after_race["bytes"])
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertIsNone(settings["target"])
        self.assertFalse(settings["sync"]["enabled"])
        # 台账里的 target 仍在（旧读侧不丢），下次迁移写回还能补上 settings。
        self.assertEqual(pr.load_ledger(self.repo)["target"]["remote"], "origin")
        self.assertNotEqual(pr.kb_sync.settings_sha256(self.repo), stale)

    def test_set_sync_defaults_to_fingerprint_read_at_load(self):
        pr.kb_sync.save_settings(self.repo, {"sync": {"remote": "origin", "branch": "main",
                                                      "enabled": True, "auto_merge": True}})
        real_load = pr.kb_sync.load_settings
        called = {"done": False}

        def racing_load(root):
            result = real_load(root)
            if not called["done"]:
                called["done"] = True
                # 读完配置之后、写之前另一个写者改了配置。
                pr.kb_sync.save_settings(self.repo, {
                    "sync": {"remote": "origin", "branch": "main",
                             "enabled": False, "auto_merge": True}})
            return result

        with mock.patch.object(pr.kb_sync, "load_settings", side_effect=racing_load):
            code, payload = run_cli("--root", str(self.repo), "--set-sync", "--enable")
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_CAS")
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertFalse(settings["sync"]["enabled"])


class SetSyncCheckFieldsTest(RepoCase):
    """`--set-sync` 的提醒检查两键：只改 check 字段、越界拒绝、CAS 照旧。"""

    def seed_sync(self):
        pr.kb_sync.save_settings(self.repo, {"sync": {
            "remote": "origin", "branch": "release", "enabled": False, "auto_merge": False}})

    def test_only_check_fields_leave_others_untouched(self):
        self.seed_sync()
        code, payload = run_cli("--root", str(self.repo), "--set-sync",
                                "--check-reminders", "off", "--check-minutes", "45")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        sync = payload["sync"]
        self.assertFalse(sync["check_enabled"])
        self.assertEqual(sync["check_minutes"], 45)
        self.assertEqual((sync["remote"], sync["branch"]), ("origin", "release"))
        self.assertFalse(sync["enabled"])
        self.assertFalse(sync["auto_merge"])
        # 落盘与读侧（--status 给面板的 settings.sync）都带这两键。
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertFalse(settings["sync"]["check_enabled"])
        self.assertEqual(settings["sync"]["check_minutes"], 45)
        code, status = run_cli("--root", str(self.repo))
        self.assertEqual(code, 0, status)
        self.assertFalse(status["settings"]["sync"]["check_enabled"])
        self.assertEqual(status["settings"]["sync"]["check_minutes"], 45)

    def test_check_full_access_roundtrip(self):
        self.seed_sync()
        code, payload = run_cli("--root", str(self.repo), "--set-sync",
                                "--check-full-access", "off")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        self.assertFalse(payload["sync"]["check_full_access"])
        # 只动这一键：其余键保持原值（seed 的四个键 + 读侧补的默认值）。
        self.assertEqual((payload["sync"]["remote"], payload["sync"]["branch"]), ("origin", "release"))
        self.assertFalse(payload["sync"]["enabled"])
        self.assertFalse(payload["sync"]["auto_merge"])
        self.assertTrue(payload["sync"]["check_enabled"])
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertFalse(settings["sync"]["check_full_access"])
        code, status = run_cli("--root", str(self.repo))
        self.assertEqual(code, 0, status)
        self.assertFalse(status["settings"]["sync"]["check_full_access"])
        code, payload = run_cli("--root", str(self.repo), "--set-sync",
                                "--check-full-access", "on")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["sync"]["check_full_access"])

    def test_check_field_alone_counts_as_a_change(self):
        self.seed_sync()
        code, payload = run_cli("--root", str(self.repo), "--set-sync",
                                "--check-reminders", "on")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["sync"]["check_enabled"])

    def test_check_minutes_out_of_range_is_arg_error(self):
        self.seed_sync()
        for value in ("0", "4", "721"):
            with self.subTest(value=value):
                code, payload = run_cli("--root", str(self.repo), "--set-sync",
                                        "--check-minutes", value)
                self.assertEqual(code, pr.EXIT_ARGS, payload)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["error"]["code"], "E_ARGS")
        # 被拒绝的写没有落盘：分钟数还是默认值。
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertEqual(settings["sync"]["check_minutes"], 30)

    def test_check_minutes_bounds_are_accepted(self):
        for value in (5, 720):
            with self.subTest(value=value):
                code, payload = run_cli("--root", str(self.repo), "--set-sync",
                                        "--check-minutes", str(value))
                self.assertEqual(code, 0, payload)
                self.assertTrue(payload["ok"], payload)
                self.assertEqual(payload["sync"]["check_minutes"], value)

    def test_check_fields_write_respects_cas(self):
        self.seed_sync()
        stale = pr.kb_sync.settings_sha256(self.repo)
        # 另一个写者在读完指纹之后改了配置。
        pr.kb_sync.save_settings(self.repo, {"sync": {
            "remote": "origin", "branch": "main", "enabled": True, "auto_merge": True,
            "check_enabled": False, "check_minutes": 60}})
        before = pr.kb_sync.settings_path(self.repo).read_bytes()
        code, payload = run_cli("--root", str(self.repo), "--set-sync",
                                "--check-reminders", "on", "--expect-sha256", stale)
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_CAS")
        self.assertEqual(pr.kb_sync.settings_path(self.repo).read_bytes(), before)
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertFalse(settings["sync"]["check_enabled"])
        self.assertEqual(settings["sync"]["check_minutes"], 60)


# ---------------------------------------------------------------- 目标与推荐

class TargetTest(RepoCase):
    def _set_upstream(self):
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.repo, "checkout", "-q", "-b", "feature")
        git(self.repo, "branch", "--set-upstream-to=origin/main", "feature")

    def test_saved_target_wins(self):
        data = pr.empty_ledger()
        data["target"] = {"remote": "origin", "base": "main", "platform": "github",
                          "url": "https://github.com/pillumina/ascend-sleuth.git",
                          "note": "团队仓", "labels": {}, "source": "user",
                          "chosen_at": "2026-11-01T10:00:00+08:00"}
        pr.save_ledger(self.repo, data)
        targets = pr.list_targets(self.repo)
        self.assertEqual(targets["recommendation"]["remote"], "origin")
        self.assertEqual(targets["recommendation"]["reason"], "上次选择的目标")
        self.assertEqual(targets["remotes"][0]["note"], "团队仓")

    def test_upstream_remote_recommended_when_identity_unresolved(self):
        # 归属仓显式指向不存在的远端时不参与推荐，落到当前分支上游。
        self._set_upstream()
        pr.kb_sync.save_settings(self.repo, {"identity": {"remote": "gone"}})
        targets = pr.list_targets(self.repo)
        self.assertEqual(targets["recommendation"],
                         {"remote": "origin", "base": "main", "reason": "当前分支的上游"})

    def test_identity_remote_recommended_before_upstream(self):
        self._set_upstream()
        targets = pr.list_targets(self.repo)
        self.assertEqual(targets["recommendation"],
                         {"remote": "origin", "base": "main", "reason": "归属仓"})

    def test_single_remote_recommended_when_identity_unresolved(self):
        pr.kb_sync.save_settings(self.repo, {"identity": {"remote": "gone"}})
        targets = pr.list_targets(self.repo)
        self.assertEqual(targets["recommendation"]["reason"], "只有一个远端")

    def test_multiple_remotes_without_signal_gives_null(self):
        git(self.repo, "remote", "add", "backup", "https://gitlab.com/o/r.git")
        pr.kb_sync.save_settings(self.repo, {"identity": {"remote": "gone"}})
        targets = pr.list_targets(self.repo)
        self.assertIsNone(targets["recommendation"])

    def test_identity_beats_multiple_remotes(self):
        git(self.repo, "remote", "add", "backup", "https://gitlab.com/o/r.git")
        targets = pr.list_targets(self.repo)
        self.assertEqual(targets["recommendation"]["remote"], "origin")
        self.assertEqual(targets["recommendation"]["reason"], "归属仓")

    def test_identity_fields_are_listed(self):
        targets = pr.list_targets(self.repo)
        self.assertEqual(targets["identity"]["remote"], "origin")
        self.assertEqual(targets["identity"]["url"],
                         "https://github.com/pillumina/ascend-sleuth.git")
        self.assertFalse(targets["identity"]["explicit"])
        pr.kb_sync.save_settings(self.repo, {"identity": {"remote": "origin", "explicit": True}})
        targets = pr.list_targets(self.repo)
        self.assertTrue(targets["identity"]["explicit"])

    def test_remote_fields_include_platform_and_dependencies(self):
        targets = pr.list_targets(self.repo)
        remote = targets["remotes"][0]
        self.assertEqual(remote["host"], "github.com")
        self.assertEqual(remote["platform"], "github")
        self.assertEqual(remote["platform_name"], "GitHub")
        self.assertTrue(remote["has_adapter"])
        self.assertEqual(remote["base"], "main")

    def test_last_used_prefers_remote_field_then_repo_fallback(self):
        data = pr.empty_ledger()
        data["prs"] = {
            "a": {"platform": "github", "repo": "pillumina/ascend-sleuth", "number": 1,
                  "url": "https://github.com/pillumina/ascend-sleuth/pull/1",
                  "state": "open", "source": "ledger",
                  "created_at": "2026-10-01T10:00:00+08:00"},
            "b": {"platform": "github", "repo": "pillumina/ascend-sleuth", "number": 2,
                  "url": "https://github.com/pillumina/ascend-sleuth/pull/2",
                  "state": "open", "source": "ledger", "remote": "origin",
                  "created_at": "2026-10-05T10:00:00+08:00"},
        }
        pr.save_ledger(self.repo, data)
        remote = pr.list_targets(self.repo)["remotes"][0]
        self.assertEqual(remote["last_used"], "2026-10-05T10:00:00+08:00")

    def test_set_target_writes_source_user(self):
        code, payload = run_cli("--root", str(self.repo), "--set-target",
                                "--remote", "origin", "--base", "develop",
                                "--note", "内网")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["target"]["platform"], "github")
        self.assertEqual(payload["target"]["source"], "user")
        self.assertEqual(payload["target"]["base"], "develop")
        loaded = pr.load_ledger(self.repo)["target"]
        self.assertEqual(loaded["remote"], "origin")
        self.assertTrue(loaded["chosen_at"])

    def test_set_target_unknown_remote_is_arg_error(self):
        code, payload = run_cli("--root", str(self.repo), "--set-target", "--remote", "nope")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_ARGS")

    def test_set_target_without_adapter_keeps_platform_empty(self):
        git(self.repo, "remote", "add", "mirror", "https://example.com/o/r.git")
        code, payload = run_cli("--root", str(self.repo), "--set-target", "--remote", "mirror")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["target"]["platform"], "")
        self.assertEqual(payload["platformName"], "")

    def test_set_target_respects_expect_sha(self):
        digest = pr.save_ledger(self.repo, pr.empty_ledger())
        code, payload = run_cli("--root", str(self.repo), "--set-target", "--remote", "origin",
                                "--expect-sha256", "0" * 64)
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_CAS")
        self.assertIsNone(pr.load_ledger(self.repo)["target"])
        # 正确的令牌可以写进去
        code, payload = run_cli("--root", str(self.repo), "--set-target", "--remote", "origin",
                                "--expect-sha256", digest)
        self.assertTrue(payload["ok"], payload)


# ---------------------------------------------------------------- 归属仓与写侧基准

class IdentityBaseTest(RepoCase):
    """`--set-identity` 的校验与写入，以及 `effective_base` 的三段顺序。"""

    def add_remote(self, name="team", url="https://example.com/team/r.git"):
        git(self.repo, "remote", "add", name, url)

    def test_set_identity_writes_remote(self):
        self.add_remote()
        code, payload = run_cli("--root", str(self.repo), "--set-identity", "--remote", "team")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["identity"], {"remote": "team"})
        self.assertTrue(payload["sha256"])
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertEqual(settings["identity"]["remote"], "team")
        self.assertTrue(settings["identity"]["explicit"])

    def test_set_identity_origin_is_explicit(self):
        # 显式把默认值 origin 设为归属仓：要落盘成显式声明，未来 origin 被删才拦。
        code, payload = run_cli("--root", str(self.repo), "--set-identity", "--remote", "origin")
        self.assertEqual(code, 0, payload)
        saved = json.loads((self.repo / ".local" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["identity"], {"remote": "origin"})
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertTrue(settings["identity"]["explicit"])

    def test_set_identity_unknown_remote_is_arg_error(self):
        code, payload = run_cli("--root", str(self.repo), "--set-identity", "--remote", "nope")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_ARGS")

    def test_set_identity_requires_remote(self):
        code, payload = run_cli("--root", str(self.repo), "--set-identity")
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "E_ARGS")

    def test_set_identity_respects_settings_fingerprint(self):
        self.add_remote()
        code, payload = run_cli("--root", str(self.repo), "--set-identity",
                                "--remote", "team", "--expect-sha256", "0" * 64)
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["error"]["code"], "E_CAS")
        settings, _source, _problem = pr.kb_sync.load_settings(self.repo)
        self.assertEqual(settings["identity"]["remote"], "origin")
        digest = pr.kb_sync.settings_sha256(self.repo)
        code, payload = run_cli("--root", str(self.repo), "--set-identity",
                                "--remote", "team", "--expect-sha256", digest)
        self.assertTrue(payload["ok"], payload)

    def test_effective_base_prefers_saved_target(self):
        pr.kb_sync.save_settings(self.repo, {"target": {"remote": "origin", "base": "develop"}})
        self.assertEqual(pr.effective_base(self.repo), "origin/develop")

    def test_effective_base_uses_identity_default_branch(self):
        self.add_remote()
        git(self.repo, "update-ref", "refs/remotes/team/develop", "HEAD")
        git(self.repo, "symbolic-ref", "refs/remotes/team/HEAD", "refs/remotes/team/develop")
        pr.kb_sync.save_settings(self.repo, {"identity": {"remote": "team"}})
        self.assertEqual(pr.effective_base(self.repo), "team/develop")

    def test_effective_base_falls_back_to_origin_main(self):
        pr.kb_sync.save_settings(self.repo, {"identity": {"remote": "gone"}})
        self.assertEqual(pr.effective_base(self.repo), "origin/main")


# ---------------------------------------------------------------- 平台适配器

class PlatformTest(RepoCase):
    def test_list_platforms_marks_missing_token(self):
        with mock.patch.dict(os.environ, clean_env(), clear=True):
            code, payload = run_cli("--root", str(self.repo), "--list-platforms")
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        by_id = {item["id"]: item for item in payload["platforms"]}
        self.assertIn("gitcode", by_id)
        gitcode = by_id["gitcode"]
        self.assertEqual(gitcode["kind"], "http")
        self.assertEqual(gitcode["hosts"], ["gitcode.com"])
        self.assertEqual(gitcode["auth_env"], "GITCODE_TOKEN")
        self.assertFalse(gitcode["available"])
        self.assertIn("GITCODE_TOKEN", gitcode["reason"])

    def test_gitcode_normalize_open_merged_closed(self):
        adapter = pr.find_adapter(pr.load_adapters(), "gitcode")
        self.assertIsNotNone(adapter)
        spec = adapter["spec"]["check"]
        fixtures = [
            ({"state": "open", "merged": False}, "open"),
            ({"state": "closed", "merged": True}, "merged"),
            ({"state": "closed", "merged": False}, "closed"),
        ]
        for response, expected in fixtures:
            mapped = {key: pr._json_path(response, path) for key, path in spec["map"].items()}
            self.assertEqual(pr._normalize(spec["normalize"], mapped), expected, response)

    def test_gitcode_selftest_does_not_touch_network(self):
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("联网了")):
            code, payload = run_cli("--root", str(self.repo), "--selftest", "gitcode")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["passed"], payload["total"])
        self.assertGreaterEqual(payload["passed"], 3)

    def test_exec_adapter_import_runs_no_subprocess(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("import 时跑了子进程")):
            adapters = pr.load_adapters()
        self.assertIn("github", [a["id"] for a in adapters])

    def test_exec_selftest_passes(self):
        code, payload = run_cli("--root", str(self.repo), "--selftest", "github")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        self.assertGreaterEqual(payload["total"], 3)

    def test_unknown_platform_selftest_is_not_found(self):
        code, payload = run_cli("--root", str(self.repo), "--selftest", "nope")
        self.assertEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_NOT_FOUND")

    def test_broken_manifest_is_reported_not_raised(self):
        platforms = self.base / "platforms"
        platforms.mkdir()
        (platforms / "broken.yaml").write_text("id: broken\nname: Broken\n",
                                               encoding="utf-8")
        (platforms / "demo.yaml").write_text(
            "id: demo\nname: Demo\nhosts: [demo.example]\nauth_env: DEMO_TOKEN\n"
            "check:\n"
            "  method: GET\n"
            "  url: https://demo.example/api/{owner}/{repo}/pulls/{number}\n"
            "  query: {token: \"{env:DEMO_TOKEN}\"}\n"
            "  map: {status: \"$.result.status\", merged_at: \"$.result.merged_at\"}\n"
            "  normalize:\n"
            "    - {when: {merged_at: null, status: merged}, state: merged}\n"
            "    - {when: {status: closed}, state: closed}\n"
            "    - {state: open}\n", encoding="utf-8")
        with mock.patch.object(pr, "PLATFORMS_DIR", platforms), \
                mock.patch.dict(os.environ, clean_env(DEMO_TOKEN="demo-token"), clear=True):
            code, payload = run_cli("--root", str(self.repo), "--list-platforms")
            self.assertEqual(code, 0)
            by_id = {item["id"]: item for item in payload["platforms"]}
            self.assertFalse(by_id["broken"]["available"])
            self.assertIn("清单损坏", by_id["broken"]["reason"])
            self.assertTrue(by_id["demo"]["available"])
            # 用适配器自己的 normalize 反推样例，加平台不用改核心脚本
            code, selftest = run_cli("--root", str(self.repo), "--selftest", "demo")
            self.assertEqual(code, 0, selftest)
            self.assertTrue(selftest["ok"], selftest)
            self.assertGreaterEqual(selftest["passed"], 3)

    def test_http_check_maps_and_normalizes_without_leaking_token(self):
        adapter = pr.find_adapter(pr.load_adapters(), "gitcode")
        entry = {"platform": "gitcode", "repo": "owner/repo", "number": 418,
                 "url": "https://gitcode.com/owner/repo/pulls/418", "state": "open",
                 "source": "ledger", "created_at": "2026-11-01T10:00:00+08:00"}
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            return FakeResponse({"state": "closed", "merged": True})

        with mock.patch.dict(os.environ, clean_env(GITCODE_TOKEN="tok-secret"), clear=True):
            with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                state, detail, error = pr.http_check(adapter, entry)
        self.assertIsNone(error)
        self.assertEqual(state, "merged")
        self.assertIn("access_token", seen["url"])
        self.assertNotIn("tok-secret", detail)
        self.assertIn("***", detail)
        self.assertEqual(seen["timeout"], 10)

    def test_http_check_without_token_fails_before_request(self):
        adapter = pr.find_adapter(pr.load_adapters(), "gitcode")
        entry = {"repo": "owner/repo", "number": 1, "url": ""}
        with mock.patch.dict(os.environ, clean_env(), clear=True):
            with mock.patch("urllib.request.urlopen",
                            side_effect=AssertionError("不该发请求")):
                state, _detail, error = pr.http_check(adapter, entry)
        self.assertEqual(state, "unknown")
        self.assertEqual(error["code"], "E_NO_AUTH")

    def test_redact_url_hides_query_values(self):
        redacted = pr._redact_url("https://api.example/x?access_token=secret&a=1")
        self.assertNotIn("secret", redacted)
        self.assertIn("access_token=***", redacted)


# ---------------------------------------------------------------- 台账写入与查询流程

class FlowTest(RepoCase):
    def _set_pr(self, draft="draft-a", url="https://github.com/o/r/pull/1",
                platform="github", repo="o/r", number=1):
        code, payload = run_cli("--root", str(self.repo), "--set", "--draft", draft,
                                "--platform", platform, "--repo", repo,
                                "--number", str(number), "--url", url)
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        return payload

    def test_set_writes_ledger_defaults(self):
        payload = self._set_pr()
        entry = payload["pr"]
        self.assertEqual(entry["state"], "unknown")
        self.assertEqual(entry["source"], "ledger")
        self.assertIsInstance(entry["number"], int)
        self.assertTrue(entry["created_at"])
        saved = pr.load_ledger(self.repo)["prs"]["draft-a"]
        self.assertEqual(saved["url"], "https://github.com/o/r/pull/1")

    def test_set_with_remote_records_it(self):
        code, payload = run_cli("--root", str(self.repo), "--set", "--draft", "draft-a",
                                "--platform", "github", "--repo", "o/r", "--number", "1",
                                "--url", "https://github.com/o/r/pull/1",
                                "--remote", "origin")
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["pr"]["remote"], "origin")

    def test_set_from_url_only(self):
        code, payload = run_cli("--root", str(self.repo), "--set", "--draft", "draft-a",
                                "--url", "https://github.com/o/r/pull/7")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["pr"]["platform"], "github")
        self.assertEqual(payload["pr"]["repo"], "o/r")
        self.assertEqual(payload["pr"]["number"], 7)

    def test_set_from_gitlab_url(self):
        code, payload = run_cli("--root", str(self.repo), "--set", "--draft", "draft-a",
                                "--url", "https://gitlab.com/o/r/-/merge_requests/9")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["pr"]["platform"], "gitlab")
        self.assertEqual(payload["pr"]["repo"], "o/r")
        self.assertEqual(payload["pr"]["number"], 9)

    def test_set_rejects_bad_number(self):
        code, payload = run_cli("--root", str(self.repo), "--set", "--draft", "draft-a",
                                "--platform", "github", "--repo", "o/r", "--number", "abc",
                                "--url", "https://github.com/o/r/pull/1")
        self.assertEqual(code, 2)
        self.assertFalse(payload["ok"])

    def test_mark_writes_manual_source(self):
        self._set_pr()
        code, payload = run_cli("--root", str(self.repo), "--mark", "--draft", "draft-a",
                                "--state", "merged")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        entry = payload["pr"]
        self.assertEqual(entry["state"], "merged")
        self.assertEqual(entry["source"], "manual")
        self.assertTrue(entry["checked_at"])

    def test_mark_without_pr_is_not_found(self):
        code, payload = run_cli("--root", str(self.repo), "--mark", "--draft", "nope",
                                "--state", "merged")
        self.assertEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_NOT_FOUND")

    def test_forget_closed_record_removes_it(self):
        self._set_pr()
        run_cli("--root", str(self.repo), "--mark", "--draft", "draft-a", "--state", "closed")
        code, payload = run_cli("--root", str(self.repo), "--forget", "--draft", "draft-a")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["pr"]["state"], "closed")
        self.assertNotIn("draft-a", pr.load_ledger(self.repo)["prs"])

    def test_forget_accepts_state_with_spaces_and_case(self):
        self._set_pr()
        data = pr.load_ledger(self.repo)
        data["prs"]["draft-a"]["state"] = " Closed "
        pr.save_ledger(self.repo, data)
        code, payload = run_cli("--root", str(self.repo), "--forget", "--draft", "draft-a")
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        self.assertNotIn("draft-a", pr.load_ledger(self.repo)["prs"])

    def test_forget_bad_record_is_bad_record_not_missing(self):
        self._set_pr()
        data = pr.load_ledger(self.repo)
        data["prs"]["draft-a"] = None
        pr.save_ledger(self.repo, data)
        code, payload = run_cli("--root", str(self.repo), "--forget", "--draft", "draft-a")
        self.assertEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_BAD_RECORD")
        self.assertIn("draft-a", pr.load_ledger(self.repo)["prs"])

    def test_forget_refuses_unclosed_record(self):
        # open / unknown / merged 都还拦撤销；删掉记录会让队列与审计失去依据。
        self._set_pr()
        code, payload = run_cli("--root", str(self.repo), "--forget", "--draft", "draft-a")
        self.assertEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_PR_ACTIVE")
        self.assertIn("draft-a", pr.load_ledger(self.repo)["prs"])

        run_cli("--root", str(self.repo), "--mark", "--draft", "draft-a", "--state", "merged")
        code, payload = run_cli("--root", str(self.repo), "--forget", "--draft", "draft-a")
        self.assertEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_PR_ACTIVE")
        self.assertIn("draft-a", pr.load_ledger(self.repo)["prs"])

    def test_forget_missing_record_is_not_found(self):
        code, payload = run_cli("--root", str(self.repo), "--forget", "--draft", "nope")
        self.assertEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_NOT_FOUND")

    def test_forget_respects_stale_cas_token(self):
        self._set_pr()
        run_cli("--root", str(self.repo), "--mark", "--draft", "draft-a", "--state", "closed")
        stale = pr.ledger_sha256(self.repo)
        self._set_pr(draft="draft-b", number=2)
        code, payload = run_cli("--root", str(self.repo), "--forget", "--draft", "draft-a",
                                "--expect-sha256", stale)
        self.assertEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_CAS")
        self.assertIn("draft-a", pr.load_ledger(self.repo)["prs"])

    def test_check_without_adapter_writes_unknown_and_keeps_pr(self):
        self._set_pr(url="https://example.com/o/r/pulls/1", platform="unknown")
        code, payload = run_cli("--root", str(self.repo), "--check", "--draft", "draft-a")
        self.assertEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_NO_ADAPTER")
        entry = pr.load_ledger(self.repo)["prs"]["draft-a"]
        self.assertEqual(entry["state"], "unknown")
        self.assertEqual(entry["source"], "platform")
        self.assertTrue(entry["checked_at"])
        self.assertEqual(entry["url"], "https://example.com/o/r/pulls/1")

    def test_check_without_token_writes_unknown(self):
        self._set_pr(url="https://gitcode.com/o/r/pulls/9", platform="gitcode")
        with mock.patch.dict(os.environ, clean_env(), clear=True):
            code, payload = run_cli("--root", str(self.repo), "--check", "--draft", "draft-a")
        self.assertEqual(code, 0)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_NO_AUTH")
        entry = pr.load_ledger(self.repo)["prs"]["draft-a"]
        self.assertEqual(entry["state"], "unknown")
        self.assertEqual(entry["source"], "platform")

    def _add_other_writer_change(self):
        """模拟另一个写者先改台账：加一条 PR 记录，内容与旧版必然不同。"""
        data = pr.load_ledger(self.repo)
        data["prs"]["draft-b"] = {"platform": "github", "repo": "o/r", "number": 2,
                                  "url": "https://github.com/o/r/pull/2", "state": "open",
                                  "source": "ledger",
                                  "created_at": "2026-11-01T10:00:00+08:00"}
        pr.save_ledger(self.repo, data)

    def test_check_rejects_stale_expect_sha_before_query(self):
        self._set_pr(url="https://gitcode.com/o/r/pulls/9", platform="gitcode")
        stale = pr.ledger_sha256(self.repo)
        self._add_other_writer_change()
        current = pr.ledger_sha256(self.repo)
        self.assertNotEqual(stale, current)
        ledger_before = pr.ledger_path(self.repo).read_bytes()
        # 没有 token：CAS 若没生效，查询会先报 E_NO_AUTH 并写回。断言 E_CAS 即证明查询前就拒绝了。
        with mock.patch.dict(os.environ, clean_env(), clear=True):
            code, payload = run_cli("--root", str(self.repo), "--check", "--draft", "draft-a",
                                    "--expect-sha256", stale)
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_CAS")
        self.assertEqual(pr.ledger_path(self.repo).read_bytes(), ledger_before)

    def test_check_accepts_current_expect_sha(self):
        self._set_pr(url="https://gitcode.com/o/r/pulls/9", platform="gitcode")
        current = pr.ledger_sha256(self.repo)
        with mock.patch.dict(os.environ, clean_env(), clear=True):
            code, payload = run_cli("--root", str(self.repo), "--check", "--draft", "draft-a",
                                    "--expect-sha256", current)
        self.assertEqual(code, 0, payload)
        # CAS 通过后查询确实执行：没 token 的结果留痕并写回台账。
        self.assertEqual(payload["error"]["code"], "E_NO_AUTH")
        entry = pr.load_ledger(self.repo)["prs"]["draft-a"]
        self.assertEqual(entry["source"], "platform")

    def test_check_all_isolates_failures(self):
        self._set_pr("draft-a", url="https://example.com/o/r/pulls/1", platform="unknown")
        self._set_pr("draft-b", url="https://unknown.example/o/r/pulls/2", platform="other")
        code, payload = run_cli("--root", str(self.repo), "--check-all")
        self.assertEqual(code, 0)
        self.assertFalse(payload["ok"])
        checked = {item["draft"]: item for item in payload["checked"]}
        self.assertEqual(set(checked), {"draft-a", "draft-b"})
        for item in checked.values():
            self.assertFalse(item["ok"])
            self.assertEqual(item["error"], "E_NO_ADAPTER")
        for key in ("draft-a", "draft-b"):
            self.assertEqual(pr.load_ledger(self.repo)["prs"][key]["source"], "platform")

    def test_check_all_skips_terminal_states(self):
        self._set_pr()
        run_cli("--root", str(self.repo), "--mark", "--draft", "draft-a", "--state", "merged")
        code, payload = run_cli("--root", str(self.repo), "--check-all")
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"], payload)
        self.assertEqual(payload["checked"], [])

    def test_check_write_refused_reports_ledger_error_with_checked_state(self):
        # 平台结果已经查到、只是没写进台账：失败载荷要带上 state 与 checked_at，
        # 面板才能说「查到 X，但没写进台账」，而不是让读者白查一遍。
        self._set_pr(url="https://example.com/o/r/pulls/1", platform="unknown")
        refused = RefusedLock("/tmp/r/.groom/pr-state.json.lock")
        with mock.patch.object(pr, "log_lock", return_value=refused):
            code, payload = run_cli("--root", str(self.repo), "--check", "--draft", "draft-a")
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["error"]["code"], "E_LEDGER")
        self.assertIn("台账写不进去", payload["error"]["message"])
        self.assertIn("pr-state.json.lock", payload["error"]["message"])
        self.assertEqual(payload["draft"], "draft-a")
        self.assertEqual(payload["state"], "unknown")
        self.assertTrue(payload["checked_at"])
        self.assertTrue(payload["write_failed"])

    def test_check_write_refused_keeps_real_platform_state(self):
        # 平台确实查到 merged、只是没写进台账：带回的必须是平台状态，不是 _unknown_entry 的占位值。
        # 这条走真实 http_check + 假 urlopen，而不是手工喂 state。
        self._set_pr(url="https://gitcode.com/o/r/pulls/1", platform="gitcode")
        refused = RefusedLock("/tmp/r/.groom/pr-state.json.lock")

        def fake_urlopen(request, timeout=None):
            return FakeResponse({"state": "closed", "merged": True})

        with mock.patch.dict(os.environ, clean_env(GITCODE_TOKEN="tok-secret"), clear=True), \
                mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
                mock.patch.object(pr, "log_lock", return_value=refused):
            code, payload = run_cli("--root", str(self.repo), "--check", "--draft", "draft-a")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["error"]["code"], "E_LEDGER")
        self.assertEqual(payload["state"], "merged")
        self.assertTrue(payload["checked_at"])
        self.assertTrue(payload["write_failed"])

    def test_mark_write_refused_is_ledger_error_not_internal(self):
        self._set_pr()
        refused = RefusedLock("/tmp/r/.groom/pr-state.json.lock")
        with mock.patch.object(pr, "log_lock", return_value=refused):
            code, payload = run_cli("--root", str(self.repo), "--mark", "--draft", "draft-a",
                                    "--state", "merged")
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["ok"], payload)
        self.assertEqual(payload["error"]["code"], "E_LEDGER")
        self.assertIn("台账写不进去", payload["error"]["message"])
        self.assertTrue(payload["write_failed"])

    def test_default_read_lists_ledger(self):
        code, payload = run_cli("--root", str(self.repo), "--json")
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["ledger"]["schema"], pr.SCHEMA)
        self.assertIn("sha256", payload)


# ---------------------------------------------------------------- check-all 并发查询

class CheckAllParallelTest(RepoCase):
    """--check-all 查询阶段并发：并发度、checked[] 顺序、落盘次数。"""

    SLEEP_S = 0.2

    def _seed_ledger(self, drafts):
        data = pr.load_ledger(self.repo)
        data["prs"] = {
            key: {"platform": "fake", "repo": "o/r", "number": index + 1,
                  "url": f"https://example.com/o/r/pulls/{index + 1}",
                  "state": state, "source": "ledger",
                  "created_at": "2026-11-01T10:00:00+08:00"}
            for index, (key, state) in enumerate(drafts.items())
        }
        pr.save_ledger(self.repo, data)

    @staticmethod
    def _fake_check(lock, state, delay_for_key, sleep_s=None):
        def fake_run_check(ledger, key, adapters):
            with lock:
                state["calls"] = state.get("calls", 0) + 1
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            try:
                time.sleep(sleep_s if sleep_s is not None else delay_for_key(key))
            finally:
                with lock:
                    state["active"] -= 1
            entry = dict(ledger["prs"][key])
            entry.update({"state": "open", "source": "platform",
                          "checked_at": "2026-11-01T10:00:00+08:00"})
            return entry, None, ""
        return fake_run_check

    def test_check_all_runs_queries_concurrently(self):
        # 插入顺序与排序顺序不同，确保断言的是台账键排序而不是提交顺序。
        drafts = {"draft-h": "open", "draft-a": "open", "draft-c": "open",
                  "draft-b": "open", "draft-g": "open", "draft-e": "open",
                  "draft-d": "open", "draft-f": "open", "draft-z": "merged"}
        self._seed_ledger(drafts)
        lock = threading.Lock()
        state = {"calls": 0, "active": 0, "peak": 0}
        fake_run_check = self._fake_check(lock, state, lambda key: self.SLEEP_S)

        saves = []
        real_save = pr.save_ledger

        def counting_save(root, data, expect_sha=None):
            saves.append(expect_sha)
            return real_save(root, data, expect_sha=expect_sha)

        started = time.monotonic()
        with mock.patch.object(pr, "_run_check", side_effect=fake_run_check), \
                mock.patch.object(pr, "save_ledger", side_effect=counting_save):
            code, payload = run_cli("--root", str(self.repo), "--check-all")
        elapsed = time.monotonic() - started

        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["ok"], payload)
        # 主断言 1：峰值并发达到并发度；merged 那条终态不查。
        self.assertEqual(pr.CHECK_ALL_WORKERS, 4)
        self.assertEqual(state["peak"], pr.CHECK_ALL_WORKERS)
        self.assertEqual(state["calls"], 8)
        # 主断言 2：checked[] 按台账键排序，终态跳过。
        expected = sorted(key for key, value in drafts.items() if value in pr.CHECKABLE)
        self.assertEqual([item["draft"] for item in payload["checked"]], expected)
        for draft in expected:
            self.assertEqual(payload["ledger"]["prs"][draft]["source"], "platform")
        # 主断言 3：全部查完只落盘一次。
        self.assertEqual(len(saves), 1)
        # 耗时只作宽松上界（8 条 × 0.2s，串行 1.6s，恒为 2 波 0.4s）；留 3 倍余量防慢 runner，
        # 仍低于串行理论值，不作主断言。
        self.assertLess(elapsed, len(expected) * self.SLEEP_S * 3 / 4)

    def test_check_all_output_order_ignores_completion_order(self):
        # 先提交的查得慢、后提交的查得快：完成顺序与台账键顺序相反，输出仍须按键排序。
        keys = ["draft-a", "draft-b", "draft-c", "draft-d", "draft-e", "draft-f"]
        self._seed_ledger({key: "open" for key in keys})
        delays = {key: 0.02 * (len(keys) - index) for index, key in enumerate(keys)}
        lock = threading.Lock()
        state = {"calls": 0, "active": 0, "peak": 0}
        fake_run_check = self._fake_check(lock, state, lambda key: delays[key])

        with mock.patch.object(pr, "_run_check", side_effect=fake_run_check):
            code, payload = run_cli("--root", str(self.repo), "--check-all")

        self.assertEqual(code, 0, payload)
        self.assertEqual([item["draft"] for item in payload["checked"]], sorted(keys))
        # 顺序断言之外确认确实并发过，避免测试退化成串行也通过。
        self.assertGreater(state["peak"], 1)


# ---------------------------------------------------------------- check-all 逐条进度

class CheckAllJsonLinesTest(RepoCase):
    """--json-lines 的契约：先 row 后 done；行序是完成序；done 与 --json 同形。"""

    def _seed(self, drafts):
        data = pr.load_ledger(self.repo)
        data["prs"] = {
            key: {"platform": "unknown", "repo": "o/r", "number": index + 1,
                  "url": f"https://example.invalid/o/r/pulls/{index + 1}",
                  "state": state, "source": "ledger",
                  "created_at": "2026-11-01T10:00:00+08:00"}
            for index, (key, state) in enumerate(drafts.items())
        }
        pr.save_ledger(self.repo, data)

    def _rows_and_done(self, text):
        lines = parse_json_lines(text)
        self.assertTrue(lines, text)
        rows = [line for line in lines if line.get("type") == "row"]
        done = lines[-1]
        self.assertEqual(done.get("type"), "done", lines)
        self.assertEqual(lines[:-1], rows)  # row 全在前面，done 是最后一行
        return rows, done

    def test_emits_rows_then_done(self):
        self._seed({"draft-a": "open", "draft-b": "unknown", "draft-c": "merged"})
        code, text = run_cli_lines("--root", str(self.repo), "--check-all", "--json-lines")
        self.assertEqual(code, 0, text)
        rows, done = self._rows_and_done(text)
        self.assertEqual([row["draft"] for row in rows], ["draft-a", "draft-b"])
        self.assertFalse(done["ok"])
        self.assertEqual(done["error"]["code"], "E_CHECK_PARTIAL")
        # 失败行与 done.checked 一致：错误码、状态、draft 都对得上。
        checked = {item["draft"]: item for item in done["checked"]}
        self.assertEqual(set(checked), {"draft-a", "draft-b"})
        for row in rows:
            self.assertFalse(row["ok"])
            self.assertEqual(row["error"], "E_NO_ADAPTER")
            self.assertTrue(row["checked_at"])
            self.assertTrue(row["message"])
            self.assertEqual(checked[row["draft"]]["error"], row["error"])
            self.assertEqual(checked[row["draft"]]["state"], row["state"])
        # 终态（merged）不查。
        self.assertNotIn("draft-c", checked)

    def test_done_all_ok_carries_ledger_and_sha(self):
        self._seed({"draft-a": "open"})

        def fake_run_check(ledger, key, adapters):
            entry = dict(ledger["prs"][key])
            entry.update({"state": "open", "source": "platform",
                          "checked_at": "2026-11-01T10:00:00+08:00"})
            return entry, None, ""

        with mock.patch.object(pr, "_run_check", side_effect=fake_run_check):
            code, text = run_cli_lines("--root", str(self.repo), "--check-all", "--json-lines")
        self.assertEqual(code, 0, text)
        rows, done = self._rows_and_done(text)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["ok"])
        self.assertNotIn("error", rows[0])
        self.assertTrue(done["ok"])
        self.assertRegex(done["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(done["ledger"]["prs"]["draft-a"]["state"], "open")

    def test_rows_arrive_in_completion_order_checked_stays_sorted(self):
        keys = ["draft-a", "draft-b", "draft-c", "draft-d"]
        self._seed({key: "open" for key in keys})
        # 提交序 = 台账键序，完成序相反：row 按完成序，done.checked 按键序。
        delays = {"draft-a": 0.30, "draft-b": 0.20, "draft-c": 0.10, "draft-d": 0.0}

        def fake_run_check(ledger, key, adapters):
            time.sleep(delays[key])
            entry = dict(ledger["prs"][key])
            entry.update({"state": "open", "source": "platform",
                          "checked_at": "2026-11-01T10:00:00+08:00"})
            return entry, None, ""

        with mock.patch.object(pr, "_run_check", side_effect=fake_run_check):
            code, text = run_cli_lines("--root", str(self.repo), "--check-all", "--json-lines")
        self.assertEqual(code, 0, text)
        rows, done = self._rows_and_done(text)
        self.assertEqual([row["draft"] for row in rows],
                         ["draft-d", "draft-c", "draft-b", "draft-a"])
        self.assertEqual([item["draft"] for item in done["checked"]], keys)

    def test_rows_are_flushed_as_each_draft_finishes(self):
        self._seed({"draft-a": "open", "draft-b": "open"})

        class FlushRecorder(io.StringIO):
            def __init__(self):
                super().__init__()
                self.flushes = 0

            def flush(self):
                self.flushes += 1
                super().flush()

        recorder = FlushRecorder()
        with redirect_stdout(recorder):
            code = pr.main(["--root", str(self.repo), "--check-all", "--json-lines"])
        self.assertEqual(code, 0)
        lines = parse_json_lines(recorder.getvalue())
        self.assertGreaterEqual(recorder.flushes, len(lines))  # 每行打完都 flush 过

    def test_rows_are_written_before_ledger_save(self):
        # 逐条进度必须在落盘之前就写出去；若把 row 缓存到 save_ledger 之后统一打印，
        # 面板仍然要等整批——这条用例在 save_ledger 调用的一刻检查 stdout。
        self._seed({"draft-a": "open", "draft-b": "open"})
        out = io.StringIO()
        seen = {}
        real_save = pr.save_ledger

        def checking_save(root, data, expect_sha=None):
            seen["stdout"] = out.getvalue()
            return real_save(root, data, expect_sha=expect_sha)

        with redirect_stdout(out), mock.patch.object(pr, "save_ledger", side_effect=checking_save):
            code = pr.main(["--root", str(self.repo), "--check-all", "--json-lines"])
        self.assertEqual(code, 0)
        at_save = [json.loads(line) for line in seen.get("stdout", "").splitlines() if line.strip()]
        self.assertEqual([line.get("type") for line in at_save], ["row", "row"],
                         seen.get("stdout", ""))
        self.assertEqual(sorted(line["draft"] for line in at_save), ["draft-a", "draft-b"])
        self.assertNotIn("done", [line.get("type") for line in at_save])

    def test_cas_failure_ends_with_single_done_line(self):
        self._seed({"draft-a": "open"})
        conflict = pr.CasConflict("a" * 64, "b" * 64)
        with mock.patch.object(pr, "save_ledger", side_effect=conflict):
            code, text = run_cli_lines("--root", str(self.repo), "--check-all", "--json-lines")
        self.assertEqual(code, 0, text)
        lines = parse_json_lines(text)
        self.assertEqual(len(text.splitlines()), 2, text)  # 一行 row + 一行 done
        rows, done = self._rows_and_done(text)
        self.assertEqual([row["draft"] for row in rows], ["draft-a"])
        self.assertFalse(done["ok"])
        self.assertEqual(done["error"]["code"], "E_CAS")
        self.assertTrue(done["error"]["message"])
        self.assertEqual([item["draft"] for item in done["checked"]], ["draft-a"])

    def test_ledger_failure_ends_with_single_done_line(self):
        self._seed({"draft-a": "open"})
        with mock.patch.object(pr, "save_ledger", side_effect=pr.LedgerError("写锁不可用")):
            code, text = run_cli_lines("--root", str(self.repo), "--check-all", "--json-lines")
        self.assertEqual(code, 0, text)
        self.assertEqual(len(text.splitlines()), 2, text)
        _rows, done = self._rows_and_done(text)
        self.assertFalse(done["ok"])
        self.assertEqual(done["error"]["code"], "E_LEDGER")
        self.assertEqual(done["error"]["message"], "写锁不可用")
        self.assertTrue(done["write_failed"])
        self.assertEqual([item["draft"] for item in done["checked"]], ["draft-a"])

    def test_done_line_carries_write_failed_with_queried_state(self):
        # 查询成功、落盘被拒：done 行要带 write_failed，checked[] 保留平台查到的状态。
        # 与上面的「查询失败 + 落盘失败」分开：这里 checked[].ok 是 true。
        self._seed({"draft-a": "open"})
        entry = {"platform": "github", "repo": "o/r", "number": 1,
                 "url": "https://github.com/o/r/pull/1", "state": "merged",
                 "source": "platform", "checked_at": "2026-11-06T10:00:00+08:00"}

        def fake_run_check(ledger, key, adapters):
            return dict(entry), None, ""

        with mock.patch.object(pr, "_run_check", side_effect=fake_run_check), \
                mock.patch.object(pr, "save_ledger",
                                  side_effect=pr.LedgerError("台账写不进去：x（拒绝访问）")):
            code, text = run_cli_lines("--root", str(self.repo), "--check-all", "--json-lines")
        self.assertEqual(code, 0, text)
        _rows, done = self._rows_and_done(text)
        self.assertFalse(done["ok"])
        self.assertTrue(done["write_failed"])
        self.assertEqual(done["error"]["code"], "E_LEDGER")
        self.assertEqual(done["checked"], [{"draft": "draft-a", "ok": True, "state": "merged"}])

    def test_unexpected_error_after_rows_is_single_line_json(self):
        # 已打 row 之后抛未预期异常：最后一行的错误 JSON 必须是一行 compact JSON，
        # 不能是多行缩进 JSON（面板逐行扫不出来，会退化成 E_OUTPUT 并把裸 JSON 拼进提示）。
        self._seed({"draft-a": "open", "draft-b": "open"})
        row_printed = threading.Event()
        real_print = pr._print_json_line
        real_run = pr._run_check

        def counting_print(payload):
            if payload.get("type") == "row":
                row_printed.set()
            real_print(payload)

        def flaky(ledger, key, adapters):
            if key == "draft-b":
                row_printed.wait(2)
                raise RuntimeError("boom")
            return real_run(ledger, key, adapters)

        with mock.patch.object(pr, "_print_json_line", side_effect=counting_print), \
                mock.patch.object(pr, "_run_check", side_effect=flaky):
            code, text = run_cli_lines("--root", str(self.repo), "--check-all", "--json-lines")
        self.assertEqual(code, 1, text)
        lines = parse_json_lines(text)  # 每行都能单独解析
        self.assertEqual(len(text.splitlines()), 2, text)
        self.assertEqual(lines[0].get("type"), "row")
        self.assertEqual(lines[0]["draft"], "draft-a")
        last = lines[-1]
        self.assertFalse(last["ok"])
        self.assertEqual(last["error"]["code"], "E_INTERNAL")
        self.assertIn("RuntimeError: boom", last["error"]["message"])

    def test_json_lines_and_json_are_mutually_exclusive(self):
        code, payload = run_cli("--root", str(self.repo), "--check-all",
                                "--json", "--json-lines")
        self.assertEqual(code, 2, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "E_ARGS")

    def test_json_lines_requires_check_all(self):
        code, payload = run_cli("--root", str(self.repo), "--json-lines")
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["error"]["code"], "E_ARGS")

    def test_default_check_all_still_single_json_document(self):
        self._seed({"draft-a": "open"})
        code, payload = run_cli("--root", str(self.repo), "--check-all")
        self.assertEqual(code, 0, payload)
        self.assertNotIn("type", payload)
        self.assertEqual([item["draft"] for item in payload["checked"]], ["draft-a"])


class LogLockTest(unittest.TestCase):
    """log_lock 的跨进程语义：抢锁失败要等而不是抛 Permission denied。

    宿主重启瞬间旧进程还握着锁文件句柄（Windows 上 open 都可能被拒），log_lock 必须
    把这 10 秒都用来轮询——拿得到就 yield True，等满 10 秒才 yield False，不能像
    修复前那样在 open/locking 失败时直接抛 OSError 给写侧。
    """

    def test_contended_lock_eventually_acquires(self):
        import scripts.exec_log_path as elp
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "shared.json"
            start = threading.Event()
            released = threading.Event()
            results = {}

            def holder():
                with elp.log_lock(target) as locked:
                    results["holder_locked"] = locked
                    start.set()
                    released.wait(5)

            def waiter():
                start.wait(5)
                with elp.log_lock(target) as locked:
                    results["waiter_locked"] = locked

            t1 = threading.Thread(target=holder)
            t2 = threading.Thread(target=waiter)
            t1.start()
            t2.start()
            # holder 持锁 0.3 秒后松开，waiter 应该在这之后拿到锁。
            self.assertTrue(start.wait(5))
            time.sleep(0.3)
            released.set()
            t1.join(5)
            t2.join(5)
            self.assertFalse(t1.is_alive())
            self.assertFalse(t2.is_alive())
            self.assertTrue(results.get("holder_locked"))
            self.assertTrue(results.get("waiter_locked"))


if __name__ == "__main__":
    unittest.main()
