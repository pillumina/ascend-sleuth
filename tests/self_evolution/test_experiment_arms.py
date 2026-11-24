# -*- coding: utf-8 -*-
"""组合实验：spec 校验、多臂比较、顺序链交接与断点续跑。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.experiment_session import ExperimentSession  # noqa: E402
from evolve.experiment_spec import (ArmSpec, ExperimentSpec,  # noqa: E402
                                    ExperimentSpecError)


def arm(name, loop, **kwargs):
    return ArmSpec(name=name, loop=loop, **kwargs)


def spec(**overrides):
    data = dict(
        id="x1", target="skill", component="diagnose.routing_hints",
        arms=[arm("control", "baseline", budget={"target_runs": 4}),
              arm("gepa", "gepa", params={"population": 2},
                  budget={"target_runs": 6})],
        samples={"eval": ["s1", "s2"], "dev": ["d1"]},
        composition="parallel", primary_arm="gepa", eval_role="dev",
        seed_text="seed text",
    )
    data.update(overrides)
    return ExperimentSpec(**data)


def scorer(action):
    if action["kind"] == "evaluate":
        if action["sample_id"].startswith("s"):
            return {"score": 0.2, "feedback": ""}
        return {"score": 0.6, "feedback": ""}
    if action["kind"] == "reflect":
        return {"text": "better text"}
    if action["kind"] == "merge":
        return {"text": action["proposals"][0]}
    raise AssertionError(action["kind"])


def drive(session, limit=300):
    for _ in range(limit):
        pending = session.next_action()
        if pending.get("kind") == "stop":
            return pending
        session.apply(pending, scorer(pending["action"]))
    raise AssertionError("experiment did not stop")


class ExperimentSpecTest(unittest.TestCase):
    def test_valid_spec_defaults_primary_when_missing(self):
        data = spec(primary_arm="")
        validated = data.validate()
        self.assertEqual(validated.primary_arm, "gepa")

    def test_duplicate_sample_across_roles_rejected(self):
        data = spec(samples={"eval": ["s1", "s2"], "dev": ["s1"]})
        with self.assertRaises(ExperimentSpecError):
            data.validate()

    def test_unknown_sample_role_rejected(self):
        data = spec(samples={"eval": ["s1"], "test": ["s2"]})
        with self.assertRaises(ExperimentSpecError):
            data.validate()

    def test_unknown_loop_rejected(self):
        data = spec(arms=[arm("x", "nope")])
        with self.assertRaises(ExperimentSpecError):
            data.validate()

    def test_parallel_audit_mix_rejected(self):
        data = spec(arms=[
            arm("gepa", "gepa"),
            arm("audit", "loo", budget={"target_runs": 4}),
        ])
        with self.assertRaises(ExperimentSpecError):
            data.validate()

    def test_sequential_rejects_audit_and_primary(self):
        data = spec(composition="sequential", primary_arm="",
                    arms=[arm("gepa", "gepa"), arm("audit", "loo")])
        with self.assertRaises(ExperimentSpecError):
            data.validate()
        data = spec(composition="sequential", primary_arm="gepa",
                    arms=[arm("gepa", "gepa")])
        with self.assertRaises(ExperimentSpecError):
            data.validate()

    def test_role_mapping_is_resolved(self):
        data = spec(
            samples={"train": ["t1", "t2"], "dev": ["d1"]},
            arms=[arm("skillopt", "skillopt",
                      roles={"train": "train", "dev": "dev"})],
            primary_arm="",
        )
        validated = data.validate()
        self.assertEqual(validated.data_for(validated.arms[0]),
                         {"train": ["t1", "t2"], "dev": ["d1"]})

    def test_missing_mapped_role_rejected(self):
        data = spec(
            samples={"eval": ["s1"], "dev": ["d1"]},
            arms=[arm("skillopt", "skillopt")],
        )
        with self.assertRaises(ExperimentSpecError):
            data.validate()


class ExperimentSessionTest(unittest.TestCase):
    def test_decisions_are_written_for_arms(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "decisions.jsonl"
            session = ExperimentSession(spec(), decisions_path=str(path))
            drive(session)
            self.assertTrue(path.exists())
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(rows)
            self.assertTrue(all("loop" in row for row in rows))
            restored = ExperimentSession.from_dict(session.to_dict())
            self.assertEqual(restored.decisions_path, str(path))

    def test_three_arms_including_skillopt(self):
        data = spec(
            samples={"train": ["t1", "t2"], "dev": ["d1"]},
            primary_arm="skillopt",
            arms=[
                arm("control", "baseline", roles={"eval": "dev"},
                    budget={"target_runs": 4}),
                arm("gepa", "gepa", roles={"eval": "dev"},
                    params={"population": 2}, budget={"target_runs": 6}),
                arm("skillopt", "skillopt",
                    params={"epochs": 1, "batch_size": 2,
                            "reflection_minibatch": 1},
                    budget={"target_runs": 12, "worker_calls": 6}),
            ],
        )

        def scorer(action):
            if action["kind"] == "evaluate":
                edited = "edit" in action.get("skill", "")
                if action.get("phase") == "dev" or action["sample_id"].startswith("d"):
                    return {"score": 0.7 if edited else 0.4}
                return {"score": 0.8 if edited else 0.3}
            if action["kind"] == "reflect":
                return {"text": action["skill"] + "\n# edit"}
            if action["kind"] == "merge":
                return {"text": action["proposals"][0]}
            raise AssertionError(action["kind"])

        session = ExperimentSession(data)
        for _ in range(200):
            pending = session.next_action()
            if pending.get("kind") == "stop":
                break
            session.apply(pending, scorer(pending["action"]))
        result = session.result()
        self.assertEqual([item["arm"] for item in result["arms"]],
                         ["control", "gepa", "skillopt"])
        self.assertEqual(result["primary_eval_score"], 0.7)
        self.assertEqual(result["arms"][2]["accepted"], 1)

    def test_multi_arm_produces_comparable_eval(self):
        session = ExperimentSession(spec())
        pending = drive(session)
        self.assertEqual(pending["reason"], "complete")
        result = session.result()
        self.assertEqual([item["arm"] for item in result["arms"]],
                         ["control", "gepa"])
        self.assertTrue(all("eval_score" in item for item in result["arms"]))
        self.assertEqual(result["primary_arm"], "gepa")
        self.assertEqual(result["primary_eval_score"], 0.6)

    def test_sequential_hands_off_best_snapshot(self):
        session = ExperimentSession(spec(
            composition="sequential", primary_arm="",
            arms=[arm("first", "gepa", budget={"target_runs": 4}),
                  arm("second", "gepa", budget={"target_runs": 4})],
        ))
        def candidate_scorer(action):
            if action["kind"] == "evaluate":
                return {"score": 0.9 if action["candidate_id"] != "seed" else 0.2}
            if action["kind"] == "reflect":
                return {"text": "better text"}
            raise AssertionError(action["kind"])

        for _ in range(100):
            pending = session.next_action()
            if pending.get("kind") == "stop":
                break
            session.apply(pending, candidate_scorer(pending["action"]))
        first, second = session.result()["arms"]
        self.assertEqual(first["best_skill"], "better text")
        self.assertEqual(second["candidates"][0]["text"], "better text")

    def test_single_search_arm_becomes_primary(self):
        data = spec(
            arms=[arm("only", "gepa", roles={"eval": "dev"},
                      budget={"target_runs": 4})],
            primary_arm="",
        )
        self.assertEqual(data.validate().primary_arm, "only")

    def test_arm_stop_reason_is_preserved(self):
        data = spec(
            samples={"audit": ["a1", "a2"]},
            arms=[arm("audit", "loo",
                      params={"units": [{"id": "u1"}, {"id": "u2"}]},
                      budget={"target_runs": 4})],
            primary_arm="", eval_role="dev",
        )
        session = ExperimentSession(data)
        for _ in range(20):
            pending = session.next_action()
            if pending.get("kind") == "stop":
                break
            action = pending["action"]
            self.assertEqual(action["kind"], "evaluate")
            session.apply(pending, {
                "score": 0.8 if action["variant"] == "full" else 0.81,
            })
        result = session.result()
        self.assertEqual(result["arms"][0]["stop_reason"], "budget")
        self.assertEqual(result["arms"][0]["calls"], 4)

    def test_roundtrip_keeps_pending_action(self):
        session = ExperimentSession(spec())
        pending = session.next_action()
        restored = ExperimentSession.from_dict(session.to_dict())
        self.assertEqual(restored.next_action(), pending)
        restored.apply(pending, {"score": 0.2, "feedback": ""})
        follow = restored.next_action()
        self.assertNotEqual(follow, pending)

    def test_single_audit_arm_runs_without_eval(self):
        data = spec(
            samples={"audit": ["a1"]},
            arms=[arm("audit", "loo", params={"units": [{"id": "u1"}]},
                      budget={"target_runs": 4})],
            primary_arm="", composition="parallel", eval_role="dev",
        )
        session = ExperimentSession(data)
        result = drive(session)
        self.assertEqual(result["reason"], "complete")
        arm_result = session.result()["arms"][0]
        self.assertNotIn("eval_score", arm_result)


if __name__ == "__main__":
    unittest.main()
