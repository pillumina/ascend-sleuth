"""通用 stage runner：plan / run / report。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.policy import load_policy  # noqa: E402
from evolve.stage import StageError, judge, plan, report, run  # noqa: E402

ADAPTER = ROOT / "scripts" / "agent_adapter.py"
AGENT = [
    sys.executable, "-c",
    "import os,pathlib;"
    "pathlib.Path(os.environ['SLEUTH_TRACE']).write_text("
    "'session_id: test\\nmodel: test\\ntrace: []\\n');"
    "pathlib.Path(os.environ['SLEUTH_OUT']).write_text('ok')",
]


def _sample(sid, purpose):
    return {
        "id": sid, "status": "active", "origin": "core", "purpose": purpose,
        "source": f"github/test#{sid}", "expected": {"resolution": "ok"},
    }


class StageTest(unittest.TestCase):
    def _root(self, td, stage="regression", count=1):
        root = Path(td) / "repo"
        core = root / "eval" / "core" / "samples"
        core.mkdir(parents=True)
        for index in range(count):
            sid = f"{stage.upper()}-{1001 + index}"
            (core / f"{sid}.yaml").write_text(
                yaml.safe_dump(_sample(sid, stage)), encoding="utf-8")
        if stage == "test":
            (root / "eval" / "core" / "test-stage.yaml").write_text(
                yaml.safe_dump({"selected": [str(1001 + i) for i in range(count)]}),
                encoding="utf-8")
        return root

    def test_regression_plan_run_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            out = Path(td) / "out"
            policy = load_policy(None)
            tasks = plan(root, "regression", out, policy, limit=1)
            self.assertEqual(tasks["stage"], "regression")
            self.assertEqual(tasks["gate"], "hard")
            self.assertEqual(len(tasks["samples"]), 1)
            self.assertNotIn("baseline", tasks["arms"])
            result = run(out, AGENT)
            self.assertEqual(result["completed"], 1)
            self.assertTrue((out / "candidate" / "traces" / "1001.yaml").exists())
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({"candidate": {"1001": 1},
                                         "meta": {"agent": "echo"}}), encoding="utf-8")
            reported = report(out, "regression", judge, policy)
            self.assertTrue(reported["passed"])
            self.assertEqual(reported["n"], 1)

    def test_regression_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            out = Path(td) / "out"
            policy = load_policy(None)
            plan(root, "regression", out, policy, limit=1)
            run(out, AGENT)
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({"candidate": {"1001": 0},
                                         "meta": {"agent": "echo"}}), encoding="utf-8")
            reported = report(out, "regression", judge, policy)
            self.assertFalse(reported["passed"])
            self.assertEqual(reported["failed"], ["1001"])

    def test_test_stage_selects_four(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, stage="test", count=4)
            out = Path(td) / "out"
            policy = load_policy(None)
            tasks = plan(root, "test", out, policy)
            self.assertEqual(tasks["stage"], "test")
            self.assertEqual(tasks["gate"], "exact")
            self.assertEqual([s["short_id"] for s in tasks["samples"]],
                             ["1001", "1002", "1003", "1004"])
            self.assertEqual(tasks["budget"]["required_b"], 4)

    def test_test_stage_rejects_changed_seal(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, stage="test", count=4)
            path = root / "eval" / "core" / "test-stage.yaml"
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            doc["sealed_sha256"] = {str(1001 + i): "0" * 64 for i in range(4)}
            path.write_text(yaml.safe_dump(doc), encoding="utf-8")
            with self.assertRaises(StageError):
                plan(root, "test", Path(td) / "out", load_policy(None))

    def test_test_stage_rejects_short_selection(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, stage="test", count=3)
            out = Path(td) / "out"
            with self.assertRaises(StageError):
                plan(root, "test", out, load_policy(None))

    def test_test_report_can_mark_stage_complete(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, stage="test", count=4)
            out = Path(td) / "out"
            policy = load_policy(None)
            policy["samples"]["field_eval"] = 4
            plan(root, "test", out, policy)
            tasks = json.loads((out / "tasks.json").read_text(encoding="utf-8"))
            tasks["candidate_id"] = "C-TEST"
            tasks["candidate"] = {"candidate_id": "C-TEST"}
            (out / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
            field = root / ".s2-replay" / "evolve"
            field.mkdir(parents=True)
            (field / "conclusions.jsonl").write_text(
                json.dumps({"pool": "pilot", "decision": "accept",
                            "versions": {"candidate": "C-TEST"}}) + "\n",
                encoding="utf-8")
            run(out, AGENT)
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({
                "baseline": {"1001": 0, "1002": 0, "1003": 0, "1004": 0},
                "candidate": {"1001": 1, "1002": 1, "1003": 1, "1004": 1},
                "meta": {"agent": "echo", "calibration": {"passed": True}},
            }), encoding="utf-8")
            reported = report(out, "test", judge, policy, update_stage=True)
            self.assertEqual(reported["decision"]["conclusion"]["decision"], "accept")
            stage = yaml.safe_load(
                (root / "eval" / "core" / "test-stage.yaml").read_text(encoding="utf-8"))
            self.assertEqual(stage["status"], "complete")
            self.assertEqual(stage["decision"], "accept")

    def test_stage_judge_records_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            out = Path(td) / "out"
            policy = load_policy(None)
            plan(root, "regression", out, policy, limit=1)
            run(out, AGENT)
            data = judge(out, agent="echo")
            self.assertEqual(data["meta"]["agent"], "echo")
            self.assertEqual(data["candidate"]["1001"], 1)
            reported = report(out, "regression", out / "judge.json", policy)
            self.assertTrue(reported["passed"])

    def test_regression_where_filter(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, stage="regression", count=4)
            sample = root / "eval" / "core" / "samples" / "REGRESSION-1001.yaml"
            data = yaml.safe_load(sample.read_text(encoding="utf-8"))
            data["input"] = {"environment": "310P"}
            sample.write_text(yaml.safe_dump(data), encoding="utf-8")
            tasks = plan(root, "regression", Path(td) / "out",
                         load_policy(None), where={"environment": "310P"})
            self.assertEqual(len(tasks["samples"]), 1)
            self.assertEqual(tasks["samples"][0]["short_id"], "1001")

    def test_regression_limit_and_full(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, stage="regression", count=8)
            policy = load_policy(None)
            short = plan(root, "regression", Path(td) / "short", policy)
            full = plan(root, "regression", Path(td) / "full", policy, full=True)
            self.assertEqual(len(short["samples"]), 6)
            self.assertEqual(len(full["samples"]), 8)

    def test_holdout_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            (root / ".git").mkdir()
            (root / "eval" / "holdout.yaml").write_text(
                yaml.safe_dump({"entries": [{"fixture": "VLLM-ASC-12345.fixture.yaml"}]}),
                encoding="utf-8")
            sample = next((root / "eval" / "core" / "samples").glob("*.yaml"))
            data = yaml.safe_load(sample.read_text(encoding="utf-8"))
            data["source"] = "https://github.com/x/y/issues/12345"
            sample.write_text(yaml.safe_dump(data), encoding="utf-8")
            with self.assertRaises(StageError):
                plan(root, "regression", Path(td) / "out", load_policy(None), limit=1)

    def test_fallback_trace_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            out = Path(td) / "out"
            policy = load_policy(None)
            plan(root, "regression", out, policy, limit=1)
            run(out, AGENT)
            trace = out / "candidate" / "traces" / "1001.yaml"
            doc = yaml.safe_load(trace.read_text(encoding="utf-8"))
            doc["adapter_fallback"] = True
            trace.write_text(yaml.safe_dump(doc), encoding="utf-8")
            judge = Path(td) / "judge.json"
            judge.write_text(json.dumps({"candidate": {"1001": 1}}), encoding="utf-8")
            with self.assertRaises(StageError):
                report(out, "regression", judge, policy)

    def test_baseline_reuse_is_test_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td)
            out = Path(td) / "out"
            source = Path(td) / "baseline"
            for name in ("traces", "out"):
                (source / name).mkdir(parents=True)
            with self.assertRaises(StageError):
                plan(root, "regression", out, load_policy(None), limit=1,
                     baseline_traces=source)


if __name__ == "__main__":
    unittest.main()
