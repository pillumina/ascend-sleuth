"""sediment_state 的口径回归测试。

护的是「状态合并」这一层：草稿进队列之后，评估、人决定、PR 台账、trace 沉淀状态在四个
地方各写各的，读侧必须按固定优先级合并成一份队列。错了不会报错，只会让面板停在错的阶段。

做法：真实临时 git 仓库 + 真实共享 inbox（`groom_common.shared_inbox` 解析到该仓库），
sidecar 按 `groom_record` / `groom_decide` 写下的字段构造；新鲜度、stale、人决定有效性
一律让 `groom_status.status_rows` 现算，不 mock 判据。不联网。

覆盖：空态、无 sidecar、stale、需重批、有效决定、defer/reject、PR open/merged/closed、
孤儿、done（trace 已升格但草稿还在队列）、trace 匹配三种键、四类批次 prompt 与明细字段、
计数（含 oldestDays）、history、`--only`、目标 ref 解析（settings target / 评估记录的
target_ref 压过 origin/main 兜底）、CLI 的 ok:false 协议。
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "dsh-plugins" / "dsh-sleuth-copilot" / "lib"))

import groom_common as gm  # noqa: E402
import pr_status as pr  # noqa: E402
import sediment_state as ss  # noqa: E402
from tests.groom_fixtures import commit_all, git, run_py  # noqa: E402

CASE_TMPL = """cases:
  - id: {cid}
    title: "{title}"
{source}    category: interrupt
    tags: [test]
    symptoms:
      - "测试症状"
    root_cause: "测试根因"
    fix: "测试修复"
    severity: service-affecting
    fix_type: config-change
    quickly_check:
      primary:
        command_template: "echo {cid}"
        expected: "regex:{cid}"
