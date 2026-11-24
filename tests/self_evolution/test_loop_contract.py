# -*- coding: utf-8 -*-
"""循环层契约：快照、预算、决策记录、注册表与两个新家族的最小实现。"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.loops import (Budget, DecisionLog, LoopError, Snapshot,  # noqa: E402
                         get_loop, loop_ids, restore_loop, validate_action)
from evolve.loops.baseline import BaselineLoop  # noqa: E402
from evolve.loops.gepa import GepaSession  # noqa: E402
from evolve.loops.loo import AuditUnit, LooAudit  # noqa: E402
from evolve.loops.proposal import ProposalLoop  # noqa: E402
from evolve.loops.skillopt import SkillOptLoop  # noqa: E402
from evolve.proposal_engine import (GepaPolicy, ProposalArchive,  # noqa: E402
                                    ProposalEngine)


class ToyPopulation:
    """群体演化家族的最小实现：评估 -> 交叉 -> 再评估。"""

    id = "toy_population"

    def __init__(self, seed, samples, population=3):
        self.samples = list(samples)
        self.population = population
        self.candidates = [Snapshot.from_text("seed", seed)]
        self.pending_crossover = False

    def next_action(self):
        for candidate in self.candidates:
            missing = [sid for sid in self.samples if sid not in candidate.scores]
            if missing:
                return {"kind": "evaluate", "candidate_id": candidate.id,
                        "sample_id": missing[0]}
        if len(self.candidates) >= self.population:
            return {"kind": "stop", "reason": "population"}
        self.pending_crossover = True
        return {"kind": "crossover", "parent_a": self.candidates[0].id,
                "parent_b": self.candidates[-1].id}

    def apply(self, action, result):
        kind = action["kind"]
        if kind == "evaluate":
            for candidate in self.candidates:
                if candidate.id == action["candidate_id"]:
                    candidate.scores[action["sample_id"]] = float(result["score"])
                    return
            raise LoopError("unknown candidate")
        if kind == "crossover":
            if not self.pending_crossover:
                raise LoopError("no crossover pending")
            self.pending_crossover = False
            self.candidates.append(Snapshot.from_text(
                f"c{len(self.candidates)}", result["text"],
                parent=action["parent_a"],
            ))
            return
        raise LoopError(f"unsupported action {kind!r}")

    def result(self):
        return {"loop": self.id, "candidates": len(self.candidates)}

    def to_dict(self):
        return {"state_schema": "toy-population-v1",
                "samples": list(self.samples), "population": self.population,
                "candidates": [c.to_dict() for c in self.candidates]}

    @classmethod
    def from_dict(cls, data):
        loop = cls("seed", data["samples"], data["population"])
        loop.candidates = [Snapshot.from_dict(item) for item in data["candidates"]]
        return loop


class ToyAllocation:
    """多保真分配家族的最小实现：先粗筛一半，再对幸存者深评。"""

    id = "toy_allocation"

    def __init__(self, candidates, samples):
        self.samples = list(samples)
        self.all_candidates = [Snapshot.from_text(cid, cid) for cid in candidates]
        self.active = list(self.all_candidates)
        self.stage = 1
        self.evaluated = []

    def next_action(self):
        for candidate in self.active:
            if "s1" not in candidate.scores:
                return {"kind": "evaluate", "candidate_id": candidate.id,
                        "sample_id": "s1"}
        if self.stage == 1:
            self.active = sorted(self.active, key=lambda c: -c.scores["s1"])[:2]
            self.stage = 2
        for candidate in self.active:
            if "s2" not in candidate.scores:
                return {"kind": "evaluate", "candidate_id": candidate.id,
                        "sample_id": "s2"}
        return {"kind": "stop", "reason": "allocation_complete"}

    def apply(self, action, result):
        for candidate in self.all_candidates:
            if candidate.id == action["candidate_id"]:
                candidate.scores[action["sample_id"]] = float(result["score"])
                self.evaluated.append((candidate.id, action["sample_id"]))
                return
        raise LoopError("unknown candidate")

    def result(self):
        return {"loop": self.id, "evaluated": list(self.evaluated),
                "survivors": [c.id for c in self.active]}

    def to_dict(self):
        return {"state_schema": "toy-allocation-v1",
                "active": [c.id for c in self.active], "stage": self.stage}


def drive(loop, scorer, limit=100):
    for _ in range(limit):
        action = loop.next_action()
        if action.get("kind") == "stop":
            return action
        loop.apply(action, scorer(action))
    raise AssertionError("loop did not stop")


class SnapshotTest(unittest.TestCase):
    def test_text_and_files_are_exclusive(self):
        with self.assertRaises(LoopError):
            Snapshot(id="x")
        with self.assertRaises(LoopError):
            Snapshot(id="x", text="a", files={"a.md": "a"})

    def test_files_digest_is_stable(self):
        one = Snapshot(id="x", files={"b.md": "B", "a.md": "A"})
        two = Snapshot(id="y", files={"a.md": "A", "b.md": "B"})
        self.assertEqual(one.digest(), two.digest())
        self.assertEqual(one.content(), {"b.md": "B", "a.md": "A"})

    def test_legacy_skill_field_is_read(self):
        snapshot = Snapshot.from_dict({"id": "seed", "skill": "text"})
        self.assertEqual(snapshot.text, "text")
        self.assertEqual(snapshot.skill, "text")


class BudgetTest(unittest.TestCase):
    def test_limits_and_stop_reason(self):
        budget = Budget(target_runs=2)
        self.assertTrue(budget.can_spend("target_runs"))
        budget.spend("target_runs", 2)
        self.assertFalse(budget.can_spend("target_runs"))
        self.assertEqual(budget.stop_reason(), "target_runs_budget")
        with self.assertRaises(LoopError):
            budget.spend("target_runs")

    def test_roundtrip(self):
        budget = Budget(target_runs=3, worker_calls=2, used={"target_runs": 1})
        self.assertEqual(Budget.from_dict(budget.to_dict()).to_dict(), budget.to_dict())

    def test_unknown_kind_rejected(self):
        with self.assertRaises(LoopError):
            Budget(target_runs=1).spend("rounds")


class DecisionLogTest(unittest.TestCase):
    def test_append_and_read(self):
        with tempfile.TemporaryDirectory() as td:
            log = DecisionLog(Path(td) / "decisions.jsonl")
            log.record("skillopt", "fast", run="r1", candidate="c1",
                       score=0.8, baseline=0.6, accepted=True, reason="dev")
            rows = log.read()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["loop"], "skillopt")
            self.assertTrue(rows[0]["accepted"])

    def test_missing_fields_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            log = DecisionLog(Path(td) / "d.jsonl")
            with self.assertRaises(LoopError):
                log.append({"kind": "fast"})


class RegistryTest(unittest.TestCase):
    def test_all_registered_loops_validate(self):
        self.assertIn("gepa", loop_ids())
        self.assertIn("skillopt", loop_ids())
        for loop_id in loop_ids():
            get_loop(loop_id).validate()
        with self.assertRaises(LoopError):
            get_loop("nope")

    def test_action_validation_uses_loop_spec(self):
        spec = get_loop("skillopt")
        validate_action({"kind": "evaluate", "candidate_id": "c", "sample_id": "s",
                         "phase": "dev", "skill": "x"}, spec)
        with self.assertRaises(LoopError):
            validate_action({"kind": "merge", "candidate_id": "c"}, spec)
        with self.assertRaises(LoopError):
            validate_action({"kind": "unknown"}, spec)

    def test_restore_roundtrip(self):
        gepa = GepaSession("seed", ["s1"], max_metric_calls=4, population=2)
        action = gepa.next_action()
        gepa.apply(action, {"score": 0.0})
        restored = restore_loop("gepa", gepa.to_dict())
        self.assertEqual(restored.calls, 1)

        loo = LooAudit([AuditUnit(id="u1")], ["s1"], max_audit_calls=4)
        action = loo.next_action()
        loo.apply(action, {"score": 0.5})
        restored = restore_loop("loo", loo.to_dict())
        self.assertEqual(restored.calls, 1)

        baseline = BaselineLoop("seed", ["s1"])
        action = baseline.next_action()
        baseline.apply(action, {"score": 0.5})
        restored = restore_loop("baseline", baseline.to_dict())
        self.assertEqual(restored.calls, 1)

        skillopt = SkillOptLoop("seed", ["s1"], ["d1"], epochs=1, batch_size=1)
        restored = restore_loop("skillopt", skillopt.to_dict())
        self.assertEqual(restored.result()["best_id"], "seed")


class ConformanceTest(unittest.TestCase):
    def test_gepa_apply_protocol(self):
        loop = GepaSession("seed", ["s1"], max_metric_calls=4, population=2)
        action = loop.next_action()
        loop.apply(action, {"score": 0.0, "feedback": "miss"})
        action = loop.next_action()
        self.assertEqual(action["kind"], "reflect")
        loop.apply(action, {"text": "better"})
        self.assertEqual(loop.candidates[-1].parent, "seed")
        self.assertEqual(loop.calls, 1)

    def test_baseline_exact_budget_completes(self):
        loop = BaselineLoop("seed", ["s1", "s2"], budget=Budget(target_runs=2))
        action = drive(loop, lambda a: {"score": 0.5})
        self.assertEqual(action["reason"], "baseline_control")
        self.assertEqual(loop.calls, 2)

    def test_loo_apply_protocol(self):
        loop = LooAudit([AuditUnit(id="u1")], ["s1"], max_audit_calls=4)
        action = loop.next_action()
        loop.apply(action, {"score": 0.5})
        self.assertEqual(loop.result()["calls"], 1)

    def test_proposal_search_runs_on_contract(self):
        with tempfile.TemporaryDirectory() as td:
            engine = ProposalEngine(ProposalArchive(Path(td) / "proposals.jsonl"))
            loop = ProposalLoop(engine, ["s1"], max_rounds=1, population=2,
                                policy=GepaPolicy())
            action = loop.next_action()
            self.assertEqual(action["kind"], "reflect")
            loop.apply(action, {"drafts": [{
                "target_kind": "skill",
                "target_component": "diagnose.knowledge_usage",
                "summary": "只载筛出的候选",
                "change": {"files": ["skills/diagnose/SKILL.md"], "diff": "+ x"},
                "expected": "读取量下降", "risk": "低", "rollback": "恢复",
            }]})
            action = loop.next_action()
            self.assertEqual(action["kind"], "evaluate")
            loop.apply(action, {"scores": {"s1": 1.0}})
            self.assertEqual(loop.next_action()["kind"], "stop")
            self.assertEqual(loop.result()["evaluations"], 1)

    def test_population_family_runs_on_contract(self):
        loop = ToyPopulation("seed", ["s1"], population=2)
        action = drive(loop, lambda a: {"score": 1.0, "text": "child"})
        self.assertEqual(action["reason"], "population")
        self.assertEqual(len(loop.candidates), 2)
        self.assertEqual(loop.candidates[-1].parent, "seed")

    def test_allocation_family_schedules_subsets(self):
        loop = ToyAllocation(["c0", "c1", "c2", "c3"], ["s1", "s2"])
        scores = {"c0": 0.9, "c1": 0.8, "c2": 0.1, "c3": 0.2}
        action = drive(loop, lambda a: {"score": scores[a["candidate_id"]]})
        self.assertEqual(action["reason"], "allocation_complete")
        deep = [item for item in loop.evaluated if item[1] == "s2"]
        self.assertEqual(deep, [("c0", "s2"), ("c1", "s2")])
        self.assertEqual(loop.result()["survivors"], ["c0", "c1"])


if __name__ == "__main__":
    unittest.main()
