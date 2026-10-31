"""Groom 记录：校验、保守聚合、人机分家、幂等、损坏恢复、provenance。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.groom_fixtures import (  # noqa: E402
    init_repo, make_index, run_py, snapshot_meta, write_case, write_draft, write_json,
)
from groom_common import assessment_path, sanitize_key, work_order_id  # noqa: E402


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-rec-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base / "repo")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-LINK.yaml",
                   cid="CASE-LINK", title="HCCL timeout caused by link down",
                   symptoms=("HCCL timeout", "link down"),
                   root_cause="network link failure", fix="restore link", tags=("hccl", "link"))
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-OOM.yaml",
                   cid="CASE-OOM", title="KV cache OOM", symptoms=("out of memory",),
                   root_cause="cache too large", fix="reduce cache", tags=("oom",))
        make_index(self.repo)
        self.meta_doc = snapshot_meta(self.repo)
        self.meta = write_json(self.base / "meta.json", self.meta_doc)
        self.draft = write_draft(self.repo, key="draft-a", cid="DRAFT-A",
                                 title="网络链路故障导致 HCCL 超时",
                                 symptoms=("HCCL timeout", "interconnect interruption"),
                                 root_cause="link failure", fix="restore link", tags=("hccl",))
        self.work = self.base / "work.json"
        p = run_py(self.repo, "scripts/groom_candidates.py", "--snapshot", str(self.meta),
                   "--draft", str(self.draft), "--out", str(self.work), "--top", "2")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.order = json.loads(self.work.read_text(encoding="utf-8"))["orders"][0]
        self.results = self.base / "results"
        self.results.mkdir()
        self.key = self.order["draft"]["draft_key"]

    # ---------------------------------------------------------------- helpers
    def result(self, overrides=None, all_high=True):
        overrides = overrides or {}
        comparisons = []
        for cand in self.order["candidates"]:
            cid = cand["id"]
            item = {
                "candidate_case": cid,
                "classification": "new_pattern",
                "confidence": "high" if all_high else "medium",
                "evidence": {"root_cause": "different", "mechanism": "different", "fix": "different"},
                "rationale": "根因与失效机制不同，不能合并",
                "review_required": False,
            }
            item.update(overrides.get(cid, {}))
            comparisons.append(item)
        return {
            "schema": "groom-result/v2",
            "draft_key": self.key,
            "work_order_id": work_order_id(self.order),
            "snapshot_commit": self.order["snapshot"]["commit"],
            "draft_sha256": self.order["draft"]["case_sha256"],
            "candidate_ids": [c["id"] for c in self.order["candidates"]],
            "agent": {"id": "agent-test", "role": "comparator"},
            "comparisons": comparisons,
        }

    def write_result(self, doc, name=None):
        path = self.results / (name or f"{self.key}.result.json")
        write_json(path, doc)
        return path

    def run_record(self, *extra):
        return run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(self.meta),
                      "--work-orders", str(self.work), "--results-dir", str(self.results), *extra)

    def sidecar(self):
        return assessment_path(self.repo / "postmortems" / "inbox", self.key)

    def load_sidecar(self):
        import yaml
        return yaml.safe_load(self.sidecar().read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- cases
    def test_high_confidence_covered_is_review_required_not_decided(self):
        target = self.order["candidates"][0]["id"]
        self.write_result(self.result({target: {
            "classification": "covered", "confidence": "high",
            "evidence": {"root_cause": "same", "mechanism": "same", "fix": "same"},
            "rationale": "同一根因、同一修复机制",
        }}))
        p = self.run_record()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = self.load_sidecar()
        a = doc["assessment"]
        self.assertEqual(a["proposed_novelty"], "covered")
        self.assertEqual(a["candidate_case"], target)
        self.assertTrue(a["review_required"])
        self.assertIsNone(doc["human_decision"])
        self.assertEqual(doc["promotion_gate"]["blocked_reason"], "pending-human-review")
        self.assertEqual(doc["provenance"]["compared_against_commit"], self.meta_doc["commit"])

    def test_all_new_pattern_high_needs_no_agent_review(self):
        self.write_result(self.result())
        p = self.run_record()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        a = self.load_sidecar()["assessment"]
        self.assertEqual(a["proposed_novelty"], "new_pattern")
        self.assertFalse(a["review_required"])
        self.assertIsNone(self.load_sidecar()["promotion_gate"]["blocked_reason"])

    def test_medium_covered_downgrades_to_ambiguous(self):
        target = self.order["candidates"][0]["id"]
        self.write_result(self.result({target: {"classification": "covered", "confidence": "medium"}}))
        p = self.run_record()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        a = self.load_sidecar()["assessment"]
        self.assertEqual(a["proposed_novelty"], "ambiguous")
        self.assertIsNone(a["candidate_case"])
        self.assertTrue(a["review_required"])

    def test_conflicting_high_merges_downgrade(self):
        ids = [c["id"] for c in self.order["candidates"]]
        self.assertGreaterEqual(len(ids), 2)
        overrides = {ids[0]: {"classification": "covered", "confidence": "high",
                              "evidence": {"root_cause": "same", "mechanism": "same", "fix": "same"}},
                     ids[1]: {"classification": "covered", "confidence": "high",
                              "evidence": {"root_cause": "same", "mechanism": "same", "fix": "same"}}}
        self.write_result(self.result(overrides))
        p = self.run_record()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        a = self.load_sidecar()["assessment"]
        self.assertEqual(a["proposed_novelty"], "ambiguous")
        self.assertIsNone(a["candidate_case"])

    def test_missing_candidate_invalidates_the_whole_assessment(self):
        doc = self.result()
        doc["comparisons"] = doc["comparisons"][:1]     # 漏掉其余候选
        self.write_result(doc)
        p = self.run_record()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        a = self.load_sidecar()["assessment"]
        self.assertEqual(a["proposed_novelty"], "ambiguous")
        self.assertIn("未覆盖", a["rationale"])

    def test_unknown_candidate_id_is_rejected(self):
        doc = self.result()
        doc["comparisons"][0]["candidate_case"] = "NOT-IN-WORK-ORDER"
        self.write_result(doc)
        p = self.run_record()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        a = self.load_sidecar()["assessment"]
        self.assertEqual(a["proposed_novelty"], "ambiguous")

    def test_reviewer_challenge_forces_ambiguous(self):
        self.write_result(self.result({self.order["candidates"][0]["id"]: {
            "classification": "covered", "confidence": "high",
            "evidence": {"root_cause": "same", "mechanism": "same", "fix": "same"}}}))
        write_json(self.results / f"{self.key}.review.json", {
            "schema": "groom-review/v2", "draft_key": self.key,
            "work_order_id": work_order_id(self.order),
            "snapshot_commit": self.order["snapshot"]["commit"],
            "draft_sha256": self.order["draft"]["case_sha256"],
            "agent": {"id": "reviewer-1"},
            "verdict": "challenge", "false_merge_risk": True,
            "issues": ["症状相同但根因不同：一个是链路，一个是端口"],
            "rationale": "证据不足",
        })
        p = self.run_record()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = self.load_sidecar()
        self.assertEqual(doc["assessment"]["proposed_novelty"], "ambiguous")
        self.assertIn("false_merge_risk", " ".join(doc["assessment"]["review_reasons"]))

    def test_rerun_is_idempotent(self):
        self.write_result(self.result())
        self.assertEqual(self.run_record().returncode, 0)
        before = self.sidecar().read_bytes()
        p = self.run_record()
        self.assertEqual(p.returncode, 0)
        self.assertIn("未变 1", p.stdout)
        self.assertEqual(self.sidecar().read_bytes(), before)

    def test_human_decision_survives_agent_rerun(self):
        target = self.order["candidates"][0]["id"]
        self.write_result(self.result({target: {"classification": "covered", "confidence": "high",
                                               "evidence": {"root_cause": "same", "mechanism": "same", "fix": "same"}}}))
        self.assertEqual(self.run_record().returncode, 0)
        p = run_py(self.repo, "scripts/groom_decide.py", "--draft-key", self.key,
                   "--decision", "covered", "--candidate", target, "--by", "owner-a",
                   "--note", "同一根因")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.load_sidecar()["human_decision"]["decision"], "covered")

        # 重跑 agent（结论改成 new_pattern）不得覆盖人决定
        self.write_result(self.result())
        self.assertEqual(self.run_record().returncode, 0)
        doc = self.load_sidecar()
        self.assertEqual(doc["human_decision"]["decision"], "covered")
        self.assertEqual(doc["human_decision"]["by"], "owner-a")
        self.assertEqual(doc["review_state"], "revalidation-needed")
        self.assertEqual(doc["promotion_gate"]["blocked_reason"], "approval-stale")

    def test_offline_snapshot_blocks_promotion(self):
        meta = write_json(self.base / "offline-meta.json",
                          snapshot_meta(self.repo, authoritative=False, fresh=False))
        self.write_result(self.result())
        p = run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(meta),
                   "--work-orders", str(self.work), "--results-dir", str(self.results))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = self.load_sidecar()
        self.assertEqual(doc["promotion_gate"]["blocked_reason"], "stale-snapshot")
        self.assertTrue(doc["provenance"]["snapshot_fresh"] is False)

    def test_corrupt_sidecar_is_backed_up_not_lost(self):
        self.sidecar().parent.mkdir(parents=True, exist_ok=True)
        self.sidecar().write_text("not: [valid", encoding="utf-8")
        self.write_result(self.result())
        p = self.run_record()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        backups = list(self.sidecar().parent.glob("*.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(self.sidecar().exists())
        self.assertIn("proposed_novelty", self.load_sidecar()["assessment"])

    def test_interrupted_tmp_file_is_ignored(self):
        self.write_result(self.result())
        self.assertEqual(self.run_record().returncode, 0)
        tmp = self.sidecar().with_suffix(self.sidecar().suffix + ".dead.tmp")
        tmp.write_text("half written", encoding="utf-8")
        p = self.run_record()
        self.assertEqual(p.returncode, 0)
        # 半份 tmp 不参与读取、也不影响正式状态；正式文件仍是完整 YAML
        self.assertEqual(tmp.read_text(encoding="utf-8"), "half written")
        self.assertIn("proposed_novelty", self.load_sidecar()["assessment"])

    def test_pr_marker_has_provenance(self):
        target = self.order["candidates"][0]["id"]
        self.write_result(self.result({target: {"classification": "covered", "confidence": "high",
                                               "evidence": {"root_cause": "same", "mechanism": "same", "fix": "same"}}}))
        self.assertEqual(self.run_record().returncode, 0)
        p = run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(self.meta),
                   "--pr-marker", "--draft-key", self.key)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("assessed_commit:", p.stdout)
        self.assertIn(self.meta_doc["commit"], p.stdout)
        self.assertIn("proposed_novelty: covered", p.stdout)
        self.assertIn("human_decision: pending", p.stdout)


if __name__ == "__main__":
    unittest.main()
