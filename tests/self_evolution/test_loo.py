"""留一效用审计回归：全消融 → 效用 → 收缩队列 → 预算 stop，及 CLI 驱动协议。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.loo import AuditUnit, LooAudit, LooError  # noqa: E402

SCRIPT = ROOT / "scripts" / "evolve.py"


def _session(**kwargs) -> LooAudit:
    defaults = dict(
        units=[AuditUnit(id="u1", label="a"), AuditUnit(id="u2", label="b")],
        samples=["s1", "s2"],
        max_audit_calls=100,
        shrink_threshold=0.0,
    )
    defaults.update(kwargs)
    return LooAudit(**defaults)


def _run_all(audit: LooAudit, ablated_scores: dict) -> None:
    """按 next_action 驱动到 complete；ablated_scores[(unit, sample)] 给分。"""
    while True:
        action = audit.next_action()
        if action["kind"] == "stop":
            return action
        score = (0.8 if action["variant"] == "full"
                 else ablated_scores.get((action["unit_id"], action["sample_id"]), 0.8))
        audit.record_evaluation(action["unit_id"], action["variant"],
                                action["sample_id"], score)


class LooStateMachineTest(unittest.TestCase):
    def test_full_audit_orders_shrink_queue_by_utility(self):
        audit = _session()
        _run_all(audit, ablated_scores={
            ("u1", "s1"): 0.8, ("u1", "s2"): 0.8,   # u1 效用 0：冗余
            ("u2", "s1"): 0.4, ("u2", "s2"): 0.5,   # u2 效用正
        })
        result = audit.result()
        self.assertEqual(result["utilities"], {"u1": 0.0, "u2": 0.35})
        queue = result["shrink_queue"]
        self.assertEqual([item["unit_id"] for item in queue], ["u1"])
        self.assertEqual(queue[0]["utility"], 0.0)
        # u1 的证据：两个样例消融后都不降
        self.assertEqual(len(queue[0]["evidence"]), 2)

    def test_threshold_zero_keeps_small_positive(self):
        audit = _session(shrink_threshold=0.0)
        _run_all(audit, ablated_scores={
            ("u1", "s1"): 0.79, ("u1", "s2"): 0.79,
            ("u2", "s1"): 0.8, ("u2", "s2"): 0.8})
        # u1 效用 0.005 > 0 不进队列；u2 效用 0 进队列
        self.assertEqual([item["unit_id"] for item in audit.shrink_queue()], ["u2"])

    def test_budget_stop_and_state_error(self):
        audit = _session(max_audit_calls=2)
        action = audit.next_action()
        audit.record_evaluation(action["unit_id"], action["variant"],
                                action["sample_id"], 0.8)
        action = audit.next_action()
        audit.record_evaluation(action["unit_id"], action["variant"],
                                action["sample_id"], 0.8)
        self.assertEqual(audit.next_action()["reason"], "budget")
        with self.assertRaises(LooError):
            audit.record_evaluation("u1", "full", "s1", 0.5)

    def test_apply_without_pending_rejected(self):
        audit = _session()
        with self.assertRaises(LooError):
            audit.record_evaluation("u1", "full", "s1", 0.8)
        # 顺序错：评了消融 variant 但 pending 是 full
        action = audit.next_action()
        with self.assertRaises(LooError):
            audit.record_evaluation(action["unit_id"], f"without:{action['unit_id']}",
                                    action["sample_id"], 0.8)

    def test_state_roundtrip(self):
        audit = _session()
        action = audit.next_action()
        audit.record_evaluation(action["unit_id"], action["variant"],
                                action["sample_id"], 0.8)
        restored = LooAudit.from_dict(json.loads(json.dumps(audit.to_dict())))
        self.assertEqual(restored.calls, 1)
        self.assertEqual([u.id for u in restored.units], ["u1", "u2"])
        # 恢复后继续驱动到 complete
        while True:
            action = restored.next_action()
            if action["kind"] == "stop":
                self.assertEqual(action["reason"], "complete")
                break
            score = 0.8 if action["variant"] == "full" else 0.5
            restored.record_evaluation(action["unit_id"], action["variant"],
                                       action["sample_id"], score)


class LooCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = str(Path(self.tmp.name) / "loo-state.json")

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), "loo", *args],
                              capture_output=True, text=True, encoding="utf-8",
                              cwd=str(ROOT))

    def test_cli_loop_to_result(self):
        result = self.run_cli("init", "--state", self.state,
                              "--units", "u1:a,u2:b", "--samples", "s1,s2",
                              "--max-audit-calls", "8")
        self.assertEqual(result.returncode, 0, result.stderr)
        while True:
            nxt = self.run_cli("next", "--state", self.state)
            self.assertEqual(nxt.returncode, 0, nxt.stderr)
            action = json.loads(nxt.stdout)
            if action["kind"] == "stop":
                self.assertEqual(action["reason"], "complete")
                break
            # 去掉单元后分数不降反升 → 负效用 → 进收缩队列
            score = 0.8 if action["variant"] == "full" else (
                0.9 if action["unit_id"] == "u1" else 1.0)
            applied = self.run_cli("apply", "--state", self.state, "--kind",
                                   "evaluate", "--unit-id", action["unit_id"],
                                   "--variant", action["variant"],
                                   "--sample-id", action["sample_id"],
                                   "--score", str(score))
            self.assertEqual(applied.returncode, 0, applied.stderr)
        result = self.run_cli("result", "--state", self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        # 效用升序：u2(-0.2) 在 u1(-0.1) 前
        self.assertEqual([item["unit_id"] for item in data["shrink_queue"]],
                         ["u2", "u1"])

    def test_apply_mismatch_is_state_error(self):
        self.run_cli("init", "--state", self.state, "--units", "u1",
                     "--samples", "s1", "--max-audit-calls", "2")
        result = self.run_cli("apply", "--state", self.state, "--kind", "evaluate",
                              "--unit-id", "u1", "--variant", "full",
                              "--sample-id", "s1", "--score", "0.5")
        self.assertEqual(result.returncode, 1)
        self.assertIn("pending", result.stderr)

    def test_overwrite_guard(self):
        self.run_cli("init", "--state", self.state, "--units", "u1",
                     "--samples", "s1", "--max-audit-calls", "2")
        result = self.run_cli("init", "--state", self.state, "--units", "u1",
                              "--samples", "s1", "--max-audit-calls", "2")
        self.assertEqual(result.returncode, 2)
        self.assertIn("overwrite", result.stderr)


if __name__ == "__main__":
    unittest.main()
