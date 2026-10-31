"""证据绑定回归：结果、工作单、快照、草稿内容、PR 内容和人的批准必须是同一次评估。

这些测试在修复前应当失败。它们只覆盖确定性绑定，不覆盖语义准确率。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.groom_fixtures import (  # noqa: E402
    commit_all, init_repo, make_index, run_py, snapshot_meta, write_case, write_draft, write_json,
)
from groom_recheck import check  # noqa: E402
from groom_common import assessment_path, canonical_content_sha, load_yaml, work_order_id  # noqa: E402


class BindingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-bind-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base / "repo")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml",
                   cid="CASE-A", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="link failure", fix="restore link", tags=("hccl",),
                   sig="HCCL timeout")
        make_index(self.repo)
        self.m0 = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True,
            encoding="utf-8").stdout.strip()
        self.draft = write_draft(self.repo, key="draft-a", cid="DRAFT-A",
                                 title="HCCL timeout", symptoms=("HCCL timeout",),
                                 root_cause="link failure", fix="restore link", tags=("hccl",),
                                 sig="HCCL timeout")
        self.inbox = self.repo / "postmortems" / "inbox"
        self.work = self.base / "work.json"
        self.results = self.base / "results"
        self.results.mkdir()

    def meta(self, commit=None, name="meta.json"):
        return write_json(self.base / name, snapshot_meta(self.repo, commit=commit))

    def candidates(self, meta_path, out_name="work.json"):
        out = self.base / out_name
        p = run_py(self.repo, "scripts/groom_candidates.py", "--snapshot", str(meta_path),
                   "--draft", str(self.draft), "--out", str(out), "--top", "2")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return out, json.loads(out.read_text(encoding="utf-8"))["orders"][0]

    def result(self, order, name="draft-a.result.json", **overrides):
        doc = {
            "schema": "groom-result/v2",
            "draft_key": order["draft"]["draft_key"],
            "work_order_id": work_order_id(order),
            "snapshot_commit": order["snapshot"]["commit"],
            "draft_sha256": order["draft"]["case_sha256"],
            "candidate_ids": [c["id"] for c in order["candidates"]],
            "agent": {"id": "binding-test"},
            "comparisons": [{
                "candidate_case": c["id"],
                "classification": "new_pattern",
                "confidence": "high",
                "evidence": {"root_cause": "different", "mechanism": "different", "fix": "different"},
                "rationale": "different",
                "review_required": False,
            } for c in order["candidates"]],
            "overall": "new_pattern",
            "rationale": "different",
        }
        doc.update(overrides)
        write_json(self.results / name, doc)
        return doc

    def _head_content_sha(self, head, rel):
        data = yaml.safe_load(subprocess.run(
            ["git", "show", f"{head}:{rel}"], cwd=self.repo, capture_output=True, text=True,
            encoding="utf-8").stdout)
        return canonical_content_sha(data["cases"][0])

    def _pr_case(self, rel="knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                 cid="CASE-B", root="submitted root", fix="submitted fix"):
        subprocess.run(["git", "checkout", "-q", "-b", "pr-b", self.m0], cwd=self.repo)
        write_case(self.repo, rel, cid=cid, title="HCCL timeout",
                   symptoms=("HCCL timeout",), root_cause=root, fix=fix,
                   tags=("hccl",), sig="HCCL timeout")
        head = commit_all(self.repo, "PR case")
        return head, self._head_content_sha(head, rel)

    def _marker(self, assessed, content_sha, *, submitted="CASE-B", novelty="new_pattern",
                candidate="", human="new_pattern", assessment_id="a" * 64,
                human_id=None, human_content=None):
        lines = [
            "<!-- groom-assessment", "schema: groom-pr/v2", "draft: draft-a",
            "case_id: CASE-B", f"submitted_case_id: {submitted}", "category: interrupt",
            f"assessed_commit: {assessed}", f"assessment_id: {assessment_id}",
            f"assessed_content_sha256: {content_sha}", f"proposed_novelty: {novelty}",
            f"candidate_case: {candidate}", f"human_decision: {human}",
        ]
        if human != "pending":
            lines += [
                f"human_decision_assessment_id: {human_id or assessment_id}",
                f"human_decision_content_sha256: {human_content or content_sha}",
            ]
        else:
            lines += ["human_decision_assessment_id:", "human_decision_content_sha256:"]
        lines += ["review_required: false", "-->", ""]
        return "\n".join(lines)

    # ---------------------------------------------------------------- P1-1
    def test_mismatched_snapshot_and_work_order_are_rejected(self):
        meta_a = self.meta(self.m0, "meta-a.json")
        work, order = self.candidates(meta_a, "work-a.json")
        self.result(order)
        # 另一个 commit 的 meta，配上 A 的工作单：当前实现只看 candidate ids，会接受
        (self.repo / "notes.txt").write_text("m1\n", encoding="utf-8")
        m1 = commit_all(self.repo, "next")
        meta_b = self.meta(m1, "meta-b.json")
        p = run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(meta_b),
                   "--work-orders", str(work), "--results-dir", str(self.results))
        path = assessment_path(self.inbox, "draft-a")
        if path.exists():
            doc = load_yaml(path)
            self.assertEqual(doc["assessment"]["proposed_novelty"], "ambiguous")
            self.assertEqual(doc["promotion_gate"]["blocked_reason"], "binding-mismatch")
        else:
            self.assertIn("binding", (p.stdout + p.stderr).lower())

    # ---------------------------------------------------------------- P1-2
    def test_incomplete_or_unknown_marker_is_rejected(self):
        body = (
            "<!-- groom-assessment\n"
            "draft: draft-a\n"
            f"assessed_commit: {self.m0}\n"
            "proposed_novelty: covered\n"
            "human_decision: banana\n"
            "-->\n"
        )
        findings, _ = check(body, self.repo, self.m0, self.m0, enforce_marker=True)
        codes = [f["code"] for f in findings]
        self.assertIn("marker-invalid", codes, findings)

    # ---------------------------------------------------------------- P1-3
    def test_pr_content_must_match_assessed_content(self):
        # PR 分支新增一个 case；marker 声称评估的是另一段 root cause
        head = "pr-b"
        subprocess.run(["git", "checkout", "-q", "-b", head, self.m0], cwd=self.repo)
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   cid="CASE-B", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="SUBMITTED ROOT CAUSE", fix="submitted fix", tags=("hccl",),
                   sig="HCCL timeout")
        head_sha = commit_all(self.repo, "PR B")
        body = (
            "<!-- groom-assessment\n"
            "schema: groom-pr/v2\n"
            "draft: draft-a\n"
            "case_id: CASE-B\n"
            "submitted_case_id: CASE-B\n"
            "category: interrupt\n"
            f"assessed_commit: {self.m0}\n"
            f"assessment_id: {'a' * 64}\n"
            f"assessed_content_sha256: {'b' * 64}\n"
            "proposed_novelty: new_pattern\n"
            "candidate_case:\n"
            "human_decision: new_pattern\n"
            f"human_decision_assessment_id: {'a' * 64}\n"
            f"human_decision_content_sha256: {'b' * 64}\n"
            "review_required: false\n"
            "-->\n"
        )
        findings, _ = check(body, self.repo, self.m0, head_sha, enforce_marker=True)
        codes = [f["code"] for f in findings]
        self.assertIn("content-mismatch", codes, findings)

    def test_changed_root_cause_after_assessment_is_rejected(self):
        head, sha = self._pr_case(root="assessed root", fix="assessed fix")
        # 评估之后改 root cause：用评估时算出的 content hash 去校验提交内容
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   cid="CASE-B", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="CHANGED ROOT", fix="assessed fix", tags=("hccl",),
                   sig="HCCL timeout")
        head2 = commit_all(self.repo, "change root")
        findings, _ = check(self._marker(self.m0, sha), self.repo, self.m0, head2,
                            enforce_marker=True)
        self.assertIn("content-mismatch", [f["code"] for f in findings])

    def test_changed_fix_after_assessment_is_rejected(self):
        head, sha = self._pr_case(root="assessed root", fix="assessed fix")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   cid="CASE-B", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="assessed root", fix="CHANGED FIX", tags=("hccl",),
                   sig="HCCL timeout")
        head2 = commit_all(self.repo, "change fix")
        findings, _ = check(self._marker(self.m0, sha), self.repo, self.m0, head2,
                            enforce_marker=True)
        self.assertIn("content-mismatch", [f["code"] for f in findings])

    def test_every_affected_case_needs_a_marker(self):
        head, sha = self._pr_case()
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-D.yaml",
                   cid="CASE-D", title="another case", symptoms=("other",),
                   root_cause="other", fix="other", tags=("other",), sig="other")
        head2 = commit_all(self.repo, "second case")
        findings, _ = check(self._marker(self.m0, sha), self.repo, self.m0, head2,
                            enforce_marker=True)
        self.assertIn("case-without-provenance", [f["code"] for f in findings])

    def test_rejected_decision_with_content_is_rejected(self):
        head, sha = self._pr_case()
        findings, _ = check(self._marker(self.m0, sha, human="reject"), self.repo, self.m0,
                            head, enforce_marker=True)
        self.assertIn("decision-does-not-authorize", [f["code"] for f in findings])

    def test_duplicate_marker_field_is_rejected(self):
        head, sha = self._pr_case()
        body = self._marker(self.m0, sha).replace(
            "human_decision: new_pattern",
            "human_decision: new_pattern\nhuman_decision: reject")
        findings, _ = check(body, self.repo, self.m0, head, enforce_marker=True)
        self.assertIn("marker-invalid", [f["code"] for f in findings])

    def test_human_decision_must_match_assessment_and_content(self):
        head, sha = self._pr_case()
        body = self._marker(self.m0, sha, human="new_pattern",
                            human_id="c" * 64, human_content="d" * 64)
        findings, _ = check(body, self.repo, self.m0, head, enforce_marker=True)
        self.assertIn("marker-invalid", [f["code"] for f in findings])

    def test_result_candidate_set_mismatch_is_rejected(self):
        meta_a = self.meta(self.m0, "meta-a.json")
        work, order = self.candidates(meta_a, "work-a.json")
        self.result(order, candidate_ids=["NOT-A-REAL-CANDIDATE"])
        p = run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(meta_a),
                   "--work-orders", str(work), "--results-dir", str(self.results))
        doc = load_yaml(assessment_path(self.inbox, "draft-a"))
        self.assertEqual(doc["assessment"]["proposed_novelty"], "ambiguous")
        self.assertEqual(doc["promotion_gate"]["blocked_reason"], "binding-mismatch")
        self.assertEqual(p.returncode, 2)

    def test_result_without_binding_fields_is_rejected(self):
        meta_a = self.meta(self.m0, "meta-a.json")
        work, order = self.candidates(meta_a, "work-a.json")
        doc = self.result(order)
        for key in ("work_order_id", "snapshot_commit", "draft_sha256", "candidate_ids"):
            doc.pop(key, None)
        write_json(self.results / "draft-a.result.json", doc)
        p = run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(meta_a),
                   "--work-orders", str(work), "--results-dir", str(self.results))
        state = load_yaml(assessment_path(self.inbox, "draft-a"))
        self.assertEqual(state["promotion_gate"]["blocked_reason"], "binding-mismatch")
        self.assertEqual(p.returncode, 2)

    # ---------------------------------------------------------------- P1-4
    def test_old_human_approval_is_not_transferred_to_new_assessment(self):
        meta_a = self.meta(self.m0, "meta-a.json")
        work_a, order_a = self.candidates(meta_a, "work-a.json")
        self.result(order_a)
        p = run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(meta_a),
                   "--work-orders", str(work_a), "--results-dir", str(self.results))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p = run_py(self.repo, "scripts/groom_decide.py", "--snapshot", str(meta_a),
                   "--draft-key", "draft-a", "--decision", "new_pattern", "--by", "owner")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

        # 草稿内容改变 → 新评估；旧批准不得自动用于新评估
        self.draft.write_text(
            self.draft.read_text(encoding="utf-8").replace("link failure", "port exhaustion"),
            encoding="utf-8")
        work_b, order_b = self.candidates(meta_a, "work-b.json")
        self.result(order_b)
        p = run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(meta_a),
                   "--work-orders", str(work_b), "--results-dir", str(self.results))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        marker = run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(meta_a),
                        "--pr-marker", "--draft-key", "draft-a").stdout
        self.assertIn("human_decision: pending", marker)
        self.assertNotIn("human_decision: new_pattern", marker)

        # 重新批准后，旧批准进 history，不丢
        p = run_py(self.repo, "scripts/groom_decide.py", "--snapshot", str(meta_a),
                   "--draft-key", "draft-a", "--decision", "new_pattern", "--by", "owner")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = load_yaml(assessment_path(self.inbox, "draft-a"))
        self.assertGreaterEqual(len(doc.get("human_decision_history") or []), 1)
        self.assertNotEqual(doc["human_decision_history"][0].get("assessment_id"),
                            doc["human_decision"].get("assessment_id"))

    def test_changed_severity_or_side_effects_after_assessment_is_rejected(self):
        head, sha = self._pr_case()
        path = self.repo / "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["cases"][0]["severity"] = "data-loss-risk"
        doc["cases"][0]["fix_side_effects"] = ["requires-restart"]
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        head2 = commit_all(self.repo, "change safety fields")
        findings, _ = check(self._marker(self.m0, sha), self.repo, self.m0, head2,
                            enforce_marker=True)
        self.assertIn("content-mismatch", [f["code"] for f in findings])

    def test_reordered_diagnosis_steps_after_assessment_is_rejected(self):
        subprocess.run(["git", "checkout", "-q", "-b", "pr-b", self.m0], cwd=self.repo)
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   cid="CASE-B", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="submitted root", fix="submitted fix", tags=("hccl",),
                   sig="HCCL timeout")
        path = self.repo / "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["cases"][0]["diagnosis"] = [
            {"check": "第一步", "command_template": "echo 1", "expected": "regex:1"},
            {"check": "第二步", "command_template": "echo 2", "expected": "regex:2"},
        ]
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        head = commit_all(self.repo, "two steps")
        sha = self._head_content_sha(
            head, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml")
        doc["cases"][0]["diagnosis"] = list(reversed(doc["cases"][0]["diagnosis"]))
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        head2 = commit_all(self.repo, "swap steps")
        findings, _ = check(self._marker(self.m0, sha), self.repo, self.m0, head2,
                            enforce_marker=True)
        self.assertIn("content-mismatch", [f["code"] for f in findings])

    def test_generated_marker_authorizes_only_the_assessed_content(self):
        meta_a = self.meta(self.m0, "meta-a.json")
        work_a, order_a = self.candidates(meta_a, "work-a.json")
        self.result(order_a)
        self.assertEqual(run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(meta_a),
                                "--work-orders", str(work_a), "--results-dir", str(self.results)).returncode, 0)
        self.assertEqual(run_py(self.repo, "scripts/groom_decide.py", "--snapshot", str(meta_a),
                                "--draft-key", "draft-a", "--decision", "new_pattern",
                                "--by", "owner").returncode, 0)
        subprocess.run(["git", "checkout", "-q", "-b", "pr-b", self.m0], cwd=self.repo)
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/PROMOTED-A.yaml",
                   cid="PROMOTED-A", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="link failure", fix="restore link", tags=("hccl",),
                   sig="HCCL timeout")
        head = commit_all(self.repo, "promote")
        marker = run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(meta_a),
                        "--pr-marker", "--draft-key", "draft-a",
                        "--submitted-case-id", "PROMOTED-A").stdout
        findings, _ = check(marker, self.repo, self.m0, head, enforce_marker=True)
        self.assertEqual([f for f in findings if f["severity"] == "error"], [], findings)

        # 同一 PR 里把 fix 改掉：marker 的 content hash 不再匹配
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/PROMOTED-A.yaml",
                   cid="PROMOTED-A", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="link failure", fix="a different fix", tags=("hccl",),
                   sig="HCCL timeout")
        head2 = commit_all(self.repo, "change fix")
        findings2, _ = check(marker, self.repo, self.m0, head2, enforce_marker=True)
        self.assertIn("content-mismatch", [f["code"] for f in findings2])

    def test_draft_edit_after_decision_cannot_reuse_approval(self):
        meta_a = self.meta(self.m0, "meta-a.json")
        work_a, order_a = self.candidates(meta_a, "work-a.json")
        self.result(order_a)
        self.assertEqual(run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(meta_a),
                                "--work-orders", str(work_a), "--results-dir", str(self.results)).returncode, 0)
        self.assertEqual(run_py(self.repo, "scripts/groom_decide.py", "--snapshot", str(meta_a),
                                "--draft-key", "draft-a", "--decision", "new_pattern",
                                "--by", "owner").returncode, 0)
        self.draft.write_text(self.draft.read_text(encoding="utf-8").replace(
            "restore link", "new fix"), encoding="utf-8")
        p = run_py(self.repo, "scripts/groom_decide.py", "--snapshot", str(meta_a),
                   "--draft-key", "draft-a", "--decision", "new_pattern", "--by", "owner")
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
