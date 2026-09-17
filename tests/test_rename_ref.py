"""rename_ref：把"移动一个 tracked 文件"变成一条命令。

为什么值得单测：这三处都是**手工做过一次、并且当场踩过**的地方——
  · 被移动文件自己的相对链接要按旧目录重算（手工那次漏了 10 条，跑坏链检查才发现）；
  · `decisions` 块与 `docs/adr/` 是只追加档案，一个字都不能改（改了等于篡改审计链）；
  · 组件键要经别名归一到现址，否则同一处改动被搬家前/后的卡拆成两个键，判据少报且不报错。
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ev_board_data as ebd  # noqa: E402
import rename_ref as rr  # noqa: E402


def _git(root: Path):
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class RenameRefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # 旧文档与新址
        _write(self.root, "docs/old/eval.md", "# 评估\n\n见 [norms.md](../spec/norms.md)。\n")
        _write(self.root, "docs/spec/norms.md", "# 规范\n")
        # 引用它的三类文件：散文裸路径、YAML 注释、markdown 相对链接
        _write(self.root, "README.md", "见 docs/old/eval.md 的门禁分级。\n")
        _write(self.root, "metrics/gates.yaml", "# 谁读：docs/old/eval.md 的周批第 2 步\nversion: 1\n")
        _write(self.root, "docs/guide/other.md", "机制见 [eval.md](../old/eval.md)。\n")
        # 只追加档案：两处都不许改
        _write(self.root, "docs/adr/0001.md", "依据 docs/old/eval.md。\n")
        _write(self.root, "proposals/ideas/EV-2026-001.yaml",
               "id: EV-2026-001\ntitle: t\ndecisions:\n"
               "  - who: agent\n    when: 2026-01-01\n    type: action\n"
               "    conclusion: \"改了 docs/old/eval.md\"\n")
        _git(self.root)

    def _move(self):
        # git mv 不会自己建目录
        (self.root / "docs/guide/deep").mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "mv", "docs/old/eval.md", "docs/guide/deep/eval.md"], cwd=self.root, check=True)

    def test_dry_run_writes_nothing(self):
        self._move()
        rr.main.__wrapped__ if hasattr(rr.main, "__wrapped__") else None
        sys.argv = ["rename_ref.py", "docs/old/eval.md", "docs/guide/deep/eval.md", "--root", str(self.root)]
        rr.main()
        self.assertIn("docs/old/eval.md", (self.root / "README.md").read_text(encoding="utf-8"))
        self.assertFalse((self.root / "proposals/component-aliases.yaml").exists())

    def test_apply_rewrites_all_three_shapes(self):
        self._move()
        sys.argv = ["rename_ref.py", "docs/old/eval.md", "docs/guide/deep/eval.md", "--apply",
                    "--root", str(self.root)]
        rr.main()
        self.assertIn("docs/guide/deep/eval.md", (self.root / "README.md").read_text(encoding="utf-8"))
        self.assertNotIn("docs/old/eval.md", (self.root / "README.md").read_text(encoding="utf-8"))
        self.assertIn("docs/guide/deep/eval.md", (self.root / "metrics/gates.yaml").read_text(encoding="utf-8"))
        # markdown 相对链接：从 docs/guide/ 看应当是同目录
        other = (self.root / "docs/guide/other.md").read_text(encoding="utf-8")
        self.assertIn("[eval.md](deep/eval.md)", other)   # 标签是人读名字，保留不动

    def test_moved_file_own_links_are_rebased(self):
        """被移动文件自己的相对链接：目标没动，链接也会断——必须按旧目录重算。"""
        self._move()
        sys.argv = ["rename_ref.py", "docs/old/eval.md", "docs/guide/deep/eval.md", "--apply",
                    "--root", str(self.root)]
        rr.main()
        moved = (self.root / "docs/guide/deep/eval.md").read_text(encoding="utf-8")
        self.assertIn("[norms.md](../../spec/norms.md)", moved)   # 原为 ../spec/norms.md（深了一层）

    def test_audit_chains_untouched(self):
        self._move()
        sys.argv = ["rename_ref.py", "docs/old/eval.md", "docs/guide/deep/eval.md", "--apply",
                    "--root", str(self.root)]
        rr.main()
        self.assertIn("docs/old/eval.md", (self.root / "docs/adr/0001.md").read_text(encoding="utf-8"))
        card = (self.root / "proposals/ideas/EV-2026-001.yaml").read_text(encoding="utf-8")
        self.assertIn("改了 docs/old/eval.md", card)

    def test_alias_is_appended(self):
        self._move()
        sys.argv = ["rename_ref.py", "docs/old/eval.md", "docs/guide/deep/eval.md", "--apply",
                    "--root", str(self.root)]
        rr.main()
        aliases = ebd.load_component_aliases(self.root)
        self.assertEqual(aliases.get("docs/old/eval.md"), "docs/guide/deep/eval.md")

    def test_refuses_when_new_path_missing(self):
        sys.argv = ["rename_ref.py", "docs/old/eval.md", "docs/guide/nope.md", "--apply",
                    "--root", str(self.root)]
        self.assertEqual(rr.main(), 1)


class ComponentAliasNormalizationTest(unittest.TestCase):
    """别名归一：历史卡（decisions 未回写）与新卡的组件键要落在同一个键上。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        _write(self.root, "proposals/component-aliases.yaml",
               "version: 1\naliases:\n  docs/old/eval.md: docs/guide/deep/eval.md\n")
        _git(self.root)

    def _card(self, cid, text):
        return {"id": cid, "title": text, "decisions": [], "validation": {},
                "source_signals": [{"evidence": text, "trajectory": []}]}

    def test_old_and_new_paths_land_on_one_key(self):
        aliases = ebd.load_component_aliases(self.root)
        old = ebd.derive_surface(self._card("EV-2026-901", "改了 `docs/old/eval.md`"), aliases)
        new = ebd.derive_surface(self._card("EV-2026-902", "改了 `docs/guide/deep/eval.md`"), aliases)
        self.assertEqual(old["basis_path"], new["basis_path"])
        self.assertEqual(new["basis_path"], "docs/guide/deep/eval.md")

    def test_without_aliases_the_key_splits(self):
        """反证：不传别名时两个键就是分开的——这正是判据少报的机制。"""
        old = ebd.derive_surface(self._card("EV-2026-903", "改了 `docs/old/eval.md`"))
        new = ebd.derive_surface(self._card("EV-2026-904", "改了 `docs/guide/deep/eval.md`"))
        self.assertNotEqual(old["basis_path"], new["basis_path"])


