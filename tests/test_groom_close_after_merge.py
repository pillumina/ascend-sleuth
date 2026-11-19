"""合入后收尾：按 PR body 的 marker 与合入提交核对，再写 trace 与出队。

护四件事：
1. 证据齐全时收尾成功（trace 写 knowledge、草稿进 `.done/`、close-log 记 mode）；
2. marker 与本地评估不一致时不写；
3. 合入提交里的内容与 marker 指纹不一致时不写；
4. 草稿不在 inbox（已收尾或已撤销）时跳过。
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.groom_fixtures import (  # noqa: E402
    commit_all, git, init_repo, run_py, write_case, write_draft,
)
from groom_common import assessment_path, canonical_content_sha, sha256_full  # noqa: E402
import groom_close_after_merge  # noqa: E402

TRACE_TMPL = """session_id: "{sid}"
status: resolved
summary: "HCCL 超时，链路恢复后自愈"
severity: service-affecting
fix_emitted: true
updated_at: "2026-11-01T09:00:00+08:00"
sedimented:
  state: submitted
  case_id: ""
  inbox_path: "postmortems/inbox/draft-a.case.yaml"
trace:
  - {{step: 1, role: user, content: "贴了栈"}}
"""

CASE_REL = "knowledge/inference/vllm-ascend/interrupt/DRAFT-A.yaml"
KEY = "draft-a"
AID = "a" * 64


class AfterMergeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-after-merge-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base / "repo")
        self.inbox = self.repo / "postmortems" / "inbox"
        self.sid = "2026-11-01-after-merge"
        (self.repo / "traces").mkdir(parents=True, exist_ok=True)
        (self.repo / "traces" / f"{self.sid}.yaml").write_text(
            TRACE_TMPL.format(sid=self.sid), encoding="utf-8")

        case_path = write_case(self.repo, CASE_REL, cid="DRAFT-A", title="HCCL timeout",
                               symptoms=("HCCL timeout",), root_cause="link failure",
                               fix="restore link", tags=("hccl",))
        self.case_sha = canonical_content_sha(
            yaml.safe_load(case_path.read_text(encoding="utf-8"))["cases"][0])
        self.merge = commit_all(self.repo, "case")

        draft = write_draft(self.repo, key=KEY, cid="DRAFT-A", title="HCCL timeout",
                            symptoms=("HCCL timeout",), root_cause="link failure",
                            fix="restore link", tags=("hccl",))
        draft.write_text(f"# 来源: traces/{self.sid}.yaml\n" + draft.read_text(encoding="utf-8"),
                         encoding="utf-8")
        self.write_sidecar()

    def write_sidecar(self, sha=None):
        doc = {
            "assessment_id": AID,
            "content_binding": {"sha256": sha or self.case_sha},
            "category": "interrupt",
            "human_decision": {
                "decision": "new_pattern", "assessment_id": AID,
                "content_sha256": sha or self.case_sha,
                "by": "owner", "decided_at": "2026-11-01T10:00:00+08:00",
                "candidate_case": "",
            },
            "human_decision_valid": True,
            "draft_case_id": "DRAFT-A",
            "provenance": {"compared_against_commit": self.merge},
        }
        path = assessment_path(self.inbox, KEY)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def body(self, sha=None, assessed=None):
        return (
            "<!-- groom-assessment\n"
            "schema: groom-pr/v2\n"
            f"draft: {KEY}\n"
            "case_id: DRAFT-A\n"
            "submitted_case_id: DRAFT-A\n"
            "category: interrupt\n"
            f"assessed_commit: {assessed or self.merge}\n"
            f"assessment_id: {AID}\n"
            f"assessed_content_sha256: {sha or self.case_sha}\n"
            "proposed_novelty: new_pattern\n"
            "candidate_case: \n"
            "human_decision: new_pattern\n"
            f"human_decision_assessment_id: {AID}\n"
            f"human_decision_content_sha256: {sha or self.case_sha}\n"
            "review_required: false\n"
            "-->\n"
        )

    def run_after_merge(self, body, *args):
        path = self.base / "pr-body.md"
        path.write_text(body, encoding="utf-8")
        return run_py(self.repo, "scripts/groom_close_after_merge.py",
                      "--pr-body-file", str(path), "--merge", self.merge,
                      "--no-cleanup", *args)

    def trace_state(self):
        doc = yaml.safe_load((self.repo / "traces" / f"{self.sid}.yaml").read_text(encoding="utf-8"))
        return doc["sedimented"]["state"]

    # ── 用例 ──────────────────────────────────────────────────────────────
    def test_closes_after_merge(self):
        p = self.run_after_merge(self.body(), "--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.trace_state(), "knowledge")
        self.assertFalse((self.inbox / f"{KEY}.case.yaml").exists())
        self.assertTrue((self.inbox / ".done" / KEY).is_dir())
        log = (self.inbox / ".groom" / "close-log.jsonl").read_text(encoding="utf-8").strip()
        last = json.loads(log.splitlines()[-1])
        self.assertEqual(last["mode"], "after-merge")
        self.assertEqual(last["status"], "closed")

    def test_marker_mismatch_blocks(self):
        # marker 与 sidecar 都换一份错的指纹：绑定通过，内容核对失败
        self.write_sidecar(sha="0" * 64)
        p = self.run_after_merge(self.body(sha="0" * 64), "--apply")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(self.trace_state(), "submitted")
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())

    def test_missing_draft_is_skipped(self):
        (self.inbox / f"{KEY}.case.yaml").unlink()
        p = self.run_after_merge(self.body(), "--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.trace_state(), "submitted")
        self.assertIn("不在 inbox", p.stdout)

    def test_draft_key_filters(self):
        p = self.run_after_merge(self.body(), "--apply", "--draft-key", "other")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.trace_state(), "submitted")
        self.assertIn("没有可处理", p.stdout)


    def test_cleanup_failure_marks_run_failed(self):
        import argparse
        import contextlib
        import io
        from unittest import mock

        path = self.base / "pr-body.md"
        path.write_text(self.body(), encoding="utf-8")
        args = argparse.Namespace(pr_body_file=str(path), merge=self.merge, base=None,
                                  draft_key=None, repo=str(self.repo), traces=None,
                                  apply=True, no_cleanup=False, json=True)
        out = io.StringIO()
        with mock.patch("groom_cleanup.cleanup",
                        return_value={"ok": False, "error": "boom"}), \
                contextlib.redirect_stdout(out):
            rc = groom_close_after_merge.run(args)
        self.assertEqual(rc, 2)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["cleanup"]["ok"])


    def test_sidecar_only_close_without_body(self):
        p = run_py(self.repo, "scripts/groom_close_after_merge.py",
                   "--repo", str(self.repo), "--draft-key", KEY,
                   "--merge", self.merge, "--apply", "--no-cleanup")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.trace_state(), "knowledge")
        self.assertFalse((self.inbox / f"{KEY}.case.yaml").exists())

    def test_sidecar_only_default_path_calls_cleanup(self):
        import argparse
        import contextlib
        import io
        from unittest import mock

        from groom_recheck import parse_markers
        import groom_close_after_merge as gam

        args = argparse.Namespace(pr_body_file=None, draft_key=[KEY], merge=self.merge,
                                  base=None, repo=str(self.repo), traces=None,
                                  apply=True, no_cleanup=False, json=True)
        seen = {}

        def _fake(body, repo, base, head, **kw):
            seen["markers"] = parse_markers(body)
            return {"ok": True, "complete": True}

        out = io.StringIO()
        with mock.patch("groom_cleanup.cleanup", side_effect=_fake), \
                contextlib.redirect_stdout(out):
            rc = gam.run(args)
        self.assertEqual(rc, 0, out.getvalue())
        self.assertEqual(len(seen["markers"]), 1)
        self.assertEqual(seen["markers"][0]["draft"], KEY)

    def test_case_only_in_merge_commit(self):
        # 工作树停在合入之后又删掉了 case：收尾仍应从合入提交读出内容。
        (self.repo / CASE_REL).unlink()
        commit_all(self.repo, "remove case from working tree")
        p = self.run_after_merge(self.body(), "--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.trace_state(), "knowledge")
        self.assertTrue((self.inbox / ".done" / KEY).is_dir())

    def test_cleanup_uses_merged_content_not_working_index(self):
        # 工作树的生成索引过期；收尾在隔离合入提交上重建索引，cleanup 不应被拦住。
        index = self.repo / "knowledge" / "_index.yaml"
        index.write_text("stale\n", encoding="utf-8")
        base = git(self.repo, "rev-parse", f"{self.merge}^").stdout.strip()
        path = self.base / "pr-body.md"
        path.write_text(self.body(assessed=base), encoding="utf-8")
        p = run_py(self.repo, "scripts/groom_close_after_merge.py",
                   "--pr-body-file", str(path), "--merge", self.merge,
                   "--base", base, "--apply", "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        payload = json.loads(p.stdout)
        self.assertTrue(payload["cleanup"]["ok"], payload["cleanup"])
        self.assertFalse(assessment_path(self.inbox, KEY).exists())

    def test_synthetic_body_is_parseable(self):
        from groom_close_after_merge import _render_marker_body
        from groom_recheck import parse_markers
        markers = [{
            "schema": "groom-pr/v2", "draft": KEY, "case_id": "DRAFT-A",
            "submitted_case_id": "DRAFT-A", "category": "interrupt",
            "assessed_commit": self.merge, "assessment_id": AID,
            "assessed_content_sha256": self.case_sha,
            "proposed_novelty": "new_pattern", "candidate_case": "",
            "human_decision": "new_pattern",
            "human_decision_assessment_id": AID,
            "human_decision_content_sha256": self.case_sha,
            "review_required": "false",
        }]
        parsed = parse_markers(_render_marker_body(markers))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["draft"], KEY)

    def test_markers_fall_back_to_close_log(self):
        from groom_close_after_merge import _markers_from_sidecars, append_log
        append_log(self.inbox, {
            "draft": KEY, "decision": "new_pattern", "status": "closed",
            "case_id": "DRAFT-A", "assessed_commit": self.merge,
            "assessment_id": AID, "assessed_content_sha256": self.case_sha,
            "category": "interrupt", "review_required": "false",
            "candidate_case": "", "merge": self.merge,
        })
        assessment_path(self.inbox, KEY).unlink()
        markers, why = _markers_from_sidecars(self.inbox, [KEY], self.merge)
        self.assertIsNone(why)
        self.assertEqual(markers[0]["assessed_commit"], self.merge)
        self.assertEqual(markers[0]["assessment_id"], AID)
        _, why2 = _markers_from_sidecars(self.inbox, [KEY], "b" * 40)
        self.assertIsNotNone(why2)

    def test_sidecar_only_variant_keeps_candidate(self):
        doc_path = assessment_path(self.inbox, KEY)
        doc = yaml.safe_load(doc_path.read_text(encoding="utf-8"))
        doc["human_decision"]["decision"] = "variant"
        doc["human_decision"]["candidate_case"] = "CASE-A"
        doc_path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                            encoding="utf-8")
        from groom_close_after_merge import _markers_from_sidecars
        markers, why = _markers_from_sidecars(self.inbox, [KEY], self.merge)
        self.assertIsNone(why)
        self.assertEqual(markers[0]["candidate_case"], "CASE-A")
        self.assertEqual(markers[0]["case_id"], "CASE-A")


if __name__ == "__main__":
    unittest.main()
