"""validated 卡必须有一次 PASS 的实测证据（不是只有一条能跑的命令）。"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import _measure_evidence as evidence  # noqa: E402
import evolution_health  # noqa: E402


def _card(created="2026-11-21"):
    return {
        "id": "EV-2026-999",
        "layer": "L2",
        "title": "实测证据测试",
        "status": "validated",
        "authorization": "review",
        "dimension": "observability",
        "created_at": created,
        "target_component": "scripts/example.py",
        "source_signals": [{"signal": "gap", "evidence": "e", "trajectory": ["t"]}],
        "hypothesis": "h",
        "predicted_effect": {
            "metric": "m", "from": "a", "to": "b",
            "measure": {"command": "python3 -c \"print('MEASURE-OK')\"",
                        "expect_stdout": "MEASURE-OK"},
        },
        "validation": {"method": "scan_review"},
        "risk": "low",
        "principle_refs": [8],
        "decisions": [
            {"who": "agent", "when": "2026-11-21", "type": "decision", "conclusion": "ok"},
            {"who": "agent", "when": "2026-11-21", "type": "eval", "conclusion": "ok"},
        ],
        "actual_cost": {"tokens": 1},
    }


def _run(root, *args):
    argv = [sys.executable]
    if args and str(args[0]).startswith("scripts/"):
        argv.append(str(ROOT / args[0]))
        args = args[1:]
    argv.extend(args)
    return subprocess.run(argv, cwd=str(root),
                          capture_output=True, text=True, encoding="utf-8")


class MeasureEvidenceTest(unittest.TestCase):
    def test_validated_without_pass_evidence_fails_then_passes_after_record(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ideas = root / "proposals" / "ideas"
            ideas.mkdir(parents=True)
            path = ideas / "EV-2026-999.yaml"
            path.write_text(yaml.safe_dump(_card(), allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
            rc = _run(root, "scripts/verify_proposals.py", "--check", "--root", ".")
            self.assertEqual(rc.returncode, 1, rc.stdout + rc.stderr)
            self.assertIn("没有 measure PASS 证据", rc.stdout)

            rc = _run(root, "scripts/ev_measure.py", "EV-2026-999", "--run", "--record",
                      "--root", ".", "--local")
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["measure_evidence"][0]["verdict"], "PASS")

            rc = _run(root, "scripts/verify_proposals.py", "--check", "--root", ".")
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)

    def test_declared_unmeasurable_cannot_be_validated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ideas = root / "proposals" / "ideas"
            ideas.mkdir(parents=True)
            card = _card()
            card["predicted_effect"]["measure"] = {"reason": "外部团队排期"}
            (ideas / "EV-2026-999.yaml").write_text(
                yaml.safe_dump(card, allow_unicode=True, sort_keys=False), encoding="utf-8")
            rc = _run(root, "scripts/verify_proposals.py", "--check", "--root", ".")
            self.assertEqual(rc.returncode, 1, rc.stdout + rc.stderr)
            self.assertIn("声明了不可度量", rc.stdout)

    def test_decision_without_status_advance_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ideas = root / "proposals" / "ideas"
            ideas.mkdir(parents=True)
            card = _card()
            card["status"] = "in_experiment"
            card["actual_cost"] = None
            (ideas / "EV-2026-999.yaml").write_text(
                yaml.safe_dump(card, allow_unicode=True, sort_keys=False), encoding="utf-8")
            rc = _run(root, "scripts/verify_proposals.py", "--check", "--root", ".")
            self.assertEqual(rc.returncode, 1, rc.stdout + rc.stderr)
            self.assertIn("状态滞后", rc.stdout)
    def test_long_and_multiline_measure_command_still_matches(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ideas = root / "proposals" / "ideas"
            ideas.mkdir(parents=True)
            card = _card()
            command = "python3 -c \"print('MEASURE-OK')\"  # " + "padding " * 30
            card["predicted_effect"]["measure"] = {
                "command": command, "expect_stdout": "MEASURE-OK",
            }
            path = ideas / "EV-2026-999.yaml"
            path.write_text(yaml.safe_dump(card, allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
            rc = _run(root, "scripts/ev_measure.py", "EV-2026-999", "--run", "--record",
                      "--root", ".", "--local")
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["measure_evidence"][0]["command"], command.strip())
            rc = _run(root, "scripts/verify_proposals.py", "--check", "--root", ".")
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)

    def test_record_writes_version_and_health_uses_card_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ideas = root / "proposals" / "ideas"
            ideas.mkdir(parents=True)
            path = ideas / "EV-2026-999.yaml"
            path.write_text(yaml.safe_dump(_card(), allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
            rc = _run(root, "scripts/ev_measure.py", "EV-2026-999", "--run", "--record",
                      "--root", ".", "--local")
            self.assertEqual(rc.returncode, 0, rc.stdout + rc.stderr)
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertIn("version", doc["measure_evidence"][0])

            # fresh clone 没有本机日志，只剩卡内证据。体检必须仍把这张卡算作已测过。
            log = root / "metrics" / "ev-measure-log.yaml"
            if log.exists():
                log.unlink()
            dims, _readouts = evolution_health.collect_dimensions(root)
            self.assertEqual(dims["runnable_never_measured"], 0)
            self.assertEqual(dims["measure_evidence_cards"], 1)
            self.assertEqual(dims["reproducible_evidence_ratio"], 1.0)

    def test_card_passes_accepts_old_entry_without_version(self):
        doc = {"measure_evidence": [{"verdict": "PASS", "command": "python3 x.py"}]}
        self.assertTrue(evidence.card_passes(doc, "python3 x.py"))
        self.assertFalse(evidence.card_passes(doc, "python3 y.py"))
        self.assertEqual(evidence.card_entries({"measure_evidence": "bad"}), [])

