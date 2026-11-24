"""演进信号记录的回归测试。

钉住四件事，因为交接口径全压在它们上面：

1. 文件名是内容哈希：同一条信号重复出现得到同一个文件，只累加次数（不重号、不去重掉证据）；
2. 证据改了就换文件：不做模糊合并，宁可多一条也不静默并掉；
3. 导出是纯 Markdown，一条信号一节，带组件、证据、出处与次数——拿批的人可以直接贴；
4. 坏文件不静默跳过：报错退 2，免得"导出成功但少了一条"。
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import evolve_signals as ES  # noqa: E402


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._saved = os.environ.get("ASCEND_SLEUTH_DEPLOYMENT")
        os.environ["ASCEND_SLEUTH_DEPLOYMENT"] = "test-dep"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("ASCEND_SLEUTH_DEPLOYMENT", None)
        else:
            os.environ["ASCEND_SLEUTH_DEPLOYMENT"] = self._saved
        self.tmp.cleanup()

    def add(self, **kw):
        base = dict(signal="T10", signal_text="自审发现的缺口",
                    target="skills/evolve-check/SKILL.md", evidence="证据一",
                    trajectory=["products/X(submitted)"], suggested="建议一")
        base.update(kw)
        return ES.add(self.root, **base)

    def test_id_is_content_hash_and_stable(self):
        a = self.add()
        b = self.add()
        self.assertEqual(a["doc"]["id"], b["doc"]["id"])
        self.assertEqual(a["path"].name, f"test-dep-{a['doc']['id']}.yaml")

    def test_repeat_increments_occurrences_and_keeps_file(self):
        self.add()
        second = self.add(trajectory=["products/Y(submitted)"])
        self.assertEqual(second["doc"]["occurrences"], 2)
        self.assertEqual(len(list((self.root / "proposals" / "signals").glob("*.yaml"))), 1)
        self.assertIn("products/Y(submitted)", second["doc"]["trajectory"])

    def test_changed_evidence_is_a_new_file(self):
        self.add()
        self.add(evidence="证据二")
        files = list((self.root / "proposals" / "signals").glob("*.yaml"))
        self.assertEqual(len(files), 2)

    def test_export_markdown_shape(self):
        self.add(signal="T3", signal_text="重复手动动作", target="scripts/replay_golden.py",
                 evidence="同一命令手工跑了 3 次", suggested="加过滤", trajectory=[])
        self.add()
        self.add()
        items = ES.collect(self.root)
        md = ES.render_md(sorted(items, key=lambda pd: -int(pd[1].get("occurrences") or 1)))
        self.assertTrue(md.startswith("# 演进信号批次：test-dep，2 条"))
        self.assertIn("## 1. [T10] 自审发现的缺口", md)
        self.assertIn("- 组件：`skills/evolve-check/SKILL.md`", md)
        self.assertIn("- 出处：`products/X(submitted)`", md)
        self.assertIn("2 次", md)

    def test_cli_export_since_filter(self):
        self.add()
        doc = ES.load(next((self.root / "proposals" / "signals").glob("*.yaml")))
        out = io.StringIO()
        with redirect_stdout(out):
            rc = ES.main(["--root", str(self.root), "export", "--since", "2999-01-01"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.getvalue().strip(), "")
        self.assertTrue(doc["first_seen"])

    def test_cli_export_out_file(self):
        self.add()
        dest = self.root / "out" / "signals.md"
        with redirect_stdout(io.StringIO()):
            rc = ES.main(["--root", str(self.root), "export", "--out", str(dest)])
        self.assertEqual(rc, 0)
        self.assertIn("演进信号批次", dest.read_text(encoding="utf-8"))

    def test_broken_file_exits_2(self):
        d = self.root / "proposals" / "signals"
        d.mkdir(parents=True)
        (d / "bad.yaml").write_text("id: ''\n", encoding="utf-8")
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = ES.main(["--root", str(self.root), "list"])
        self.assertEqual(rc, 2)
        self.assertIn("解析失败", err.getvalue())

    def test_list_json(self):
        self.add()
        out = io.StringIO()
        with redirect_stdout(out):
            rc = ES.main(["--root", str(self.root), "list", "--json"])
        self.assertEqual(rc, 0)
        self.assertIn('"signal": "T10"', out.getvalue())

    def test_empty_export_is_silent_success(self):
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            rc = ES.main(["--root", str(self.root), "export"])
        self.assertEqual(rc, 0)
        self.assertIn("无信号可导出", err.getvalue())


class MainCheckoutAnchorTest(unittest.TestCase):
    """信号落主检出：worktree 里写的信号不是孤儿，周批收得走。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.main = base / "main"
        self.main.mkdir()
        self._git("init", "-q")
        (self.main / "README.md").write_text("x\n", encoding="utf-8")
        self._git("add", "README.md")
        self._git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
        self.wt = base / "wt"
        self._git("worktree", "add", "-q", "-b", "b", str(self.wt))
        self._saved = os.environ.get("ASCEND_SLEUTH_DEPLOYMENT")
        os.environ["ASCEND_SLEUTH_DEPLOYMENT"] = "test-dep"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("ASCEND_SLEUTH_DEPLOYMENT", None)
        else:
            os.environ["ASCEND_SLEUTH_DEPLOYMENT"] = self._saved
        self.tmp.cleanup()

    def _git(self, *args):
        subprocess.run(["git", "-C", str(self.main), *args], check=True,
                       capture_output=True, text=True, encoding="utf-8")

    def _add(self, evidence="证据一"):
        return ES.add(self.wt, signal="T10", signal_text="自审发现的缺口",
                      target="skills/evolve-check/SKILL.md", evidence=evidence,
                      trajectory=["products/X(submitted)"], suggested="建议一")

    def test_signals_dir_is_main_checkout(self):
        want = (self.main / "proposals" / "signals").resolve()
        self.assertEqual(ES.signals_dir(self.wt).resolve(), want)
        self.assertEqual(ES.signals_dir(self.main).resolve(), want)

    def test_add_from_worktree_lands_in_main(self):
        r = self._add()
        self.assertEqual(r["path"].parent.resolve(), (self.main / "proposals" / "signals").resolve())
        self.assertTrue(r["path"].is_file())
        self.assertFalse((self.wt / "proposals" / "signals").exists())

    def test_pending_excludes_tracked_files(self):
        r = self._add()
        self.assertEqual([p.name for p in ES.pending(self.wt)], [r["path"].name])
        self._git("add", "proposals/signals/" + r["path"].name)
        self._git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "signal")
        self.assertEqual(ES.pending(self.wt), [])

    def test_sweep_copies_into_worktree_and_archives_source(self):
        r = self._add()
        copied = ES.sweep(self.wt, self.wt)
        self.assertEqual([p.name for p in copied], [r["path"].name])
        self.assertTrue((self.wt / "proposals" / "signals" / r["path"].name).is_file())
        # 原件移进 .swept：pending 立即为空，周批 PR 合入时不会撞未跟踪文件
        self.assertFalse(r["path"].exists())
        self.assertTrue((self.main / "proposals" / "signals" / ".swept" / r["path"].name).is_file())
        self.assertEqual(ES.pending(self.wt), [])

    def test_sweep_into_main_is_noop(self):
        self._add()
        self.assertEqual(ES.sweep(self.wt, self.main), [])
        self.assertEqual(len(ES.pending(self.wt)), 1)

    def test_local_mode_reads_current_checkout(self):
        self._add()
        local = self.wt / "proposals" / "signals"
        self.assertNotEqual(ES.signals_dir(self.wt), ES.signals_dir(self.wt, local=True))
        self.assertEqual(ES.signals_dir(self.wt, local=True), local)
        # 当前检出里没有信号时，--local 读空（PR 自检不能空过主检出那份）
        self.assertEqual(ES.collect(self.wt, local=True), [])


if __name__ == "__main__":
    unittest.main()
