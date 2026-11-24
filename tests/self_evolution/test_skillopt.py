# -*- coding: utf-8 -*-
"""SkillOpt 快更新循环：分组反思、合并、dev 严格采纳、拒绝记忆与预算。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.loops import LoopError  # noqa: E402
from evolve.loops.budget import Budget  # noqa: E402
from evolve.loops.skillopt import SkillOptLoop  # noqa: E402


def drive(loop, train_score=0.2, dev_score=0.9, limit=100):
    steps = 0
    while True:
        action = loop.next_action()
        steps += 1
        if steps > limit:
            raise AssertionError("loop did not stop")
        kind = action["kind"]
        if kind == "stop":
            return action
        if kind == "evaluate":
            if action["phase"] == "dev":
                score = 0.4 if action["candidate_id"] == "seed" else dev_score
            else:
                score = train_score
            loop.apply(action, {"score": score, "feedback": "f"})
        elif kind == "reflect":
            loop.apply(action, {"text": action["skill"] + "\n#edit"})
        elif kind == "merge":
            loop.apply(action, {"text": action["proposals"][0]})
        else:
            raise AssertionError(kind)


class SkillOptTest(unittest.TestCase):
    def test_batches_groups_and_strict_dev_acceptance(self):
        loop = SkillOptLoop("v0", ["s1", "s2"], ["d1", "d2"], epochs=1,
                            batch_size=2, reflection_minibatch=1,
                            success_threshold=0.5,
                            budget=Budget(target_runs=20, worker_calls=10))
        action = drive(loop, train_score=0.2, dev_score=0.9)
        self.assertEqual(action["reason"], "complete")
        result = loop.result()
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(result["rejected"], 0)
        self.assertEqual(result["best_score"], 0.9)
        self.assertEqual(result["seed_score"], 0.4)
        # 两组（失败 / 成功）各一次反思，再加一次合并 = 3 次 worker 调用
        self.assertEqual(result["worker_calls"], 3)

    def test_dev_tie_keeps_incumbent_and_remembers_rejection(self):
        loop = SkillOptLoop("v0", ["s1"], ["d1"], epochs=1, batch_size=1,
                            reflection_minibatch=1, rejected_memory=1,
                            budget=Budget(target_runs=20, worker_calls=10))
        action = drive(loop, train_score=0.2, dev_score=0.4)
        self.assertEqual(action["reason"], "complete")
        result = loop.result()
        self.assertEqual(result["accepted"], 0)
        self.assertEqual(result["best_id"], "seed")
        self.assertEqual(len(loop.rejected), 1)

    def test_reflect_actions_carry_rejected_memory(self):
        loop = SkillOptLoop("v0", ["s1"], ["d1"], epochs=2, batch_size=1,
                            reflection_minibatch=1, rejected_memory=5,
                            budget=Budget(target_runs=40, worker_calls=20))
        first_rejected = None
        last_rejected = None
        while True:
            action = loop.next_action()
            if action["kind"] == "stop":
                break
            if action["kind"] == "reflect":
                if first_rejected is None:
                    first_rejected = action["rejected"]
                last_rejected = action["rejected"]
                loop.apply(action, {"text": action["skill"] + "\n#edit"})
            elif action["kind"] == "merge":
                loop.apply(action, {"text": action["proposals"][0]})
            else:
                score = 0.4 if action["phase"] == "dev" else 0.2
                loop.apply(action, {"score": score})
        self.assertEqual(first_rejected, [])  # 第一次反思时还没有拒绝记录
        self.assertEqual(len(last_rejected), 1)  # 第一轮被拒的补丁进入第二轮提示

    def test_shuffle_is_deterministic_by_seed_and_epoch(self):
        one = SkillOptLoop("v0", ["s1", "s2", "s3", "s4"], ["d1"],
                           epochs=2, batch_size=2, seed=7)
        two = SkillOptLoop("v0", ["s1", "s2", "s3", "s4"], ["d1"],
                           epochs=2, batch_size=2, seed=7)
        self.assertEqual(one.batches, [])
        seed_action = one.next_action()
        two.next_action()
        one.apply(seed_action, {"score": 0.5})
        two.apply(two.next_action(), {"score": 0.5})
        one.next_action()
        two.next_action()
        self.assertEqual(one.batches, two.batches)

    def test_budget_stop(self):
        loop = SkillOptLoop("v0", ["s1"], ["d1"], epochs=1, batch_size=1,
                            budget=Budget(target_runs=1))
        action = drive(loop, limit=10)
        self.assertEqual(action["reason"], "target_runs_budget")
        self.assertEqual(loop.result()["calls"], 1)

    def test_budget_exhaustion_after_dev_still_decides(self):
        loop = SkillOptLoop("v0", ["s1"], ["d1"], epochs=1, batch_size=1,
                            reflection_minibatch=1,
                            budget=Budget(target_runs=3, worker_calls=2))
        action = drive(loop, train_score=0.2, dev_score=0.9)
        self.assertEqual(action["reason"], "target_runs_budget")
        self.assertEqual(loop.result()["accepted"], 1)

    def test_disjoint_train_and_dev(self):
        with self.assertRaises(LoopError):
            SkillOptLoop("v0", ["s1"], ["s1"])

    def test_state_roundtrip_mid_epoch(self):
        loop = SkillOptLoop("v0", ["s1", "s2"], ["d1"], epochs=1, batch_size=2,
                            reflection_minibatch=1,
                            budget=Budget(target_runs=20, worker_calls=10))
        action = loop.next_action()
        loop.apply(action, {"score": 0.4})  # seed dev
        action = loop.next_action()
        loop.apply(action, {"score": 0.2})  # first train sample
        restored = SkillOptLoop.from_dict(loop.to_dict())
        self.assertEqual(restored.to_dict(), loop.to_dict())
        action = restored.next_action()
        self.assertEqual(action["phase"], "train")


if __name__ == "__main__":
    unittest.main()