class FrozenArtifactGuardTest(unittest.TestCase):
    """按内容哈希钉住的量尺件默认不碰——这条守卫是被工具自己咬过一次才加的。

    开发过程中跑 `--apply` 做幂等回测，顺手把 `eval/golden/**` 的注释路径也改了：
    于是 `holdout --check` 与 `eval-scorecard` 同时红，要重新封存 + 重建账本才能恢复。
    为一句注释付这套摩擦不值得，所以默认跳过并如实报出，要改得显式 `--include-frozen`。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        _write(self.root, "docs/old/eval.md", "# 评估\n")
        _write(self.root, "eval/golden/F1.fixture.yaml", "assertion: top-3  # 口径见 docs/old/eval.md\n")
        _write(self.root, "eval/holdout.yaml",
               "version: 1\nentries:\n- fixture: F1.fixture.yaml\n  sha256: abc\n")
        _git(self.root)

    def _move(self):
        (self.root / "docs/new").mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "mv", "docs/old/eval.md", "docs/new/eval.md"], cwd=self.root, check=True)

    def test_frozen_fixture_is_reported_not_written(self):
        self._move()
        sys.argv = ["rename_ref.py", "docs/old/eval.md", "docs/new/eval.md", "--apply",
                    "--root", str(self.root)]
        rr.main()
        body = (self.root / "eval/golden/F1.fixture.yaml").read_text(encoding="utf-8")
        self.assertIn("docs/old/eval.md", body)          # 一字未改

    def test_include_frozen_writes_it(self):
        self._move()
        sys.argv = ["rename_ref.py", "docs/old/eval.md", "docs/new/eval.md", "--apply",
                    "--include-frozen", "--root", str(self.root)]
        rr.main()
        body = (self.root / "eval/golden/F1.fixture.yaml").read_text(encoding="utf-8")
        self.assertIn("docs/new/eval.md", body)
