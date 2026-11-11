"""Groom 状态：未评估 / 知识前进 / 草稿被改 / 孤儿状态 / 目标 ref 解析 / --check-stale。"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tests.groom_fixtures import (  # noqa: E402
    commit_all, git, init_repo, make_index, run_py, snapshot_meta, write_case, write_draft,
    write_json,
)
from groom_status import print_decision_prompts, status_rows  # noqa: E402
import groom_common  # noqa: E402
from groom_common import assessment_path, case_fingerprint, work_order_id  # noqa: E402


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

    def test_decision_prompt_is_answerable_without_writing(self):
        p = run_py(self.repo, "scripts/groom_status.py", "--snapshot", str(self.meta),
                   "--decision-prompt")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("### draft-a", p.stdout)
        self.assertIn("请选择", p.stdout)
        self.assertIn("1. 同意建议", p.stdout)
        self.assertIn("groom_decide", p.stdout)
        self.assertNotIn("已记录", p.stdout)

    def test_decision_prompt_does_not_offer_invalid_decision(self):
        rows = [{"draft": "draft-x", "proposed_novelty": "ambiguous",
                 "candidate_case": None, "confidence": "low", "stale": False,
                 "human_decision": None, "rationale": "", "review_reasons": []}]
        out = io.StringIO()
        with redirect_stdout(out):
            print_decision_prompts(rows)
        text = out.getvalue()
        self.assertIn("1. 先重跑/补证据", text)
        self.assertNotIn("同意建议：ambiguous", text)
        self.assertIn("reject", text)

    def test_duplicate_proposal_offers_covered(self):
        # agent 判精确重复（duplicate）时，人决定层没有这个枚举项，同意项要落到 covered。
        rows = [{"draft": "draft-dup", "proposed_novelty": "duplicate",
                 "candidate_case": "CASE-A", "confidence": "high", "stale": False,
                 "human_decision": None, "rationale": "同一根因与失效机制", "review_reasons": []}]
        out = io.StringIO()
        with redirect_stdout(out):
            print_decision_prompts(rows)
        text = out.getvalue()
        self.assertIn("1. 同意建议：covered（CASE-A）", text)
        self.assertNotIn("先重跑/补证据", text)
        self.assertIn("duplicate", text)

    def test_stale_approval_gets_reapproval_prompt(self):
        p = run_py(self.repo, "scripts/groom_decide.py", "--draft-key", "draft-a",
                   "--decision", "new_pattern", "--by", "owner-a", "--note", "initial")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        path = assessment_path(self.inbox, "draft-a")
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["human_decision_valid"] = False
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        rows = status_rows(self.repo, self.meta_doc["commit"], self.inbox)
        row = next(r for r in rows if r["draft"] == "draft-a")
        self.assertTrue(row["needs_reapproval"], row)
        out = io.StringIO()
        with redirect_stdout(out):
            print_decision_prompts(rows)
        self.assertIn("重新确认", out.getvalue())

    def test_freshness_git_calls_are_shared_between_drafts(self):
        """同一评估基准的草稿共用 ref 解析、祖先判定与知识库 diff。

        台账与评估记录常指向同一个目标 ref 和 commit；逐行各起子进程是随条目数增长的开销。
        这里钉上限：3 份同基准草稿只解析 1 次 ref、判 1 次祖先、取 1 次 diff。
        """
        commit = self.meta_doc["commit"]
        git(self.repo, "update-ref", "refs/remotes/origin/main", commit)
        draft_text = self.draft.read_text(encoding="utf-8")
        sidecar = yaml.safe_load(
            assessment_path(self.inbox, "draft-a").read_text(encoding="utf-8"))
        sidecar["draft_sha256"] = case_fingerprint(yaml.safe_load(draft_text)["cases"][0])
        sidecar["provenance"]["target_ref"] = "refs/remotes/origin/main"
        for key in ("draft-b", "draft-c"):
            (self.inbox / f"{key}.case.yaml").write_text(draft_text, encoding="utf-8")
            assessment_path(self.inbox, key).write_text(
                yaml.safe_dump(sidecar, allow_unicode=True, sort_keys=False), encoding="utf-8")
        calls = []
        original = groom_common.run_git

        def counted(args, cwd, **kwargs):
            calls.append(" ".join(args[:2]))
            return original(args, cwd, **kwargs)

        groom_common.run_git = counted
        try:
            rows = status_rows(self.repo, commit, self.inbox)
        finally:
            groom_common.run_git = original
        self.assertEqual(len(rows), 3)
        self.assertEqual([row["target_state"] for row in rows], ["ok", "ok", "ok"])
        self.assertEqual(calls.count("rev-parse --verify"), 1)
        self.assertEqual(calls.count("merge-base --is-ancestor"), 1)
        self.assertEqual(calls.count("diff --name-only"), 1)

    def test_corrupt_sidecar_is_reported_not_crash(self):
        path = assessment_path(self.inbox, "draft-a")
        path.write_text("not: [valid", encoding="utf-8")
        rows = status_rows(self.repo, self.meta_doc["commit"], self.inbox)
        row = next(r for r in rows if r["draft"] == "draft-a")
        self.assertTrue(row["stale"])
        self.assertTrue(any("解析失败" in r for r in row["stale_reasons"]), row)


class TargetRefTest(unittest.TestCase):
    """每份评估按自己的目标 ref 判新鲜度；兜底 ref 不再跨 ref 误报「知识前进」。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-target-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base / "repo")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml",
                   cid="CASE-A", title="HCCL timeout")
        self.c0 = commit_all(self.repo, "base")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   cid="CASE-B", title="new case")
        self.c1 = commit_all(self.repo, "add B")
        # origin/main 故意停在旧 commit，mirror/main 跟着最新 knowledge 前进。
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.c0)
        git(self.repo, "update-ref", "refs/remotes/mirror/main", self.c1)
        self.inbox = self.repo / "postmortems" / "inbox"
        write_draft(self.repo, key="draft-a", cid="DRAFT-A", title="HCCL timeout")

    def assess(self, commit, target_ref=None, key="draft-a"):
        doc = {
            "assessment": {"proposed_novelty": "new_pattern", "confidence": "high",
                           "rationale": "different", "review_required": False},
            "provenance": {"compared_against_commit": commit,
                           "compared_against_short": commit[:12],
                           "snapshot_authoritative": True},
            "assessment_id": "a" * 64,
            "human_decision": {},
            "human_decision_valid": False,
            "promotion_gate": {"allowed": True, "blocked_reason": None},
            "review_state": "pending-review",
        }
        if target_ref:
            doc["provenance"]["target_ref"] = target_ref
        path = assessment_path(self.inbox, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def row(self, target=None, **kwargs):
        rows = status_rows(self.repo, target or self.c0, self.inbox, **kwargs)
        return next(r for r in rows if r["draft"] == "draft-a")

    def write_settings(self, remote, base="main"):
        path = self.repo / ".local" / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": "ascend-sleuth-settings/1",
            "target": {"remote": remote, "base": base, "platform": "",
                       "source": "user", "chosen_at": "2026-11-05T10:00:00+08:00"},
        }, ensure_ascii=False), encoding="utf-8")

    def test_assessment_target_ref_beats_older_origin(self):
        # ① 兜底是更旧的 origin/main，评估记录自己的 ref 已包含最新知识 → fresh。
        self.assess(self.c1, target_ref="refs/remotes/mirror/main")
        row = self.row(target=self.c0)
        self.assertFalse(row["stale"], row)
        self.assertEqual(row["target_state"], "ok")
        self.assertEqual(row["target_source"], "assessment")
        self.assertEqual(row["target_ref"], "refs/remotes/mirror/main")
        self.assertEqual(row["target_commit"], self.c1)
        self.assertEqual(row["target_short"], self.c1[:12])

    def test_missing_assessment_ref_is_stale_with_clear_reason(self):
        # ② ref 不可用：说明是哪条 ref，不退回别的 commit 比较。
        self.assess(self.c1, target_ref="refs/remotes/gone/main")
        row = self.row(target=self.c1)
        self.assertTrue(row["stale"])
        self.assertEqual(row["target_state"], "ref_missing")
        self.assertTrue(any("refs/remotes/gone/main" in r for r in row["stale_reasons"]), row)
        self.assertNotIn("前进了", "".join(row["stale_reasons"]))

    def test_missing_explicit_ref_reports_which_ref(self):
        self.assess(self.c0)
        row = self.row(target=self.c1, target_ref="refs/remotes/gone/main")
        self.assertTrue(row["stale"])
        self.assertEqual(row["target_state"], "ref_missing")
        self.assertEqual(row["target_source"], "explicit")
        self.assertTrue(any("refs/remotes/gone/main" in r for r in row["stale_reasons"]), row)

    def test_target_behind_uses_behind_wording(self):
        # ③ 目标是评估的祖先：文案是「落后」，不是「前进了」。
        self.assess(self.c1, target_ref="refs/remotes/origin/main")
        row = self.row(target=self.c0)
        self.assertTrue(row["stale"])
        self.assertEqual(row["target_state"], "target_behind")
        reasons = "".join(row["stale_reasons"])
        self.assertIn("落后", reasons)
        self.assertIn("1 个知识文件", reasons)
        self.assertNotIn("前进", reasons)

    def test_unrelated_history_is_not_comparable(self):
        # ④ 两条不同的历史线：报无法比较，不冒充「知识前进」。
        tree = git(self.repo, "rev-parse", f"{self.c0}^{{tree}}").stdout.strip()
        other = git(self.repo, "commit-tree", tree, "-m", "unrelated").stdout.strip()
        git(self.repo, "update-ref", "refs/remotes/other/main", other)
        self.assess(self.c1, target_ref="refs/remotes/other/main")
        row = self.row(target=self.c0)
        self.assertTrue(row["stale"])
        self.assertEqual(row["target_state"], "not_comparable")
        reasons = "".join(row["stale_reasons"])
        self.assertIn("无法比较", reasons)
        self.assertNotIn("前进", reasons)

    def test_assessment_ref_vs_configured_ref_mismatch(self):
        # ⑤ 评估基准 ref 与当前提 PR 目标 ref 解析到不同 commit。
        self.assess(self.c1, target_ref="refs/remotes/mirror/main")
        row = self.row(target=self.c0, configured_target_ref="refs/remotes/origin/main")
        self.assertTrue(row["stale"])
        self.assertEqual(row["target_state"], "ref_changed")
        reasons = "".join(row["stale_reasons"])
        self.assertIn("refs/remotes/mirror/main", reasons)
        self.assertIn("refs/remotes/origin/main", reasons)

    def test_same_commit_configured_ref_is_not_a_mismatch(self):
        git(self.repo, "update-ref", "refs/remotes/upstream/main", self.c1)
        self.assess(self.c1, target_ref="refs/remotes/mirror/main")
        row = self.row(target=self.c0, configured_target_ref="refs/remotes/upstream/main")
        self.assertFalse(row["stale"], row)
        self.assertEqual(row["target_state"], "ok")

    def test_old_sidecar_uses_configured_target_with_warning(self):
        # ⑥ 旧 sidecar 没有 target_ref，但配置目标可用：按配置目标比较，只给提示。
        self.assess(self.c1)
        row = self.row(target=self.c0, configured_target_ref="refs/remotes/mirror/main")
        self.assertFalse(row["stale"], row)
        self.assertEqual(row["target_source"], "configured")
        self.assertEqual(row["target_ref"], "refs/remotes/mirror/main")
        self.assertTrue(any("评估记录没有目标 ref" in w for w in row["target_warnings"]), row)
        self.assertFalse(any("评估记录没有目标 ref" in r for r in row["stale_reasons"]), row)

    def test_fallback_is_warning_not_stale(self):
        self.assess(self.c0)
        row = self.row(target=self.c0)
        self.assertFalse(row["stale"], row)
        self.assertEqual(row["target_source"], "fallback")
        self.assertTrue(any("目标未配置" in w for w in row["target_warnings"]), row)
        self.assertTrue(all("目标未配置" not in r for r in row["stale_reasons"]), row)

    def test_unassessed_row_has_no_target_state(self):
        row = self.row(target=self.c0)
        self.assertTrue(row["stale"])
        self.assertIsNone(row["target_state"])
        self.assertIsNone(row["target_source"])

    def test_target_ref_advance_is_reported_as_progress(self):
        self.assess(self.c0, target_ref="refs/remotes/mirror/main")
        git(self.repo, "update-ref", "refs/remotes/mirror/main", self.c1)
        row = self.row(target=self.c1)
        self.assertTrue(row["stale"])
        self.assertEqual(row["target_state"], "ok")
        self.assertIn("前进了 1 个文件", "".join(row["stale_reasons"]))

    def test_cli_target_overrides_fallback(self):
        # ⑦ 显式 --target 优先于评估记录/兜底。
        self.assess(self.c1)
        p = run_py(self.repo, "scripts/groom_status.py", "--repo", str(self.repo),
                   "--target", "refs/remotes/mirror/main", "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["target_source"], "explicit")
        self.assertEqual(out["target_ref"], "refs/remotes/mirror/main")
        self.assertEqual(out["target_short"], self.c1[:12])
        row = out["drafts"][0]
        self.assertFalse(row["stale"], row)
        self.assertEqual(row["target_state"], "ok")

    def test_cli_reports_unconfigured_target(self):
        self.assess(self.c0)
        p = run_py(self.repo, "scripts/groom_status.py", "--repo", str(self.repo))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("目标未配置", p.stdout)
        self.assertIn("兜底基准", p.stdout)

    def test_cli_uses_settings_target(self):
        self.assess(self.c1)
        self.write_settings("mirror", "main")
        p = run_py(self.repo, "scripts/groom_status.py", "--repo", str(self.repo), "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["target_source"], "configured")
        self.assertEqual(out["target_short"], self.c1[:12])
        row = out["drafts"][0]
        self.assertFalse(row["stale"], row)
        self.assertEqual(row["target_source"], "configured")

    def test_cli_snapshot_uses_meta_commit_and_ref(self):
        self.assess(self.c1)
        meta = write_json(self.base / "meta.json", snapshot_meta(
            self.repo, commit=self.c1, ref="refs/remotes/mirror/main"))
        p = run_py(self.repo, "scripts/groom_status.py", "--snapshot", str(meta), "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["target_source"], "explicit")
        self.assertEqual(out["target_ref"], "refs/remotes/mirror/main")
        self.assertEqual(out["target_short"], self.c1[:12])
        row = out["drafts"][0]
        self.assertFalse(row["stale"], row)
        self.assertEqual(row["target_state"], "ok")

    def test_cli_snapshot_without_ref_pins_commit(self):
        # 旧 meta 没有 ref：钉住 meta 的 commit，并提示这是快照基准。
        self.assess(self.c1)
        meta_doc = snapshot_meta(self.repo, commit=self.c1)
        meta_doc.pop("ref")
        meta = write_json(self.base / "meta.json", meta_doc)
        p = run_py(self.repo, "scripts/groom_status.py", "--snapshot", str(meta), "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["target_short"], self.c1[:12])
        self.assertEqual(out["target_source"], "explicit")
        self.assertEqual(out["target_ref"], self.c1)
        self.assertTrue(any("快照" in w for w in out["target_warnings"]), out["target_warnings"])
        row = out["drafts"][0]
        self.assertFalse(row["stale"], row)

    def test_cli_snapshot_advanced_ref_pins_commit_with_warning(self):
        # meta 的 ref 已前进：按快照 commit 比较并提示，不让 ref 把基准换掉。
        self.assess(self.c1)
        meta = write_json(self.base / "meta.json", snapshot_meta(
            self.repo, commit=self.c1, ref="refs/remotes/origin/main"))
        p = run_py(self.repo, "scripts/groom_status.py", "--snapshot", str(meta), "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["target_short"], self.c1[:12])
        self.assertTrue(any("已前进" in w for w in out["target_warnings"]), out["target_warnings"])
        self.assertFalse(out["drafts"][0]["stale"], out["drafts"][0])

    def test_cli_invalid_target_exits_3(self):
        self.assess(self.c0)
        p = run_py(self.repo, "scripts/groom_status.py", "--repo", str(self.repo),
                   "--target", "refs/remotes/gone/main")
        self.assertEqual(p.returncode, 3, p.stdout + p.stderr)
        self.assertIn("解析不到", p.stderr)


if __name__ == "__main__":
    unittest.main()
