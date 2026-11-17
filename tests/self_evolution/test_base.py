"""运行件落点：默认锚主检出，显式 --root 才落当前检出。"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

from evolve.records import ConclusionStore  # noqa: E402
from evolve.samples import SampleStore  # noqa: E402
from exec_log_path import CHECKOUT_DIRS, resolve_checkout_dir  # noqa: E402

SCRIPT = ROOT / "scripts" / "evolve.py"
EXPECTED = '{"namespace": "inference/vllm-ascend"}'


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", cwd=str(cwd),
    )


class BaseParamTest(unittest.TestCase):
    def test_evolve_is_registered_shared_dir(self):
        self.assertEqual(CHECKOUT_DIRS["evolve"], Path(".s2-replay") / "evolve")

    def test_sample_store_accepts_explicit_base(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "shared" / ".s2-replay" / "evolve"
            store = SampleStore(base=base)
            self.assertEqual(store.base, base)
            sample = store.new(
                id="S-1", object_type="diagnosis", source="https://example.com/1",
                expected={"namespace": "inference/vllm-ascend"},
            )
            self.assertTrue((base / "samples" / f"{sample.id}.yaml").exists())

    def test_conclusion_store_accepts_explicit_base(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / ".s2-replay" / "evolve"
            for store in (ConclusionStore.for_base(base), ConclusionStore(base=base)):
                store.append({"decision": "accept"})
            self.assertTrue((base / "conclusions.jsonl").exists())
            self.assertEqual(len(ConclusionStore(base=base).read()), 2)


class CheckoutResolutionTest(unittest.TestCase):
    def setUp(self):
        if shutil.which("git") is None:
            self.skipTest("需要 git 才能验证 worktree 落点")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.main = (self.root / "main").resolve()
        self.main.mkdir()
        self.assertEqual(git("init", "-q", cwd=self.main).returncode, 0)
        (self.main / "README.md").write_text("x\n", encoding="utf-8")
        self.assertEqual(git("add", "README.md", cwd=self.main).returncode, 0)
        commit = git(
            "-c", "user.email=test@example.com", "-c", "user.name=test",
            "commit", "-q", "-m", "init", cwd=self.main,
        )
        self.assertEqual(commit.returncode, 0, commit.stderr)
        self.worktree = (self.root / "wt").resolve()
        added = git("worktree", "add", "-q", "-b", "evolve-test", str(self.worktree),
                    cwd=self.main)
        self.assertEqual(added.returncode, 0, added.stderr)

    def test_resolver_anchors_main_checkout_from_worktree(self):
        path, where, rel = resolve_checkout_dir("evolve", self.worktree)
        self.assertEqual(where, "shared")
        self.assertEqual(rel, Path(".s2-replay") / "evolve")
        self.assertEqual(Path(path).resolve(), self.main / ".s2-replay" / "evolve")
        self.assertNotEqual(Path(path).resolve(), self.worktree / ".s2-replay" / "evolve")

    def test_cli_default_writes_main_checkout(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "sample", "new", "--id", "S-1",
             "--object-type", "diagnosis", "--source", "https://example.com/1",
             "--expected", EXPECTED],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.worktree),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        main_sample = self.main / ".s2-replay" / "evolve" / "samples" / "S-1.yaml"
        wt_sample = self.worktree / ".s2-replay" / "evolve" / "samples" / "S-1.yaml"
        self.assertTrue(main_sample.exists(), result.stdout)
        self.assertFalse(wt_sample.exists())
        raw = yaml.safe_load(main_sample.read_text(encoding="utf-8"))
        self.assertEqual(raw["id"], "S-1")
        listed = subprocess.run(
            [sys.executable, str(SCRIPT), "sample", "list"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.worktree),
        )
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("S-1", listed.stdout)
        brief = subprocess.run(
            [sys.executable, str(SCRIPT), "brief"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.worktree),
        )
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn("samples: 1", brief.stdout)

    def test_judge_record_uses_same_main_checkout_base(self):
        versions = (
            '{"protocol": "p1", "policy": "policy-3", "base_kb": "9f2c1a", '
            '"candidate_kb": "9f2c1a", "candidate": "4d8e0b", '
            '"model": "deepseek-flash/default"}'
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "judge", "--b", "4", "--c", "0", "--n", "9",
             "--record", "--versions", versions],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.worktree),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        main_record = self.main / ".s2-replay" / "evolve" / "conclusions.jsonl"
        self.assertTrue(main_record.exists(), result.stdout)
        self.assertFalse(
            (self.worktree / ".s2-replay" / "evolve" / "conclusions.jsonl").exists()
        )
        brief = subprocess.run(
            [sys.executable, str(SCRIPT), "brief"],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.worktree),
        )
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn("conclusions: 1", brief.stdout)

    def test_cli_explicit_root_stays_local(self):
        local = self.worktree / "local-root"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "sample", "new", "--id", "S-2",
             "--object-type", "diagnosis", "--source", "https://example.com/2",
             "--expected", EXPECTED, "--root", str(local)],
            capture_output=True, text=True, encoding="utf-8", cwd=str(self.worktree),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((local / ".s2-replay" / "evolve" / "samples" / "S-2.yaml").exists())
        self.assertFalse(
            (self.main / ".s2-replay" / "evolve" / "samples" / "S-2.yaml").exists()
        )


if __name__ == "__main__":
    unittest.main()
