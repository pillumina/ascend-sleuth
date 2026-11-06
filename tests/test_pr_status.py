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

    def test_upstream_remote_recommended(self):
        self._set_upstream()
        targets = pr.list_targets(self.repo)
        self.assertEqual(targets["recommendation"],
                         {"remote": "origin", "base": "main", "reason": "当前分支的上游"})

    def test_single_remote_recommended_when_no_saved_target(self):
        targets = pr.list_targets(self.repo)
        self.assertEqual(targets["recommendation"]["reason"], "只有一个远端")

    def test_multiple_remotes_without_signal_gives_null(self):
        git(self.repo, "remote", "add", "backup", "https://gitlab.com/o/r.git")
        targets = pr.list_targets(self.repo)
        self.assertIsNone(targets["recommendation"])

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


if __name__ == "__main__":
    unittest.main()
