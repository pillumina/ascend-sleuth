"""RSI 链路集成：trace -> plan -> GEPA state -> experiment record。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.agent_gepa import GepaSession  # noqa: E402
from evolve.experiments import validate_experiment  # noqa: E402
from evolve.rsi import build_plan  # noqa: E402


class RsiIntegrationTest(unittest.TestCase):
    def test_trace_to_gepa_to_record(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace_state = root / "trace-state.json"
            trace_state.write_text(json.dumps({
                "snapshot_id": "snap-1", "processed": {
                    "t1": {"attribution": {"events": [
                        {"component": "routing", "hard": True}
                    ]}}
                }
            }), encoding="utf-8")
            plan = build_plan(root, trace_state=trace_state)
            self.assertEqual(plan["status"], "actionable")
            spec = plan["experiment"]
            self.assertEqual(spec["mutable_region"], "diagnose.routing_hints")

            session = GepaSession(
                "seed region", ["S-1"], max_metric_calls=4, population=2,
                target_skill=spec["target_skill"],
                mutable_region=spec["mutable_region"],
                select_stage="select.pareto",
            )
            action = session.next_action()
            self.assertEqual(action["kind"], "evaluate")
            session.record_evaluation("seed", "S-1", 0.0, "generic")
            self.assertEqual(session.next_action()["kind"], "reflect")
            candidate = session.record_candidate("specific root cause")
            action = session.next_action()
            self.assertEqual(action["candidate_id"], candidate.id)
            session.record_evaluation(candidate.id, "S-1", 1.0, "matched")
            result = session.result()
            self.assertEqual(result["best_id"], candidate.id)

            record = validate_experiment({
                "target_kind": "skill",
                "target_component": spec["mutable_region"],
                "algorithm": "gepa-agent",
                "algorithm_version": "state-v1",
                "execution": "subagent",
                "decision": "accept",
                "samples": ["S-1"],
                "baseline": {"score": 0.0, "samples": ["S-1"]},
                "candidate": {"score": 1.0, "samples": ["S-1"]},
                "eval_profile_id": "subagent_judge",
                "eval_ready": False,
                "paired": {"b": 4, "c": 0, "n": 4},
                "stages": {"select_candidate": "select.pareto", "propose": "propose.agent"},
            })
            self.assertEqual(record["decision"], "accept")
            self.assertEqual(record["stages"]["propose"], "propose.agent")


if __name__ == "__main__":
    unittest.main()
