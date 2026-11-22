"""非 DSH agent 把 model/tokens 写进 trace 顶层。"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import trace_usage  # noqa: E402


class TraceUsageTest(unittest.TestCase):
    def _trace(self, td, text=None):
        path = Path(td) / "t.yaml"
        path.write_text(text or "session_id: s\nmodel: \"\"\ntokens_start: null\ntrace: []\n",
                        encoding="utf-8")
        return path

    def test_sets_model_and_tokens(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._trace(td)
            self.assertEqual(trace_usage.main([
                "--trace", str(path), "--model", "claude-sonnet-4", "--tokens", "1234"]), 0)
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["model"], "claude-sonnet-4")
            self.assertEqual(doc["tokens"], 1234)

    def test_inserts_missing_keys_before_trace(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._trace(td, "session_id: s\ntrace: []\n")
            self.assertEqual(trace_usage.main(["--trace", str(path), "--tokens", "7"]), 0)
            text = path.read_text(encoding="utf-8")
            self.assertLess(text.index("tokens: 7"), text.index("trace: []"))

    def test_rejects_negative_and_non_trace(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._trace(td)
            self.assertEqual(trace_usage.main(["--trace", str(path), "--tokens", "-1"]), 2)
            self.assertEqual(trace_usage.main(["--trace", str(path)]), 2)
            plain = Path(td) / "plain.yaml"
            plain.write_text("session_id: s\n", encoding="utf-8")
            self.assertEqual(trace_usage.main(["--trace", str(plain), "--tokens", "1"]), 2)


if __name__ == "__main__":
    unittest.main()
