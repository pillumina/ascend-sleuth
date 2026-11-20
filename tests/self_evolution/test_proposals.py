"""target-specific agent proposal contract."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.proposals import ProposalError, request, validate_draft  # noqa: E402


def draft(target="knowledge", files=None, component="knowledge.case_content"):
    return {
        "target_kind": target,
        "target_component": component,
        "summary": "补一条判别条件",
        "change": {"files": files or ["knowledge/inference/vllm-ascend/x.yaml"],
                   "diff": "+ quickly_check: token > 1024"},
        "expected": "命中率提升",
        "risk": "低",
        "rollback": "恢复原判别条件",
    }


class ProposalTest(unittest.TestCase):
    def test_request_is_target_specific(self):
        result = request("knowledge", "knowledge.case_content")
        self.assertEqual(result["target_kind"], "knowledge")
        self.assertIn("knowledge/", result["allowed_paths"])
        self.assertIn("scripts/", result["forbidden_paths"])
        self.assertIn("YAML", result["prompt"])
        self.assertEqual(result["authority"], "A2")
        self.assertTrue(result["eval_ready"])

    def test_harness_request_marks_not_ready(self):
        result = request("harness", "harness.scheduler")
        self.assertFalse(result["eval_ready"])
        self.assertIn("A1", result["authority"])

    def test_validate_knowledge_draft(self):
        patch = validate_draft(draft())
        self.assertEqual(patch.target_kind, "knowledge")
        self.assertEqual(patch.algorithm, "agent_draft")
        self.assertEqual(patch.payload["source"], "agent")

    def test_validate_rejects_wrong_path(self):
        with self.assertRaises(ProposalError):
            validate_draft(draft(target="tooling", component="tooling.source_fetch",
                                 files=["knowledge/x.yaml"]))

    def test_validate_rejects_unsafe_path(self):
        with self.assertRaises(ProposalError):
            validate_draft(draft(files=["../outside.yaml"]))

    def test_validate_rejects_missing_rollback(self):
        data = draft()
        del data["rollback"]
        with self.assertRaises(ProposalError):
            validate_draft(data)

    def test_target_override(self):
        with self.assertRaises(ProposalError):
            validate_draft(draft(), target_override="skill")

    def test_skill_draft(self):
        patch = validate_draft({
            "target_kind": "skill",
            "target_component": "diagnose.knowledge_usage",
            "summary": "阶段二只载筛出的全文",
            "change": {"files": ["skills/diagnose/SKILL.md"],
                       "diff": "- 载入全部候选\n+ 只载筛出的候选"},
            "expected": "读取量下降",
            "risk": "低",
            "rollback": "恢复原阶段二说明",
        })
        self.assertEqual(patch.target_kind, "skill")


if __name__ == "__main__":
    unittest.main()
