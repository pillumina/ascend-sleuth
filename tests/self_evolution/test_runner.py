"""维护者计划：issue_plan 的读数、动作与 brief/run 的输出。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evolve.adapters.metrics import load_metrics  # noqa: E402
from evolve.policy import load_policy  # noqa: E402
from evolve.records import ConclusionStore  # noqa: E402
from evolve.runner import issue_plan, render_plan  # noqa: E402
from evolve.samples import SampleStore  # noqa: E402
from metrics_fixture import write_metrics  # noqa: E402

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

    def test_pool_capacity_short_is_reported(self):
        plan = self.plan()
        self.assertTrue(any(action.startswith("judgment_capacity_short")
                            for action in plan["next_actions"]))
        self.assertEqual(plan["judgment_capacity"]["required_b"], 4)
        self.assertEqual(plan["judgment_capacity"]["potential"], 0)

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

    def test_metrics_block_reads_fixture(self):
        write_metrics(self.root)
        plan = issue_plan(self.root, self.base, self.policy, metrics=load_metrics(self.root))
        self.assertEqual(plan["metrics"]["latest_period"]["period"], "2026-W36-live")
        self.assertEqual(plan["metrics"]["sessions_total"], 11)
        self.assertEqual(plan["metrics"]["tier2_hit"], 4)
        self.assertEqual(plan["metrics"]["case_total"], 42)
        self.assertEqual(plan["metrics"]["entry_usage"]["active_cases"], 1)

    def test_metrics_missing_is_unavailable_not_zero(self):
        plan = issue_plan(self.root, self.base, self.policy, metrics=load_metrics(self.root))
        self.assertFalse(plan["metrics"]["timeline"]["available"])
        self.assertIsNone(plan["metrics"]["sessions_total"])

    def test_strata_short_action_and_counts(self):
        self.create("S-1", expected={"namespace": "inference/vllm-ascend", "category": "interrupt"})
        self.store.review("S-1", approve=True)
        self.store.promote("S-1", to="core")
        self.store.set_purpose("S-1", "test")
        self.policy["samples"]["strata"] = {"inference/vllm-ascend/interrupt": 2}
        plan = self.plan()
        bucket = plan["counts"]["strata"]["inference/vllm-ascend/interrupt"]
        self.assertEqual((bucket["core_test"], bucket["target"]), (1, 2))
        self.assertTrue(any(action.startswith("test_strata_short") for action in plan["next_actions"]))
        self.assertIn("strata:", render_plan(plan))

    def test_metrics_stale_adds_action(self):
        from datetime import date
        from evolve.adapters.metrics import load_metrics
        write_metrics(self.root)
        metrics = load_metrics(self.root, today=date(2026, 9, 10))
        plan = issue_plan(self.root, self.base, self.policy, metrics=metrics)
        self.assertTrue(any(action.startswith("metrics_stale") for action in plan["next_actions"]))

    def test_metrics_same_period_stale_is_not_duplicated(self):
        from datetime import date
        from evolve.adapters.metrics import load_metrics
        write_metrics(self.root)
        gates = self.root / "metrics" / "gates.yaml"
        gates.write_text(
            "freshness: {live_snapshot_max_age_days: 7, structural_max_age_days: 7}\n"
            "gates: []\n",
            encoding="utf-8",
        )
        (self.root / "metrics" / "timeline.yaml").write_text(
            "periods:\n- period: 2026-W36\n  kind: live\n  recorded_at: '2026-09-02'\n"
            "  metrics: {sessions_total: 1, case_total: 42}\n",
            encoding="utf-8",
        )
        metrics = load_metrics(self.root, today=date(2026, 9, 10))
        plan = issue_plan(self.root, self.base, self.policy, metrics=metrics)
        stale = [a for a in plan["next_actions"] if a.startswith("metrics_stale:")]
        self.assertEqual(len(stale), 1)
        self.assertIn("live, structural", stale[0])

    def test_metrics_without_gates_gets_unavailable_action(self):
        from evolve.adapters.metrics import load_metrics
        write_metrics(self.root)
        (self.root / "metrics" / "gates.yaml").unlink()
        metrics = load_metrics(self.root)
        plan = issue_plan(self.root, self.base, self.policy, metrics=metrics)
        self.assertTrue(any(
            action.startswith("metrics_freshness_unavailable")
            for action in plan["next_actions"]
        ))

    def test_conclusion_is_counted(self):
        ConclusionStore.for_base(self.base).append({"decision": "accept"})
        plan = self.plan()
        self.assertEqual(plan["counts"]["conclusions"], 1)
        self.assertFalse(any(action.startswith("no_conclusion") for action in plan["next_actions"]))

    def test_json_plan_has_policy_hash(self):
        plan = self.plan()
        self.assertEqual(len(plan["policy_hash"]), 64)
        self.assertEqual(set(plan), {"policy_hash", "target", "algorithm", "trace_snapshot", "trace_state", "counts", "metrics", "judgment_capacity", "cost_plan", "next_actions", "warnings"})


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

    def test_brief_includes_metrics(self):
        write_metrics(self.root)
        result = run_cli("brief", "--root", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("metrics_period: 2026-W36-live", result.stdout)
        self.assertIn("sessions_total: 11", result.stdout)
        self.assertIn("tier2_hit: 4", result.stdout)
        self.assertIn("case_total: 42", result.stdout)

    def test_brief_missing_metrics_says_unavailable(self):
        result = run_cli("brief", "--root", str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("metrics_period: unavailable", result.stdout)
        self.assertIn("sessions_total: unavailable", result.stdout)

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
