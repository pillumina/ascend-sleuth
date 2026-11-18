"""Candidate Patch：有界校验、隔离 worktree、apply/rollback。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.candidate import (  # noqa: E402
    CandidateError, apply_to_root, create_workspace, rollback_workspace,
    validate_candidate,
)


def candidate(root: Path, old="old line", new="new line"):
    return {
        "candidate_id": "C-1", "target_kind": "skill",
        "target_component": "diagnose.verification_checklist",
        "region": "diagnose.verification_checklist",
        "file": "skills/diagnose/SKILL.md", "base_rev": "HEAD",
        "old_text": old, "new_text": new,
        "evidence": ["trace:t1"], "expected_effect": "test",
    }


class CandidateTest(unittest.TestCase):
    def _repo(self, td: str):
        root = Path(td) / "repo"
        (root / "skills/diagnose").mkdir(parents=True)
        (root / "skills/diagnose/SKILL.md").write_text("before\nold line\nafter\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
        return root

    def test_apply_exactly_once_and_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            data = validate_candidate(candidate(root))
            result = apply_to_root(root, data)
            text = (root / data["file"]).read_text(encoding="utf-8")
            self.assertIn("new line", text)
            self.assertNotEqual(result["before_sha256"], result["after_sha256"])

    def test_duplicate_old_text_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            (root / "skills/diagnose/SKILL.md").write_text("old line\nold line\n", encoding="utf-8")
            with self.assertRaises(CandidateError):
                apply_to_root(root, validate_candidate(candidate(root)))

    def test_worktree_apply_diff_rollback(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            ws = Path(td) / "ws"
            data = validate_candidate(candidate(root))
            create_workspace(root, data, ws)
            self.assertTrue(ws.exists())
            self.assertIn("new line", (ws / data["file"]).read_text(encoding="utf-8"))
            rollback_workspace(root, ws)
            self.assertFalse(ws.exists())


if __name__ == "__main__":
    unittest.main()
