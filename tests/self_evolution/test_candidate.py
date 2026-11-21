"""Candidate Patch：有界校验、隔离 worktree、apply/rollback。"""

import json
import os
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


def tool_candidate(root: Path, old="def fetch(ref):\n    return ref\n",
                   new="def fetch(ref):\n    return ref.strip()\n"):
    return {
        "candidate_id": "C-T1", "target_kind": "tooling",
        "target_component": "tooling.source_fetch",
        "region": "tooling.source_fetch",
        "file": "scripts/src_fetch.py", "base_rev": "HEAD",
        "old_text": old, "new_text": new,
    }


def candidate(root: Path, old="quickly_check old line", new="quickly_check new line"):
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
        (root / "skills/diagnose/SKILL.md").write_text("before\nquickly_check old line\nafter\n", encoding="utf-8")
        (root / "scripts").mkdir()
        (root / "scripts/src_fetch.py").write_text("def fetch(ref):\n    return ref\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
        return root

    def test_traversal_is_rejected(self):
        data = candidate(Path("."))
        data["file"] = "skills/diagnose/../../../x.md"
        with self.assertRaises(CandidateError):
            validate_candidate(data)

    def test_region_marker_is_required(self):
        data = candidate(Path("."), old="unrelated text", new="new")
        with self.assertRaises(CandidateError):
            validate_candidate(data)

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
            (root / "skills/diagnose/SKILL.md").write_text("quickly_check old line\nquickly_check old line\n", encoding="utf-8")
            with self.assertRaises(CandidateError):
                apply_to_root(root, validate_candidate(candidate(root)))

    def test_tooling_candidate_applies_with_checks(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            data = tool_candidate(root)
            data["checks"] = ["py_compile", "diff_check"]
            validated = validate_candidate(data)
            apply_to_root(root, validated)
            self.assertIn("strip", (root / "scripts/src_fetch.py").read_text(encoding="utf-8"))

    def test_knowledge_candidate_applies(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            (root / "knowledge/inference/vllm-ascend").mkdir(parents=True)
            path = root / "knowledge/inference/vllm-ascend/case.yaml"
            path.write_text("id: K-1\nquickly_check: 旧判别\n", encoding="utf-8")
            data = {
                "candidate_id": "C-K1", "target_kind": "knowledge",
                "target_component": "knowledge.case_content",
                "region": "knowledge.case_content",
                "file": "knowledge/inference/vllm-ascend/case.yaml",
                "base_rev": "HEAD",
                "old_text": "quickly_check: 旧判别\n",
                "new_text": "quickly_check: 新判别\n",
            }
            apply_to_root(root, validate_candidate(data))
            self.assertIn("新判别", path.read_text(encoding="utf-8"))

    def test_invalid_knowledge_yaml_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            (root / "knowledge/inference/vllm-ascend").mkdir(parents=True)
            path = root / "knowledge/inference/vllm-ascend/case.yaml"
            path.write_text("id: K-1\nquickly_check: 旧判别\n", encoding="utf-8")
            data = {
                "candidate_id": "C-K2", "target_kind": "knowledge",
                "target_component": "knowledge.case_content",
                "region": "knowledge.case_content",
                "file": "knowledge/inference/vllm-ascend/case.yaml",
                "base_rev": "HEAD",
                "old_text": "quickly_check: 旧判别\n",
                "new_text": "quickly_check: [broken\n",
            }
            with self.assertRaises(CandidateError):
                apply_to_root(root, validate_candidate(data))
            self.assertIn("旧判别", path.read_text(encoding="utf-8"))

    def test_invalid_tooling_python_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            data = tool_candidate(root, new="def fetch(ref):\n    return ref.strip(\n")
            with self.assertRaises(CandidateError):
                apply_to_root(root, validate_candidate(data))
            self.assertIn("return ref", (root / "scripts/src_fetch.py").read_text(encoding="utf-8"))

    def test_harness_candidate_applies_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            (root / "eval").mkdir()
            path = root / "eval" / "scheduler.yaml"
            path.write_text("scheduler: old\n", encoding="utf-8")
            data = {
                "candidate_id": "C-H1", "target_kind": "harness",
                "target_component": "harness.scheduler",
                "region": "harness.scheduler",
                "file": "eval/scheduler.yaml", "base_rev": "HEAD",
                "old_text": "scheduler: old\n",
                "new_text": "scheduler: new\n",
            }
            apply_to_root(root, validate_candidate(data))
            self.assertIn("new", path.read_text(encoding="utf-8"))

    def test_harness_scheduler_requires_key(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            (root / "eval").mkdir()
            path = root / "eval" / "scheduler.yaml"
            path.write_text("scheduler: old\n", encoding="utf-8")
            data = {
                "candidate_id": "C-H2", "target_kind": "harness",
                "target_component": "harness.scheduler",
                "region": "harness.scheduler",
                "file": "eval/scheduler.yaml", "base_rev": "HEAD",
                "old_text": "scheduler: old\n",
                "new_text": "other: new\n",
            }
            with self.assertRaises(CandidateError):
                apply_to_root(root, validate_candidate(data))
            self.assertIn("scheduler: old", path.read_text(encoding="utf-8"))

    def test_harness_cannot_change_judge_policy_or_holdout(self):
        for file in ("sleuth.config.yaml", "config/rsi/pipelines.yaml", "eval/holdout.yaml", "eval/core/test.yaml",
                     "scripts/evolve/stage.py", "tests/self_evolution/test_flow.py"):
            with self.assertRaises(CandidateError):
                validate_candidate({
                    "candidate_id": "C-H3", "target_kind": "harness",
                    "target_component": "harness.scheduler",
                    "region": "harness.scheduler", "file": file,
                    "base_rev": "HEAD", "old_text": "old\n", "new_text": "new\n",
                })

    def test_knowledge_candidate_can_add_new_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            path = root / "knowledge/inference/vllm-ascend/new-case.yaml"
            data = {
                "candidate_id": "C-KA-1", "target_kind": "knowledge",
                "target_component": "knowledge.case_content",
                "region": "knowledge.case_content", "action": "add",
                "file": "knowledge/inference/vllm-ascend/new-case.yaml",
                "base_rev": "HEAD",
                "content": "id: K-NEW\nquickly_check: 新判别\n",
            }
            apply_to_root(root, validate_candidate(data))
            self.assertIn("K-NEW", path.read_text(encoding="utf-8"))

    def test_add_cannot_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            (root / "knowledge/inference/vllm-ascend").mkdir(parents=True)
            path = root / "knowledge/inference/vllm-ascend/case.yaml"
            path.write_text("id: K-1\n", encoding="utf-8")
            data = {
                "candidate_id": "C-KA-2", "target_kind": "knowledge",
                "target_component": "knowledge.case_content",
                "region": "knowledge.case_content", "action": "add",
                "file": "knowledge/inference/vllm-ascend/case.yaml",
                "base_rev": "HEAD", "content": "id: K-2\n",
            }
            with self.assertRaises(CandidateError):
                apply_to_root(root, validate_candidate(data))
            self.assertIn("K-1", path.read_text(encoding="utf-8"))

    def test_knowledge_candidate_can_delete_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            (root / "knowledge/inference/vllm-ascend").mkdir(parents=True)
            path = root / "knowledge/inference/vllm-ascend/old.yaml"
            path.write_text("id: K-OLD\n", encoding="utf-8")
            data = {
                "candidate_id": "C-KD-1", "target_kind": "knowledge",
                "target_component": "knowledge.case_content",
                "region": "knowledge.case_content", "action": "delete",
                "file": "knowledge/inference/vllm-ascend/old.yaml",
                "base_rev": "HEAD",
            }
            apply_to_root(root, validate_candidate(data))
            self.assertFalse(path.exists())

    def test_catalog_candidate_can_use_src_fetch_self_test(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            (root / "source-catalog.d").mkdir()
            (root / "source-catalog.d" / "repos.yaml").write_text("# repos\n", encoding="utf-8")
            data = {
                "candidate_id": "C-CAT", "target_kind": "tooling",
                "target_component": "tooling.source_catalog",
                "region": "tooling.source_catalog",
                "file": "source-catalog.d/repos.yaml", "base_rev": "HEAD",
                "old_text": "# repos\n", "new_text": "# repos\n- org/repo\n",
                "checks": ["src_fetch_self_test"],
            }
            apply_to_root(root, validate_candidate(data))
            self.assertIn("org/repo", (root / "source-catalog.d" / "repos.yaml")
                          .read_text(encoding="utf-8"))

    def test_py_compile_rejects_non_python_file_at_validate(self):
        data = tool_candidate(Path("."))
        data["file"] = "source-catalog.d/repos.yaml"
        data["checks"] = ["py_compile"]
        with self.assertRaises(CandidateError):
            validate_candidate(data)

    def test_tooling_file_outside_region_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            (root / "scripts/other.py").write_text("x = 1\n", encoding="utf-8")
            data = tool_candidate(root)
            data["file"] = "scripts/other.py"
            with self.assertRaises(CandidateError):
                validate_candidate(data)

    def test_tooling_cannot_touch_skill_or_ci(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            for file in ("skills/diagnose/SKILL.md", ".github/workflows/x.yml"):
                data = tool_candidate(root)
                data["file"] = file
                with self.assertRaises(CandidateError):
                    validate_candidate(data)

    def test_unknown_or_duplicate_check_is_rejected(self):
        data = tool_candidate(Path("."))
        data["checks"] = ["rm -rf /"]
        with self.assertRaises(CandidateError):
            validate_candidate(data)
        data["checks"] = ["py_compile", "py_compile"]
        with self.assertRaises(CandidateError):
            validate_candidate(data)

    def test_failed_check_rolls_back_the_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            before = (root / "scripts/src_fetch.py").read_text(encoding="utf-8")
            data = tool_candidate(
                root, new="def fetch(ref):\n    return (\n")
            data["checks"] = ["py_compile"]
            with self.assertRaises(CandidateError):
                apply_to_root(root, validate_candidate(data))
            self.assertEqual((root / "scripts/src_fetch.py").read_text(encoding="utf-8"), before)

    def test_failed_check_removes_the_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            ws = Path(td) / "ws"
            data = tool_candidate(
                root, new="def fetch(ref):\n    return (\n")
            data["checks"] = ["py_compile"]
            with self.assertRaises(CandidateError):
                create_workspace(root, validate_candidate(data), ws)
            self.assertFalse(ws.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink not available")
    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._repo(td)
            outside = Path(td) / "outside.py"
            outside.write_text("def fetch(ref):\n    return ref\n", encoding="utf-8")
            (root / "scripts/src_fetch.py").unlink()
            try:
                os.symlink(outside, root / "scripts/src_fetch.py")
            except (OSError, NotImplementedError):
                self.skipTest("symlink not permitted on this platform")
            with self.assertRaises(CandidateError):
                apply_to_root(root, validate_candidate(tool_candidate(root)))

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
