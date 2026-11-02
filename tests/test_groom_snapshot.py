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
from groom_snapshot import build_snapshot, cleanup_snapshot, list_remotes  # noqa: E402


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
        # 快照只物化索引的输入集（knowledge/scripts/metrics）。注意 cone 模式的规则：
        # 仓库根目录下的文件**总是**被包含（notes.txt 在），所以这里断言的是
        # 「检出范围」与「清单外的目录不落盘」，而不是「notes.txt 不存在」。
        self.assertEqual(meta["checkout"]["mode"], "sparse")
        self.assertEqual(meta["checkout"]["paths"], ["knowledge", "scripts"])
        self.assertEqual(
            sorted(git(Path(meta["worktree"]), "sparse-checkout", "list").stdout.split()),
            ["knowledge", "scripts"])
        self.assertNotIn("postmortems", {p.name for p in Path(meta["worktree"]).iterdir()})
        # 快照里的 notes.txt 来自 commit，不是本地那份未提交改动
        self.assertNotIn("dirty local edit",
                         (Path(meta["worktree"]) / "notes.txt").read_text(encoding="utf-8"))

    def test_sparse_snapshot_only_materializes_index_inputs(self):
        meta, rc = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc, 0, meta)
        worktree = Path(meta["worktree"])
        top = {p.name for p in worktree.iterdir() if p.is_dir() and p.name != ".git"}
        self.assertLessEqual(top, {"knowledge", "scripts", "metrics"})
        self.assertTrue((worktree / "knowledge/common/interrupt/CASE-A.yaml").exists())

    def test_sparse_scope_change_forces_rebuild(self):
        meta, rc = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc, 0, meta)
        worktree = Path(meta["worktree"])
        git(worktree, "sparse-checkout", "disable")      # 退化成整树检出（范围漂移）
        # 非稀疏 worktree 上 `sparse-checkout list` 以 128 退出（"this worktree is
        # not sparse"），脚本按 returncode 区分「整树」与「init 过但没 set 的半成品」；
        # 测试这里同样按 check=False 读。
        self.assertEqual(
            git(worktree, "sparse-checkout", "list", check=False).stdout.strip(), "")

        meta2, rc2 = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc2, 0, meta2)
        self.assertEqual(meta2["checkout"]["mode"], "sparse")
        # 范围不一致必须被识别并重建，否则快照的内容范围会悄悄漂移
        self.assertEqual(
            sorted(git(worktree, "sparse-checkout", "list").stdout.split()),
            ["knowledge", "scripts"])

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

    def test_reuses_worktree_without_rebuilding(self):
        meta1, rc = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc, 0, meta1)
        worktree = Path(meta1["worktree"])
        git_file = worktree / ".git"
        before = git_file.stat().st_mtime_ns
        meta2, rc2 = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc2, 0, meta2)
        self.assertEqual(meta1["worktree"], meta2["worktree"])
        # 重建会新写 worktree 元数据（.git 指针文件）；mtime 不变 = 这次真的复用了，
        # 没有清掉重铺。只比路径的话，重建和复用看起来完全一样。
        self.assertEqual(git_file.stat().st_mtime_ns, before)

    def test_cleanup_removes_worktree_and_meta_keeps_latest(self):
        meta, rc = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc, 0, meta)
        worktree = Path(meta["worktree"])
        meta_json = Path(meta["meta_path"])
        self.assertTrue(worktree.exists())
        self.assertTrue(meta_json.exists())

        result = cleanup_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["worktree_removed"])
        self.assertTrue(result["meta_removed"])
        self.assertFalse(worktree.exists())
        self.assertFalse(meta_json.exists())

        # latest.json 保留：它记录"上一次比的是哪个 commit"，是评估过期判定的锚
        latest = self.snaps / "latest.json"
        self.assertTrue(latest.exists())
        doc = json.loads(latest.read_text(encoding="utf-8"))
        self.assertEqual(doc["commit"], meta["commit"])
        self.assertEqual(doc["worktree_state"], "removed")
        self.assertTrue(doc.get("cleaned_at"))

        # 下一次 groom 重新 fetch 并重建，不复用已删目录
        meta2, rc2 = build_snapshot(self.repo, snapshot_dir=self.snaps)
        self.assertEqual(rc2, 0, meta2)
        self.assertTrue(Path(meta2["worktree"]).exists())
        self.assertTrue(Path(meta2["meta_path"]).exists())

    def test_cleanup_cli_reports_removed(self):
        build_snapshot(self.repo, snapshot_dir=self.snaps)
        p = run_py(self.repo, "scripts/groom_snapshot.py", "--cleanup",
                   "--snapshot-dir", str(self.snaps))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("快照已清理", p.stdout)
        self.assertEqual([d.name for d in self.snaps.iterdir() if d.is_dir()], [])

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
