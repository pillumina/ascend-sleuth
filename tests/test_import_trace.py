"""import_trace 的接收侧版本比对：先 fetch，比本机远端分支；失败降级不阻塞。

为什么测它：fetch 失败时若拿本机 HEAD 代替远端，比出来的"一致"会给出错误结论。这里钉住
失败 → 「无法比对」、成功 → 按远端分支判，并且两种情况都不阻断落位。
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

import import_trace  # noqa: E402


def git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", *args],
        cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败：{proc.stderr}")
    return (proc.stdout or "").strip()


class KbVersionStateTest(unittest.TestCase):
    def test_unknown_when_origin_has_no_rev(self):
        state, note = import_trace.kb_version_state("unknown", {"ok": True})
        self.assertEqual(state, "unknown")
        self.assertIn("上家没有记录知识库版本", note)

    def test_fetch_failure_degrades_to_unknown(self):
        state, note = import_trace.kb_version_state(
            "deadbee", {"ok": False, "reason": "timeout", "remote_rev": None})
        self.assertEqual(state, "unknown")
        self.assertIn("无法比对知识库版本", note)
        self.assertIn("fetch 超时", note)

    def test_missing_remote_ref_degrades_to_unknown(self):
        state, note = import_trace.kb_version_state(
            "deadbee", {"ok": True, "remote": "origin", "branch": "main", "remote_rev": None})
        self.assertEqual(state, "unknown")
        self.assertIn("无法比对知识库版本", note)

    def test_match_against_remote_branch(self):
        state, note = import_trace.kb_version_state(
            "deadbee", {"ok": True, "remote": "origin", "branch": "main",
                        "remote_rev": "deadbee"})
        self.assertEqual(state, "match")
        self.assertIn("origin/main", note)

    def test_mismatch_against_remote_branch(self):
        state, note = import_trace.kb_version_state(
            "deadbee", {"ok": True, "remote": "origin", "branch": "main",
                        "remote_rev": "c0ffee0"})
        self.assertEqual(state, "mismatch")
        self.assertIn("上家 deadbee", note)
        self.assertIn("c0ffee0", note)


MANIFEST = """\
schema: ascend-sleuth-handoff/v1
session_id: h1
exported_at: "2026-11-01T10:00:00+08:00"
origin:
  kb_rev: deadbee
contents:
  files: []
"""

TRACE = """\
session_id: "h1"
status: in_progress
kb_rev: "deadbee"
trace: []
"""


class ImportDegradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="import-trace-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "README.md").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "init")
        bare = self.base / "origin.git"
        git(self.base, "init", "--bare", "-q", str(bare))
        git(self.repo, "remote", "add", "origin", str(bare))
        git(self.repo, "push", "-q", "-u", "origin", "main")
        self.traces = self.repo / "traces"
        self.package = self.base / "pkg"
        (self.package / "handoff").mkdir(parents=True)
        (self.package / "handoff" / "h1.yaml").write_text(MANIFEST, encoding="utf-8")
        (self.package / "h1.yaml").write_text(TRACE, encoding="utf-8")

    def run_import(self, sync_result):
        out = io.StringIO()
        argv = ["import_trace.py", str(self.package), "--root", str(self.repo),
                "--traces-root", str(self.traces), "--json"]
        with mock.patch("sys.argv", argv), \
                mock.patch.object(import_trace.kb_sync, "sync",
                                  return_value=sync_result) as sync_mock, \
                contextlib.redirect_stdout(out):
            code = import_trace.main()
        return code, json.loads(out.getvalue()), sync_mock

    def test_fetch_failure_does_not_block_import(self):
        code, doc, sync_mock = self.run_import(
            {"ok": False, "reason": "timeout", "remote": "", "branch": "",
             "remote_rev": None})
        self.assertEqual(code, 0)
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["kb_rev_state"], "unknown")
        self.assertIn("无法比对知识库版本", doc["kb_rev_note"])
        self.assertEqual(doc["kb_sync"], {"ok": False, "reason": "timeout"})
        sync_mock.assert_called_once()
        self.assertTrue((self.traces / "h1.yaml").is_file())

    def test_remote_branch_match_after_successful_fetch(self):
        code, doc, _ = self.run_import(
            {"ok": True, "reason": "", "remote": "origin", "branch": "main",
             "remote_rev": "deadbee"})
        self.assertEqual(code, 0)
        self.assertEqual(doc["kb_rev_state"], "match")
        self.assertTrue((self.traces / "h1.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
