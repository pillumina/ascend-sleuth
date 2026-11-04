"""知识库漂移检查：只报在途诊断用过的 case，终态单与无版本单分开处理。

为什么：续接时如果 case 在中断期间变过，续接方可能按旧内容往下走。这组测试钉住三条判据：
有漂移要报出来；已收尾的单不报；没有 `kb_rev` 的单报"不可比"而不是静默当成没变。
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kb_drift  # noqa: E402

CASE = """cases:
  - id: {cid}
    title: "漂移测试 {cid}"
    category: interrupt
    symptoms:
      - "症状 {cid}"
"""


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=test@example.com",
         "-c", "user.name=test", *args],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return r.stdout.strip()


class DriftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        git(self.repo, "init")
        (self.repo / "trace-status.yaml").write_text(
            (ROOT / "trace-status.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        self.case_path = self.repo / "knowledge" / "inference" / "vllm-ascend" / "VLLM-ASC-1.yaml"
        self.case_path.parent.mkdir(parents=True)
        self.case_path.write_text(CASE.format(cid="VLLM-ASC-1"), encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "init")
        self.rev = git(self.repo, "rev-parse", "--short", "HEAD")
        self.traces = self.repo / "traces"
        self.traces.mkdir()
        self.write_trace("s1", self.rev, "in_progress", "VLLM-ASC-1")

    def tearDown(self):
        self.tmp.cleanup()

    def write_trace(self, sid: str, rev: str | None, status: str, case: str):
        lines = [f'session_id: "{sid}"', f"status: {status}"]
        if rev:
            lines.append(f'kb_rev: "{rev}"')
        lines += [f'active_case: "{case}"', "trace:", "  - {role: user, step: 1}", ""]
        (self.traces / f"{sid}.yaml").write_text("\n".join(lines), encoding="utf-8")

    def scan(self, *args: str):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = kb_drift.main(["--root", str(self.repo), "--traces", str(self.traces), "--json", *args])
        return rc, json.loads(out.getvalue())

    def commit_case_change(self, cid: str = "VLLM-ASC-1"):
        self.case_path.write_text(CASE.format(cid=cid) + "    tags: [changed]\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "change case")

    def test_reports_case_changed_after_trace(self):
        self.commit_case_change()
        _rc, doc = self.scan("--session", "s1")
        self.assertEqual(doc["sessions"][0]["sessionId"], "s1")
        self.assertEqual(doc["sessions"][0]["cases"][0]["id"], "VLLM-ASC-1")
        self.assertEqual(doc["sessions"][0]["cases"][0]["how"], "committed")

    def test_terminal_trace_is_not_reported(self):
        self.write_trace("s1", self.rev, "resolved", "VLLM-ASC-1")
        self.commit_case_change()
        _rc, doc = self.scan()
        self.assertEqual(doc["sessions"], [])
        self.assertEqual(doc["terminalSkipped"], 1)

    def test_trace_without_kb_rev_is_uncomparable(self):
        self.write_trace("s1", None, "in_progress", "VLLM-ASC-1")
        self.commit_case_change()
        _rc, doc = self.scan()
        self.assertEqual(doc["sessions"], [])
        self.assertEqual(doc["uncomparable"], 1)

    def test_in_place_id_rename_is_seen_via_old_content(self):
        # 同一个文件把 case id 从 VLLM-ASC-1 改成 VLLM-ASC-9：只看 HEAD 会漏掉旧 id。
        self.case_path.write_text(CASE.format(cid="VLLM-ASC-9"), encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "rename id in place")
        _rc, doc = self.scan()
        ids = [c["id"] for row in doc["sessions"] for c in row["cases"]]
        self.assertIn("VLLM-ASC-1", ids)

    def test_working_tree_rename_is_seen(self):
        new_path = self.case_path.with_name("VLLM-ASC-1-renamed.yaml")
        git(self.repo, "mv", str(self.case_path.relative_to(self.repo)),
            str(new_path.relative_to(self.repo)))
        _rc, doc = self.scan()
        hits = [c for row in doc["sessions"] for c in row["cases"] if c["id"] == "VLLM-ASC-1"]
        self.assertTrue(hits, doc)

    def test_dirty_trace_marks_version_imprecise(self):
        trace = self.traces / "s1.yaml"
        trace.write_text(trace.read_text(encoding="utf-8").replace("trace:", 'kb_rev_dirty: "true"\ntrace:'),
                         encoding="utf-8")
        self.commit_case_change()
        _rc, doc = self.scan()
        self.assertTrue(doc["sessions"][0]["dirty"])

    def test_committed_delete_is_seen_via_old_content(self):
        self.case_path.unlink()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "delete case")
        _rc, doc = self.scan()
        self.assertEqual(doc["sessions"][0]["cases"][0]["id"], "VLLM-ASC-1")

    def test_bad_rev_is_uncomparable(self):
        self.write_trace("s1", "deadbee", "in_progress", "VLLM-ASC-1")
        _rc, doc = self.scan()
        self.assertEqual(doc["sessions"], [])
        self.assertEqual(doc["uncomparable"], 1)

    def test_check_returns_one_only_when_drifted(self):
        self.commit_case_change()
        self.assertEqual(self.scan()[0], 0)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = kb_drift.main(["--root", str(self.repo), "--traces", str(self.traces), "--check"])
            rc2 = kb_drift.main(["--root", str(self.repo), "--traces", str(self.traces), "--check",
                                 "--session", "no-such-session"])
        self.assertEqual(rc, 1)
        self.assertEqual(rc2, 0)

    def test_working_tree_change_is_seen(self):
        self.write_trace("s1", self.rev, "in_progress", "VLLM-ASC-2")
        new_case = self.repo / "knowledge" / "inference" / "vllm-ascend" / "VLLM-ASC-2.yaml"
        new_case.write_text(CASE.format(cid="VLLM-ASC-2"), encoding="utf-8")
        _rc, doc = self.scan()
        hits = [c for row in doc["sessions"] for c in row["cases"] if c["id"] == "VLLM-ASC-2"]
        self.assertTrue(hits, doc)
        self.assertEqual(hits[0]["how"], "working-tree")


if __name__ == "__main__":
    unittest.main()


class RemoteDriftTest(unittest.TestCase):
    """带 kb_remote_rev 的新 trace：比远端分支；旧 trace 保持与本机 HEAD 比。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "trace-status.yaml").write_text(
            (ROOT / "trace-status.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        self.case_path = self.repo / "knowledge" / "inference" / "vllm-ascend" / "VLLM-ASC-1.yaml"
        self.case_path.parent.mkdir(parents=True)
        self.case_path.write_text(CASE.format(cid="VLLM-ASC-1"), encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "init")
        self.rev = git(self.repo, "rev-parse", "--short", "HEAD")
        self.bare = self.base / "origin.git"
        git(self.base, "init", "--bare", "-q", str(self.bare))
        git(self.repo, "remote", "add", "origin", str(self.bare))
        git(self.repo, "push", "-q", "-u", "origin", "main")
        self.other = self.base / "other"
        git(self.base, "clone", "-q", "-b", "main", str(self.bare), str(self.other))
        self.traces = self.repo / "traces"
        self.traces.mkdir()
        settings = self.repo / ".local" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({
            "schema": "ascend-sleuth-settings/1",
            "sync": {"remote": "origin", "branch": "main",
                     "enabled": True, "auto_merge": True},
        }), encoding="utf-8")

    def push_case_change(self):
        path = self.other / "knowledge" / "inference" / "vllm-ascend" / "VLLM-ASC-1.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(CASE.format(cid="VLLM-ASC-1") + "    tags: [changed]\n", encoding="utf-8")
        git(self.other, "add", ".")
        git(self.other, "commit", "-m", "change case upstream")
        git(self.other, "push", "-q", "origin", "main")
        return git(self.other, "rev-parse", "--short", "HEAD")

    def write_trace(self, sid: str, rev: str, *, remote_fields: bool = True,
                    remote_rev: str = None):
        lines = [f'session_id: "{sid}"', "status: in_progress"]
        if rev:
            lines.append(f'kb_rev: "{rev}"')
        if remote_fields:
            lines += ['kb_remote: "origin/main"',
                      f'kb_remote_rev: "{remote_rev if remote_rev is not None else rev}"']
        lines += ['active_case: "VLLM-ASC-1"', "trace:", "  - {role: user, step: 1}", ""]
        (self.traces / f"{sid}.yaml").write_text("\n".join(lines), encoding="utf-8")

    def scan(self, *args: str):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = kb_drift.main(["--root", str(self.repo), "--traces", str(self.traces),
                                "--json", *args])
        return rc, json.loads(out.getvalue())

    def test_remote_drift_is_reported_after_fetch(self):
        self.write_trace("s1", self.rev)
        upstream = self.push_case_change()
        _rc, doc = self.scan("--session", "s1")
        self.assertTrue(doc["fetch"]["ok"])
        self.assertEqual(len(doc["sessions"]), 1)
        self.assertEqual(doc["sessions"][0]["targetRev"], "origin/main")
        self.assertEqual(doc["sessions"][0]["cases"][0]["id"], "VLLM-ASC-1")
        self.assertEqual(doc["sessions"][0]["cases"][0]["how"], "committed")
        self.assertNotEqual(upstream, self.rev)

    def test_no_fetch_uses_stale_local_ref(self):
        self.write_trace("s1", self.rev)
        self.push_case_change()
        _rc, doc = self.scan("--session", "s1", "--no-fetch")
        self.assertEqual(doc["sessions"], [])
        self.assertEqual(doc["fetch"]["reason"], "no-fetch")

    def test_old_trace_without_remote_fields_compares_to_head(self):
        self.write_trace("s1", self.rev, remote_fields=False)
        self.case_path.write_text(CASE.format(cid="VLLM-ASC-1") + "    tags: [local]\n",
                                  encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "change case locally")
        _rc, doc = self.scan("--session", "s1", "--no-fetch")
        self.assertEqual(len(doc["sessions"]), 1)
        self.assertEqual(doc["sessions"][0]["targetRev"], "HEAD")

    def test_old_trace_does_not_report_remote_drift(self):
        # 旧 trace 没有 kb_remote_rev：远端变了也不按远端比，仍走本机 HEAD 那套。
        self.write_trace("s1", self.rev, remote_fields=False)
        self.push_case_change()
        _rc, doc = self.scan("--session", "s1")
        self.assertEqual(doc["sessions"], [])
        self.assertEqual(doc["uncomparable"], 0)

    def test_new_trace_without_usable_remote_ref_is_uncomparable(self):
        self.write_trace("s1", self.rev, remote_fields=True, remote_rev="deadbee")
        path = self.traces / "s1.yaml"
        path.write_text(path.read_text(encoding="utf-8").replace(
            'kb_remote: "origin/main"', 'kb_remote: "nope/missing"'), encoding="utf-8")
        _rc, doc = self.scan("--session", "s1", "--no-fetch")
        self.assertEqual(doc["sessions"], [])
        self.assertEqual(doc["uncomparable"], 1)
