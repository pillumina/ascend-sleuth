"""agent GEPA 状态文件 CLI：动作循环可跨进程。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "agent_gepa.py"


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
        encoding="utf-8", cwd=str(ROOT),
    )


class AgentGepaCliTest(unittest.TestCase):
    def test_full_action_loop(self):
        with tempfile.TemporaryDirectory() as td:
            state = str(Path(td) / "state.json")
            init = run("init", "--seed", "seed skill", "--samples", "S-1,S-2",
                       "--state", state, "--max-metric-calls", "4", "--population", "2",
                       "--target-skill", "diagnose", "--region", "routing_hints")
            self.assertEqual(init.returncode, 0, init.stderr)
            action = json.loads(run("next", "--state", state).stdout)
            self.assertEqual(action["kind"], "evaluate")
            run("record", "--state", state, "--candidate", "seed", "--sample", "S-1",
                "--score", "0", "--feedback", "missing root cause")
            run("record", "--state", state, "--candidate", "seed", "--sample", "S-2",
                "--score", "1")
            reflect = json.loads(run("next", "--state", state).stdout)
            self.assertEqual(reflect["kind"], "reflect")
            self.assertEqual(len(reflect["failures"]), 1)
            created = run("candidate", "--state", state, "--skill", "candidate skill")
            self.assertIn("candidate: c1", created.stdout)
            action = json.loads(run("next", "--state", state).stdout)
            self.assertEqual(action["candidate_id"], "c1")
            result = json.loads(run("result", "--state", state).stdout)
            self.assertEqual(result["best_id"], "seed")
            self.assertEqual(result["calls"], 2)

    def test_candidate_before_reflect_fails(self):
        with tempfile.TemporaryDirectory() as td:
            state = str(Path(td) / "state.json")
            run("init", "--seed", "seed", "--samples", "S-1", "--state", state)
            result = run("candidate", "--state", state, "--skill", "x")
            self.assertEqual(result.returncode, 2)
            self.assertIn("no reflect", result.stderr)


if __name__ == "__main__":
    unittest.main()
