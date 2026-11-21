"""体检器：数据缺口记 unknown，不能盖掉已能动作的违反。"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolution_health import evaluate  # noqa: E402


class HealthSemanticsTest(unittest.TestCase):
    def test_unknown_data_does_not_hide_violation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "proposals").mkdir()
            (root / "proposals" / "gates.yaml").write_text(yaml.safe_dump({
                "freshness": {},
                "gates": [
                    {"id": "no_negative_feedback", "dimension": "negative_terminal",
                     "op": "==", "value": 0, "title": "测试违反"},
                    {"id": "pool_reuse_uncontrolled", "dimension": "arena_pool_reuse",
                     "op": ">", "value": 10, "title": "缺数据"},
                ],
                "readability": [],
            }, allow_unicode=True), encoding="utf-8")
            payload = evaluate(root)
            self.assertEqual(payload["check_verdict"], "violations")
            self.assertEqual(payload["exit_code"], 1)
            self.assertTrue(payload["unknown"])
            self.assertFalse(payload["broken"])
            self.assertTrue(any(f["id"] == "no_negative_feedback" for f in payload["findings"]))
    def test_usable_treats_incomplete_as_unavailable(self):
        payload = {"check_verdict": "incomplete", "exit_code": 2, "fail_count": 0}
        with mock.patch("evolution_health.evaluate", return_value=payload), \
                mock.patch("evolution_health.render", return_value=""), \
                mock.patch.object(sys, "argv", ["evolution_health.py", "--usable"]):
            from evolution_health import main
            self.assertEqual(main(), 2)

