"""候选样本回流：trace/case 抽取、完整性、查重与核心集脱敏。"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.intake import completeness, extract_case, extract_trace, make_sample  # noqa: E402
from evolve.samples import SampleStore  # noqa: E402


def _trace(path: Path):
    path.write_text(yaml.safe_dump({
        "session_id": "2026-11-18-15815-demo",
        "summary": "现象：服务启动即崩。\n\n排除链：候选都不符。\n\n根因：patch 未刷新已导入模块。\n\n处置：重绑 sys.modules。",
        "incident_env": "A3 / vllm-ascend 0.26.0rc1",
        "report_file": "15815.report.md",
        "kb_rev": "abc1234",
        "trace": [{
            "role": "user", "content": "启动崩",
            "evidence": {"inline": "AttributeError", "missing": ["plog"]},
        }],
    }), encoding="utf-8")


def _case(path: Path):
    path.write_text(yaml.safe_dump({"cases": [{
        "id": "VLLM-ASC-99999",
        "upstream": [{"repo": "vllm-project/vllm-ascend", "issue": 99999,
                      "url": "https://github.com/vllm-project/vllm-ascend/issues/99999"}],
        "platforms": ["A3-910C"],
        "symptoms": ["启动即崩", "错误码 507034"],
        "root_cause": "通信次序无保证。",
        "fix": "升级到含修复的版本。",
        "verification": {"source": "upstream-maintainer-confirmed"},
        "references": ["https://github.com/vllm-project/vllm-ascend/issues/99999"],
    }]}), encoding="utf-8")


class IntakeTest(unittest.TestCase):
    def test_trace_extraction_keeps_answer_out_of_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "traces" / "t.yaml"
            trace.parent.mkdir()
            _trace(trace)
            payload = extract_trace(trace, root)
            phenomenon = payload["input"]["phenomenon"]
            self.assertIn("启动即崩", phenomenon)
            self.assertNotIn("patch 未刷新", phenomenon)
            self.assertIn("patch 未刷新", payload["proposed"]["resolution"])
            self.assertEqual(payload["provenance"]["trigger"], "diagnosis_end")
            self.assertFalse(payload["provenance"]["sanitized"])

    def test_continuous_summary_does_not_leak_answer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "t.yaml"
            trace.write_text(yaml.safe_dump({
                "session_id": "2026-11-04-13976-demo",
                "summary": "现象：启动崩。根因：绑定未刷新。处置：重绑 sys.modules。",
                "trace": [{"role": "user", "content": "启动崩"}],
            }), encoding="utf-8")
            payload = extract_trace(trace, root)
            self.assertEqual(payload["input"]["phenomenon"], "启动崩。")
            self.assertNotIn("绑定未刷新", payload["input"]["phenomenon"])
            self.assertIn("绑定未刷新", payload["proposed"]["resolution"])

    def test_unlabeled_summary_uses_user_content_not_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "t.yaml"
            trace.write_text(yaml.safe_dump({
                "session_id": "s",
                "summary": "定位：命中 case 但触发不稳，根因在 kernel。",
                "trace": [{"role": "user", "content": "服务启动崩"}],
            }), encoding="utf-8")
            payload = extract_trace(trace, root)
            self.assertEqual(payload["input"]["phenomenon"], "服务启动崩")
            self.assertNotIn("根因", payload["input"]["phenomenon"])
            self.assertEqual(payload["proposed"]["resolution"], "")

    def test_preamble_without_phenomenon_uses_user_content(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "t.yaml"
            trace.write_text(yaml.safe_dump({
                "session_id": "s",
                "summary": "启动崩，根因是绑定未刷新。排除链：候选都不符。",
                "trace": [{"role": "user", "content": "启动崩，贴日志"}],
            }), encoding="utf-8")
            payload = extract_trace(trace, root)
            self.assertEqual(payload["input"]["phenomenon"], "启动崩，贴日志")
            self.assertNotIn("根因", payload["input"]["phenomenon"])

    def test_status_and_check_agree_on_missing_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SampleStore(root=root)
            sample = store.new(
                id="S-LOCAL", object_type="diagnosis", source="traces/x.yaml",
                purpose="evaluation", expected={"resolution": "r"},
            )
            self.assertEqual(completeness(sample, store=store, root=root)["state"],
                             "needs_sanitize")
            self.assertTrue(store.check(sample.id))

    def test_empty_resolution_is_missing_answer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SampleStore(root=root)
            sample = store.new(
                id="S-EMPTY", object_type="diagnosis", source="traces/t.yaml",
                purpose="evaluation", expected={"resolution": ""},
                provenance={"trigger": "manual_case", "sanitized": True,
                            "redactions": [], "confidence": "maintainer-reviewed",
                            "extraction": "manual"},
            )
            with self.assertRaises(Exception):
                store.review(sample.id, approve=True)

    def test_case_without_root_cause_is_needs_answer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            case = root / "c.yaml"
            case.write_text(yaml.safe_dump({"cases": [{
                "id": "VLLM-ASC-1", "symptoms": ["崩"],
            }]}), encoding="utf-8")
            payload = extract_case(case, root)
            self.assertIsNone(payload["expected"])
            result = completeness(make_sample(payload), root=root)
            self.assertEqual(result["state"], "needs_answer")

    def test_holdout_number_requires_exact_match(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            holdout = root / "eval" / "holdout.yaml"
            holdout.parent.mkdir()
            holdout.write_text(yaml.safe_dump({"entries": [
                {"fixture": "VLLM-ASC-12345.fixture.yaml"}]}), encoding="utf-8")
            payload = {
                "id": "S-1234", "object_type": "diagnosis",
                "source": "https://github.com/x/y/issues/1234",
                "purpose": "evaluation", "expected": {"resolution": "r"},
                "expected_kind": "resolution",
                "provenance": {"trigger": "postmortem", "sanitized": True,
                               "redactions": [], "confidence": "maintainer-reviewed",
                               "extraction": "auto"},
            }
            self.assertEqual(completeness(make_sample(payload), root=root)["state"], "ready")
            payload["id"] = "S-12345"
            payload["source"] = "https://github.com/x/y/issues/12345"
            self.assertEqual(completeness(make_sample(payload), root=root)["state"], "duplicate")

    def test_trace_session_number_matches_knowledge(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            traces = root / "traces"
            traces.mkdir()
            trace = traces / "2026-11-04-13976-demo.yaml"
            _trace(trace)
            knowledge = root / "knowledge" / "inference" / "vllm-ascend" / "interrupt"
            knowledge.mkdir(parents=True)
            (knowledge / "VLLM-ASC-13976.yaml").write_text("cases: []\n", encoding="utf-8")
            sample = make_sample(extract_trace(trace, root))
            self.assertEqual(completeness(sample, root=root)["state"], "absorbed")

    def test_trace_without_summary_is_needs_answer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "t.yaml"
            trace.write_text(yaml.safe_dump({"session_id": "s", "trace": []}), encoding="utf-8")
            sample = make_sample(extract_trace(trace, root))
            result = completeness(sample, root=root)
            self.assertEqual(result["state"], "needs_answer")
            self.assertIn("missing_answer", result["reasons"])

    def test_ready_after_answer_and_sanitize(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "t.yaml"
            _trace(trace)
            store = SampleStore(root=root)
            sample = store.new(**extract_trace(trace, root))
            self.assertEqual(completeness(sample, store=store, root=root)["state"], "needs_answer")
            updated = store.set_answer(
                sample.id, expected={"resolution": "根因与修复"},
                provenance={"confidence": "maintainer-reviewed", "sanitized": True},
            )
            self.assertEqual(completeness(updated, store=store, root=root)["state"], "ready")

    def test_case_extraction_and_absorbed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            case = root / "case.yaml"
            _case(case)
            knowledge = root / "knowledge" / "inference" / "vllm-ascend" / "interrupt"
            knowledge.mkdir(parents=True)
            (knowledge / "VLLM-ASC-99999.yaml").write_text("cases: []\n", encoding="utf-8")
            payload = extract_case(case, root)
            self.assertEqual(payload["expected"]["case"], "VLLM-ASC-99999")
            self.assertIn("通信次序", payload["expected"]["resolution"])
            result = completeness(make_sample(payload), root=root)
            self.assertEqual(result["state"], "absorbed")
            self.assertTrue(any(item.startswith("knowledge:") for item in result["duplicates"]))

    def test_duplicate_from_eval_s2(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            s2 = root / "eval" / "s2"
            s2.mkdir(parents=True)
            (s2 / "pool.yaml").write_text(
                yaml.safe_dump({"calibration": [{"issue": 12345}]}), encoding="utf-8")
            payload = {
                "id": "S-1", "object_type": "diagnosis",
                "source": "https://github.com/x/y/issues/12345",
                "purpose": "evaluation", "expected": {"resolution": "r"},
                "expected_kind": "resolution",
                "provenance": {"trigger": "postmortem", "sanitized": True,
                               "redactions": [], "confidence": "maintainer-reviewed",
                               "extraction": "auto"},
            }
            result = completeness(make_sample(payload), root=root)
            self.assertEqual(result["state"], "duplicate")
            self.assertIn("eval:12345", result["duplicates"])

    def test_unsanitized_cannot_review_as_evaluation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "t.yaml"
            _trace(trace)
            store = SampleStore(root=root)
            sample = store.new(**extract_trace(trace, root))
            store.set_answer(sample.id, expected={"resolution": "r"})
            store.review(sample.id, approve=True)
            with self.assertRaises(Exception):
                store.set_purpose(sample.id, "evaluation")

    def test_unsanitized_evaluation_sample_cannot_review(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = SampleStore(root=root)
            sample = store.new(
                id="S-EVAL", object_type="diagnosis", source="https://x/issues/999",
                purpose="evaluation", expected={"resolution": "r"},
                provenance={"trigger": "manual_case", "sanitized": False,
                            "redactions": [], "confidence": "maintainer-reviewed",
                            "extraction": "manual"},
            )
            with self.assertRaises(Exception):
                store.review(sample.id, approve=True)

    def test_unsanitized_cannot_promote_to_core(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            trace = root / "t.yaml"
            _trace(trace)
            store = SampleStore(root=root)
            sample = store.new(**extract_trace(trace, root))
            store.set_answer(sample.id, expected={"resolution": "r"},
                             provenance={"confidence": "maintainer-reviewed"})
            store.review(sample.id, approve=True)
            with self.assertRaises(Exception):
                store.promote(sample.id, to="core")


if __name__ == "__main__":
    unittest.main()
