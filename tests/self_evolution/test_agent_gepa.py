"""agent-native GEPA 状态机：候选池、reflection、Pareto、预算、序列化。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.agent_gepa import GepaError, GepaSession  # noqa: E402


def drain(session, scores, candidate_id="seed"):
    while True:
        action = session.next_action()
        if action["kind"] != "evaluate":
            return action
        session.record_evaluation(
            action["candidate_id"], action["sample_id"], scores[action["sample_id"]],
            feedback=f"f:{action['sample_id']}",
        )


class AgentGepaTest(unittest.TestCase):
    def test_seed_then_reflection_then_candidate(self):
        session = GepaSession("seed skill", ["S-1", "S-2"], max_metric_calls=8, population=2)
        action = drain(session, {"S-1": 0.0, "S-2": 1.0})
        self.assertEqual(action["kind"], "reflect")
        self.assertEqual(len(action["failures"]), 1)
        candidate = session.record_candidate("better skill")
        self.assertEqual(candidate.parent, "seed")
        action = drain(session, {"S-1": 1.0, "S-2": 1.0}, candidate.id)
        self.assertEqual(action["kind"], "stop")
        result = session.result()
        self.assertEqual(result["best_id"], candidate.id)
        self.assertEqual(result["best_score"], 1.0)
        self.assertEqual(result["calls"], 4)

    def test_perfect_seed_stops_without_reflection(self):
        session = GepaSession("seed", ["S-1"], max_metric_calls=4, population=3)
        action = drain(session, {"S-1": 1.0})
        self.assertEqual(action, {"kind": "stop", "reason": "perfect_score"})

    def test_baseline_control_evaluates_seed_then_stops(self):
        session = GepaSession("seed", ["S-1"], max_metric_calls=4, population=2,
                              select_stage="select.none", propose_stage="propose.none")
        action = session.next_action()
        self.assertEqual(action["kind"], "evaluate")
        session.record_evaluation("seed", "S-1", 0.0)
        self.assertEqual(session.next_action(), {"kind": "stop", "reason": "baseline_control"})

    def test_budget_stops_without_new_candidate(self):
        session = GepaSession("seed", ["S-1"], max_metric_calls=1, population=3)
        action = drain(session, {"S-1": 0.0})
        self.assertEqual(action, {"kind": "stop", "reason": "budget"})

    def test_budget_checked_before_pending_sample(self):
        session = GepaSession("seed", ["S-1", "S-2"], max_metric_calls=1, population=3)
        action = session.next_action()
        self.assertEqual(action["kind"], "evaluate")
        session.record_evaluation("seed", "S-1", 0.0)
        self.assertEqual(session.next_action(), {"kind": "stop", "reason": "budget"})

    def test_pareto_keeps_non_dominated(self):
        session = GepaSession("seed", ["S-1", "S-2"], max_metric_calls=8, population=3)
        drain(session, {"S-1": 1.0, "S-2": 0.0})
        session.record_candidate("tradeoff")
        drain(session, {"S-1": 0.0, "S-2": 1.0}, "c1")
        self.assertEqual(set(session.pareto_ids()), {"seed", "c1"})

    def test_bad_state_shape_is_an_error(self):
        with self.assertRaises(GepaError):
            GepaSession.from_dict({"samples": "S-1", "max_metric_calls": 1, "population": 2,
                                   "candidates": []})
        with self.assertRaises(GepaError):
            GepaSession.from_dict({"samples": ["S-1"], "max_metric_calls": 1, "population": 2,
                                   "candidates": [{"id": "seed"}]})

    def test_state_roundtrip(self):
        session = GepaSession("seed", ["S-1"], max_metric_calls=3, population=2, seed=9,
                              target_skill="diagnose", mutable_region="routing_hints")
        drain(session, {"S-1": 0.0})
        session.record_candidate("candidate")
        restored = GepaSession.from_dict(session.to_dict())
        self.assertEqual(restored.to_dict(), session.to_dict())
        self.assertEqual(restored.seed, 9)

    def test_order_errors(self):
        session = GepaSession("seed", ["S-1"])
        session.record_evaluation("seed", "S-1", 0.5)
        with self.assertRaises(GepaError):
            session.record_evaluation("seed", "S-1", 0.5)
        with self.assertRaises(GepaError):
            session.record_candidate("x")  # no reflect pending


if __name__ == "__main__":
    unittest.main()
