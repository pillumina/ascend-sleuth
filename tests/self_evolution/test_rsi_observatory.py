# -*- coding: utf-8 -*-
"""RSI 实验台只读桥：list / detail / 错误码 / history 与缺口。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.store import RSIStore  # noqa: E402

SCRIPT = ROOT / "scripts" / "rsi_observatory.py"


def _proposal(proposal_id="P-1", diff="+x"):
    return {
        "id": proposal_id,
        "target": "skill",
        "component": "diagnose.knowledge_usage",
        "summary": "阶段二只载筛出的候选全文",
        "artifact_kind": "code",
        "artifact": {"files": ["skills/diagnose/SKILL.md"], "diff": diff},
        "expected": "知识读取量下降",
        "risk": "低",
        "rollback": "恢复原说明",
        "status": "reject",
        "decision": "insufficient",
        "rolled_back": True,
        "workspace": "/tmp/ws",
        "at": "2026-11-20T15:28:00+00:00",
    }


def _conclusion():
    return {
        "decision": "insufficient",
        "reason": "9 条有效样本中只有 1 条支持候选。",
        "metrics": {"constraints": {"knowledge": {"decision": "accept", "paired": 9}}},
        "cost": {"tokens": {"baseline": 100, "candidate": 90}, "paired": 9, "missing": 0},
        "alpha_eff": 0.1,
        "b": 1,
        "c": 0,
        "n": 9,
        "p_value": 0.5,
        "proposal": "P-1",
        "at": "2026-11-20T15:41:02+00:00",
    }


def _experiment():
    return {
        "target_kind": "skill",
        "target_component": "diagnose.knowledge_usage",
        "algorithm": "agent_draft",
        "execution": "subagent",
        "decision": "insufficient",
        "samples": ["S-1", "S-2"],
        "baseline": {"score": 0.5, "samples": ["S-1"]},
        "candidate": {"score": 0.5, "samples": ["S-1"]},
        "paired": {"b": 1, "c": 0, "n": 2},
        "summary": "阶段二只载筛出的候选全文",
    }


def _tasks():
    return {
        "samples": [{"short_id": "S-1"}, {"short_id": "S-2"}],
        "arms": {"baseline": {"trace_dir": "/tmp/a"}, "candidate": {"trace_dir": "/tmp/b"}},
        "workspace": "/tmp/ws",
    }


def _collected():
    return {"arms": {"baseline": [{}, {}], "candidate": [{}, {}]}}


def _record(base, experiment_id=None):
    store = RSIStore(base)
    store.record_experiment(_proposal(), _experiment(), _conclusion(), _tasks(), _collected(),
                            "insufficient", experiment_id=experiment_id)
    return store


def _run(base, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args, "--json", "--base", str(base)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
    )


class RsiObservatoryBridgeTest(unittest.TestCase):
    def test_empty_store_lists_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "evolve"
            proc = _run(base, "list")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["schema"], "rsi-observatory-v1")
            self.assertEqual(payload["counts"], {"events": 0, "experiments": 0, "proposals": 0})
            self.assertEqual(payload["experiments"], [])
            self.assertEqual(payload["source"]["backend"], "local")

    def test_list_and_detail_read_through_store(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "evolve"
            store = _record(base)
            rows = store.read()
            self.assertEqual(len(rows), 4)
            self.assertEqual({row["kind"] for row in rows},
                             {"proposal", "decision", "rollout", "experiment"})

            listed = _run(base, "list")
            self.assertEqual(listed.returncode, 0, listed.stderr)
            payload = json.loads(listed.stdout)
            self.assertEqual(payload["counts"]["experiments"], 1)
            row = payload["experiments"][0]
            self.assertEqual(row["proposalId"], "P-1")
            self.assertEqual(row["decision"], "insufficient")
            self.assertTrue(row["rolledBack"])
            self.assertIn("rolled_back", row["gaps"])
            self.assertIsInstance(row["eventId"], str)

            detailed = _run(base, "detail", "--experiment", row["eventId"])
            self.assertEqual(detailed.returncode, 0, detailed.stderr)
            detail = json.loads(detailed.stdout)
            self.assertEqual(detail["experiment"]["eventId"], row["eventId"])
            self.assertEqual(detail["proposal"]["id"], "P-1")
            self.assertEqual(detail["rollout"]["arms"], {"baseline": 2, "candidate": 2})
            self.assertEqual([item["kind"] for item in detail["history"]],
                             ["proposal", "decision", "rollout", "experiment"])
            stages = {item["id"]: item for item in detail["stages"]}
            self.assertEqual(stages["propose"]["state"], "evidence")
            self.assertEqual(stages["gate"]["state"], "evidence")
            self.assertEqual(stages["attribute"]["state"], "evidence")
            self.assertIn("rolled_back", detail["gaps"])

    def test_unknown_experiment_exits_4(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "evolve"
            _record(base)
            proc = _run(base, "detail", "--experiment", "EX-nope")
            self.assertEqual(proc.returncode, 4)
            self.assertIn("EX-nope", proc.stderr)

    def test_corrupt_store_exits_3(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "evolve"
            base.mkdir(parents=True)
            (base / "rsi-events.jsonl").write_text("{not json\n", encoding="utf-8")
            proc = _run(base, "list")
            self.assertEqual(proc.returncode, 3)
            self.assertIn("invalid JSON", proc.stderr)

    def test_long_diff_is_clipped(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "evolve"
            store = RSIStore(base)
            proposal = _proposal(diff="x" * 9000)
            store.record_experiment(proposal, _experiment(), _conclusion(), _tasks(),
                                    _collected(), "insufficient")
            row = json.loads(_run(base, "list").stdout)["experiments"][0]
            detail = json.loads(_run(base, "detail", "--experiment", row["eventId"]).stdout)
            diff = detail["proposal"]["artifact"]["diff"]
            self.assertLessEqual(len(diff), 4100)
            self.assertTrue(diff.endswith("已截断）"))
            self.assertTrue(detail["truncated"])

    def test_reused_experiment_id_is_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "evolve"
            store = RSIStore(base)
            for _ in range(2):
                store.record_experiment(_proposal(), _experiment(), _conclusion(), _tasks(),
                                        _collected(), "insufficient", experiment_id="EX-shared")
            row = json.loads(_run(base, "list").stdout)["experiments"][0]
            detail = json.loads(_run(base, "detail", "--experiment", row["eventId"]).stdout)
            self.assertEqual(len([item for item in detail["history"]
                                  if item["kind"] == "experiment"]), 2)
            self.assertIn("id_collision", detail["gaps"])


if __name__ == "__main__":
    unittest.main()
