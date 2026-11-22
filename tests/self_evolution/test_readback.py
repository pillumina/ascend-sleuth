"""按 EV 卡回读最新 Conclusion。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.readback import latest_conclusion, summary  # noqa: E402


class ReadbackTest(unittest.TestCase):
    def test_latest_by_card(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / ".s2-replay" / "evolve"
            base.mkdir(parents=True)
            rows = [
                {"card": "EV-2026-001", "decision": "insufficient", "at": "2026-11-01T00:00:00+00:00",
                 "b": 1, "c": 0, "n": 9, "versions": {"model": "m"}, "cost": {"tokens": {"baseline": 1, "candidate": 2}, "paired": 1, "missing": 0}},
                {"card": "EV-2026-001", "decision": "accept", "at": "2026-11-02T00:00:00+00:00",
                 "b": 4, "c": 0, "n": 9, "versions": {"model": "m"}, "cost": {"tokens": {"baseline": 3, "candidate": 4}, "paired": 1, "missing": 0}},
            ]
            (base / "conclusions.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            record = latest_conclusion("EV-2026-001", base)
            self.assertEqual(record["decision"], "accept")
            data = summary(record)
            self.assertEqual(data["model"], "m")
            self.assertEqual(data["cost"]["baseline"], 3)
            self.assertIsNone(latest_conclusion("EV-2026-999", base))

    def test_empty_card_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(Exception):
                latest_conclusion("", Path(td))


if __name__ == "__main__":
    unittest.main()
