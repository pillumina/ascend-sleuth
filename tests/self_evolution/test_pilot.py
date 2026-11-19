"""pilot manifest/collect 的样本 ID 映射与失败路径可见性。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.pilot import (PilotError, _read_samples, _short_id, checkpoint,  # noqa: E402
                          collect, models_from_collect, record_runs, version_for)


class PilotIdTest(unittest.TestCase):
    def test_extracts_issue_from_common_forms(self):
        self.assertEqual(_short_id("GH-VLLM-PROJECT-VLLM-ASCEND-13934"), "13934")
        self.assertEqual(_short_id("VLLM-ASC-10253"), "10253")
        self.assertEqual(_short_id("2026-11-18-15815-qwen"), "15815")

    def test_collision_is_visible(self):
        self.assertEqual(_short_id("GH-X-10253"), _short_id("VLLM-ASC-10253"))


class PilotCollectTest(unittest.TestCase):
    def _collect(self, trace_text):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            tasks = {"candidate_id": "C", "candidate": {}, "workspace": "w", "apply": {},
                     "samples": [{"id": "GH-X-1234", "short_id": "1234",
                                  "path": "p", "expected": {}}], "arms": {}}
            (out / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
            for arm in ("baseline", "candidate"):
                (out / arm / "traces").mkdir(parents=True)
                (out / arm / "out").mkdir(parents=True)
                (out / arm / "traces" / "1234.yaml").write_text(trace_text, encoding="utf-8")
                (out / arm / "out" / "1234.out.md").write_text("report", encoding="utf-8")
            result = collect(out)
        return result["arms"]["baseline"][0]

    def test_usage_is_keyed_by_pilot_sample_id(self):
        trace = {"session_id": "2026-11-18-1234-some-session", "trace": [
            {"action": "load_index", "considered_candidates": ["C-1"]},
            {"action": "load_full", "case": "C-1"},
            {"action": "quickly_check", "case": "C-1"},
            {"action": "hit", "case": "C-1", "step": 2},
        ]}
        row = self._collect(yaml.safe_dump(trace))
        self.assertEqual(row["knowledge_usage"]["sample_id"], "1234")
        self.assertEqual(row["knowledge_usage"]["full_body_reads"], 1)

    def test_collect_records_model_from_session(self):
        trace = {"session_id": "s", "harness_session": "abc", "trace": []}
        with patch("evolve.pilot.read_session",
                   return_value={"model": "deepseek-flash", "tokens": 10}):
            row = self._collect(yaml.safe_dump(trace))
        self.assertEqual(row["model"], "deepseek-flash")

    def test_sealed_samples_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            for purpose in ("test", "regression"):
                path = Path(td) / f"{purpose}.yaml"
                path.write_text(yaml.safe_dump({
                    "id": f"S-{purpose}", "purpose": purpose,
                    "expected": {"resolution": "r"},
                }), encoding="utf-8")
                with self.assertRaises(PilotError):
                    _read_samples([str(path)])

    def test_checkpoint_stops_on_futility(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            sample = out / "s.yaml"
            sample.write_text(yaml.safe_dump({"id": "S-1", "expected": {"resolution": "r"}}),
                              encoding="utf-8")
            tasks = {
                "candidate_id": "C",
                "samples": [{"id": "S-1", "short_id": "1", "path": str(sample)}],
                "budget": {"max_pairs": 2, "max_tokens": None, "early_stop": True,
                           "alpha": 0.1, "required_b": 4},
                "arms": {
                    "baseline": {"trace_dir": str(out / "baseline" / "traces"),
                                 "out_dir": str(out / "baseline" / "out")},
                    "candidate": {"trace_dir": str(out / "candidate" / "traces"),
                                  "out_dir": str(out / "candidate" / "out")},
                },
            }
            (out / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
            for arm in ("baseline", "candidate"):
                (out / arm / "traces").mkdir(parents=True)
                (out / arm / "out").mkdir(parents=True)
                (out / arm / "traces" / "1.yaml").write_text(
                    yaml.safe_dump({"session_id": "1", "trace": []}), encoding="utf-8")
                (out / arm / "out" / "1.md").write_text("report", encoding="utf-8")
            judge = out / "judge.json"
            judge.write_text(json.dumps({"baseline": {"1": 1}, "candidate": {"1": 0}}),
                             encoding="utf-8")
            result = checkpoint(out, judge, {}, reuse_index=0)
            self.assertTrue(result["stop"])
            self.assertEqual(result["reason"], "futility")
            self.assertEqual(result["b"], 0)
            self.assertEqual(result["c"], 1)

    def test_holdout_samples_are_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "eval").mkdir()
            (root / "eval" / "holdout.yaml").write_text(yaml.safe_dump({
                "entries": [{"fixture": "VLLM-ASC-12345.fixture.yaml"}]}),
                encoding="utf-8")
            sample = root / "s.yaml"
            sample.write_text(yaml.safe_dump({
                "id": "S-1", "source": "https://github.com/x/y/issues/12345",
                "expected": {"resolution": "r"},
            }), encoding="utf-8")
            with self.assertRaises(PilotError):
                _read_samples([str(sample)], root=root)

    def test_models_from_collect_joins_arms(self):
        collect = {"arms": {
            "baseline": [{"model": "deepseek-flash"}],
            "candidate": [{"model": "deepseek-flash"}],
        }}
        self.assertEqual(models_from_collect(collect), "deepseek-flash")
        self.assertIsNone(models_from_collect({"arms": {"baseline": [{}]}}))

    def test_version_model_prefers_explicit_value(self):
        version = version_for({"candidate_id": "C"}, {}, model="deepseek-flash")
        self.assertEqual(version["model"], "deepseek-flash")
        self.assertEqual(version_for({"candidate_id": "C"}, {})["model"], "unknown")

    def test_record_runs_uses_collected_model(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            (out / "tasks.json").write_text(
                json.dumps({"candidate_id": "C"}), encoding="utf-8")
            (out / "collect.json").write_text(json.dumps({"arms": {"baseline": [
                {"sample_id": "1234", "trace": "t", "model": "deepseek-flash"}]}}),
                encoding="utf-8")
            result = record_runs(out, {}, base=out)
            self.assertEqual(result["version"]["model"], "deepseek-flash")
            run = json.loads((out / "runs.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(run["versions"]["model"], "deepseek-flash")

    def test_empty_trace_reports_usage_error(self):
        row = self._collect("")
        self.assertEqual(row["usage_error"], "trace is empty")
        self.assertNotIn("knowledge_usage", row)
        self.assertNotIn("source_usage", row)
        self.assertTrue(row["has_trace"] and row["has_output"])

    def test_malformed_trace_keeps_parse_error(self):
        row = self._collect("trace: [unclosed")
        self.assertIn("usage_error", row)
        self.assertNotEqual(row["usage_error"], "trace is empty")
        self.assertTrue(row["has_trace"])

    def test_knowledge_failure_keeps_source_usage_visible(self):
        trace = {"session_id": "s", "trace": [
            {"action": "hit", "case": "C-1"},
            {"action": "source_analysis", "repo": "r", "files_read": ["a.py"]},
        ]}
        row = self._collect(yaml.safe_dump(trace))
        self.assertIn("usage_error", row)
        self.assertEqual(row["source_usage"]["files_read"], 1)

    def test_source_failure_keeps_knowledge_usage_visible(self):
        trace = {"session_id": "s", "trace": [
            {"action": "load_index", "considered_candidates": ["C-1"]},
            {"action": "load_full", "case": "C-1"},
            {"action": "hit", "case": "C-1", "step": 2},
        ]}
        row = self._collect(yaml.safe_dump(trace))
        self.assertIn("source_usage_error", row)
        self.assertEqual(row["knowledge_usage"]["full_body_reads"], 1)


if __name__ == "__main__":
    unittest.main()
