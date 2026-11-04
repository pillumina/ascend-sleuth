"""issue 台账的写入纪律：原子替换与幂等。

为什么单独测它：`ingest-state.json` 是 issue 去重的唯一依据。直接 `json.dump` 到目标文件时，
进程在写一半中断会留下半截 JSON，下一轮 `load_state` 直接失败，且没有第二份记录可恢复。
这份测试钉住两条契约：替换失败不能破坏上一版台账；重复标记同一批编号不改变结果。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import issue_filter  # noqa: E402


class SaveStateTest(unittest.TestCase):
    def test_roundtrip_writes_readable_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ingest-state.json"
            state = {"sources": {"github/x/y": {"processed": [1, 2]}}}
            issue_filter.save_state(path, state)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), state)
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))

    def test_failed_replace_keeps_previous_state(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ingest-state.json"
            old = {"sources": {"github/x/y": {"processed": [1]}}}
            issue_filter.save_state(path, old)
            before = path.read_text(encoding="utf-8")

            with mock.patch.object(issue_filter.os, "replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    issue_filter.save_state(path, {"sources": {"github/x/y": {"processed": [1, 2]}}})

            self.assertEqual(path.read_text(encoding="utf-8"), before)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), old)
            self.assertTrue((Path(td) / "ingest-state.json.tmp").exists())


class MarkImportedTest(unittest.TestCase):
    def run_cli(self, state: Path, nums: str):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "issue_filter.py"),
             "--state", str(state), "--source", "github/x/y", "--mark-imported", nums],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )

    def test_marking_the_same_batch_twice_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "ingest-state.json"
            first = self.run_cli(state, "1,2")
            self.assertEqual(first.returncode, 0, first.stderr)
            second = self.run_cli(state, "1,2")
            self.assertEqual(second.returncode, 0, second.stderr)
            data = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(data["sources"]["github/x/y"]["processed"], [1, 2])


if __name__ == "__main__":
    unittest.main()
