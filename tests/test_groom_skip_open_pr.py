"""跳过重复评估：已开 PR 且评估仍有效的草稿不再生成工作单。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.groom_fixtures import (  # noqa: E402
    init_repo, make_index, run_py, snapshot_meta, write_case, write_draft, write_json,
)
from groom_common import assessment_path, canonical_content_sha  # noqa: E402
import pr_status  # noqa: E402


class SkipOpenPrTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-skip-pr-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base / "repo")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml",
                   cid="CASE-A", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="link failure", fix="restore link", tags=("hccl",))
        make_index(self.repo)
        self.meta = write_json(self.base / "meta.json", snapshot_meta(self.repo))
        self.inbox = self.repo / "postmortems" / "inbox"
        self.key = "draft-a"
        draft = write_draft(self.repo, key=self.key, cid="DRAFT-A", title="HCCL timeout",
                            symptoms=("HCCL timeout",), root_cause="link failure",
                            fix="restore link", tags=("hccl",))
        case = yaml.safe_load(draft.read_text(encoding="utf-8"))["cases"][0]
        self.sha = canonical_content_sha(case)
        self.write_sidecar()
        self.write_ledger("open")

    def write_sidecar(self, valid=True, sha=None):
        doc = {
            "assessment_id": "a" * 64,
            "content_binding": {"sha256": sha or self.sha},
            "human_decision": {"decision": "new_pattern", "assessment_id": "a" * 64,
                               "content_sha256": sha or self.sha},
            "human_decision_valid": valid,
            "draft_case_id": "DRAFT-A",
        }
        path = assessment_path(self.inbox, self.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def write_ledger(self, state):
        ledger = pr_status.empty_ledger()
        ledger["prs"][self.key] = {
            "platform": "github", "repo": "owner/repo", "number": 7,
            "url": "https://github.com/owner/repo/pull/7", "state": state,
            "source": "ledger", "created_at": "2026-11-04T10:00:00+08:00",
        }
        pr_status.save_ledger(self.repo, ledger)

    def candidates(self, *args):
        out = self.base / "work-orders.json"
        p = run_py(self.repo, "scripts/groom_candidates.py", "--snapshot", str(self.meta),
                   "--all", "--out", str(out), *args)
        return p, out

    def test_open_pr_with_valid_assessment_is_skipped(self):
        p, out = self.candidates("--skip-open-pr")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["orders"], [])
        self.assertEqual(len(doc["skipped"]), 1)
        self.assertEqual(doc["skipped"][0]["draft"], self.key)
        self.assertIn("跳过", p.stdout)

    def test_closed_pr_is_not_skipped(self):
        self.write_ledger("closed")
        p, out = self.candidates("--skip-open-pr")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["orders"]), 1)
        self.assertEqual(doc["skipped"], [])

    def test_stale_assessment_is_not_skipped(self):
        self.write_sidecar(valid=False)
        p, out = self.candidates("--skip-open-pr")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["orders"]), 1)

    def test_draft_changed_is_not_skipped(self):
        draft = self.inbox / f"{self.key}.case.yaml"
        text = draft.read_text(encoding="utf-8").replace("restore link", "restore link with retry")
        draft.write_text(text, encoding="utf-8")
        p, out = self.candidates("--skip-open-pr")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(len(doc["orders"]), 1)


if __name__ == "__main__":
    unittest.main()
