#!/usr/bin/env python3
"""source_ref 指针校验：形态必须是 org/repo，且能在 source-catalog.d 里解析到。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import verify_case_draft as vcd  # noqa: E402


def check(case, root=ROOT):
    fails, warns = [], []
    vcd.check_source_ref(case, Path("case.yaml"), Path(root), fails.append, warns.append)
    return fails, warns


class SourceRefPointerTest(unittest.TestCase):
    def test_canonical_repo_passes(self):
        fails, _ = check({"id": "C1", "source_ref": {"repo": "vllm-project/vllm-ascend",
                                                     "ref": "v0.23.0", "file": "a.py", "line": 1}})
        self.assertEqual(fails, [])

    def test_catalog_only_repo_passes(self):
        """fast_path: false 的仓也要能解析（它进不了已知表，但在目录里）。"""
        fails, _ = check({"id": "C2", "source_ref": {"repo": "cann/pyasc", "ref": "v9.1.1"}})
        self.assertEqual(fails, [])

    def test_bare_repo_is_rejected(self):
        fails, _ = check({"id": "C3", "source_ref": {"repo": "vllm", "ref": "v0.23.0"}})
        self.assertEqual(len(fails), 1)
        self.assertIn("org/repo", fails[0])

    def test_unknown_repo_is_rejected(self):
        fails, _ = check({"id": "C4", "source_ref": {"repo": "no-such/ops", "ref": "v1"}})
        self.assertEqual(len(fails), 1)
        self.assertIn("不在源码仓目录", fails[0])

    def test_list_form_checks_every_entry(self):
        fails, _ = check({"id": "C5", "source_ref": [
            {"repo": "vllm-project/vllm", "ref": "v0.23.0"},
            {"repo": "vllm-ascend", "ref": "v0.23.0"},
        ]})
        self.assertEqual(len(fails), 1)
        self.assertIn("source_ref[2]", fails[0])

    def test_empty_ref_is_rejected(self):
        fails, _ = check({"id": "C6", "source_ref": {"repo": "vllm-project/vllm", "ref": ""}})
        self.assertEqual(len(fails), 1)
        self.assertIn("ref", fails[0])

    def test_missing_repo_is_rejected(self):
        fails, _ = check({"id": "C7", "source_ref": {"ref": "v0.23.0"}})
        self.assertEqual(len(fails), 1)
        self.assertIn("缺 repo", fails[0])


if __name__ == "__main__":
    unittest.main()
