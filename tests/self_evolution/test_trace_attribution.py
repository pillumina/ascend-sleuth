"""trace 归因幂等：同内容跳过、变内容重算、快照随集合变化。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evolve.trace_attribution import status, sync  # noqa: E402


def write_trace(root: Path, name: str, component: str = "diagnose", kind: str = "execution"):
    path = root / "traces" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "trace:\n"
        f"- {{action: attribution, attribution_kind: {kind}, component: {component}, evidence: failed}}\n"
        "- {action: user, content: x}\n",
        encoding="utf-8",
    )
    return path


class TraceAttributionTest(unittest.TestCase):
    def test_same_content_is_reused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_trace(root, "t1")
            state = root / "state.json"
            first = sync(root, state)
            second = sync(root, state)
            self.assertEqual((first["new"], first["reused"]), (1, 0))
            self.assertEqual((second["new"], second["reused"]), (0, 1))
            self.assertEqual(first["snapshot_id"], second["snapshot_id"])

    def test_changed_content_and_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = write_trace(root, "t1")
            state = root / "state.json"
            first = sync(root, state)
            path.write_text(
                "trace:\n- {action: attribution, attribution_kind: execution, component: routing}\n",
                encoding="utf-8",
            )
            second = sync(root, state)
            self.assertEqual(second["changed"], 1)
            self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
            self.assertIn("routing", second["components"])
            self.assertEqual(second["experiment"]["mutable_region"], "diagnose.routing_hints")

    def test_new_trace_changes_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_trace(root, "t1")
            state = root / "state.json"
            first = sync(root, state)
            write_trace(root, "t2")
            second = sync(root, state)
            self.assertEqual(second["new"], 1)
            self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
            self.assertEqual(status(state)["traces"], 2)

    def test_state_schema_and_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "state.json"
            state.write_text(json.dumps({"state_schema": "bad"}), encoding="utf-8")
            with self.assertRaises(Exception):
                sync(root, state)


if __name__ == "__main__":
    unittest.main()
