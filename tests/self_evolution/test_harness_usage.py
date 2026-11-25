"""DSH 会话记录里的模型与 token；取不到时不补零。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.harness_usage import normalize_session_id, read_session  # noqa: E402


def _session(path: Path, model="deepseek-flash", totals=None):
    rows = {
        "modelSelection": {"val": {"lastUsed": {
            "provider": "deepseek-account", "model": model,
            "reasoningEffort": "high",
        }}},
        "tokenUsage": {"val": {"totals": totals or {
            "uncachedInputTokens": 10, "outputTokens": 20,
            "cacheReadTokens": 30, "cacheWriteTokens": 0,
        }}},
    }
    path.write_text(json.dumps({"record": {"rows": rows}}), encoding="utf-8")


class HarnessUsageTest(unittest.TestCase):
    def test_reads_model_and_total(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _session(root / "session-abc.json")
            usage = read_session("abc", root)
            self.assertEqual(usage["model"], "deepseek-flash")
            self.assertEqual(usage["tokens"], 60)
            self.assertEqual(usage["token_totals"]["cacheReadTokens"], 30)

    def test_prefixed_id_reads_bare_named_file(self):
        # 会话记录文件名有两种；带前缀的 id 也要能读到裸文件名的会话。
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _session(root / "abc.json")
            self.assertEqual(read_session("session-abc", root)["tokens"], 60)

    def test_normalize_session_id_forms(self):
        bare = "d4ff3b1c-2f7a-4c1e-9a55-0b8f6d2e7c13"
        self.assertEqual(normalize_session_id(bare), "session-" + bare)
        self.assertEqual(normalize_session_id("session-" + bare), "session-" + bare)
        self.assertEqual(normalize_session_id("session-abc"), "session-abc")
        self.assertEqual(normalize_session_id("2026-10-30-welink"), "")
        self.assertEqual(normalize_session_id(""), "")

    def test_missing_or_invalid_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertIsNone(read_session("nope", root))
            self.assertIsNone(read_session("../etc/passwd", root))
            (root / "bad.json").write_text("{", encoding="utf-8")
            self.assertIsNone(read_session("bad", root))

    def test_no_home_directory_returns_none(self):
        with patch("pathlib.Path.home", side_effect=RuntimeError("no home")):
            self.assertIsNone(read_session("abc"))

    def test_session_without_usage_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "empty.json").write_text(
                json.dumps({"record": {"rows": {}}}), encoding="utf-8")
            self.assertIsNone(read_session("empty", root))


if __name__ == "__main__":
    unittest.main()
