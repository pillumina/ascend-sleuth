"""交接包 needs 的口径：只取当前提问，终态单不倒历史缺口。

为什么：`needs` 是接手方第一屏要问的问题。已收尾的单里那些 `evidence.missing` 是当时提过、
后来可能已经补上的历史；全部倒出来会让接手方按旧问题重开一轮。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import export_trace  # noqa: E402


class DeriveNeedsTest(unittest.TestCase):
    def test_terminal_statuses_come_from_the_vocabulary(self):
        import yaml
        vocab = yaml.safe_load((ROOT / "trace-status.yaml").read_text(encoding="utf-8"))
        expected = {s["value"] for s in vocab["status"] if s.get("terminal")}
        self.assertEqual(export_trace.terminal_statuses(ROOT), expected)

    def test_terminal_trace_has_no_needs(self):
        doc = {"status": "resolved",
               "trace": [{"role": "user", "evidence": {"missing": "缺日志"}}],
               "last_action": "产出诊断结果"}
        self.assertEqual(export_trace.derive_needs(doc), [])

    def test_last_action_is_the_current_ask(self):
        doc = {"status": "in_progress", "last_action": "等用户确认三条路径选哪条",
               "trace": [{"role": "user", "evidence": {"missing": "缺日志"}}]}
        self.assertEqual(export_trace.derive_needs(doc), ["等用户确认三条路径选哪条"])

    def test_latest_missing_is_the_fallback(self):
        doc = {"status": "in_progress",
               "trace": [{"role": "user", "evidence": {"missing": "旧的缺口"}},
                         {"role": "agent"},
                         {"role": "user", "evidence": {"missing": "新的缺口"}}]}
        self.assertEqual(export_trace.derive_needs(doc), ["新的缺口"])

    def test_no_ask_returns_empty(self):
        self.assertEqual(export_trace.derive_needs({"status": "in_progress"}), [])


if __name__ == "__main__":
    unittest.main()
