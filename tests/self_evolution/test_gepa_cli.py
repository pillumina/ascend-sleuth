"""gepa 命令组回归：init → evaluate → reflect → stop → result 全链与报错路径。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evolve.py"


def run_cli(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          cwd=str(ROOT))


class GepaCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = str(Path(self.tmp.name) / "gepa-state.json")
        self.seed = str(Path(self.tmp.name) / "seed.txt")
        Path(self.seed).write_text("seed region text", encoding="utf-8")

    def init(self, extra=()):
        result = run_cli("gepa", "init", "--state", self.state,
                         "--seed-file", self.seed,
                         "--samples", "s1,s2",
                         "--max-metric-calls", "4",
                         "--population", "3", *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def apply(self, *args):
        return run_cli("gepa", "apply", "--state", self.state, *args)

    def next_action(self):
        result = run_cli("gepa", "next", "--state", self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_full_loop_reaches_stop_and_result(self):
        info = self.init(extra=("--min-score", "0.5"))
        self.assertEqual(info["samples"], ["s1", "s2"])

        # seed 候选先评完两个样本
        action = self.next_action()
        self.assertEqual(action["kind"], "evaluate")
        self.assertEqual(action["candidate_id"], "seed")
        self.assertEqual(self.apply("--kind", "evaluate", "--candidate-id", "seed",
                                    "--sample-id", action["sample_id"],
                                    "--score", "0.4", "--feedback", "weak").returncode, 0)
        action = self.next_action()
        self.assertEqual(action["kind"], "evaluate")
        self.assertEqual(self.apply("--kind", "evaluate", "--candidate-id", "seed",
                                    "--sample-id", action["sample_id"],
                                    "--score", "0.6").returncode, 0)

        # 评完 seed 后进入反思，产出新候选
        action = self.next_action()
        self.assertEqual(action["kind"], "reflect")
        self.assertEqual(action["candidate_id"], "seed")
        self.assertTrue(action["failures"])
        mutated = str(Path(self.tmp.name) / "mutated.txt")
        Path(mutated).write_text("mutated region text", encoding="utf-8")
        self.assertEqual(self.apply("--kind", "reflect",
                                    "--skill-file", mutated).returncode, 0)

        # 新候选再评，直到预算耗尽返回 stop
        kinds = []
        while True:
            action = self.next_action()
            kinds.append(action["kind"])
            if action["kind"] == "stop":
                self.assertEqual(action["reason"], "budget")
                break
            self.assertEqual(self.apply("--kind", "evaluate",
                                        "--candidate-id", action["candidate_id"],
                                        "--sample-id", action["sample_id"],
                                        "--score", "0.5").returncode, 0)
        self.assertIn("evaluate", kinds)

        result = run_cli("gepa", "result", "--state", self.state)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["calls"], 4)
        self.assertEqual(data["max_metric_calls"], 4)
        self.assertEqual(len(data["candidates"]), 2)
        self.assertIn("seed", data["pareto"])

    def test_reflect_requires_skill_file(self):
        self.init()
        result = self.apply("--kind", "reflect")
        self.assertEqual(result.returncode, 2)
        self.assertIn("skill-file", result.stderr)

    def test_unknown_kind_rejected(self):
        self.init()
        result = run_cli("gepa", "apply", "--state", self.state,
                         "--kind", "spawn")
        self.assertNotEqual(result.returncode, 0)

    def test_overwrite_guard(self):
        self.init()
        result = run_cli("gepa", "init", "--state", self.state,
                         "--seed-file", self.seed, "--samples", "s1",
                         "--max-metric-calls", "1", "--population", "1")
        self.assertEqual(result.returncode, 2)
        self.assertIn("overwrite", result.stderr)
        result = run_cli("gepa", "init", "--state", self.state, "--overwrite",
                         "--seed-file", self.seed, "--samples", "s1",
                         "--max-metric-calls", "1", "--population", "1")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_apply_after_budget_exhausted_fails_with_state_exit(self):
        self.init(extra=("--max-metric-calls", "2"))
        for sid, score in (("s1", "0.5"), ("s2", "0.5")):
            self.assertEqual(self.apply("--kind", "evaluate", "--candidate-id",
                                        "seed", "--sample-id", sid,
                                        "--score", score).returncode, 0)
        action = self.next_action()
        self.assertEqual(action["kind"], "stop")
        result = self.apply("--kind", "evaluate", "--candidate-id", "seed",
                            "--sample-id", "s1", "--score", "1.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("max_metric_calls", result.stderr)

    def test_state_roundtrip_matches_core(self):
        self.init()
        sys.path.insert(0, str(ROOT / "scripts"))
        from evolve.agent_gepa import GepaSession  # noqa: E402
        data = json.loads(Path(self.state).read_text(encoding="utf-8"))
        session = GepaSession.from_dict(data)
        self.assertEqual(session.samples, ["s1", "s2"])
        self.assertEqual(session.select_stage.id, "select.pareto")
        self.assertEqual(session.propose_stage.id, "propose.reflection")


if __name__ == "__main__":
    unittest.main()
