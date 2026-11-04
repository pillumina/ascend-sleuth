"""doctor 的知识库同步检查：只读、不联网，判 ok / degraded / off 三态。

为什么单测：体检器把「这台机器能不能同步知识库」压成一行。落后、上次 fetch 失败、
部署声明离线三种情况的结论不同；判错时人看到的是一句"环境齐了"或一条假红。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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

    def write_settings(self):
        path = self.repo / ".local" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": "ascend-sleuth-settings/1",
            "sync": {"remote": "origin", "branch": "main",
                     "enabled": True, "auto_merge": True},
        }), encoding="utf-8")

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
        (self.repo / "deployment.yaml").write_text(
            'evolution:\n  mode: "full"\nsync:\n  mode: "offline"\n', encoding="utf-8")
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


class RegistrationTest(unittest.TestCase):
    def test_kb_sync_is_in_capability_table(self):
        needs = {name for _label, items in doctor.CAPABILITIES for name in items}
        self.assertIn("kb-sync", needs)

    def test_capability_table_accepts_registered_checks(self):
        ids = {name for _label, items in doctor.CAPABILITIES for name in items}
        checks = [{"id": name, "state": doctor.OK} for name in ids]
        row = doctor.check_capability_table(checks)
        self.assertEqual(row["state"], doctor.OK)


if __name__ == "__main__":
    unittest.main()
