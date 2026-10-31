"""Groom 状态：未评估 / 知识前进 / 草稿被改 / 孤儿状态 / --check-stale。"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.groom_fixtures import (  # noqa: E402
    commit_all, init_repo, make_index, run_py, snapshot_meta, write_case, write_draft, write_json,
)
from groom_status import status_rows  # noqa: E402
from groom_common import assessment_path, work_order_id  # noqa: E402


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-status-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base / "repo")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml",
                   cid="CASE-A", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="link failure", fix="restore link", tags=("hccl",))
        make_index(self.repo)
        self.meta_doc = snapshot_meta(self.repo)
        self.meta = write_json(self.base / "meta.json", self.meta_doc)
        self.draft = write_draft(self.repo, key="draft-a", cid="DRAFT-A",
                                 title="HCCL timeout", symptoms=("HCCL timeout",),
                                 root_cause="link failure", fix="restore link", tags=("hccl",))
        self.work = self.base / "work.json"
        p = run_py(self.repo, "scripts/groom_candidates.py", "--snapshot", str(self.meta),
                   "--draft", str(self.draft), "--out", str(self.work), "--top", "1")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.order = __import__("json").loads(self.work.read_text(encoding="utf-8"))["orders"][0]
        self.results = self.base / "results"
        self.results.mkdir()
        self._write_all_new()
        p = run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(self.meta),
                   "--work-orders", str(self.work), "--results-dir", str(self.results))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.inbox = self.repo / "postmortems" / "inbox"

    def _write_all_new(self):
        key = self.order["draft"]["draft_key"]
        comparisons = [{
            "candidate_case": c["id"], "classification": "new_pattern", "confidence": "high",
            "evidence": {"root_cause": "different"}, "rationale": "different", "review_required": False,
        } for c in self.order["candidates"]]
        write_json(self.results / f"{key}.result.json", {
            "draft_key": key, "agent": {"id": "status-test"}, "comparisons": comparisons,
            "work_order_id": work_order_id(self.order),
            "snapshot_commit": self.order["snapshot"]["commit"],
            "draft_sha256": self.order["draft"]["case_sha256"],
            "candidate_ids": [c["id"] for c in self.order["candidates"]],
        })

    def test_fresh_after_assessment(self):
        rows = status_rows(self.repo, self.meta_doc["commit"], self.inbox)
        row = next(r for r in rows if r["draft"] == "draft-a")
        self.assertFalse(row["stale"], row)
        self.assertEqual(row["proposed_novelty"], "new_pattern")

    def test_knowledge_progress_makes_assessment_stale(self):
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   cid="CASE-B", title="new case")
        new = commit_all(self.repo, "add B")
        rows = status_rows(self.repo, new, self.inbox)
        row = next(r for r in rows if r["draft"] == "draft-a")
        self.assertTrue(row["stale"])
        self.assertTrue(any("知识库" in r for r in row["stale_reasons"]))

    def test_draft_edit_makes_assessment_stale(self):
        self.draft.write_text(self.draft.read_text(encoding="utf-8").replace(
            "HCCL timeout", "HCCL timeout after link flap"), encoding="utf-8")
        rows = status_rows(self.repo, self.meta_doc["commit"], self.inbox)
        row = next(r for r in rows if r["draft"] == "draft-a")
        self.assertTrue(row["stale"])
        self.assertTrue(any("草稿" in r for r in row["stale_reasons"]))

    def test_unevaluated_draft_is_stale(self):
        write_draft(self.repo, key="draft-b", cid="DRAFT-B", title="unknown")
        rows = status_rows(self.repo, self.meta_doc["commit"], self.inbox)
        row = next(r for r in rows if r["draft"] == "draft-b")
        self.assertTrue(row["stale"])
        self.assertIn("未评估", row["stale_reasons"])

    def test_check_stale_cli_exits_two(self):
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-C.yaml", cid="CASE-C")
        commit_all(self.repo, "add C")
        meta2 = write_json(self.base / "meta2.json", snapshot_meta(self.repo))
        p = run_py(self.repo, "scripts/groom_status.py", "--snapshot", str(meta2), "--check-stale")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)

    def test_check_stale_cli_passes_when_fresh(self):
        p = run_py(self.repo, "scripts/groom_status.py", "--snapshot", str(self.meta), "--check-stale")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_corrupt_sidecar_is_reported_not_crash(self):
        path = assessment_path(self.inbox, "draft-a")
        path.write_text("not: [valid", encoding="utf-8")
        rows = status_rows(self.repo, self.meta_doc["commit"], self.inbox)
        row = next(r for r in rows if r["draft"] == "draft-a")
        self.assertTrue(row["stale"])
        self.assertTrue(any("解析失败" in r for r in row["stale_reasons"]), row)


if __name__ == "__main__":
    unittest.main()
