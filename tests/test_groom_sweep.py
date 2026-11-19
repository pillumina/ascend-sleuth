"""每日 sweep：从台账挑已合入项，取证后调统一收尾入口。

护四件事：
1. 台账带 body 与合入提交时，sweep 能把草稿收尾并出队；
2. 缺证据时只报缺失，不动草稿与 trace；
3. 没有已合入项时输出「无事可做」，退出 0；
4. dry-run 不写任何文件。
"""

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.groom_fixtures import (  # noqa: E402
    commit_all, git, init_repo, run_py, write_case, write_draft,
)
from groom_common import assessment_path, canonical_content_sha  # noqa: E402
import groom_sweep  # noqa: E402
import pr_status  # noqa: E402

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


class SweepTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-sweep-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base / "repo")
        git(self.repo, "remote", "add", "origin", "https://github.com/owner/repo.git")
        self.inbox = self.repo / "postmortems" / "inbox"
        self.sid = "2026-11-01-sweep"
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

    def write_sidecar(self):
        doc = {
            "assessment_id": AID,
            "content_binding": {"sha256": self.case_sha},
            "category": "interrupt",
            "human_decision": {"decision": "new_pattern", "assessment_id": AID,
                               "content_sha256": self.case_sha, "by": "owner",
                               "decided_at": "2026-11-01T10:00:00+08:00",
                               "candidate_case": ""},
            "human_decision_valid": True,
            "draft_case_id": "DRAFT-A",
            "provenance": {"compared_against_commit": self.merge},
        }
        path = assessment_path(self.inbox, KEY)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def marker_body(self):
        return (
            "<!-- groom-assessment\n"
            "schema: groom-pr/v2\n"
            f"draft: {KEY}\n"
            "case_id: DRAFT-A\n"
            "submitted_case_id: DRAFT-A\n"
            "category: interrupt\n"
            f"assessed_commit: {self.merge}\n"
            f"assessment_id: {AID}\n"
            f"assessed_content_sha256: {self.case_sha}\n"
            "proposed_novelty: new_pattern\n"
            "candidate_case: \n"
            "human_decision: new_pattern\n"
            f"human_decision_assessment_id: {AID}\n"
            f"human_decision_content_sha256: {self.case_sha}\n"
            "review_required: false\n"
            "-->\n"
        )

    def write_ledger(self, **extra):
        ledger = pr_status.empty_ledger()
        entry = {"platform": "github", "repo": "owner/repo", "number": 7,
                 "url": "https://github.com/owner/repo/pull/7", "state": "merged",
                 "source": "platform", "checked_at": "2026-11-02T00:00:00+08:00",
                 "body": self.marker_body(), "merge_commit": self.merge}
        entry.update(extra)
        ledger["prs"][KEY] = entry
        pr_status.save_ledger(self.repo, ledger)

    def sweep(self, *args):
        return run_py(self.repo, "scripts/groom_sweep.py", "--repo", str(self.repo),
                      "--no-check", "--no-cleanup", *args)

    def commit_with_remote(self, message):
        git(self.repo, "commit", "--allow-empty", "-m", message)
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    def trace_state(self):
        doc = yaml.safe_load((self.repo / "traces" / f"{self.sid}.yaml").read_text(encoding="utf-8"))
        return doc["sedimented"]["state"]

    def test_sweep_closes_merged_item(self):
        self.write_ledger()
        p = self.sweep("--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.trace_state(), "knowledge")
        self.assertFalse((self.inbox / f"{KEY}.case.yaml").exists())

    def test_sweep_reports_missing_evidence(self):
        self.write_ledger(body="", merge_commit="")
        p = self.sweep("--apply", "--allow-git-only")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("missing-evidence", p.stdout)
        self.assertEqual(self.trace_state(), "submitted")
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())

    def test_sweep_no_merged_is_noop(self):
        pr_status.save_ledger(self.repo, pr_status.empty_ledger())
        p = self.sweep("--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("无事可做", p.stdout)
        self.assertEqual(self.trace_state(), "submitted")

    def test_dry_run_writes_nothing(self):
        self.write_ledger()
        p = self.sweep()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("ready", p.stdout)
        self.assertEqual(self.trace_state(), "submitted")
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())

    def test_json_output(self):
        self.write_ledger()
        p = self.sweep("--apply", "--json")
        payload = json.loads(p.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["merged"], 1)
        self.assertEqual(payload["results"][0]["status"], "closed")


    def test_already_cleaned_pr_is_skipped(self):
        self.write_ledger()
        log = self.inbox / ".groom" / "cleanup-log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps({"ok": True, "head": self.merge}) + "\n", encoding="utf-8")
        p = self.sweep("--apply", "--json")
        payload = json.loads(p.stdout)
        self.assertEqual(payload["results"][0]["status"], "already-done")
        self.assertEqual(self.trace_state(), "submitted")

    def test_fatal_ledger_error_stops(self):
        self.write_ledger()
        args = argparse.Namespace(repo=str(self.repo), apply=True, fetch=False,
                                  no_check=False, no_cleanup=True, source="test", json=True)
        with mock.patch.object(groom_sweep, "_check_all",
                               return_value={"ok": False, "code": "E_LEDGER",
                                             "message": "锁冲突", "checked": []}):
            payload = groom_sweep.run(args)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["error"]["code"], "E_LEDGER")

    def test_same_pr_multiple_drafts_runs_once(self):
        self.write_ledger()
        ledger = pr_status.load_ledger(self.repo)
        ledger["prs"]["draft-b"] = dict(ledger["prs"][KEY])
        pr_status.save_ledger(self.repo, ledger)
        p = self.sweep("--apply", "--json")
        payload = json.loads(p.stdout)
        self.assertEqual(payload["merged"], 1)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(set(payload["results"][0]["drafts"]), {KEY, "draft-b"})

    def test_cleanup_with_kept_items_is_not_done(self):
        self.write_ledger()
        log = self.inbox / ".groom" / "cleanup-log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(json.dumps({"ok": True, "head": self.merge,
                                   "deleted": {"kept": ["draft-a"]}}) + "\n", encoding="utf-8")
        p = self.sweep("--apply", "--json")
        payload = json.loads(p.stdout)
        self.assertNotEqual(payload["results"][0]["status"], "already-done")

    def test_check_all_parses_structured_error(self):
        class Proc:
            returncode = 1
            stdout = json.dumps({"ok": False, "error": {"code": "E_INTERNAL",
                                                        "message": "boom"}})
            stderr = ""
        with mock.patch.object(groom_sweep, "_run", return_value=Proc()):
            check = groom_sweep._check_all(self.repo)
        self.assertFalse(check["ok"])
        self.assertEqual(check["code"], "E_INTERNAL")

    def test_check_all_maps_exit_code_without_json(self):
        class Proc:
            returncode = 2
            stdout = ""
            stderr = "usage"
        with mock.patch.object(groom_sweep, "_run", return_value=Proc()):
            check = groom_sweep._check_all(self.repo)
        self.assertFalse(check["ok"])
        self.assertEqual(check["code"], "E_ARGS")


    def test_sweep_uses_git_to_find_merge_commit(self):
        # squash 形态：显式开启后，才用 git 标题匹配取合入提交。
        self.commit_with_remote("HCCL timeout (#7)")
        self.write_ledger(body="", merge_commit="", base="main")
        p = self.sweep("--apply", "--json", "--allow-git-only")
        payload = json.loads(p.stdout)
        self.assertTrue(payload["ok"], p.stdout + p.stderr)
        self.assertEqual(payload["results"][0]["status"], "closed")
        self.assertEqual(self.trace_state(), "knowledge")

    def test_merged_without_sha_is_report_only(self):
        # 台账已 merged 但缺合入 SHA：默认不自动写，避免拿 fork 的同号提交误删。
        self.commit_with_remote("HCCL timeout (#7)")
        self.write_ledger(body="", merge_commit="", base="main")
        p = self.sweep("--apply", "--json")
        payload = json.loads(p.stdout)
        self.assertEqual(payload["results"][0]["status"], "git-suspected")
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())

    def test_closed_record_with_old_sha_is_skipped(self):
        self.commit_with_remote("HCCL timeout (#7)")
        self.write_ledger(state="closed", merge_commit=self.merge)
        p = self.sweep("--apply", "--json")
        payload = json.loads(p.stdout)
        self.assertEqual(payload["results"], [])
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())

    def test_git_merge_reports_missing_remote_ref(self):
        git(self.repo, "commit", "--allow-empty", "-m", "HCCL timeout (#7)")
        sha, why = groom_sweep._git_merge(
            self.repo, {"number": 7, "repo": "owner/repo", "base": "main"})
        self.assertEqual(sha, "")
        self.assertIn("远端引用缺失", why)

    def test_git_merge_requires_repo_remote_match(self):
        git(self.repo, "remote", "set-url", "origin", "https://github.com/other/repo.git")
        self.commit_with_remote("HCCL timeout (#7)")
        sha, why = groom_sweep._git_merge(self.repo, {"number": 7, "repo": "owner/repo"})
        self.assertEqual(sha, "")
        self.assertIn("不一致", why)


    def test_git_only_closes_open_record(self):
        # 显式开启后，git 能匹配合入提交的 open 记录才允许自动写。
        self.commit_with_remote("HCCL timeout (#7)")
        self.write_ledger(state="open", body="", merge_commit="", base="main")
        p = self.sweep("--apply", "--json", "--allow-git-only")
        payload = json.loads(p.stdout)
        self.assertTrue(payload["ok"], p.stdout + p.stderr)
        self.assertEqual(payload["results"][0]["status"], "closed")
        self.assertEqual(self.trace_state(), "knowledge")

    def test_git_only_is_report_only_by_default(self):
        # 没有平台状态确认时，git 只算疑似合入，默认不自动出队或删评估。
        self.commit_with_remote("HCCL timeout (#7)")
        self.write_ledger(state="open", body="", merge_commit="", base="main")
        p = self.sweep("--apply", "--json")
        payload = json.loads(p.stdout)
        self.assertEqual(payload["results"][0]["status"], "git-suspected")
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())


    def test_git_merge_ignores_prefix_number(self):
        # 只提到 #70 的提交不能被当成 PR #7 的合入提交。
        git(self.repo, "commit", "--allow-empty", "-m", "other (#70)")
        sha, _ = groom_sweep._git_merge(self.repo, {"number": 7, "base": "main"})
        self.assertEqual(sha, "")


    def test_git_merge_ignores_body_mention(self):
        # 只在正文提到 (#7)，不能当成 PR #7 的合入证据。
        git(self.repo, "commit", "--allow-empty", "-m", "unrelated",
            "-m", "mentions (#7) in body")
        sha, _ = groom_sweep._git_merge(self.repo, {"number": 7, "base": "main"})
        self.assertEqual(sha, "")

    def test_git_merge_ignores_title_mention(self):
        # 标题中间提到 (#7)，不是 squash 的结尾编号，也不能当成合入证据。
        git(self.repo, "commit", "--allow-empty", "-m", "mention (#7) in title")
        sha, _ = groom_sweep._git_merge(self.repo, {"number": 7, "base": "main"})
        self.assertEqual(sha, "")

    def test_git_merge_ancestor_picks_merge_commit(self):
        git(self.repo, "checkout", "-b", "feature")
        git(self.repo, "commit", "--allow-empty", "-m", "feature work")
        feature = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        # 登记 head 之后又加了一个提交；合入点应是 merge commit，不是这个中间提交。
        git(self.repo, "commit", "--allow-empty", "-m", "more work")
        git(self.repo, "checkout", "main")
        git(self.repo, "merge", "--no-ff", "feature", "-m", "merge feature")
        merge = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        git(self.repo, "commit", "--allow-empty", "-m", "after merge")
        sha, _ = groom_sweep._git_merge(self.repo, {"head": feature, "base": "main"})
        self.assertEqual(sha, merge)


    def test_evidence_accepts_platform_merged_sha(self):
        entry = {"platform": "github", "repo": "owner/repo", "number": 7,
                 "url": "https://github.com/owner/repo/pull/7", "state": "merged"}
        fetched = {"ok": True, "state": "merged", "merge_commit": "a" * 40}
        with mock.patch.object(groom_sweep, "_adapter_fetch", return_value=(fetched, None)):
            _, merge, _, source = groom_sweep._evidence(self.repo, entry)
        self.assertEqual(source, "platform")
        self.assertEqual(merge, "a" * 40)

    def test_evidence_platform_open_stops(self):
        entry = {"state": "open", "repo": "owner/repo", "number": 7,
                 "url": "https://github.com/owner/repo/pull/7"}
        with mock.patch.object(groom_sweep, "_adapter_fetch",
                               return_value=({"ok": True, "state": "open"}, None)):
            _, merge, why, _ = groom_sweep._evidence(self.repo, entry)
        self.assertEqual(merge, "")
        self.assertIn("平台状态 open", why)

    def test_same_pr_open_blocks_default_write(self):
        self.write_ledger()
        ledger = pr_status.load_ledger(self.repo)
        ledger["prs"]["draft-b"] = dict(ledger["prs"][KEY], state="open", merge_commit="")
        pr_status.save_ledger(self.repo, ledger)
        args = argparse.Namespace(repo=str(self.repo), apply=True, fetch=False,
                                  no_check=False, no_cleanup=True, source="test",
                                  json=True)
        checked = [{"draft": "draft-b", "ok": True, "state": "open"}]
        with mock.patch.object(groom_sweep, "_check_all",
                               return_value={"ok": False, "code": "E_CHECK_PARTIAL",
                                             "message": "有 PR 状态没查到", "checked": checked}):
            payload = groom_sweep.run(args)
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())
        self.assertFalse(any(r.get("status") == "closed" for r in payload["results"]))

    def test_git_merge_uses_full_repo_path(self):
        git(self.repo, "remote", "set-url", "origin",
            "https://gitlab.com/group/subgroup/target-project.git")
        git(self.repo, "commit", "--allow-empty", "-m", "HCCL timeout (#7)")
        sha, why = groom_sweep._git_merge(self.repo, {
            "number": 7, "repo": "group/subgroup/other-project", "platform": "gitlab",
            "url": "https://gitlab.com/group/subgroup/other-project/-/merge_requests/7",
            "base": "main"})
        self.assertEqual(sha, "")
        self.assertIn("不一致", why)

    def test_group_key_uses_link_repo(self):
        self.write_ledger()
        ledger = pr_status.load_ledger(self.repo)
        ledger["prs"]["draft-b"] = dict(ledger["prs"][KEY], state="closed",
                                        repo="another/repo")
        pr_status.save_ledger(self.repo, ledger)
        p = self.sweep("--apply", "--json")
        payload = json.loads(p.stdout)
        self.assertEqual(payload["results"][0]["status"], "identity-mismatch")
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())

    def test_group_rejects_any_draft_identity_mismatch(self):
        self.write_ledger()
        ledger = pr_status.load_ledger(self.repo)
        ledger["prs"]["draft-b"] = dict(ledger["prs"][KEY], number=8)
        pr_status.save_ledger(self.repo, ledger)
        p = self.sweep("--apply", "--json")
        payload = json.loads(p.stdout)
        self.assertEqual(payload["results"][0]["status"], "identity-mismatch")
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())

    def test_identity_rejects_repo_mismatch(self):
        self.write_ledger()
        ledger = pr_status.load_ledger(self.repo)
        ledger["prs"][KEY]["repo"] = "another/repo"
        pr_status.save_ledger(self.repo, ledger)
        p = self.sweep("--apply", "--json")
        payload = json.loads(p.stdout)
        self.assertEqual(payload["results"][0]["status"], "identity-mismatch")
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())

    def test_platform_identity_mismatch_ignores_query_number(self):
        entry = {"repo": "owner/repo", "number": 8,
                 "url": "https://github.com/owner/repo/pull/7?redirect=/pulls/8"}

        class GitHub:
            hosts = ["github.com"]

            def fetch(self, _entry):
                return {"ok": True, "state": "merged", "merge_commit": "b" * 40}

        adapters = [{"id": "github", "hosts": ["github.com"], "module": GitHub()}]
        with mock.patch.object(pr_status, "load_adapters", return_value=adapters):
            fetched, why = groom_sweep._adapter_fetch(entry)
        self.assertIsNone(fetched)
        self.assertIn("不一致", why)

    def test_ledger_sha_does_not_bypass_identity(self):
        entry = {"repo": "owner/repo", "number": 8,
                 "url": "https://github.com/owner/repo/pull/7",
                 "state": "merged", "merge_commit": "a" * 40}
        _, merge, why, _ = groom_sweep._evidence(self.repo, entry)
        self.assertEqual(merge, "")
        self.assertIn("不一致", why)

    def test_git_does_not_bypass_identity(self):
        entry = {"repo": "owner/repo", "number": 8,
                 "url": "https://github.com/owner/repo/pull/7",
                 "state": "merged"}
        with mock.patch.object(groom_sweep, "_git_merge") as git_merge:
            _, merge, why, _ = groom_sweep._evidence(self.repo, entry)
        self.assertEqual(merge, "")
        self.assertIn("不一致", why)
        git_merge.assert_not_called()

    def test_adapter_fetch_rejects_number_mismatch(self):
        entry = {"repo": "owner/repo", "number": 8,
                 "url": "https://github.com/owner/repo/pull/7"}
        fetched, why = groom_sweep._adapter_fetch(entry)
        self.assertIsNone(fetched)
        self.assertIn("不一致", why)

    def test_adapter_fetch_rejects_evidence_other_number(self):
        entry = {"repo": "owner/repo", "number": 7,
                 "url": "https://gitlab.com/owner/repo/-/merge_requests/7"}

        class GitLab:
            hosts = ["gitlab.com"]

            def fetch(self, _entry):
                return {"ok": True, "state": "merged", "merge_commit": "b" * 40,
                        "url": "https://gitlab.com/owner/repo/-/merge_requests/8"}

        adapters = [{"id": "gitlab", "hosts": ["gitlab.com"], "module": GitLab()}]
        with mock.patch.object(pr_status, "load_adapters", return_value=adapters):
            fetched, why = groom_sweep._adapter_fetch(entry)
        self.assertIsNone(fetched)
        self.assertIn("不属于同一 PR", why)

    def test_adapter_fetch_uses_parsed_host(self):
        entry = {"platform": "gitlab", "repo": "owner/repo", "number": 7,
                 "url": "https://gitlab.com/owner/repo/-/merge_requests/7?redirect=github.com"}

        class GitLab:
            hosts = ["gitlab.com"]

            def fetch(self, _entry):
                return {"ok": True, "state": "merged", "merge_commit": "b" * 40}

        class GitHub:
            hosts = ["github.com"]

            def fetch(self, _entry):
                return {"ok": True, "state": "merged", "merge_commit": "a" * 40}

        adapters = [{"id": "github", "hosts": ["github.com"], "module": GitHub()},
                    {"id": "gitlab", "hosts": ["gitlab.com"], "module": GitLab()}]
        with mock.patch.object(pr_status, "load_adapters", return_value=adapters):
            fetched, why = groom_sweep._adapter_fetch(entry)
        self.assertIsNone(why)
        self.assertEqual(fetched["merge_commit"], "b" * 40)

    def test_adapter_fetch_rejects_other_pr_evidence(self):
        entry = {"repo": "owner/repo", "number": 7,
                 "url": "https://gitlab.com/owner/repo/-/merge_requests/7"}

        class GitLab:
            hosts = ["gitlab.com"]

            def fetch(self, _entry):
                return {"ok": True, "state": "merged", "merge_commit": "b" * 40,
                        "url": "https://github.com/other/repo/pull/7"}

        adapters = [{"id": "gitlab", "hosts": ["gitlab.com"], "module": GitLab()}]
        with mock.patch.object(pr_status, "load_adapters", return_value=adapters):
            fetched, why = groom_sweep._adapter_fetch(entry)
        self.assertIsNone(fetched)
        self.assertIn("不属于同一 PR", why)

    def test_pr_ident_ignores_platform_alias(self):
        first = {"platform": "gitlab", "repo": "owner/repo", "number": 7,
                 "url": "https://gitlab.com/owner/repo/-/merge_requests/7"}
        second = dict(first, platform="glab")
        self.assertEqual(groom_sweep._pr_ident(first), groom_sweep._pr_ident(second))

    def test_same_pr_url_query_variants_group_together(self):
        self.write_ledger()
        ledger = pr_status.load_ledger(self.repo)
        ledger["prs"][KEY]["url"] = "https://github.com/owner/repo/pull/7?diff_id=2"
        ledger["prs"]["draft-b"] = dict(ledger["prs"][KEY], state="open", merge_commit="")
        ledger["prs"]["draft-b"]["url"] = "https://github.com/owner/repo/pull/7"
        pr_status.save_ledger(self.repo, ledger)
        args = argparse.Namespace(repo=str(self.repo), apply=True, fetch=False,
                                  no_check=False, no_cleanup=True, source="test",
                                  json=True)
        checked = [{"draft": "draft-b", "ok": True, "state": "open"}]
        with mock.patch.object(groom_sweep, "_check_all",
                               return_value={"ok": False, "code": "E_CHECK_PARTIAL",
                                             "message": "有 PR 状态没查到", "checked": checked}):
            payload = groom_sweep.run(args)
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())
        self.assertFalse(any(r.get("status") == "closed" for r in payload["results"]))

    def test_git_merge_uses_fetch_url_not_push_url(self):
        git(self.repo, "remote", "set-url", "origin",
            "https://gitlab.com/group/subgroup/target-project.git")
        git(self.repo, "remote", "set-url", "--push", "origin",
            "https://gitlab.com/group/subgroup/other-project.git")
        git(self.repo, "commit", "--allow-empty", "-m", "HCCL timeout (#7)")
        sha, why = groom_sweep._git_merge(self.repo, {
            "number": 7, "repo": "group/subgroup/other-project", "platform": "gitlab",
            "url": "https://gitlab.com/group/subgroup/other-project/-/merge_requests/7",
            "base": "main"})
        self.assertEqual(sha, "")
        self.assertIn("不一致", why)

    def test_same_pr_open_protects_all_drafts(self):
        self.commit_with_remote("HCCL timeout (#7)")
        self.write_ledger(state="open")
        ledger = pr_status.load_ledger(self.repo)
        ledger["prs"]["draft-b"] = dict(ledger["prs"][KEY], state="unknown")
        pr_status.save_ledger(self.repo, ledger)
        args = argparse.Namespace(repo=str(self.repo), apply=True, fetch=False,
                                  no_check=False, no_cleanup=True, source="test",
                                  json=True, allow_git_only=True)
        checked = [{"draft": KEY, "ok": True, "state": "open"},
                   {"draft": "draft-b", "ok": False, "state": "unknown"}]
        with mock.patch.object(groom_sweep, "_check_all",
                               return_value={"ok": False, "code": "E_CHECK_PARTIAL",
                                             "message": "有 PR 状态没查到", "checked": checked}):
            payload = groom_sweep.run(args)
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())
        self.assertFalse(any(r.get("status") == "closed" for r in payload["results"]))

    def test_git_merge_rejects_same_repo_on_other_host(self):
        git(self.repo, "commit", "--allow-empty", "-m", "HCCL timeout (#7)")
        sha, why = groom_sweep._git_merge(self.repo, {
            "number": 7, "repo": "owner/repo", "platform": "gitlab",
            "url": "https://gitlab.com/owner/repo/-/merge_requests/7",
            "base": "main"})
        self.assertEqual(sha, "")
        self.assertIn("不一致", why)

    def test_check_partial_does_not_override_open(self):
        self.commit_with_remote("HCCL timeout (#7)")
        self.write_ledger(state="open")
        args = argparse.Namespace(repo=str(self.repo), apply=True, fetch=False,
                                  no_check=False, no_cleanup=True, source="test",
                                  json=True, allow_git_only=True)
        checked = [{"draft": KEY, "ok": True, "state": "open"},
                   {"draft": "draft-b", "ok": False, "state": "unknown"}]
        with mock.patch.object(groom_sweep, "_check_all",
                               return_value={"ok": False, "code": "E_CHECK_PARTIAL",
                                             "message": "有 PR 状态没查到", "checked": checked}):
            payload = groom_sweep.run(args)
        self.assertTrue((self.inbox / f"{KEY}.case.yaml").exists())
        self.assertFalse(any(r.get("draft") == KEY and r.get("status") == "closed"
                             for r in payload["results"]))

    def test_git_merge_requires_full_remote_ref(self):
        git(self.repo, "branch", "upstream/release/v1")
        git(self.repo, "commit", "--allow-empty", "-m", "HCCL timeout (#7)")
        sha, why = groom_sweep._git_merge(
            self.repo, {"number": 7, "repo": "owner/repo", "base": "release/v1"})
        self.assertEqual(sha, "")
        self.assertIn("远端引用缺失", why)

    def test_git_merge_requires_remote_ref_for_slash_branch(self):
        git(self.repo, "branch", "release/v1")
        git(self.repo, "commit", "--allow-empty", "-m", "HCCL timeout (#7)")
        sha, why = groom_sweep._git_merge(
            self.repo, {"number": 7, "repo": "owner/repo", "base": "release/v1"})
        self.assertEqual(sha, "")
        self.assertIn("远端引用缺失", why)

    def test_git_merge_uses_matched_remote_for_bare_base(self):
        git(self.repo, "remote", "set-url", "origin", "https://github.com/fork/repo.git")
        git(self.repo, "remote", "add", "upstream", "https://github.com/owner/repo.git")
        self.commit_with_remote("HCCL timeout (#7)")
        upstream_sha = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        git(self.repo, "update-ref", "refs/remotes/upstream/main", upstream_sha)
        # fork 的本地 main 上再来一个同号提交；用 upstream 时应选前一个。
        git(self.repo, "commit", "--allow-empty", "-m", "fork (#7)")
        sha, why = groom_sweep._git_merge(
            self.repo, {"number": 7, "repo": "owner/repo", "base": "main"})
        self.assertEqual(sha, upstream_sha, why)


if __name__ == "__main__":
    unittest.main()
