"""judge 双标校准：一致率、kappa、门槛与坏标签。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.calibration import CalibrationError, calibrate, cohen_kappa, load_labels  # noqa: E402


class CalibrationTest(unittest.TestCase):
    def _write(self, td, name, data):
        path = Path(td) / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_perfect_agreement(self):
        a = {"a": 1, "b": 0, "c": 1}
        self.assertEqual(cohen_kappa(a, a)["kappa"], 1.0)

    def test_disagreement_lowers_kappa(self):
        a = {"a": 1, "b": 1, "c": 1, "d": 0}
        b = {"a": 1, "b": 1, "c": 0, "d": 0}
        result = cohen_kappa(a, b)
        self.assertEqual(result["agree"], 3)
        self.assertLess(result["kappa"], 1.0)
        self.assertGreater(result["kappa"], 0)

    def test_gate_and_id_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            a = self._write(td, "a.json", {"scores": [{"id": "x", "score": 1}]})
            b = self._write(td, "b.json", {"x": 0})
            result = calibrate(a, b, min_raw=0.8, min_kappa=0.6)
            self.assertFalse(result["passed"])
            c = self._write(td, "c.json", {"scores": [{"id": "y", "score": 1}]})
            with self.assertRaises(CalibrationError):
                calibrate(a, c)

    def test_rejects_bad_labels(self):
        with tempfile.TemporaryDirectory() as td:
            bad = self._write(td, "bad.json", {"x": 2})
            with self.assertRaises(CalibrationError):
                load_labels(bad)
            dup = self._write(td, "dup.json", {"scores": [
                {"id": "x", "score": 1}, {"id": "x", "score": 0}]})
            with self.assertRaises(CalibrationError):
                load_labels(dup)


if __name__ == "__main__":
    unittest.main()
