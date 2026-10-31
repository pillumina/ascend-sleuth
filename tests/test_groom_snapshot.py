"""Groom 快照：fetch / 只读 worktree / 索引校验 / 离线降级 / 不碰源工作区。"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.groom_fixtures import git, init_repo, make_index, run_py, write_case  # noqa: E402
from groom_snapshot import build_snapshot, list_remotes  # noqa: E402


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-snap-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.origin = base / "origin.git"
        git(base, "init", "--bare", "-q", str(self.origin))
        self.repo = init_repo(base / "repo", {
            "knowledge/common/interrupt/CASE-A.yaml": dict(cid="CASE-A", sig="CASE-A"),
        })
        make_index(self.repo)
        (self.repo / "notes.txt").write_text("original\n", encoding="utf-8")
        git(self.repo, "add", "notes.txt")
        git(self.repo, "commit", "-qm", "notes")
        git(self.repo, "remote", "add", "origin", str(self.origin))
        git(self.repo, "push", "-q", "-u", "origin", "main")
        self.snaps = base / "snaps"

    def _push_new_commit(self):
        other = Path(self.tmp.name) / "other"
        subprocess.run(["git", "clone", "-q", "-b", "main", str(self.origin), str(other)], check=True,
                       capture_output=True)
        git(other, "config", "user.email", "other@example.com")
        git(other, "config", "user.name", "Other")
        write_case(other, "knowledge/common/interrupt/CASE-B.yaml", cid="CASE-B", sig="CASE-B")
        git(other, "add", "-A")
        git(other, "commit", "-qm", "add B")
        git(other, "push", "-q", "origin", "main")
        return git(other, "rev-parse", "HEAD").stdout.strip()

    def test_fetch_creates_isolated_worktree_and_preserves_source(self):
        tracked = self.repo / "notes.txt"
        tracked.write_text("dirty local edit\n", encoding="utf-8")
        draft = self.repo / "postmortems" / "inbox" / "local-draft.case.yaml"
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text("cases: [{id: LOCAL-1}]\n", encoding="utf-8")

        meta, rc = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc, 0, meta)
        self.assertTrue(meta["fresh"])
        self.assertTrue(meta["authoritative"])
        self.assertEqual(meta["index"]["state"], "verified")
        self.assertTrue(meta["source_worktree_dirty"])
        self.assertNotEqual(Path(meta["worktree"]).resolve(), self.repo.resolve())
        # 源工作区的本地改动与未跟踪草稿原样保留
        self.assertEqual(tracked.read_text(encoding="utf-8"), "dirty local edit\n")
        self.assertTrue(draft.exists())
        # 快照是独立检出：它不包含未提交的 notes 改动
        self.assertNotIn("dirty local edit", (Path(meta["worktree"]) / "notes.txt").read_text(encoding="utf-8"))

    def test_fetch_sees_new_remote_commit(self):
        meta, rc = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc, 0)
        first = meta["commit"]
        new = self._push_new_commit()
        meta2, rc2 = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc2, 0)
        self.assertEqual(meta2["commit"], new)
        self.assertNotEqual(meta2["commit"], first)
        self.assertTrue((Path(meta2["worktree"]) / "knowledge/common/interrupt/CASE-B.yaml").exists())

    def test_offline_is_explicit_and_non_authoritative(self):
        git(self.repo, "remote", "set-url", "origin", str(Path(self.tmp.name) / "missing.git"))
        meta, rc = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc, 2)
        self.assertFalse(meta["ok"])
        self.assertFalse(meta["authoritative"])

        meta2, rc2 = build_snapshot(self.repo, snapshot_dir=self.snaps, offline=True)
        self.assertEqual(rc2, 0, meta2)
        self.assertFalse(meta2["fresh"])
        self.assertFalse(meta2["authoritative"])

    def test_stale_index_is_rebuilt_inside_snapshot_only(self):
        new = self._push_new_commit()          # 只加了 case，没有重建索引
        meta, rc = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc, 0, meta)
        self.assertEqual(meta["commit"], new)
        self.assertEqual(meta["index"]["state"], "rebuilt", meta["index"])
        # 源仓库的索引没有被这次快照改动（还是 HEAD 里那份）
        status = git(self.repo, "status", "--porcelain").stdout
        self.assertNotIn("knowledge/_index", status)

    def test_cli_auto_selects_sole_remote(self):
        p = run_py(self.repo, "scripts/groom_snapshot.py", "--json",
                   "--snapshot-dir", str(self.snaps))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["remote"], "origin")
        self.assertIn("只有一个远端", p.stderr)

    def test_cli_refuses_to_guess_when_multiple_remotes(self):
        git(self.repo, "remote", "add", "upstream",
            "https://example.invalid/ascend-sleuth.git")
        p = run_py(self.repo, "scripts/groom_snapshot.py", "--json",
                   "--snapshot-dir", str(self.snaps))
        self.assertEqual(p.returncode, 3)
        self.assertIn("--remote", p.stderr)

    def test_lists_remotes_and_records_selected_source(self):
        git(self.repo, "remote", "add", "upstream",
            "https://example.invalid/ascend-sleuth.git")
        rows = {r["name"] for r in list_remotes(self.repo)}
        self.assertIn("origin", rows)
        self.assertIn("upstream", rows)
        meta, rc = build_snapshot(self.repo, snapshot_dir=self.snaps, remote="origin")
        self.assertEqual(rc, 0, meta)
        self.assertEqual(meta["remote"], "origin")
        self.assertNotIn("remote_url", meta)
        self.assertNotIn("remote_kind", meta)

    def test_reuses_same_worktree(self):
        meta1, _ = build_snapshot(self.repo, snapshot_dir=self.snaps)
        meta2, _ = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(meta1["worktree"], meta2["worktree"])

    def test_modified_source_case_forces_snapshot_rebuild(self):
        meta1, _ = build_snapshot(self.repo, snapshot_dir=self.snaps)
        worktree = Path(meta1["worktree"])
        case = worktree / "knowledge/common/interrupt/CASE-A.yaml"
        original = case.read_text(encoding="utf-8")
        case.write_text(original.replace("root_cause:", "root_cause: TAMPERED\n    #", 1),
                        encoding="utf-8")
        self.assertIn("TAMPERED", case.read_text(encoding="utf-8"))

        meta2, rc = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc, 0, meta2)
        self.assertEqual(meta2["commit"], meta1["commit"])
        self.assertEqual(meta2["index"]["state"], "verified", meta2["index"])
        # 被改过的源 Case 不得被当成该 commit 的权威表示：复用前必须重建
        self.assertNotIn("TAMPERED", case.read_text(encoding="utf-8"))
        self.assertEqual(case.read_text(encoding="utf-8"), original)

    def test_snapshot_worktree_does_not_pollute_source_status(self):
        build_snapshot(self.repo, snapshot_dir=self.snaps)
        status = git(self.repo, "status", "--porcelain").stdout
        self.assertNotIn(".groom", status)


if __name__ == "__main__":
    unittest.main()
