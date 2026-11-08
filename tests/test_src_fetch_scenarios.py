#!/usr/bin/env python3
"""src_fetch.py 的场景测试：数据目录（source-catalog.d/）+ 通用发现与验证。

护的是「新增一个仓只改数据，不改脚本」这条重构后的承诺。每个场景用
`tempfile.TemporaryDirectory()` 造本地 git 仓 + `--catalog` 夹具 + `--dest` 临时缓存，
全部走真实 CLI（subprocess），不联网。

覆盖的契约：
  - 只改数据新增一个仓：`--find` 命中 → 拉取 → `--verify` 命中 → 再跑走复用；
  - `--verify` 未命中 exit 6，且 stdout 末行不是版本目录；
  - 候选歧义 / `--offline` 候选 ≥2 都 exit 3，且不 clone 进 `--dest`；
  - 版本不存在 exit 3 并给出可用 tag；
  - 零候选 exit 3 并给出下一步命令，`--list-orgs` / `--list-org-repos` 可用；
  - 坏目录 `--self-test` exit 1 并指出哪条规则坏了；
  - `--verify ""` 是用法错 exit 2。
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "src_fetch.py"
SIGNATURE = "foox kernel failed"


def last_line(proc) -> str:
    lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


class SrcFetchScenarioTest(unittest.TestCase):
    """一个场景一个 test；每个 test 自建夹具与缓存，互不共享状态。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.repos_dir = base / "repos"
        self.catalog_dir = base / "catalog"
        self.dest = base / "cache"
        for path in (self.repos_dir, self.catalog_dir, self.dest):
            path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ 夹具构造
    def git(self, cwd, *args, check=True):
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
        if check and proc.returncode != 0:
            self.fail(f"git {' '.join(args)} 失败：\n{proc.stdout}\n{proc.stderr}")
        return proc

    def make_repo(self, name: str, files: dict, tags=("v1.0",)) -> Path:
        """本地 git 仓：一次提交 + 按需打 tag，供 file:// URL 克隆。"""
        path = self.repos_dir / name
        path.mkdir(parents=True)
        self.git(path, "init", "-q")
        for rel, content in files.items():
            target = path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.git(path, "add", "-A")
        self.git(path, "-c", "commit.gpgsign=false",
                 "-c", "user.email=scenario@example.test",
                 "-c", "user.name=Scenario Test",
                 "commit", "-q", "-m", f"fixture {name}")
        for tag in tags:
            self.git(path, "tag", tag)
        return path

    def custom_repo(self, short: str, url: str, keywords, why="夹具仓") -> dict:
        return {
            "repo": f"acme/{short}",
            "sources": [{"host": "custom", "url": url}],
            "why": why,
            "discover": {"any_of": list(keywords)},
        }

    def write_catalog(self, repos, org="acme", name="acme.yaml", layer="acme") -> Path:
        doc = {
            "layer": layer,
            "title": "src_fetch 场景测试夹具",
            "orgs": [{"name": org, "host": "custom", "enumerable": False,
                      "note": "场景测试用的本地夹具组织，不可枚举"}],
            "repos": repos,
            "self_test": [],
        }
        path = self.catalog_dir / name
        path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                        encoding="utf-8")
        return self.catalog_dir

    # ------------------------------------------------------------ CLI 调用
    def run_cli(self, *args) -> subprocess.CompletedProcess:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              cwd=str(REPO_ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env)

    def assertExit(self, proc, expected: int):
        self.assertEqual(proc.returncode, expected,
                         f"exit 期望 {expected}，实际 {proc.returncode}\n"
                         f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}")

    def cat_args(self):
        return ["--catalog", str(self.catalog_dir)]

    # ------------------------------------------------------------ 场景 1
    def test_new_repo_from_data_find_fetch_verify_and_reuse(self):
        """只改数据新增一个仓：--find 命中 → 拉取 → --verify 命中 → 复用。"""
        repo = self.make_repo("ops-foo", {
            "kernel/ops.c": "#include <stdio.h>\n"
                            "if (foox kernel failed) { report(); }\n",
        })
        self.write_catalog([self.custom_repo("ops-foo", repo.as_uri(), ["foox"])])
        args = ["--find", SIGNATURE, "--org", "acme", "--ref", "v1.0",
                *self.cat_args(), "--dest", str(self.dest), "--verify", SIGNATURE]

        first = self.run_cli(*args)
        self.assertExit(first, 0)
        version_dir = Path(last_line(first))
        self.assertTrue(version_dir.is_dir(),
                        f"stdout 末行不是版本目录：{last_line(first)}")
        self.assertEqual(version_dir.name, "v1.0")
        self.assertEqual(version_dir.parent.name, "ops-foo")
        # 命中输出必须带"文件:行"
        self.assertRegex(first.stdout, r"(?m)\S+:\d+:.*foox kernel failed")

        second = self.run_cli(*args)
        self.assertExit(second, 0)
        self.assertIn("复用", second.stdout)
        self.assertEqual(Path(last_line(second)), version_dir)

    # ------------------------------------------------------------ 场景 2
    def test_verify_miss_exits_6_and_last_line_is_not_version_dir(self):
        """--verify 未命中 exit 6；失败不得把版本目录当结果交出来。"""
        repo = self.make_repo("ops-foo", {
            "kernel/ops.c": "int only_foox_path;\nif (foox kernel failed) {}\n",
        })
        self.write_catalog([self.custom_repo("ops-foo", repo.as_uri(), ["foox"])])
        proc = self.run_cli("--find", SIGNATURE, "--org", "acme", "--ref", "v1.0",
                            *self.cat_args(), "--dest", str(self.dest),
                            "--verify", "not-in-tree")

        self.assertExit(proc, 6)
        tail = last_line(proc)
        self.assertTrue(tail.startswith("✗"), f"末行应是失败声明：{tail!r}")
        self.assertNotEqual(tail, str(self.dest.resolve()))
        self.assertFalse(Path(tail).is_absolute(), f"末行不应是路径：{tail!r}")
        self.assertIn("not-in-tree", proc.stderr)

    # ------------------------------------------------------------ 场景 3
    def test_ambiguous_candidates_exit_3_without_clone(self):
        """两个仓都有 v1.0 且签名都命中：不能替人选（exit 3），也不 clone。"""
        one = self.make_repo("ops-foo", {"src/one.c": "if (foox kernel failed) {}\n"})
        two = self.make_repo("ops-bar", {"src/two.c": "if (foox kernel failed) {}\n"})
        self.write_catalog([
            self.custom_repo("ops-foo", one.as_uri(), ["foox"]),
            self.custom_repo("ops-bar", two.as_uri(), ["foox"]),
        ])
        proc = self.run_cli("--find", SIGNATURE, "--org", "acme", "--ref", "v1.0",
                            *self.cat_args(), "--dest", str(self.dest))

        self.assertExit(proc, 3)
        self.assertEqual(list(self.dest.rglob("*")), [], "候选歧义时不应 clone 进 --dest")
        self.assertIn("尝试解析", proc.stdout)          # 逐个试 ref 是预期动作
        self.assertTrue(last_line(proc).startswith("✗"))

    # ------------------------------------------------------------ 场景 4
    def test_offline_with_multiple_candidates_does_not_resolve(self):
        """--offline 且候选 ≥2：只给候选，不发 ls-remote，也不 clone。"""
        one = self.make_repo("ops-foo", {"src/one.c": "if (foox kernel failed) {}\n"})
        two = self.make_repo("ops-bar", {"src/two.c": "if (foox kernel failed) {}\n"})
        self.write_catalog([
            self.custom_repo("ops-foo", one.as_uri(), ["foox"]),
            self.custom_repo("ops-bar", two.as_uri(), ["foox"]),
        ])
        proc = self.run_cli("--find", SIGNATURE, "--org", "acme", "--ref", "v1.0",
                            "--offline", *self.cat_args(), "--dest", str(self.dest))

        self.assertExit(proc, 3)
        self.assertNotIn("尝试解析", proc.stdout)
        self.assertEqual(list(self.dest.rglob("*")), [])
        self.assertIn("离线模式", proc.stderr)

    # ------------------------------------------------------------ 场景 5
    def test_missing_ref_exits_3_with_available_tag_hint(self):
        """版本不存在：exit 3，并提示可用的 tag（v1.0）。"""
        repo = self.make_repo("ops-foo", {"src/one.c": "if (foox kernel failed) {}\n"})
        self.write_catalog([self.custom_repo("ops-foo", repo.as_uri(), ["foox"])])
        proc = self.run_cli("--find", SIGNATURE, "--org", "acme", "--ref", "v9.9.9",
                            *self.cat_args(), "--dest", str(self.dest))

        self.assertExit(proc, 3)
        self.assertIn("v1.0", proc.stdout + proc.stderr)
        self.assertTrue(last_line(proc).startswith("✗"))

    # ------------------------------------------------------------ 场景 6
    def test_zero_candidates_gives_next_steps_and_list_commands(self):
        """签名不命中任何仓：exit 3 + 下一步命令；--list-orgs/--list-org-repos 可用。"""
        repo = self.make_repo("ops-foo", {"src/one.c": "if (foox kernel failed) {}\n"})
        self.write_catalog([self.custom_repo("ops-foo", repo.as_uri(), ["foox"])])

        proc = self.run_cli("--find", "zzz-unmatched-signature", "--org", "acme",
                            "--ref", "v1.0", *self.cat_args(), "--dest", str(self.dest))
        self.assertExit(proc, 3)
        self.assertIn("--list-orgs", proc.stdout)
        self.assertIn("--list-org-repos", proc.stdout)
        self.assertTrue(last_line(proc).startswith("✗"))

        orgs = self.run_cli("--list-orgs", *self.cat_args())
        self.assertExit(orgs, 0)
        self.assertIn("acme", orgs.stdout)

        org_repos = self.run_cli("--list-org-repos", "acme", *self.cat_args())
        self.assertExit(org_repos, 0)
        self.assertIn("acme/ops-foo", org_repos.stdout)

    # ------------------------------------------------------------ 场景 7
    def test_bad_catalog_self_test_reports_rule(self):
        """坏目录（discover 关键词大写）：--self-test exit 1 并点名是哪条规则。"""
        bad_catalog = self.catalog_dir / "bad"
        bad_catalog.mkdir()
        doc = {
            "layer": "bad",
            "title": "坏目录夹具",
            "orgs": [{"name": "acme", "host": "custom", "enumerable": False}],
            "repos": [{
                "repo": "acme/ops-bad",
                "sources": [{"host": "custom", "url": "file:///tmp/does-not-matter"}],
                "why": "坏规则夹具",
                "discover": {"any_of": ["FooX"]},
            }],
            "self_test": [],
        }
        (bad_catalog / "bad.yaml").write_text(
            yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")

        proc = self.run_cli("--self-test", "--catalog", str(bad_catalog))
        self.assertExit(proc, 1)
        report = proc.stderr + proc.stdout
        self.assertIn("FooX", report)
        self.assertIn("ops-bad", report)
        self.assertIn("discover.any_of", report)

    # ------------------------------------------------------------ 场景 8
    def test_empty_verify_is_usage_error_exit_2(self):
        """--verify "" 是用法错（exit 2），不是"验证失败"。"""
        repo = self.make_repo("ops-foo", {"src/one.c": "if (foox kernel failed) {}\n"})
        self.write_catalog([self.custom_repo("ops-foo", repo.as_uri(), ["foox"])])
        proc = self.run_cli(*self.cat_args(), "--verify", "")

        self.assertExit(proc, 2)
        self.assertIn("--verify", proc.stderr)
        self.assertIn("非空", proc.stderr)


    # ------------------------------------------------------------ 场景 9
    def test_offline_with_explicit_repo_reuses_cache_only(self):
        """显式仓名 + --offline：只复用本地缓存，不联网。"""
        repo = self.make_repo("ops-foo", {"src/one.c": "if (foox kernel failed) {}\n"})
        self.write_catalog([self.custom_repo("ops-foo", repo.as_uri(), ["foox"])])
        args = ("acme/ops-foo", "--ref", "v1.0", "--offline", *self.cat_args(),
                "--dest", str(self.dest))

        miss = self.run_cli(*args)
        self.assertExit(miss, 3)
        self.assertNotIn("尝试解析", miss.stdout)
        self.assertEqual(list(self.dest.rglob("*")), [], "离线模式不该 clone")
        self.assertIn("离线模式只复用本地缓存", miss.stderr)

        first = self.run_cli("acme/ops-foo", "--ref", "v1.0", *self.cat_args(),
                             "--dest", str(self.dest))
        self.assertExit(first, 0)
        again = self.run_cli(*args)
        self.assertExit(again, 0)
        self.assertIn("复用", again.stdout)

    # ------------------------------------------------------------ 场景 10
    def test_discover_only_repo_with_custom_source_is_fetchable(self):
        """只进签名候选表（fast_path: false）的仓也要能取地址：不能靠已知表 lookup。"""
        repo = self.make_repo("ops-hidden", {"src/h.c": "if (hidden failure) {}\n"})
        entry = self.custom_repo("ops-hidden", repo.as_uri(), ["hidden"])
        entry["fast_path"] = False
        self.write_catalog([entry])

        proc = self.run_cli("--find", "hidden failure", "--org", "acme", "--ref", "v1.0",
                            *self.cat_args(), "--dest", str(self.dest),
                            "--verify", "hidden failure")
        self.assertExit(proc, 0)
        self.assertTrue(last_line(proc).endswith("/v1.0"))

    # ------------------------------------------------------------ 场景 11
    def test_unknown_repo_in_custom_org_is_usage_error_not_traceback(self):
        """custom host 组织里的未登记仓拿不到地址：给用法错，不能抛 traceback。"""
        self.write_catalog([self.custom_repo("ops-foo", "file:///tmp/not-used", ["foox"])])
        proc = self.run_cli("--find", SIGNATURE, "acme/ops-unknown", "--org", "acme",
                            "--ref", "v1.0", *self.cat_args(), "--dest", str(self.dest))

        self.assertExit(proc, 2)
        self.assertIn("custom", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr + proc.stdout)

    # ------------------------------------------------------------ 场景 12
    def test_bad_catalog_path_is_not_silent(self):
        """--catalog 写错路径：给用法错，不静默当成空目录。"""
        bad = Path(self._tmp.name) / "no-such-catalog"
        proc = self.run_cli("--list", "--catalog", str(bad))

        self.assertExit(proc, 2)
        self.assertIn("不可用", proc.stderr)


    # ------------------------------------------------------------ 场景 13
    def test_explicit_name_for_discover_only_repo_uses_catalog_sources(self):
        """显式写 canonical 的仓（fast_path: false）不能当未知仓去 GitHub 找。"""
        repo = self.make_repo("ops-hidden", {"src/h.c": "if (hidden failure) {}\n"})
        entry = self.custom_repo("ops-hidden", repo.as_uri(), ["hidden"])
        entry["fast_path"] = False
        self.write_catalog([entry])

        proc = self.run_cli("acme/ops-hidden", "--ref", "v1.0", *self.cat_args(),
                            "--dest", str(self.dest))
        self.assertExit(proc, 0)
        self.assertNotIn("未知仓库，默认走 GitHub", proc.stdout)
        self.assertTrue(last_line(proc).endswith("/v1.0"))


    # ------------------------------------------------------------ 场景 14
    def test_explicit_name_falls_back_from_github_to_gitcode(self):
        """显式仓名在 GitHub 解析不到时，自动再试 GitCode（GitCode-only 仓不用进表）。"""
        import contextlib
        import io
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import src_fetch

        remotes = Path(self._tmp.name) / "remotes"
        repo_path = remotes / "gitcode" / "acme" / "ops-foo.git"
        repo_path.mkdir(parents=True)
        self.git(repo_path, "init", "-q")
        (repo_path / "src.c").write_text("if (foox kernel failed) {}\n", encoding="utf-8")
        self.git(repo_path, "add", "-A")
        self.git(repo_path, "-c", "commit.gpgsign=false",
                 "-c", "user.email=scenario@example.test",
                 "-c", "user.name=Scenario Test", "commit", "-q", "-m", "init")
        self.git(repo_path, "tag", "v1.0")

        base = remotes.resolve().as_uri()
        original_hosts = dict(src_fetch.HOSTS)
        old_argv = sys.argv
        try:
            src_fetch.HOSTS.update({
                "github": f"{base}/github/{{owner}}/{{repo}}.git",
                "gitcode": f"{base}/gitcode/{{owner}}/{{repo}}.git",
                "gitee": f"{base}/gitee/{{owner}}/{{repo}}.git",
            })
            sys.argv = ["src_fetch.py", "acme/ops-foo", "--ref", "v1.0",
                        "--dest", str(self.dest), "--verify", SIGNATURE]
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = src_fetch.main()
        finally:
            src_fetch.HOSTS.clear()
            src_fetch.HOSTS.update(original_hosts)
            sys.argv = old_argv

        stdout = out.getvalue()
        self.assertEqual(rc, 0, stdout + err.getvalue())
        self.assertIn("未知仓库，依次试 GitHub 与 GitCode", stdout)
        self.assertIn("github", stdout)          # 先试 GitHub
        self.assertIn("gitcode", stdout)         # 失败后回退
        self.assertTrue(last_line(type("P", (), {"stdout": stdout})).endswith("/v1.0"))


if __name__ == "__main__":
    unittest.main()
