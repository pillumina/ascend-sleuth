"""Groom 合入前复核：stale assessment、并发 PR、marker 校验、post-merge。"""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.groom_fixtures import (  # noqa: E402
    commit_all, git, init_repo, make_index, run_py, write_case, write_draft,
)
from groom_recheck import check  # noqa: E402
from groom_common import canonical_content_sha  # noqa: E402


def case_sha(repo, commit, path):
    out = git(repo, "show", f"{commit}:{path}").stdout
    case = yaml.safe_load(out)["cases"][0]
    return canonical_content_sha(case)


def marker(assessed, content_sha, submitted_case_id="CASE-B", category="interrupt",
           novelty="new_pattern", candidate="", human="new_pattern", assessment_id="a" * 64):
    human_ids = (
        f"human_decision_assessment_id: {assessment_id if human != 'pending' else ''}\n"
        f"human_decision_content_sha256: {content_sha if human != 'pending' else ''}\n"
    )
    return (
        "<!-- groom-assessment\n"
        "schema: groom-pr/v2\n"
        "draft: draft-b\n"
        "case_id: DRAFT-B\n"
        f"submitted_case_id: {submitted_case_id}\n"
        f"category: {category}\n"
        f"assessed_commit: {assessed}\n"
        f"assessment_id: {assessment_id}\n"
        f"assessed_content_sha256: {content_sha}\n"
        f"proposed_novelty: {novelty}\n"
        f"candidate_case: {candidate}\n"
        f"human_decision: {human}\n"
        + human_ids +
        "review_required: false\n"
        "-->\n"
    )


class RecheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-rcheck-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base / "repo")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml",
                   cid="CASE-A", title="HCCL timeout", symptoms=("HCCL timeout", "collective timeout"),
                   root_cause="link failure", fix="restore link", tags=("hccl",), sig="collective timeout")
        make_index(self.repo)
        self.m0 = git(self.repo, "rev-parse", "HEAD").stdout.strip()

        # PR-B 分支：基于 M0 加一条 case
        git(self.repo, "checkout", "-q", "-b", "pr-b", self.m0)
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   cid="CASE-B", title="collective timeout after link flap",
                   symptoms=("HCCL collective timeout",), root_cause="interconnect interruption",
                   fix="restore link", tags=("hccl",), sig="collective timeout")
        self.head_b = commit_all(self.repo, "PR B")
        self.b_sha = case_sha(self.repo, self.head_b,
                              "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml")

        # main 前进：基于 M0 新增一条相似 case（模拟 PR-A 已合入）
        git(self.repo, "checkout", "-q", "main")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-C.yaml",
                   cid="CASE-C", title="HCCL collective timeout after network interruption",
                   symptoms=("collective timeout",), root_cause="network link failure",
                   fix="restore link", tags=("hccl",), sig="collective timeout")
        self.m1 = commit_all(self.repo, "PR A merged")
        make_index(self.repo)
        self.m1 = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.a_sha = case_sha(self.repo, self.m0,
                              "knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml")
        self.c_sha = case_sha(self.repo, self.m1,
                              "knowledge/inference/vllm-ascend/interrupt/CASE-C.yaml")

    def test_fresh_assessment_passes(self):
        findings, _ = check(marker(self.m0, self.b_sha), self.repo, self.m0, self.head_b, enforce_marker=True)
        self.assertEqual(findings, [])

    def test_assessment_against_old_main_is_stale(self):
        findings, ctx = check(marker(self.m0, self.b_sha), self.repo, self.m1, self.head_b, enforce_marker=True)
        codes = [f["code"] for f in findings]
        self.assertIn("assessment-stale", codes)
        self.assertTrue(any(f["severity"] == "error" for f in findings if f["code"] == "assessment-stale"))

    def test_concurrent_prs_flag_possible_duplicate(self):
        findings, _ = check(marker(self.m0, self.b_sha), self.repo, self.m1, self.head_b, enforce_marker=True)
        dup = [f for f in findings if f["code"] == "possible-duplicate-after-merge"]
        self.assertTrue(dup, findings)
        self.assertEqual(dup[0]["detail"]["pr_case"], "CASE-B")
        self.assertEqual(dup[0]["detail"]["main_case"], "CASE-C")

    def test_missing_marker_is_advisory_by_default_and_fatal_on_enforce(self):
        findings, _ = check("no marker here", self.repo, self.m0, self.head_b, enforce_marker=False)
        self.assertEqual(findings[0]["code"], "missing-marker")
        self.assertEqual(findings[0]["severity"], "warning")
        findings2, _ = check("no marker here", self.repo, self.m0, self.head_b, enforce_marker=True)
        self.assertEqual(findings2[0]["severity"], "error")

    def test_assessed_commit_ahead_of_base_is_rejected(self):
        findings, _ = check(marker(self.head_b, self.b_sha), self.repo, self.m0, self.head_b, enforce_marker=True)
        codes = [f["code"] for f in findings]
        self.assertIn("assessment-not-ancestor", codes)

    def test_candidate_missing_in_base_is_rejected(self):
        # 在 main 上删除 CASE-A 并重建索引
        git(self.repo, "rm", "-q", "knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml")
        commit_all(self.repo, "remove A")
        make_index(self.repo)
        m2 = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        findings, _ = check(marker(self.m0, self.b_sha, candidate="CASE-A"), self.repo, m2, self.head_b,
                            enforce_marker=True)
        self.assertIn("candidate-missing", [f["code"] for f in findings])

    def test_merge_class_without_human_decision_is_blocked_on_enforce(self):
        body = marker(self.m0, self.b_sha, novelty="covered", candidate="CASE-A", human="pending")
        findings, _ = check(body, self.repo, self.m0, self.head_b, enforce_marker=True)
        self.assertIn("decision-does-not-authorize",
                      [f["code"] for f in findings if f["severity"] == "error"])

    def test_post_merge_index_check(self):
        findings, _ = check(marker(self.m1, self.a_sha, submitted_case_id="CASE-A", novelty="covered", candidate="CASE-A", human="covered"), self.repo, self.m1, self.m1, enforce_marker=True,
                            post_merge=True)
        self.assertNotIn("post-merge-index-stale", [f["code"] for f in findings])

    def test_revalidation_after_regroom_passes(self):
        # 场景：B 对 M0 的评估过期 → 对 M1 重跑 groom（新 marker）→ 复核通过
        stale, _ = check(marker(self.m0, self.b_sha), self.repo, self.m1, self.head_b, enforce_marker=True)
        self.assertIn("assessment-stale", [f["code"] for f in stale])
        fresh, _ = check(marker(self.m1, self.b_sha), self.repo, self.m1, self.head_b, enforce_marker=True)
        self.assertEqual([f for f in fresh if f["severity"] == "error"], [])

    def test_cli_advisory_does_not_block(self):
        body = self.base / "pr.md"
        body.write_text(marker(self.m0, self.b_sha), encoding="utf-8")
        p = run_py(self.repo, "scripts/groom_recheck.py", "--pr-body-file", str(body),
                   "--base", self.m1, "--head", self.head_b, "--advisory")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("assessment-stale", p.stdout)

    def test_cli_blocks_without_advisory(self):
        body = self.base / "pr.md"
        body.write_text(marker(self.m0, self.b_sha), encoding="utf-8")
        p = run_py(self.repo, "scripts/groom_recheck.py", "--pr-body-file", str(body),
                   "--base", self.m1, "--head", self.head_b)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)


class TwoInboxTest(unittest.TestCase):
    def test_two_clones_have_independent_inboxes(self):
        with tempfile.TemporaryDirectory(prefix="groom-inbox-") as tmp:
            base = Path(tmp)
            origin = base / "origin.git"
            git(base, "init", "--bare", "-q", str(origin))
            seed = init_repo(base / "seed")
            git(seed, "remote", "add", "origin", str(origin))
            git(seed, "push", "-q", "-u", "origin", "main")

            a = base / "clone-a"
            b = base / "clone-b"
            for clone in (a, b):
                git(base, "clone", "-q", "-b", "main", str(origin), str(clone))
                git(clone, "config", "user.email", "x@example.com")
                git(clone, "config", "user.name", "x")
            write_draft(a, key="draft-a", cid="A-1", title="A 的草稿")
            write_draft(b, key="draft-b", cid="B-1", title="B 的草稿")

            from groom_common import find_drafts, shared_inbox
            keys_a = {d.key for d in find_drafts(shared_inbox(a))}
            keys_b = {d.key for d in find_drafts(shared_inbox(b))}
            self.assertEqual(keys_a, {"draft-a"})
            self.assertEqual(keys_b, {"draft-b"})


if __name__ == "__main__":
    unittest.main()
