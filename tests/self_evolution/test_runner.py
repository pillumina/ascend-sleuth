"""维护者计划：issue_plan 的读数、动作与 brief/run 的输出。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.policy import load_policy  # noqa: E402
from evolve.records import ConclusionStore  # noqa: E402
from evolve.runner import issue_plan, render_plan  # noqa: E402
from evolve.samples import SampleStore  # noqa: E402

SCRIPT = ROOT / "scripts" / "evolve.py"


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", cwd=str(cwd or ROOT),
    )


class IssuePlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / ".s2-replay" / "evolve"
        self.store = SampleStore(base=self.base)
        self.policy = load_policy(None)

    def create(self, sid, **overrides):
        values = dict(
            id=sid, object_type="diagnosis", source=f"https://example.com/{sid}",
            expected={"namespace": "inference/vllm-ascend"},
        )
        values.update(overrides)
        return self.store.new(**values)

    def plan(self):
        return issue_plan(self.root, self.base, self.policy)

    def test_empty_store_has_actions_and_warnings(self):
        plan = self.plan()
        self.assertEqual(plan["counts"]["total"], 0)
        self.assertTrue(any(action.startswith("no_conclusion") for action in plan["next_actions"]))
        self.assertTrue(any(action.startswith("field_eval_short") for action in plan["next_actions"]))
        self.assertTrue(any(action.startswith("test_short") for action in plan["next_actions"]))
        self.assertIn("sample store is empty", plan["warnings"])
        text = render_plan(plan)
        self.assertIn("next_actions:", text)
        self.assertIn("samples: 0", text)

    def test_candidates_need_review_and_missing_answer_warns(self):
        self.create("S-1", expected=None)
        plan = self.plan()
        self.assertEqual(plan["counts"]["candidate"], 1)
        self.assertTrue(any(action.startswith("review_candidates") for action in plan["next_actions"]))
        self.assertTrue(any("S-1" in warning for warning in plan["warnings"]))

    def test_field_and_test_counts(self):
        self.create("S-1")
        self.store.review("S-1", approve=True)  # active/field evaluation
        self.create("S-2")
        self.store.review("S-2", approve=True)
        self.store.promote("S-2", to="core")
        self.store.set_purpose("S-2", "test")
        plan = self.plan()
        self.assertEqual(plan["counts"]["field_eval"], 1)
        self.assertEqual(plan["counts"]["core_test"], 1)
        self.assertFalse(any(action.startswith("draw_test") for action in plan["next_actions"]))

    def test_conclusion_is_counted(self):
        ConclusionStore.for_base(self.base).append({"decision": "accept"})
        plan = self.plan()
        self.assertEqual(plan["counts"]["conclusions"], 1)
        self.assertFalse(any(action.startswith("no_conclusion") for action in plan["next_actions"]))

    def test_json_plan_has_policy_hash(self):
        plan = self.plan()
        self.assertEqual(len(plan["policy_hash"]), 64)
        self.assertEqual(set(plan), {"policy_hash", "counts", "next_actions", "warnings"})


class RunCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_run_human_and_json(self):
        human = run_cli("run", "--root", str(self.root))
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn("next_actions:", human.stdout)
        payload = run_cli("run", "--root", str(self.root), "--json")
        self.assertEqual(payload.returncode, 0, payload.stderr)
        plan = json.loads(payload.stdout)
        self.assertIn("counts", plan)
        self.assertIn("next_actions", plan)

    def test_brief_includes_plan_fields(self):
        created = run_cli(
            "sample", "new", "--root", str(self.root), "--id", "S-1",
            "--object-type", "diagnosis", "--source", "https://example.com/1",
            "--expected", '{"namespace": "inference/vllm-ascend"}',
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        result = run_cli("brief", "--root", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        for text in ("candidate: 1", "field: 0", "test: 0",
                     "next_actions:", "review_candidates"):
            self.assertIn(text, result.stdout)


if __name__ == "__main__":
    unittest.main()
