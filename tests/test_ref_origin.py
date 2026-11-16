"""ref_origin 的口径回归。

护三件事：
1. 文件级产出处：加入提交 + 把它带进当前分支的第一次合并（PR 号从合并消息取）；
2. 表内条目：同一个文件里后加的一行，定位到「加这一行」的提交，不是文件首次加入；
3. 查不到时拒绝猜：未提交 / 未知 id 返回错误，不拿修改时间或作者顶替。
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ref_origin as ro  # noqa: E402

GIT = shutil.which("git")


def run(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败：{proc.stderr or proc.stdout}")
    return proc.stdout.strip()


@unittest.skipUnless(GIT, "本机没有 git")
class RefOriginTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        run(self.root, "init", "-q")
        run(self.root, "config", "user.email", "test@example.com")
        run(self.root, "config", "user.name", "test")
        run(self.root, "config", "commit.gpgsign", "false")
        (self.root / "references" / "tools").mkdir(parents=True)
        (self.root / "references" / "errors").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, message: str) -> str:
        run(self.root, "add", "-A")
        run(self.root, "commit", "-q", "-m", message)
        return run(self.root, "rev-parse", "HEAD")

    def merge(self, branch: str, message: str) -> str:
        run(self.root, "checkout", "-q", "-b", branch)
        return branch

    def finish_merge(self, branch: str, message: str) -> str:
        run(self.root, "checkout", "-q", "main")
        run(self.root, "merge", "-q", "--no-ff", branch, "-m", message)
        return run(self.root, "rev-parse", "HEAD")

    def test_file_level_origin_and_pr(self):
        (self.root / "references" / "tools" / "a.yaml").write_text(
            "id: a\ntype: tool\ntitle: A\nsummary: A\nsources: [{type: engineer-input}]\n"
            "last_verified: 2026-01-01\nstatus: active\n", encoding="utf-8")
        first = self.commit("add a")
        run(self.root, "branch", "-m", "main")
        self.merge("feat", "feat")
        (self.root / "references" / "tools" / "b.yaml").write_text(
            "id: b\ntype: tool\ntitle: B\nsummary: B\nsources: [{type: engineer-input}]\n"
            "last_verified: 2026-01-01\nstatus: active\n", encoding="utf-8")
        self.commit("add b")
        merge_sha = self.finish_merge("feat", "Merge pull request #7 from x")

        row = ro.lookup(self.root, "a")
        self.assertEqual(row["added"]["sha"], first)
        self.assertEqual(row["added"]["level"], "file")
        self.assertEqual(row["merge"]["sha"], merge_sha)
        self.assertEqual(row["pr"], "#7")

    def test_table_row_uses_row_addition_not_file_creation(self):
        (self.root / "references" / "errors" / "t.yaml").write_text(
            "id: t\ntype: error-code\ntitle: T\nsummary: T\nsources: [{type: engineer-input}]\n"
            "last_verified: 2026-01-01\nstatus: active\ncontent:\n  errors:\n"
            "    - {code: 'A-1', meaning: one}\n", encoding="utf-8")
        self.commit("add table")
        run(self.root, "branch", "-m", "main")
        self.merge("feat", "feat")
        (self.root / "references" / "errors" / "t.yaml").write_text(
            "id: t\ntype: error-code\ntitle: T\nsummary: T\nsources: [{type: engineer-input}]\n"
            "last_verified: 2026-01-01\nstatus: active\ncontent:\n  errors:\n"
            "    - {code: 'A-1', meaning: one}\n    - {code: 'B-2', meaning: two}\n", encoding="utf-8")
        row_sha = self.commit("add code B-2")
        self.finish_merge("feat", "Merge pull request #8 from y")

        row = ro.lookup(self.root, "B-2")
        self.assertEqual(row["added"]["sha"], row_sha)
        self.assertEqual(row["added"]["level"], "row")
        self.assertEqual(row["pr"], "#8")
        # 同一文件里首版本就有的行仍按文件级报
        first = ro.lookup(self.root, "A-1")
        self.assertEqual(first["added"]["level"], "file")

    def test_path_input(self):
        (self.root / "references" / "tools" / "a.yaml").write_text(
            "id: a\ntype: tool\ntitle: A\nsummary: A\nsources: [{type: engineer-input}]\n"
            "last_verified: 2026-01-01\nstatus: active\n", encoding="utf-8")
        self.commit("add a")
        run(self.root, "branch", "-m", "main")
        row = ro.lookup(self.root, str(self.root / "references" / "tools" / "a.yaml"))
        self.assertEqual(row["id"], "a")
        self.assertEqual(row["added"]["level"], "file")
        self.assertIsNone(row["merge"], "没有合并提交时如实报未知，不猜 PR")

    def test_unknown_id_is_an_error(self):
        (self.root / "references" / "tools" / "a.yaml").write_text(
            "id: a\ntype: tool\ntitle: A\nsummary: A\nsources: [{type: engineer-input}]\n"
            "last_verified: 2026-01-01\nstatus: active\n", encoding="utf-8")
        self.commit("add a")
        with self.assertRaises(ro.OriginError) as ctx:
            ro.lookup(self.root, "nope")
        self.assertEqual(ctx.exception.code, "E_NOT_FOUND")

    def test_shallow_clone_does_not_report_boundary_as_addition(self):
        src = self.root / "src"
        src.mkdir()
        run(src, "init", "-q")
        run(src, "config", "user.email", "test@example.com")
        run(src, "config", "user.name", "test")
        run(src, "config", "commit.gpgsign", "false")
        (src / "references" / "tools").mkdir(parents=True)
        (src / "references" / "tools" / "old-1.yaml").write_text(
            "id: old-1\ntype: tool\ntitle: A\nsummary: A\nsources: [{type: engineer-input}]\n"
            "last_verified: 2026-01-01\nstatus: active\n", encoding="utf-8")
        run(src, "add", "-A")
        run(src, "commit", "-q", "-m", "add old")
        (src / "references" / "tools" / "new-2.yaml").write_text(
            "id: new-2\ntype: tool\ntitle: B\nsummary: B\nsources: [{type: engineer-input}]\n"
            "last_verified: 2026-01-01\nstatus: active\n", encoding="utf-8")
        run(src, "add", "-A")
        run(src, "commit", "-q", "-m", "add new")

        dst = self.root / "clone"
        proc = subprocess.run(["git", "clone", "--depth", "1", "--quiet", src.as_uri(), str(dst)],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            self.skipTest("本机 git 不支持本地浅克隆：" + (proc.stderr or "").strip())
        with self.assertRaises(ro.OriginError) as ctx:
            ro.lookup(dst, "old-1")
        self.assertEqual(ctx.exception.code, "E_NOT_FOUND")
        self.assertIn("浅克隆", ctx.exception.message)

    def test_untracked_table_row_is_not_guessed(self):
        table = self.root / "references" / "errors" / "t.yaml"
        table.write_text(
            "id: t\ntype: error-code\ntitle: T\nsummary: T\nsources: [{type: engineer-input}]\n"
            "last_verified: 2026-01-01\nstatus: active\ncontent:\n  errors:\n"
            "    - {code: 'A-1', meaning: one}\n", encoding="utf-8")
        self.commit("add table")
        # 工作区加了 B-2，但没提交：文件能读到这一行，历史里没有。
        table.write_text(
            "id: t\ntype: error-code\ntitle: T\nsummary: T\nsources: [{type: engineer-input}]\n"
            "last_verified: 2026-01-01\nstatus: active\ncontent:\n  errors:\n"
            "    - {code: 'A-1', meaning: one}\n    - {code: 'B-2', meaning: two}\n", encoding="utf-8")
        with self.assertRaises(ro.OriginError) as ctx:
            ro.lookup(self.root, "B-2")
        self.assertEqual(ctx.exception.code, "E_NOT_FOUND")

    def test_untracked_file_is_not_guessed(self):
        (self.root / "references" / "tools" / "a.yaml").write_text(
            "id: a\ntype: tool\ntitle: A\nsummary: A\nsources: [{type: engineer-input}]\n"
            "last_verified: 2026-01-01\nstatus: active\n", encoding="utf-8")
        with self.assertRaises(ro.OriginError) as ctx:
            ro.lookup(self.root, "a")
        self.assertEqual(ctx.exception.code, "E_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