"""


# ---------------------------------------------------------------- 构造临时仓库与运行时件

def init_repo(base: Path):
    repo = base / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "sediment@example.com")
    git(repo, "config", "user.name", "Sediment Test")
    write_case(repo, "knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml",
               "CASE-A", title="HCCL timeout")
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    commit_all(repo, "base")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


def write_case(repo: Path, rel: str, cid: str, title: str = "测试 case",
               source_session: str = "") -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    source = f'    source_session: "{source_session}"\n' if source_session else ""
    path.write_text(CASE_TMPL.format(cid=cid, title=title, source=source), encoding="utf-8")
    return path


def inbox(repo: Path) -> Path:
    return repo / "postmortems" / "inbox"


def write_draft(repo: Path, key: str = "2026-10-20-draft-a", cid: str = "DRAFT-A",
                title: str = "PD 分离 prefill 卡死：AscendStore 异步 load 从不完成",
                created_at: str = "", source_session: str = "") -> Path:
    path = inbox(repo) / f"{key}.case.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    head = f'created_at: "{created_at}"\n' if created_at else ""
    source = f'    source_session: "{source_session}"\n' if source_session else ""
    path.write_text(head + CASE_TMPL.format(cid=cid, title=title, source=source),
                    encoding="utf-8")
    return path


def fresh_commit(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def write_assessment(repo: Path, key: str, commit: str, decision: str = "new_pattern",
                     candidate=None, human_valid: bool = True, authoritative: bool = True,
                     assessment_id: str = "assess-1", proposed: str = "",
                     target_ref: str = "") -> Path:
    draft_path = inbox(repo) / f"{key}.case.yaml"
    doc = yaml.safe_load(draft_path.read_text(encoding="utf-8"))
    case = (doc.get("cases") or [{}])[0]
    provenance = {
        "compared_against_commit": commit,
        "compared_against_short": commit[:12],
        "snapshot_authoritative": authoritative,
    }
    if target_ref:
        provenance["target_ref"] = target_ref
    sidecar = {
        "assessment": {
            "proposed_novelty": proposed or decision,
            "candidate_case": candidate,
            "confidence": "high",
            "rationale": "与已有 case 根因不同",
            "review_required": False,
        },
        "provenance": provenance,
        "assessment_id": assessment_id,
        "draft_sha256": gm.case_fingerprint(case),
        "human_decision": ({
            "decision": decision,
            "candidate_case": candidate,
            "by": "测试人",
            "decided_at": "2026-11-01T09:00:00+08:00",
        } if decision else {}),
        "human_decision_valid": human_valid,
        "promotion_gate": {"allowed": True, "blocked_reason": None},
        "review_state": "decided" if decision else "pending",
    }
    path = inbox(repo) / ".groom" / "assessments" / f"{gm.sanitize_key(key)}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(sidecar, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return path


def write_trace(repo: Path, sid: str, state: str = "none", inbox_path: str = "",
                case_id: str = "", harness_session=None, status: str = "resolved") -> Path:
    """harness_session=None 时整个字段不写：主检出里还有这种旧 trace，读侧要当空值。"""
    traces = repo / "traces"
    traces.mkdir(exist_ok=True)
    path = traces / f"{sid}.yaml"
    head = f'session_id: "{sid}"\n'
    if harness_session is not None:
        head += f'harness_session: "{harness_session}"\n'
    path.write_text(
        head
        + f'status: {status}\n'
        + 'updated_at: "2026-11-01T10:00:00+08:00"\n'
        + "sedimented:\n"
        + f"  state: {state}\n"
        + f'  case_id: "{case_id}"\n'
        + f'  inbox_path: "{inbox_path}"\n'
        + "trace:\n"
        + '  - {role: user, step: 1, content: "测试"}\n',
        encoding="utf-8",
    )
    return path


def write_ledger(repo: Path, target=None, prs=None) -> str:
    data = pr.empty_ledger()
    data["target"] = target
    data["prs"] = prs or {}
    return pr.save_ledger(repo, data)


def write_settings_target(repo: Path, remote: str, base: str = "main") -> None:
    """写 `.local/settings.json` 的 target；这是面板与命令行共用的目标配置。"""
    pr.kb_sync.save_settings(repo, {
        "sync": {"remote": "origin", "branch": "main"},
        "target": {"remote": remote, "base": base, "platform": "",
                   "source": "user", "chosen_at": "2026-11-05T10:00:00+08:00"},
    })


GITHUB_TARGET = {
    "remote": "origin", "base": "main", "platform": "github",
    "url": "https://github.com/pillumina/ascend-sleuth.git",
    "note": "", "labels": {}, "source": "user",
    "chosen_at": "2026-11-01T10:00:00+08:00",
}


def pr_entry(url="https://github.com/pillumina/ascend-sleuth/pull/418",
             state="open", platform="github", repo="pillumina/ascend-sleuth",
             number=418, source="ledger"):
    return {"platform": platform, "repo": repo, "number": number, "url": url,
            "state": state, "source": source,
            "created_at": "2026-11-01T10:00:00+08:00"}


class SedimentCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sediment-state-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base)

    def collect(self, only=""):
        return ss.collect(self.repo, only=only)

    def draft(self, payload, key="2026-10-20-draft-a"):
        return next(row for row in payload["drafts"] if row["key"] == key)

    def age_iso(self, days: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


# ---------------------------------------------------------------- 基础状态

class StateTest(SedimentCase):
    def test_empty_queue(self):
        payload = self.collect()
        self.assertEqual(payload["counts"]["total"], 0)
        self.assertEqual(payload["counts"]["oldestDays"], 0)
        self.assertEqual(payload["drafts"], [])
        self.assertEqual(payload["primary"]["kind"], "none")
        self.assertEqual(payload["history"], [])
        self.assertEqual(payload["targetCommitShort"], fresh_commit(self.repo)[:12])
        self.assertEqual(Path(payload["inbox"]).resolve(), inbox(self.repo).resolve())
        for key in ("groom", "pr", "check", "close",
                    "groomDetail", "prDetail", "checkDetail", "closeDetail"):
            self.assertEqual(payload["prompts"][key], "", key)

    def test_unassessed_draft(self):
        write_draft(self.repo, created_at=self.age_iso(16))
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(row["state"], "unassessed")
        self.assertEqual(row["stage"], "已交草稿 · 未评估")
        self.assertEqual(row["stageTone"], "gray")
        self.assertEqual(row["ageDays"], 16)
        self.assertEqual(row["ageSource"], "created_at")
        self.assertEqual(row["next"]["kind"], "groom")
        # 批次指令只在顶层 prompts 出一份，行内不再复制（payload 不随行数平方增长）。
        self.assertNotIn("prompt", row["next"])
        self.assertIn("knowledge-groom", payload["prompts"]["groom"])
        self.assertIn("逐条问我，不替我决定", payload["prompts"]["groom"])
        self.assertIn("groom_status.py --decision-prompt", payload["prompts"]["groomDetail"])
        self.assertIn("shared_dir.py inbox", payload["prompts"]["groomDetail"])
        self.assertEqual(payload["counts"]["unassessed"], 1)
        self.assertEqual(payload["counts"]["overdue"], 1)
        self.assertEqual(payload["counts"]["oldestDays"], 16)
        self.assertEqual(payload["primary"]["kind"], "groom")
        self.assertEqual(row["path"], "postmortems/inbox/2026-10-20-draft-a.case.yaml")
        self.assertEqual(row["title"], "PD 分离 prefill 卡死：AscendStore 异步 load 从不完成")
        # 没有评估就没有目标可比：新字段给空值，面板不显示假的基准。
        self.assertEqual(row["targetRef"], "")
        self.assertEqual(row["targetShort"], "")
        self.assertIsNone(row["targetState"])
        self.assertIsNone(row["targetSource"])
        self.assertEqual(row["targetWarnings"], [])

    def test_age_falls_back_to_mtime(self):
        path = write_draft(self.repo)
        old = (datetime.now(timezone.utc) - timedelta(days=20)).timestamp()
        os.utime(path, (old, old))
        row = self.draft(self.collect())
        self.assertEqual(row["ageSource"], "mtime")
        self.assertGreaterEqual(row["ageDays"], 19)

    def test_prompt_keys_scope_batch_prompts_only(self):
        # 面板多选后按 key 现算批次指令：队列与计数仍是全量，只有指令名单收窄。
        write_draft(self.repo, key="draft-a", cid="DRAFT-A")
        write_draft(self.repo, key="draft-b", cid="DRAFT-B")
        write_assessment(self.repo, "draft-a", fresh_commit(self.repo))
        write_assessment(self.repo, "draft-b", fresh_commit(self.repo))
        write_ledger(self.repo, target=GITHUB_TARGET)
        payload = ss.collect(self.repo, prompt_keys=["draft-b"])
        self.assertEqual(len(payload["drafts"]), 2)
        self.assertEqual(payload["counts"]["decided"], 2)
        self.assertIn("draft-b", payload["prompts"]["pr"])
        self.assertNotIn("draft-a", payload["prompts"]["pr"])
        other = ss.collect(self.repo, prompt_keys=["draft-a"])
        self.assertIn("draft-a", other["prompts"]["pr"])
        self.assertNotIn("draft-b", other["prompts"]["pr"])

    def test_stale_assessment_needs_rerun(self):
        write_draft(self.repo)
        old_commit = fresh_commit(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", old_commit)
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   "CASE-B", title="新 case")
        new_commit = commit_all(self.repo, "add B")
        git(self.repo, "update-ref", "refs/remotes/origin/main", new_commit)
        row = self.draft(self.collect())
        self.assertEqual(row["state"], "need_rerun")
        self.assertEqual(row["stage"], "需重跑")
        self.assertEqual(row["stageTone"], "bad")
        self.assertTrue(row["stale"])
        self.assertTrue(any("知识库" in reason for reason in row["staleReasons"]))
        self.assertEqual(row["next"]["kind"], "groom")

    def test_human_approval_not_bound_needs_rerun(self):
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo),
                         human_valid=False)
        row = self.draft(self.collect())
        self.assertEqual(row["state"], "need_rerun")
        self.assertIn("人的批准", " ".join(row["staleReasons"]))

    def test_valid_decision_is_decided(self):
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo))
        write_ledger(self.repo, target=GITHUB_TARGET)
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(row["state"], "decided")
        self.assertEqual(row["stage"], "待提 PR")
        self.assertEqual(row["stageTone"], "accent")
        self.assertEqual(row["decision"], "new_pattern")
        self.assertTrue(row["decisionValid"])
        self.assertEqual(row["decisionBy"], "测试人")
        self.assertEqual(row["next"]["kind"], "pr")
        self.assertNotIn("prompt", row["next"])
        prompt = payload["prompts"]["pr"]
        self.assertIn("origin/main（GitHub）", prompt)
        self.assertIn("new_pattern", prompt)
        self.assertIn("先落盘并过升格检查", prompt)
        self.assertIn("不要跑 close / cleanup", prompt)
        self.assertIn("postmortems/inbox/.groom/pr-state.json", prompt)
        detail = payload["prompts"]["prDetail"]
        self.assertIn("verify_case_draft.py --gate", detail)
        self.assertIn("groom_record.py --pr-marker", detail)
        self.assertIn("groom_recheck.py", detail)
        self.assertIn("gh pr create", detail)
        self.assertEqual(payload["prompts"]["groomDetail"], "")
        self.assertEqual(payload["primary"]["kind"], "pr")
        self.assertEqual(payload["counts"]["decided"], 1)

    def test_undo_prompt_for_inbox_draft(self):
        # 草稿还在 inbox、没有 PR：右列给「撤销沉淀」指令，带决定提示与 .undone 去向。
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo),
                         decision="new_pattern")
        row = self.draft(self.collect())
        self.assertTrue(row["undo"]["available"])
        self.assertIn("scripts/sediment_undo.py --draft-key 2026-10-20-draft-a", row["undo"]["prompt"])
        self.assertIn("--apply", row["undo"]["prompt"])
        self.assertIn("已有人决定（new_pattern）", row["undo"]["prompt"])
        self.assertIn(".undone", row["undo"]["prompt"])

    def test_undo_hidden_when_pr_exists(self):
        write_draft(self.repo)
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="open")})
        row = self.draft(self.collect())
        self.assertEqual(row["state"], "pr_open")
        self.assertFalse(row["undo"]["available"])
        self.assertEqual(row["undo"]["prompt"], "")

    def test_undo_available_when_pr_closed(self):
        # 关闭的 PR 不再拦撤销；提示里写明台账记录会被清掉、PR 本身不动。
        write_draft(self.repo)
        write_ledger(self.repo, target=GITHUB_TARGET, prs={"2026-10-20-draft-a": pr_entry(
            state="closed", number=431,
            url="https://github.com/pillumina/ascend-sleuth/pull/431")})
        row = self.draft(self.collect())
        self.assertEqual(row["state"], "pr_closed")
        self.assertTrue(row["undo"]["available"])
        prompt = row["undo"]["prompt"]
        self.assertIn("#431", prompt)
        self.assertIn("已关闭", prompt)
        self.assertIn("清掉", prompt)
        self.assertIn("PR 本身在平台上不动", prompt)
        self.assertIn("--apply", prompt)

    def test_undo_hidden_when_pr_merged(self):
        write_draft(self.repo)
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="merged")})
        row = self.draft(self.collect())
        self.assertEqual(row["state"], "pr_merged")
        self.assertFalse(row["undo"]["available"])
        self.assertEqual(row["undo"]["prompt"], "")

    def test_undo_hidden_when_pr_record_not_object(self):
        # 台账里这份记录不是对象：脚本退 E_BAD_RECORD，面板不能先给入口。
        write_draft(self.repo)
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": None})
        row = self.draft(self.collect())
        self.assertTrue(row["prBroken"])
        self.assertFalse(row["undo"]["available"])
        self.assertEqual(row["undo"]["prompt"], "")

    def test_undo_prompt_says_diagnosis_status_is_untouched(self):
        # 撤销只还原沉淀状态；诊断状态要改时去诊断面板「重新打开」，指令里写明边界。
        write_draft(self.repo)
        write_trace(self.repo, "2026-11-01-sediment", state="submitted",
                    case_id="DRAFT-A", status="resolved",
                    inbox_path="postmortems/inbox/2026-10-20-draft-a.case.yaml")
        row = self.draft(self.collect())
        self.assertTrue(row["undo"]["available"])
        self.assertIn("不改诊断状态", row["undo"]["prompt"])
        self.assertNotIn("--keep-status", row["undo"]["prompt"])

    def test_undo_hidden_when_trace_already_promoted(self):
        # 草稿还在 inbox 但 trace 已说升格（draft_left_behind）：该走收尾指令，不是撤销。
        write_draft(self.repo)
        write_trace(self.repo, "2026-11-01-sediment",
                    state="knowledge", case_id="CASE-A",
                    inbox_path="postmortems/inbox/2026-10-20-draft-a.case.yaml")
        row = self.draft(self.collect())
        self.assertEqual(row["state"], "done")
        self.assertFalse(row["undo"]["available"])
        self.assertEqual(row["undo"]["prompt"], "")

    def test_deferred_and_rejected(self):
        write_draft(self.repo, key="draft-defer", cid="DRAFT-D")
        write_assessment(self.repo, "draft-defer", fresh_commit(self.repo), decision="defer")
        write_draft(self.repo, key="draft-reject", cid="DRAFT-R")
        write_assessment(self.repo, "draft-reject", fresh_commit(self.repo), decision="reject")
        payload = self.collect()
        self.assertEqual(self.draft(payload, "draft-defer")["state"], "deferred")
        self.assertEqual(self.draft(payload, "draft-reject")["state"], "rejected")
        self.assertEqual(self.draft(payload, "draft-defer")["next"]["kind"], "none")
        self.assertEqual(payload["counts"]["decided"], 0)

    def test_undo_hidden_when_trace_says_promoted(self):
        # trace 已升格、但知识库里找不到对应 case（missing_case）：撤销会抹掉升格指针，
        # 交给知识库变更流程处理，不给撤销入口。
        write_draft(self.repo)
        write_trace(self.repo, "2026-11-01-sediment",
                    state="knowledge", case_id="VLLM-ASC-99999",
                    inbox_path="postmortems/inbox/2026-10-20-draft-a.case.yaml")
        row = self.draft(self.collect())
        self.assertEqual(row["source"]["mismatch"], "missing_case")
        self.assertFalse(row["undo"]["available"])
        self.assertEqual(row["undo"]["prompt"], "")

    def test_undo_hidden_when_source_ambiguous(self):
        write_draft(self.repo)
        (inbox(self.repo) / "2026-10-20-draft-a.md").write_text(
            "来源：traces/2026-11-01-a.yaml 与 traces/2026-11-02-b.yaml\n", encoding="utf-8")
        write_trace(self.repo, "2026-11-01-a", state="submitted",
                    inbox_path="postmortems/inbox/2026-10-20-draft-a.case.yaml")
        row = self.draft(self.collect())
        self.assertFalse(row["undo"]["available"])
        self.assertEqual(row["undo"]["prompt"], "")

    def test_undo_hidden_when_ledger_unreadable(self):
        write_draft(self.repo)
        path = inbox(self.repo) / ".groom" / "pr-state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        row = self.draft(self.collect())
        self.assertFalse(row["undo"]["available"])
        self.assertEqual(row["undo"]["prompt"], "")

    def test_orphan_sidecar_without_draft(self):
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo))
        draft_path = inbox(self.repo) / "2026-10-20-draft-a.case.yaml"
        draft_path.unlink()
        payload = self.collect()
        self.assertEqual(len(payload["drafts"]), 1)
        row = payload["drafts"][0]
        self.assertEqual(row["state"], "orphan")
        self.assertEqual(row["stage"], "孤儿状态")
        self.assertEqual(row["stageTone"], "bad")
        self.assertEqual(row["path"], "")
        self.assertEqual(row["next"]["kind"], "none")
        self.assertEqual(payload["counts"]["total"], 1)

    def test_title_falls_back_to_postmortem_first_line(self):
        path = write_draft(self.repo)
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["cases"][0].pop("title")
        path.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
        (inbox(self.repo) / "2026-10-20-draft-a.md").write_text(
            "# 从 postmortem 标题取\n正文\n", encoding="utf-8")
        row = self.draft(self.collect())
        self.assertEqual(row["title"], "从 postmortem 标题取")


# ---------------------------------------------------------------- 目标 ref 解析

class TargetResolutionTest(SedimentCase):
    """目标解析不能再默认 origin/main：settings target 与评估记录的 target_ref 都优先。"""

    def _second_remote_ahead(self):
        """origin/main 停在旧的 C0，第二个远端 mirror/main 前进到 C1（带新 knowledge）。"""
        old = fresh_commit(self.repo)
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   "CASE-B", title="新 case")
        new = commit_all(self.repo, "add B")
        git(self.repo, "update-ref", "refs/remotes/mirror/main", new)
        self.assertNotEqual(old, new)
        return old, new

    def test_settings_target_beats_origin_main(self):
        write_draft(self.repo)
        _old, new = self._second_remote_ahead()
        # 旧 sidecar：没有 provenance.target_ref，只能靠配置目标解析。
        write_assessment(self.repo, "2026-10-20-draft-a", new)
        write_ledger(self.repo, target=None)
        write_settings_target(self.repo, "mirror", "main")
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(payload["targetCommit"], new)
        self.assertFalse(row["stale"], row["staleReasons"])
        self.assertEqual(row["state"], "decided")
        self.assertEqual(row["targetState"], "ok")
        self.assertEqual(row["targetRef"], "refs/remotes/mirror/main")
        self.assertEqual(row["targetSource"], "configured")

    def test_assessment_target_ref_beats_stale_origin_main(self):
        # 本 issue 的核心：没有配置目标，评估用的是非 origin 的远端分支。
        write_draft(self.repo)
        old, new = self._second_remote_ahead()
        write_assessment(self.repo, "2026-10-20-draft-a", new,
                         target_ref="refs/remotes/mirror/main")
        write_ledger(self.repo, target=None)
        payload = self.collect()
        row = self.draft(payload)
        # 面板兜底目标仍是落后的 origin/main，但这一行按评估自己的 ref 判新鲜度。
        self.assertEqual(payload["targetCommit"], old)
        self.assertFalse(row["stale"], row["staleReasons"])
        self.assertEqual(row["state"], "decided")
        self.assertEqual(row["targetState"], "ok")
        self.assertEqual(row["targetRef"], "refs/remotes/mirror/main")
        self.assertEqual(row["targetSource"], "assessment")


# ---------------------------------------------------------------- PR 覆盖与 done

class PrStateTest(SedimentCase):
    def setUp(self):
        super().setUp()
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo))

    def _with_pr(self, state: str, url="https://github.com/pillumina/ascend-sleuth/pull/418"):
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(url=url, state=state)})
        return self.collect()

    def test_pr_open(self):
        payload = self._with_pr("open")
        row = self.draft(payload)
        self.assertEqual(row["state"], "pr_open")
        self.assertEqual(row["stage"], "已提 PR · 合入未确认")
        self.assertEqual(row["pr"]["state"], "open")
        self.assertEqual(row["next"]["kind"], "check")
        self.assertIn("pull/418", payload["prompts"]["check"])
        self.assertIn("gh pr view 418 --repo pillumina/ascend-sleuth", payload["prompts"]["checkDetail"])
        self.assertEqual(payload["primary"]["kind"], "check")
        self.assertEqual(payload["counts"]["prOpen"], 1)

    def test_pr_merged(self):
        payload = self._with_pr("merged")
        row = self.draft(payload)
        self.assertEqual(row["state"], "pr_merged")
        self.assertEqual(row["stage"], "已合入 · 待收尾")
        self.assertEqual(row["next"]["kind"], "close")
        self.assertIn("groom_close_draft.py --draft-key 2026-10-20-draft-a --apply", payload["prompts"]["close"])
        self.assertIn("groom_cleanup", payload["prompts"]["close"])
        self.assertIn("groom_close_draft.py --all --apply", payload["prompts"]["closeDetail"])
        self.assertIn("groom_cleanup.py --pr-body-file", payload["prompts"]["closeDetail"])
        self.assertEqual(payload["primary"]["kind"], "close")
        self.assertEqual(payload["counts"]["prMerged"], 1)

    def test_pr_closed(self):
        payload = self._with_pr("closed")
        row = self.draft(payload)
        self.assertEqual(row["state"], "pr_closed")
        self.assertEqual(row["next"]["kind"], "groom")
        self.assertEqual(row["stageTone"], "bad")

    def test_pr_unknown_counts_as_open(self):
        payload = self._with_pr("unknown")
        self.assertEqual(self.draft(payload)["state"], "pr_open")

    def test_done_when_trace_ahead_of_queue(self):
        write_trace(self.repo, "2026-11-01-sediment",
                    state="knowledge", case_id="CASE-A",
                    inbox_path="postmortems/inbox/2026-10-20-draft-a.case.yaml")
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(row["state"], "done")
        self.assertEqual(row["stage"], "已升格")
        self.assertEqual(row["source"]["mismatch"], "draft_left_behind")
        self.assertIn("groom_close_draft.py --draft-key 2026-10-20-draft-a --apply", row["writeback"])
        self.assertEqual(row["next"]["kind"], "none")
        self.assertEqual(row["promotion"]["caseId"], "CASE-A")
        self.assertEqual(row["promotion"]["casePath"],
                         "knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml")
        self.assertEqual(payload["primary"]["kind"], "none")

    def test_missing_case_mismatch(self):
        write_trace(self.repo, "2026-11-01-sediment",
                    state="knowledge", case_id="VLLM-ASC-99999",
                    inbox_path="postmortems/inbox/2026-10-20-draft-a.case.yaml")
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(row["state"], "decided")
        self.assertEqual(row["source"]["mismatch"], "missing_case")
        self.assertEqual(row["writeback"], "")


# ---------------------------------------------------------------- trace 匹配三种键

class TraceMatchTest(SedimentCase):
    def setUp(self):
        super().setUp()
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo))
        write_ledger(self.repo, target=GITHUB_TARGET)

    def test_match_by_inbox_path(self):
        write_trace(self.repo, "sid-path", state="submitted",
                    inbox_path="postmortems/inbox/2026-10-20-draft-a.case.yaml",
                    harness_session="session-origin-1")
        row = self.draft(self.collect())
        self.assertEqual(row["source"]["sessionId"], "sid-path")
        # trace 单号与会话号是两个值：界面显示前者，跳转用后者。
        self.assertEqual(row["source"]["harnessSession"], "session-origin-1")
        self.assertEqual(row["source"]["sedimented"], "submitted")
        self.assertEqual(row["source"]["mismatch"], "none")

    def test_match_by_case_id(self):
        write_trace(self.repo, "sid-case", state="submitted", case_id="DRAFT-A")
        row = self.draft(self.collect())
        self.assertEqual(row["source"]["sessionId"], "sid-case")

    def test_trace_without_harness_key(self):
        # 旧 trace 可能没有这个字段（不是空串，是整行缺失），读侧按空值处理。
        write_trace(self.repo, "sid-old", state="submitted", case_id="DRAFT-A")
        row = self.draft(self.collect())
        self.assertEqual(row["source"]["sessionId"], "sid-old")
        self.assertEqual(row["source"]["harnessSession"], "")

    def test_match_by_source_session(self):
        write_draft(self.repo, key="draft-src", cid="DRAFT-S", source_session="sid-src")
        write_assessment(self.repo, "draft-src", fresh_commit(self.repo))
        write_trace(self.repo, "sid-src", state="submitted")
        row = self.draft(self.collect(), "draft-src")
        self.assertEqual(row["source"]["sessionId"], "sid-src")
        self.assertEqual(row["decision"], "new_pattern")

    def test_no_trace_gives_empty_session(self):
        row = self.draft(self.collect())
        self.assertEqual(row["source"]["sessionId"], "")
        self.assertEqual(row["source"]["harnessSession"], "")
        self.assertEqual(row["source"]["mismatch"], "none")
        self.assertEqual(row["source"]["sedimented"], "none")


# ---------------------------------------------------------------- 计数 / 历史 / --only / 无适配器

class AggregateTest(SedimentCase):
    def test_counts_and_oldest_days(self):
        write_draft(self.repo, key="old", cid="D-OLD", created_at=self.age_iso(20))
        write_draft(self.repo, key="new", cid="D-NEW", created_at=self.age_iso(1))
        payload = self.collect()
        self.assertEqual(payload["counts"]["total"], 2)
        self.assertEqual(payload["counts"]["overdue"], 1)
        self.assertEqual(payload["counts"]["oldestDays"], 20)

    def test_batch_prompt_is_not_copied_per_row(self):
        """批次指令只在顶层 prompts 与 primary 各出一份，不随行数复制。

        待提 PR 的批次指令本身是逐条列表；复制进每一行会让 payload 随条目数平方增长。
        """
        for index in range(3):
            key = f"draft-{index}"
            write_draft(self.repo, key=key, cid=f"D-{index}")
            write_assessment(self.repo, key, fresh_commit(self.repo),
                             decision="new_pattern")
        write_ledger(self.repo, target=GITHUB_TARGET)
        payload = self.collect()
        self.assertEqual(payload["counts"]["decided"], 3)
        for row in payload["drafts"]:
            self.assertNotIn("prompt", row["next"])
        prompt = json.dumps(payload["prompts"]["pr"], ensure_ascii=False)[1:-1]
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(blob.count(prompt), 2)

    def test_kb_advance_keeps_submitted_prs_in_queue(self):
        """知识库前进后，已提交 PR 的行仍留在「待合入」，过期只做行内提示。

        对应反馈：已提交的 PR 在拉取新代码后全部变成「需重跑」，待合入计数归零；
        撤销数仍对——它按 PR 台账算，与评估新鲜度无关。
        """
        assessed = fresh_commit(self.repo)
        prs = {}
        for index in range(2):
            key = f"draft-pr-{index}"
            write_draft(self.repo, key=key, cid=f"D-PR-{index}")
            write_assessment(self.repo, key, assessed)
            prs[key] = pr_entry(number=430 + index)
        write_draft(self.repo, key="draft-local", cid="D-LOCAL")
        write_assessment(self.repo, "draft-local", assessed)
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   "CASE-B", title="新 case")
        git(self.repo, "update-ref", "refs/remotes/origin/main",
            commit_all(self.repo, "add B"))
        write_ledger(self.repo, target=GITHUB_TARGET, prs=prs)

        payload = self.collect()
        self.assertEqual(payload["counts"]["prOpen"], 2)
        self.assertEqual(payload["counts"]["needRerun"], 1)
        self.assertIn("pr_status.py", payload["prompts"]["check"])
        by_key = {row["key"]: row for row in payload["drafts"]}
        for key in prs:
            self.assertEqual(by_key[key]["state"], "pr_open")
            self.assertTrue(by_key[key]["stale"])
            self.assertFalse(by_key[key]["undo"]["available"])
        self.assertEqual(by_key["draft-local"]["state"], "need_rerun")
        self.assertTrue(by_key["draft-local"]["undo"]["available"])

    def test_history_reads_last_five_close_log_lines(self):
        log = inbox(self.repo) / ".groom" / "close-log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for index in range(7):
            lines.append(json.dumps({
                "at": f"2026-10-{index + 1:02d}T10:00:00+08:00", "draft": f"draft-{index}",
                "decision": "new_pattern", "state": "knowledge"}, ensure_ascii=False))
        lines.insert(4, "{broken")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        payload = self.collect()
        self.assertEqual(len(payload["history"]), 4)     # 最后 5 行里有一行坏件
        self.assertEqual(payload["history"][0]["key"], "draft-3")
        self.assertEqual(payload["history"][0]["title"], "")
        self.assertEqual(payload["history"][0]["state"], "knowledge")

    def test_only_filters_by_source_session(self):
        write_draft(self.repo, key="draft-a", cid="D-A")
        write_draft(self.repo, key="draft-b", cid="D-B")
        write_assessment(self.repo, "draft-a", fresh_commit(self.repo))
        write_assessment(self.repo, "draft-b", fresh_commit(self.repo))
        write_ledger(self.repo, target=GITHUB_TARGET)
        write_trace(self.repo, "sid-a", state="submitted",
                    inbox_path="postmortems/inbox/draft-a.case.yaml")
        write_trace(self.repo, "sid-b", state="submitted",
                    inbox_path="postmortems/inbox/draft-b.case.yaml")
        payload = self.collect(only="sid-a")
        self.assertEqual([row["key"] for row in payload["drafts"]], ["draft-a"])
        self.assertEqual(payload["counts"]["total"], 1)
        self.assertEqual(payload["prompts"]["check"], "")

    def test_target_without_adapter_prompts_manual_pr(self):
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo))
        target = {"remote": "mirror", "base": "main", "platform": "",
                  "url": "https://example.com/o/r.git", "note": "", "labels": {},
                  "source": "user", "chosen_at": "2026-11-01T10:00:00+08:00"}
        write_ledger(self.repo, target=target)
        payload = self.collect()
        self.assertIn("无适配器", payload["prompts"]["pr"])
        self.assertIn("本机没有对应平台的适配器", payload["prompts"]["prDetail"])
        self.assertEqual(payload["target"]["platformName"], "")


# ---------------------------------------------------------------- CLI 协议

class CliTest(SedimentCase):
    def test_cli_json_ok(self):
        write_draft(self.repo)
        proc = run_py(self.repo, str(Path(ss.__file__)), "--root", str(self.repo), "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["counts"]["total"], 1)
        self.assertIn("groomDetail", payload["prompts"])

    def test_cli_git_failure_is_ok_false_and_exit_zero(self):
        empty = self.base / "not-a-repo"
        empty.mkdir()
        proc = run_py(self.repo, str(Path(ss.__file__)), "--root", str(empty), "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["code"], "E_GIT")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- 已出队草稿与台账兜底

def write_done_draft(repo: Path, key: str = "2026-10-20-draft-a", cid: str = "DRAFT-A",
                     title: str = "已出队的草稿", directory: bool = False) -> Path:
    base = inbox(repo) / ".done" / key
    if directory:
        path = base / "case.yaml"
        postmortem = base / "postmortem.md"
    else:
        path = base / f"{key}.case.yaml"
        postmortem = base / f"{key}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CASE_TMPL.format(cid=cid, title=title, source=""), encoding="utf-8")
    postmortem.write_text(f"# {title}\n正文\n", encoding="utf-8")
    return path


def append_close_log(repo: Path, key: str = "2026-10-20-draft-a",
                     decision: str = "new_pattern", state: str = "knowledge",
                     status: str = "closed", at: str = "2026-11-04T17:20:16+08:00") -> None:
    path = inbox(repo) / ".groom" / "close-log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": at, "draft": key, "decision": decision, "state": state,
             "status": status, "case_id": "DRAFT-A", "session": "sid-closed",
             "moved": [str(inbox(repo) / ".done" / key)], "trace": "written", "reason": None}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


class ClosedDraftQueueTest(SedimentCase):
    """groom 之后草稿已经出队，队列仍要跟到 PR 结束。"""

    def test_closed_draft_with_open_pr_stays_in_queue(self):
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo))
        # 模拟 close_draft：草稿移进 .done，评估状态文件还在（cleanup 之前）
        (inbox(self.repo) / "2026-10-20-draft-a.case.yaml").unlink()
        write_done_draft(self.repo, title="已出队的草稿")
        append_close_log(self.repo)
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="open")})
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(row["state"], "pr_open")
        self.assertEqual(row["stage"], "已提 PR · 合入未确认")
        self.assertTrue(row["closedDraft"])
        self.assertEqual(row["path"], "")
        self.assertIn("已出队的草稿", row["title"])
        self.assertEqual(row["decision"], "new_pattern")
        self.assertEqual(row["next"]["kind"], "check")
        self.assertEqual(payload["counts"]["total"], 1)
        self.assertEqual(payload["counts"]["prOpen"], 1)
        self.assertEqual(payload["primary"]["kind"], "check")
        self.assertEqual(payload["history"], [])

    def test_cleanup_deleted_sidecar_still_renders_row(self):
        # 本次现场：评估状态文件被 cleanup 删掉，只剩 close-log 与台账
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="open")})
        write_done_draft(self.repo)
        append_close_log(self.repo)
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(row["state"], "pr_open")
        self.assertTrue(row["closedDraft"])
        self.assertTrue(row["assessed"])
        self.assertEqual(row["decision"], "new_pattern")
        self.assertIn("已出队的草稿", row["title"])

    def test_history_joins_pr_link(self):
        write_done_draft(self.repo)
        append_close_log(self.repo)
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="merged", number=420)})
        payload = self.collect()
        self.assertEqual(payload["drafts"], [])
        self.assertEqual(len(payload["history"]), 1)
        item = payload["history"][0]
        self.assertEqual(item["key"], "2026-10-20-draft-a")
        self.assertIn("已出队的草稿", item["title"])
        self.assertEqual(item["pr"]["number"], 420)
        self.assertEqual(item["pr"]["state"], "merged")

    def test_closed_pr_offers_restore(self):
        write_done_draft(self.repo)
        append_close_log(self.repo)
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="closed")})
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(row["state"], "pr_closed")
        self.assertEqual(row["next"]["kind"], "restore")
        self.assertEqual(row["next"]["label"], "恢复草稿")
        # 单行动作指令（恢复命令）逐行不同，放在行的 restore 字段里。
        self.assertIn("mv ", row["restore"])
        self.assertIn(".done", row["restore"])
        self.assertFalse(row["undo"]["available"])

    def test_pending_pr_does_not_report_trace_mismatch(self):
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/DRAFT-A.yaml",
                   "DRAFT-A", title="草稿已升格")
        write_done_draft(self.repo)
        append_close_log(self.repo)
        write_trace(self.repo, "sid-closed", state="submitted", case_id="DRAFT-A")
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="open")})
        row = self.draft(self.collect())
        self.assertEqual(row["state"], "pr_open")
        self.assertEqual(row["source"]["mismatch"], "none")

    def test_ledger_only_open_pr_gets_row(self):
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"gone-draft": pr_entry(state="open", number=419)})
        payload = self.collect()
        row = self.draft(payload, "gone-draft")
        self.assertEqual(row["state"], "pr_open")
        self.assertTrue(row["closedDraft"])
        self.assertFalse(row["assessed"])
        self.assertEqual(row["next"]["kind"], "check")
        self.assertEqual(payload["counts"]["prOpen"], 1)

    def test_ledger_only_terminal_is_not_queued(self):
        # 没有草稿、没有 close-log 的终态 PR 没有本地动作可做；平台是唯一事实来源。
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"gone-draft": pr_entry(state="merged", number=419)})
        payload = self.collect()
        self.assertEqual(payload["drafts"], [])
        self.assertEqual(payload["counts"]["total"], 0)
        self.assertEqual(payload["history"], [])

    def test_non_http_pr_url_is_dropped(self):
        write_done_draft(self.repo)
        append_close_log(self.repo)
        entry = pr_entry(state="open")
        entry["url"] = "javascript:alert(1)"
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": entry})
        row = self.draft(self.collect())
        self.assertEqual(row["pr"]["url"], "")

    def test_bad_ledger_file_keeps_dequeued_row(self):
        write_done_draft(self.repo)
        append_close_log(self.repo)
        path = inbox(self.repo) / ".groom" / "pr-state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        payload = self.collect()
        self.assertEqual(len(payload["drafts"]), 1, payload["drafts"])
        row = self.draft(payload)
        self.assertEqual(row["state"], "pr_open")
        self.assertEqual(row["pr"]["state"], "unknown")
        self.assertTrue(payload["ledgerError"])

    def test_bad_ledger_entry_does_not_break_collect(self):
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo))
        (inbox(self.repo) / "2026-10-20-draft-a.case.yaml").unlink()
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": "broken"})
        payload = self.collect()
        self.assertEqual(len(payload["drafts"]), 1)
        self.assertEqual(payload["drafts"][0]["state"], "orphan")

    def test_orphan_with_ledger_pr_is_single_row(self):
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo))
        (inbox(self.repo) / "2026-10-20-draft-a.case.yaml").unlink()
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="open")})
        payload = self.collect()
        self.assertEqual(len(payload["drafts"]), 1, payload["drafts"])
        self.assertEqual(payload["drafts"][0]["key"], "2026-10-20-draft-a")
        self.assertEqual(payload["drafts"][0]["state"], "pr_open")
        self.assertEqual(payload["counts"]["total"], 1)

    def test_orphan_with_merged_ledger_pr_is_single_row(self):
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo))
        (inbox(self.repo) / "2026-10-20-draft-a.case.yaml").unlink()
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="merged")})
        payload = self.collect()
        self.assertEqual(len(payload["drafts"]), 1, payload["drafts"])
        self.assertEqual(payload["drafts"][0]["state"], "pr_merged")

    def test_done_directory_layout_renders_row(self):
        write_done_draft(self.repo, directory=True)
        append_close_log(self.repo)
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="open")})
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(row["state"], "pr_open")
        self.assertTrue(row["closedDraft"])
        self.assertIn("已出队的草稿", row["title"])

    def test_stale_keeps_open_pr_in_queue(self):
        # 过期不改 PR 阶段：PR 已经开着，重跑 groom 改不了它；队列先把事项跟到合入或关闭，
        # 过期留成行内提示，查合入入口照常给。
        write_draft(self.repo)
        old_commit = fresh_commit(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", old_commit)
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   "CASE-B", title="新 case")
        new_commit = commit_all(self.repo, "add B")
        git(self.repo, "update-ref", "refs/remotes/origin/main", new_commit)
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="open")})
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(row["state"], "pr_open")
        self.assertEqual(row["stage"], "已提 PR · 合入未确认")
        self.assertEqual(row["next"]["kind"], "check")
        self.assertTrue(row["stale"])
        self.assertTrue(any("知识库" in reason for reason in row["staleReasons"]),
                        row["staleReasons"])
        self.assertIsNotNone(row["pr"])
        self.assertEqual(payload["counts"]["prOpen"], 1)
        self.assertEqual(payload["counts"]["needRerun"], 0)
        self.assertIn("pr_status.py", payload["prompts"]["check"])
        self.assertEqual(payload["prompts"]["groom"], "")

    def test_stale_approval_still_needs_reconfirmation(self):
        # 只失批准、不涉知识变化：授权不成立，要人重新确认批准，PR 开着也先回 groom；
        # PR 记录仍留在详情里。这与「知识过期」不是同一件事。
        write_draft(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", fresh_commit(self.repo),
                         human_valid=False)
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="open")})
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(row["state"], "need_rerun")
        self.assertEqual(row["next"]["kind"], "groom")
        self.assertEqual(payload["counts"]["needRerun"], 1)
        self.assertEqual(payload["counts"]["prOpen"], 0)
        self.assertIn("--decision-prompt", payload["prompts"]["groomDetail"])
        self.assertTrue(row["stale"])
        self.assertIn("人的批准", " ".join(row["staleReasons"]))
        self.assertIsNotNone(row["pr"])

    def test_approval_plus_kb_advance_still_needs_reconfirmation(self):
        # 知识过期与批准失效同时发生：两条都要重跑 groom（含重新确认批准），仍判 need_rerun。
        write_draft(self.repo)
        old_commit = fresh_commit(self.repo)
        write_assessment(self.repo, "2026-10-20-draft-a", old_commit, human_valid=False)
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                   "CASE-B", title="新 case")
        git(self.repo, "update-ref", "refs/remotes/origin/main",
            commit_all(self.repo, "add B"))
        write_ledger(self.repo, target=GITHUB_TARGET,
                     prs={"2026-10-20-draft-a": pr_entry(state="open")})
        payload = self.collect()
        row = self.draft(payload)
        self.assertEqual(row["state"], "need_rerun")
        reasons = " ".join(row["staleReasons"])
        self.assertIn("知识库", reasons)
        self.assertIn("人的批准", reasons)
        self.assertIsNotNone(row["pr"])

    def test_pr_states_survive_stale(self):
        # 台账里的 PR 状态决定阶段：open/unknown → 待合入，merged → 收尾，closed → 恢复草稿。
        # 评估过期只做行内提示，不改阶段。
        for pr_state, expected in (("open", "pr_open"), ("unknown", "pr_open"),
                                   ("merged", "pr_merged"), ("closed", "pr_closed")):
            with self.subTest(pr_state=pr_state):
                self.setUp()
                write_draft(self.repo)
                old_commit = fresh_commit(self.repo)
                write_assessment(self.repo, "2026-10-20-draft-a", old_commit)
                write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-B.yaml",
                           "CASE-B", title="新 case")
                git(self.repo, "update-ref", "refs/remotes/origin/main",
                    commit_all(self.repo, "add B"))
                write_ledger(self.repo, target=GITHUB_TARGET,
                             prs={"2026-10-20-draft-a": pr_entry(state=pr_state)})
                row = self.draft(self.collect())
                self.assertEqual(row["state"], expected)
                self.assertTrue(row["stale"])
                self.assertIn("知识库", " ".join(row["staleReasons"]))
