"""trace 事件字段与顶层字段封闭的回归。

护两件事：
1. `external_lookup` 的 `output` / `reason` 按三态判，别让一次检索在回放里消失；
2. 顶层字段按 `diagnosis_state.yaml.example` 判未登记，临时字段不能混过收尾。
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verify_trace_status as vt  # noqa: E402
from _trace_state import load_vocab  # noqa: E402

AT = "2026-11-27T10:00:00+08:00"


def make_doc(**kw):
    base = {
        "status": "resolved",
        "resolved_at": AT,
        "ending": {"kind": "root_cause"},
        "transitions": [{"from": "in_progress", "to": "resolved", "at": AT,
                         "action": "close-resolved"}],
        "trace": [],
    }
    base.update(kw)
    return base


def make_event(**kw):
    base = {"role": "agent", "step": 5, "action": "external_lookup",
            "capability": "vllm_code", "outcome": "hit"}
    base.update(kw)
    return base


class EventFieldTest(unittest.TestCase):
    def check(self, *events, strict=False, known=None):
        entry = {"sessionId": "s1", "doc": make_doc(trace=list(events)), "error": None}
        return vt.check_trace(entry, load_vocab(ROOT), strict, False, known)

    def test_external_lookup_hit_requires_output(self):
        errs = self.check(make_event(outcome="hit"))
        self.assertTrue(any("output 为空" in e for e in errs), errs)

    def test_external_lookup_hit_with_output_passes(self):
        errs = self.check(make_event(outcome="hit", output="用了工具词条里的版本事实"))
        self.assertFalse(any("external_lookup" in e for e in errs), errs)

    def test_external_lookup_skipped_requires_reason(self):
        errs = self.check(make_event(outcome="skipped"))
        self.assertTrue(any("reason 为空" in e for e in errs), errs)

    def test_external_lookup_skipped_with_reason_passes(self):
        errs = self.check(make_event(outcome="skipped", reason="not-configured"))
        self.assertFalse(any("external_lookup" in e for e in errs), errs)

    def test_external_lookup_outcome_must_be_known(self):
        errs = self.check(make_event(outcome="ok", output="x"))
        self.assertTrue(any("不在三态词表" in e for e in errs), errs)

    def test_agent_output_is_checked_for_managed_trace(self):
        event = {"role": "agent", "step": 2, "action": "triage", "output": ""}
        self.assertTrue(any("没有 output" in e for e in self.check(event)))

    def test_legacy_trace_missing_output_is_only_strict(self):
        event = {"role": "agent", "step": 2, "action": "triage", "output": ""}
        entry = {"sessionId": "s1", "doc": make_doc(trace=[event]), "error": None}
        entry["doc"].pop("transitions")
        vocab = load_vocab(ROOT)
        self.assertFalse(any("没有 output" in e
                             for e in vt.check_trace(entry, vocab, False, False)))
        self.assertTrue(any("没有 output" in e
                            for e in vt.check_trace(entry, vocab, True, False)))


class TopLevelFieldTest(unittest.TestCase):
    def check(self, doc, known=None):
        entry = {"sessionId": "s1", "doc": doc, "error": None}
        return vt.check_trace(entry, load_vocab(ROOT), False, False, known)

    def test_example_is_the_schema_source(self):
        known = vt.known_top_level(ROOT)
        self.assertIn("summary", known)
        self.assertNotIn("root_cause_status", known)

    def test_example_covers_write_entry_fields(self):
        """写入口会写的顶层字段必须都在 example 里，否则正常收尾的单会被判未登记。"""
        import trace_transition as tt
        import trace_usage as tu
        known = vt.known_top_level(ROOT)
        self.assertEqual(tt.TOUCHED - known, set())
        self.assertEqual(set(tu.KEYS) - known, set())

    def test_example_covers_new_trace_header(self):
        """建单脚本写的 header 字段同样要在清单里。"""
        import yaml
        import trace_begin
        text = trace_begin.build_header(
            slug="2026-11-27-x", harness_session="session-abc",
            created_at="2026-11-27T10:00:00+08:00", kb_rev="deadbee")
        keys = set(yaml.safe_load(text))
        self.assertEqual(keys - vt.known_top_level(ROOT) - vt.LEGACY_TOP_LEVEL, set())

    def test_unknown_top_level_field_is_reported(self):
        known = vt.known_top_level(ROOT)
        errs = self.check(make_doc(root_cause_status="机制已确认、根因未确认"), known)
        self.assertTrue(any("未登记" in e and "root_cause_status" in e for e in errs), errs)

    def test_legacy_workload_type_names_are_allowed(self):
        known = vt.known_top_level(ROOT)
        errs = self.check(make_doc(side="training", side_source="evidence"), known)
        self.assertFalse(any("未登记" in e for e in errs), errs)

    def test_trace_without_transitions_is_grandfathered(self):
        known = vt.known_top_level(ROOT)
        doc = make_doc(root_cause_status="x")
        doc.pop("transitions")
        self.assertFalse(any("未登记" in e for e in self.check(doc, known)))


if __name__ == "__main__":
    unittest.main()
