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
