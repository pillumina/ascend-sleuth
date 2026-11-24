# -*- coding: utf-8 -*-
"""通用 loop / experiment arms CLI：注册表、跨进程动作循环与结果。"""

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


class LoopCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_list_and_show(self):
        result = run_cli("loop", "list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        ids = [item["id"] for item in json.loads(result.stdout)]
        self.assertEqual(ids, ["baseline", "gepa", "loo", "skillopt"])
        show = run_cli("loop", "show", "--loop", "skillopt")
        self.assertEqual(show.returncode, 0, show.stderr)
        data = json.loads(show.stdout)
        self.assertEqual(data["required_roles"], ["train", "dev"])
        self.assertIn("merge", [item["kind"] for item in data["actions"]])
        self.assertEqual(data["params"]["epochs"], 3)

    def _policy_with_loop_defaults(self):
        return self.write("policy.yaml", (
            "experiment:\n"
            "  loop: skillopt\n"
            "  loops:\n"
            "    skillopt:\n"
            "      params: {epochs: 1, batch_size: 2, reflection_minibatch: 1}\n"
            "      budget: {target_runs: 20}\n"
        ))

    def test_loop_init_uses_policy_default_loop(self):
        policy = self._policy_with_loop_defaults()
        config = self.write("skillopt.yaml", (
            "seed_text: v0\n"
            "data: {train: [s1], dev: [d1]}\n"
        ))
        state = str(self.dir / "configured.json")
        init = run_cli("loop", "init", "--state", state,
                       "--config", str(config), "--policy", str(policy))
        self.assertEqual(init.returncode, 0, init.stderr)
        self.assertEqual(json.loads(init.stdout)["loop"], "skillopt")
        data = json.loads(Path(state).read_text(encoding="utf-8"))
        self.assertEqual(data["loop"], "skillopt")
        self.assertEqual(data["state"]["budget"]["target_runs"], 20)

    def test_explicit_loop_config_overrides_policy_defaults(self):
        policy = self.write("policy.yaml", (
            "experiment:\n"
            "  loop: skillopt\n"
            "  loops:\n"
            "    skillopt:\n"
            "      params: {epochs: 1, batch_size: 2, reflection_minibatch: 1}\n"
            "      budget: {target_runs: 20, worker_calls: 9}\n"
        ))
        config = self.write("override.yaml", (
            "seed_text: v0\n"
            "data: {train: [s1], dev: [d1]}\n"
            "params: {epochs: 7}\n"
            "budget: {target_runs: 5}\n"
        ))
        state = str(self.dir / "override.json")
        init = run_cli("loop", "init", "--state", state,
                       "--config", str(config), "--policy", str(policy))
        self.assertEqual(init.returncode, 0, init.stderr)
        data = json.loads(Path(state).read_text(encoding="utf-8"))
        self.assertEqual(data["state"]["epochs"], 7)
        self.assertEqual(data["state"]["budget"]["target_runs"], 5)
        self.assertEqual(data["state"]["budget"]["worker_calls"], 9)

    def test_legacy_max_metric_calls_keeps_precedence(self):
        policy = self.write("policy.yaml", (
            "experiment:\n"
            "  loop: gepa\n"
            "  loops:\n"
            "    gepa:\n"
            "      budget: {target_runs: 20}\n"
        ))
        config = self.write("legacy.yaml", (
            "seed_text: v0\n"
            "data: {eval: [s1]}\n"
            "max_metric_calls: 7\n"
        ))
        state = str(self.dir / "legacy.json")
        init = run_cli("loop", "init", "--state", state,
                       "--config", str(config), "--policy", str(policy))
        self.assertEqual(init.returncode, 0, init.stderr)
        data = json.loads(Path(state).read_text(encoding="utf-8"))
        self.assertEqual(data["state"]["max_metric_calls"], 7)
        self.assertEqual(data["state"]["budget"]["target_runs"], 7)

    def test_zero_budget_rejected(self):
        config = self.write("zero.yaml", (
            "seed_text: seed\n"
            "data: {eval: [s1]}\n"
            "budget: {target_runs: 0}\n"
        ))
        result = run_cli("loop", "init", "--loop", "baseline",
                         "--state", str(self.dir / "zero.json"),
                         "--config", str(config))
        self.assertEqual(result.returncode, 1)
        self.assertIn("budget target_runs", result.stderr)

    def test_policy_recipe_is_default(self):
        policy = self.write("policy.yaml", "experiment:\n  recipe: skillopt-fast\n")
        config = self.write("config.yaml", (
            "seed_text: v0\n"
            "data: {train: [s1], dev: [d1]}\n"
        ))
        state = str(self.dir / "policy-recipe.json")
        init = run_cli("loop", "init", "--state", state,
                       "--config", str(config), "--policy", str(policy))
        self.assertEqual(init.returncode, 0, init.stderr)
        data = json.loads(Path(state).read_text(encoding="utf-8"))
        self.assertEqual(data["loop"], "skillopt")
        self.assertEqual(data["state"]["epochs"], 2)

    def test_recipe_selection(self):
        config = self.write("skillopt.yaml", (
            "seed_text: v0\n"
            "data: {train: [s1], dev: [d1]}\n"
        ))
        state = str(self.dir / "recipe.json")
        init = run_cli("loop", "init", "--recipe", "skillopt-fast",
                       "--state", state, "--config", str(config))
        self.assertEqual(init.returncode, 0, init.stderr)
        data = json.loads(Path(state).read_text(encoding="utf-8"))
        self.assertEqual(data["loop"], "skillopt")
        self.assertEqual(data["state"]["epochs"], 2)
        self.assertEqual(data["state"]["budget"]["target_runs"], 30)

    def test_recipe_explicit_values_override(self):
        config = self.write("skillopt.yaml", (
            "seed_text: v0\n"
            "data: {train: [s1], dev: [d1]}\n"
            "params: {epochs: 5}\n"
            "budget: {target_runs: 5}\n"
        ))
        state = str(self.dir / "recipe-override.json")
        init = run_cli("loop", "init", "--recipe", "skillopt-fast",
                       "--state", state, "--config", str(config))
        self.assertEqual(init.returncode, 0, init.stderr)
        data = json.loads(Path(state).read_text(encoding="utf-8"))
        self.assertEqual(data["state"]["epochs"], 5)
        self.assertEqual(data["state"]["budget"]["target_runs"], 5)

    def test_loop_and_recipe_are_mutually_exclusive(self):
        config = self.write("seed.yaml", "seed_text: v0\ndata: {eval: [s1]}\n")
        result = run_cli("loop", "init", "--loop", "gepa",
                         "--recipe", "skillopt-fast",
                         "--state", str(self.dir / "x.json"),
                         "--config", str(config))
        self.assertEqual(result.returncode, 1)
        self.assertIn("mutually exclusive", result.stderr)

    def test_unknown_recipe_rejected(self):
        config = self.write("seed.yaml", "seed_text: v0\ndata: {eval: [s1]}\n")
        result = run_cli("loop", "init", "--recipe", "nope",
                         "--state", str(self.dir / "x.json"),
                         "--config", str(config))
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown recipe", result.stderr)

    def test_gepa_roundtrip(self):
        config = self.write("gepa.yaml", (
            "seed_text: seed text\n"
            "data: {eval: [s1, s2]}\n"
            "target_runs: 4\n"
            "population: 2\n"
            "select_stage: select.pareto\n"
        ))
        state = str(self.dir / "gepa.json")
        init = run_cli("loop", "init", "--loop", "gepa", "--state", state,
                       "--config", str(config))
        self.assertEqual(init.returncode, 0, init.stderr)
        for _ in range(20):
            nxt = run_cli("loop", "next", "--state", state)
            self.assertEqual(nxt.returncode, 0, nxt.stderr)
            action = json.loads(nxt.stdout)
            if action["kind"] == "stop":
                break
            if action["kind"] == "evaluate":
                score = "0.2" if action["sample_id"] == "s1" else "0.8"
                applied = run_cli("loop", "apply", "--state", state, "--kind",
                                  "evaluate", "--score", score)
            else:
                text = self.write("edit.txt", "better text")
                applied = run_cli("loop", "apply", "--state", state, "--kind",
                                  "reflect", "--text-file", str(text))
            self.assertEqual(applied.returncode, 0, applied.stderr)
        result = run_cli("loop", "result", "--state", state)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["loop"], "gepa")
        self.assertGreaterEqual(data["calls"], 1)

    def test_skillopt_roundtrip(self):
        config = self.write("skillopt.yaml", (
            "seed_text: v0\n"
            "data: {train: [s1, s2], dev: [d1]}\n"
            "target_runs: 30\n"
            "worker_calls: 20\n"
            "epochs: 1\n"
            "batch_size: 2\n"
            "reflection_minibatch: 1\n"
        ))
        state = str(self.dir / "skillopt.json")
        init = run_cli("loop", "init", "--loop", "skillopt", "--state", state,
                       "--config", str(config))
        self.assertEqual(init.returncode, 0, init.stderr)
        for _ in range(50):
            nxt = run_cli("loop", "next", "--state", state)
            action = json.loads(nxt.stdout)
            if action["kind"] == "stop":
                break
            if action["kind"] == "evaluate":
                score = "0.4" if action.get("phase") == "dev" and \
                    action.get("candidate_id") == "seed" else "0.9"
                applied = run_cli("loop", "apply", "--state", state, "--kind",
                                  "evaluate", "--score", score)
            elif action["kind"] == "reflect":
                text = self.write("edit.txt", action["skill"] + "\n#edit")
                applied = run_cli("loop", "apply", "--state", state, "--kind",
                                  "reflect", "--text-file", str(text))
            else:
                text = self.write("merge.txt", action["proposals"][0])
                applied = run_cli("loop", "apply", "--state", state, "--kind",
                                  "merge", "--text-file", str(text))
            self.assertEqual(applied.returncode, 0, applied.stderr)
        result = run_cli("loop", "result", "--state", state)
        data = json.loads(result.stdout)
        self.assertEqual(data["loop"], "skillopt")
        self.assertEqual(data["accepted"], 1)
        self.assertEqual(data["seed_score"], 0.4)
        records = Path(state + ".decisions.jsonl")
        self.assertTrue(records.exists())
        rows = [json.loads(line) for line in records.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(row.get("accepted") for row in rows))

    def test_apply_kind_mismatch_is_state_error(self):
        config = self.write("g.yaml", "seed_text: seed\ndata: {eval: [s1]}\n")
        state = str(self.dir / "g.json")
        run_cli("loop", "init", "--loop", "gepa", "--state", state,
                "--config", str(config))
        action = json.loads(run_cli("loop", "next", "--state", state).stdout)
        self.assertEqual(action["kind"], "evaluate")
        applied = run_cli("loop", "apply", "--state", state, "--kind", "reflect",
                          "--text-file", str(self.write("x.txt", "x")))
        self.assertEqual(applied.returncode, 1)
        self.assertIn("pending action", applied.stderr)


class ArmsCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_invalid_yaml_reports_error_without_traceback(self):
        spec = self.dir / "bad.yaml"
        spec.write_text("id: [\n", encoding="utf-8")
        result = run_cli("experiment", "arms", "init", "--spec", str(spec),
                         "--state", str(self.dir / "bad.json"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_arms_init_uses_policy_loop_and_params(self):
        policy = self.write("policy.yaml", (
            "experiment:\n"
            "  loop: skillopt\n"
            "  loops:\n"
            "    skillopt:\n"
            "      params: {epochs: 1, batch_size: 2, reflection_minibatch: 1}\n"
            "      budget: {target_runs: 20}\n"
        ))
        spec = self.dir / "empty-arm.yaml"
        spec.write_text(
            "id: configured\n"
            "target: skill\n"
            "component: c\n"
            "composition: parallel\n"
            "seed_text: t\n"
            "samples: {train: [s1], dev: [d1]}\n"
            "arms:\n"
            "  - name: a\n"
            "    loop: \"\"\n",
            encoding="utf-8",
        )
        state = str(self.dir / "configured-arms.json")
        init = run_cli("experiment", "arms", "init", "--spec", str(spec),
                       "--state", state, "--policy", str(policy))
        self.assertEqual(init.returncode, 0, init.stderr)
        data = json.loads(Path(state).read_text(encoding="utf-8"))
        self.assertEqual(data["spec"]["arms"][0]["loop"], "skillopt")
        self.assertEqual(data["spec"]["arms"][0]["params"]["epochs"], 1)
        self.assertEqual(data["spec"]["arms"][0]["budget"]["target_runs"], 20)

    def test_arms_explicit_values_override_policy_defaults(self):
        policy = self.write("policy.yaml", (
            "experiment:\n"
            "  loop: skillopt\n"
            "  loops:\n"
            "    skillopt:\n"
            "      params: {epochs: 1, batch_size: 2, reflection_minibatch: 1}\n"
            "      budget: {target_runs: 20, worker_calls: 9}\n"
        ))
        spec = self.dir / "override-arm.yaml"
        spec.write_text(
            "id: override\n"
            "target: skill\n"
            "component: c\n"
            "composition: parallel\n"
            "seed_text: t\n"
            "samples: {train: [s1], dev: [d1]}\n"
            "arms:\n"
            "  - name: a\n"
            "    loop: \"\"\n"
            "    params: {epochs: 7}\n"
            "    budget: {target_runs: 5}\n",
            encoding="utf-8",
        )
        state = str(self.dir / "override-arms.json")
        init = run_cli("experiment", "arms", "init", "--spec", str(spec),
                       "--state", state, "--policy", str(policy))
        self.assertEqual(init.returncode, 0, init.stderr)
        data = json.loads(Path(state).read_text(encoding="utf-8"))
        arm = data["spec"]["arms"][0]
        self.assertEqual(arm["params"]["epochs"], 7)
        self.assertEqual(arm["budget"]["target_runs"], 5)
        self.assertEqual(arm["budget"]["worker_calls"], 9)

    def test_arms_policy_recipe_is_default(self):
        policy = self.write("policy.yaml", "experiment:\n  recipe: skillopt-fast\n")
        spec = self.dir / "policy-arm.yaml"
        spec.write_text(
            "id: r\n"
            "target: skill\n"
            "component: c\n"
            "composition: parallel\n"
            "seed_text: t\n"
            "samples: {train: [s1], dev: [d1]}\n"
            "arms:\n"
            "  - name: a\n",
            encoding="utf-8",
        )
        state = str(self.dir / "policy-arm.json")
        init = run_cli("experiment", "arms", "init", "--spec", str(spec),
                       "--state", state, "--policy", str(policy))
        self.assertEqual(init.returncode, 0, init.stderr)
        arm = json.loads(Path(state).read_text(encoding="utf-8"))["spec"]["arms"][0]
        self.assertEqual(arm["loop"], "skillopt")
        self.assertEqual(arm["params"]["epochs"], 2)

    def test_arms_recipe_fills_loop_and_params(self):
        spec = self.dir / "recipe-arm.yaml"
        spec.write_text(
            "id: r\n"
            "target: skill\n"
            "component: c\n"
            "composition: parallel\n"
            "seed_text: t\n"
            "samples: {train: [s1], dev: [d1]}\n"
            "arms:\n"
            "  - name: a\n"
            "    recipe: skillopt-fast\n",
            encoding="utf-8",
        )
        state = str(self.dir / "recipe-arm.json")
        init = run_cli("experiment", "arms", "init", "--spec", str(spec),
                       "--state", state)
        self.assertEqual(init.returncode, 0, init.stderr)
        arm = json.loads(Path(state).read_text(encoding="utf-8"))["spec"]["arms"][0]
        self.assertEqual(arm["loop"], "skillopt")
        self.assertEqual(arm["recipe"], "skillopt-fast")
        self.assertEqual(arm["params"]["epochs"], 2)
        self.assertEqual(arm["roles"], {"train": "train", "dev": "dev"})
        self.assertEqual(arm["budget"]["target_runs"], 30)

    def test_arms_recipe_explicit_values_override(self):
        spec = self.dir / "recipe-arm.yaml"
        spec.write_text(
            "id: r\n"
            "target: skill\n"
            "component: c\n"
            "composition: parallel\n"
            "seed_text: t\n"
            "samples: {train: [s1], dev: [d1]}\n"
            "arms:\n"
            "  - name: a\n"
            "    recipe: skillopt-fast\n"
            "    params: {epochs: 5}\n"
            "    budget: {target_runs: 5}\n",
            encoding="utf-8",
        )
        state = str(self.dir / "recipe-override.json")
        init = run_cli("experiment", "arms", "init", "--spec", str(spec),
                       "--state", state)
        self.assertEqual(init.returncode, 0, init.stderr)
        arm = json.loads(Path(state).read_text(encoding="utf-8"))["spec"]["arms"][0]
        self.assertEqual(arm["params"]["epochs"], 5)
        self.assertEqual(arm["budget"]["target_runs"], 5)

    def test_arms_recipe_loop_conflict_rejected(self):
        spec = self.dir / "conflict.yaml"
        spec.write_text(
            "id: r\n"
            "target: skill\n"
            "component: c\n"
            "seed_text: t\n"
            "samples: {train: [s1], dev: [d1]}\n"
            "arms:\n"
            "  - name: a\n"
            "    loop: gepa\n"
            "    recipe: skillopt-fast\n",
            encoding="utf-8",
        )
        result = run_cli("experiment", "arms", "init", "--spec", str(spec),
                         "--state", str(self.dir / "conflict.json"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("uses loop", result.stderr)

    def test_arms_unknown_recipe_rejected(self):
        spec = self.dir / "bad-recipe.yaml"
        spec.write_text(
            "id: r\n"
            "target: skill\n"
            "component: c\n"
            "seed_text: t\n"
            "samples: {eval: [s1], dev: [d1]}\n"
            "arms:\n"
            "  - name: a\n"
            "    recipe: nope\n",
            encoding="utf-8",
        )
        result = run_cli("experiment", "arms", "init", "--spec", str(spec),
                         "--state", str(self.dir / "bad.json"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("unknown recipe", result.stderr)

    def test_parallel_arms_roundtrip(self):
        spec = self.dir / "spec.yaml"
        spec.write_text(
            "id: x1\n"
            "target: skill\n"
            "component: diagnose.routing_hints\n"
            "composition: parallel\n"
            "primary_arm: gepa\n"
            "eval_role: dev\n"
            "seed_text: seed text\n"
            "samples:\n"
            "  eval: [s1, s2]\n"
            "  dev: [d1]\n"
            "arms:\n"
            "  - name: control\n"
            "    loop: baseline\n"
            "    budget: {target_runs: 4}\n"
            "  - name: gepa\n"
            "    loop: gepa\n"
            "    params: {population: 2}\n"
            "    budget: {target_runs: 6}\n",
            encoding="utf-8",
        )
        state = str(self.dir / "arms.json")
        init = run_cli("experiment", "arms", "init", "--spec", str(spec),
                       "--state", state)
        self.assertEqual(init.returncode, 0, init.stderr)
        for _ in range(40):
            nxt = run_cli("experiment", "arms", "next", "--state", state)
            self.assertEqual(nxt.returncode, 0, nxt.stderr)
            pending = json.loads(nxt.stdout)
            if pending.get("kind") == "stop":
                break
            action = pending["action"]
            if action["kind"] == "evaluate":
                score = "0.2" if action["sample_id"].startswith("s") else "0.6"
                applied = run_cli("experiment", "arms", "apply", "--state", state,
                                  "--kind", "evaluate", "--score", score)
            else:
                edit = self.dir / "edit.txt"
                edit.write_text("better text", encoding="utf-8")
                applied = run_cli("experiment", "arms", "apply", "--state", state,
                                  "--kind", "reflect", "--text-file", str(edit))
            self.assertEqual(applied.returncode, 0, applied.stderr)
        result = run_cli("experiment", "arms", "result", "--state", state)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([item["arm"] for item in data["arms"]],
                         ["control", "gepa"])
        self.assertEqual(data["primary_arm"], "gepa")
        self.assertIsNotNone(data["primary_eval_score"])


if __name__ == "__main__":
    unittest.main()
