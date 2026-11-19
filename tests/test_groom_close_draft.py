"""终态决定的收尾：trace 沉淀状态回写、草稿出队与证据前置。

护四件事，都是「漏了不报错、只让数据慢慢失真」的那一类：
1. covered → `archived` + 覆盖它的 case id，草稿移进 `inbox/.done/`；
2. 证据不成立就不写状态：covered 没有已转正的 postmortem 时拦下，trace 与队列都不动；
3. new_pattern 升格改过 id 时用 `--case-id` 指定，回写 `knowledge` + 新 id；
4. defer 不是终态：不动 trace、不出队，退出码仍是 0。
"""

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
from groom_common import assessment_path  # noqa: E402
from groom_close_draft import promoted_postmortem  # noqa: E402
import pr_status  # noqa: E402

TRACE_TMPL = """session_id: "{sid}"
status: resolved
summary: "HCCL 超时，链路恢复后自愈"
severity: service-affecting
fix_emitted: true
updated_at: "2026-10-30T09:00:00+08:00"
sedimented:
  state: submitted
  case_id: ""
  inbox_path: "postmortems/inbox/{key}.case.yaml"
trace:
  - {{step: 1, role: user, content: "贴了栈"}}
"""


class CloseDraftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-close-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base / "repo")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-A.yaml",
                   cid="CASE-A", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="link failure", fix="restore link", tags=("hccl",))
        make_index(self.repo)
        self.meta = write_json(self.base / "meta.json", snapshot_meta(self.repo))
        self.inbox = self.repo / "postmortems" / "inbox"
        self.sid = "2026-10-01-close-draft"
        (self.repo / "traces").mkdir(parents=True, exist_ok=True)

    # ── 夹具 ──────────────────────────────────────────────────────────────
    def make_draft(self, key="draft-a", sid=None):
        draft = write_draft(self.repo, key=key, cid="DRAFT-A",
                            title="HCCL timeout", symptoms=("HCCL timeout",),
                            root_cause="link failure", fix="restore link", tags=("hccl",))
        # 头注释是 to-postmortem 记来源 trace 的写法
        header = f"# 来源: traces/{sid or self.sid}.yaml\n"
        draft.write_text(header + draft.read_text(encoding="utf-8"), encoding="utf-8")
        if sid is None:
            (self.repo / "traces" / f"{self.sid}.yaml").write_text(
                TRACE_TMPL.format(sid=self.sid, key=key), encoding="utf-8")
        return key

    def assess(self, key, classification, candidate=None):
        work = self.base / f"work-{key}.json"
        p = run_py(self.repo, "scripts/groom_candidates.py", "--snapshot", str(self.meta),
                   "--draft", str(self.inbox / f"{key}.case.yaml"), "--out", str(work), "--top", "4")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        order = json.loads(work.read_text(encoding="utf-8"))["orders"][0]
        same = classification in ("covered", "duplicate")
        comparisons = [{
            "candidate_case": c["id"], "classification": classification, "confidence": "high",
            "evidence": {"root_cause": "same" if same else "different",
                         "mechanism": "same" if same else "different",
                         "fix": "same" if same else "different"},
            "rationale": "同一根因与失效机制" if same else "根因不同",
            "review_required": False,
        } for c in order["candidates"]]
        results = self.base / f"results-{key}"
        results.mkdir(exist_ok=True)
        write_json(results / f"{key}.result.json", {
            "draft_key": key, "agent": {"id": "fake-comparator"}, "comparisons": comparisons,
            "work_order_id": order["work_order_id"],
            "snapshot_commit": order["snapshot"]["commit"],
            "draft_sha256": order["draft"]["case_sha256"],
            "candidate_ids": [c["id"] for c in order["candidates"]],
        })
        p = run_py(self.repo, "scripts/groom_record.py", "--snapshot", str(self.meta),
                   "--work-orders", str(work), "--results-dir", str(results))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return order

    def decide(self, key, decision, candidate=None):
        cmd = ["scripts/groom_decide.py", "--snapshot", str(self.meta), "--draft-key", key,
               "--decision", decision, "--by", "owner-a", "--note", "test"]
        if candidate:
            cmd += ["--candidate", candidate]
        p = run_py(self.repo, *cmd)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def close(self, *args):
        # 这些用例是本地沉淀部署：台账没有 PR，按新语义要显式 --no-pr。
        return run_py(self.repo, "scripts/groom_close_draft.py", "--no-pr", *args)

    def trace_doc(self, sid=None):
        return yaml.safe_load((self.repo / "traces" / f"{sid or self.sid}.yaml")
                              .read_text(encoding="utf-8"))

    # ── 用例 ──────────────────────────────────────────────────────────────
    def test_covered_writes_archived_and_moves_draft(self):
        key = self.make_draft()
        self.assess(key, "covered", candidate="CASE-A")
        self.decide(key, "covered", candidate="CASE-A")
        # postmortem 转正到季度目录（covered 唯一落盘的知识）
        (self.repo / "postmortems" / "2026-Q3").mkdir(parents=True, exist_ok=True)
        (self.repo / "postmortems" / "2026-Q3" / f"{key}.md").write_text("# 案例\n", encoding="utf-8")

        p = self.close("--draft-key", key, "--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = self.trace_doc()
        self.assertEqual(doc["sedimented"]["state"], "archived")
        self.assertEqual(doc["sedimented"]["case_id"], "CASE-A")
        self.assertFalse((self.inbox / f"{key}.case.yaml").exists())
        self.assertTrue((self.inbox / ".done" / key).is_dir())
        log = (self.inbox / ".groom" / "close-log.jsonl").read_text(encoding="utf-8").strip()
        self.assertEqual(json.loads(log.splitlines()[-1])["state"], "archived")

    def test_covered_blocked_without_promoted_postmortem(self):
        key = self.make_draft()
        self.assess(key, "covered", candidate="CASE-A")
        self.decide(key, "covered", candidate="CASE-A")

        p = self.close("--draft-key", key, "--apply")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(self.trace_doc()["sedimented"]["state"], "submitted")
        self.assertTrue((self.inbox / f"{key}.case.yaml").exists())

    def test_new_pattern_uses_case_id_override(self):
        key = self.make_draft()
        self.assess(key, "new_pattern")
        self.decide(key, "new_pattern")
        # 升格时把建议 id 改成了 CASE-NEW
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/CASE-NEW.yaml",
                   cid="CASE-NEW", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="link failure", fix="restore link", tags=("hccl",))

        p = self.close("--draft-key", key, "--case-id", "CASE-NEW", "--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        doc = self.trace_doc()
        self.assertEqual(doc["sedimented"]["state"], "knowledge")
        self.assertEqual(doc["sedimented"]["case_id"], "CASE-NEW")
        self.assertFalse((self.inbox / f"{key}.case.yaml").exists())

    def test_defer_is_ignored(self):
        key = self.make_draft()
        self.assess(key, "new_pattern")
        self.decide(key, "defer")

        p = self.close("--draft-key", key, "--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.trace_doc()["sedimented"]["state"], "submitted")
        self.assertTrue((self.inbox / f"{key}.case.yaml").exists())


    def test_ambiguous_source_session_blocks_close(self):
        key = self.make_draft()
        self.assess(key, "new_pattern")
        self.decide(key, "new_pattern")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/DRAFT-A.yaml",
                   cid="DRAFT-A", title="HCCL timeout")
        # 头注释有两个不同来源：既不回写也不出队（出队等于放弃状态回写）
        path = self.inbox / f"{key}.case.yaml"
        path.write_text(path.read_text(encoding="utf-8")
                        + "# 来源: traces/2026-10-02-another.yaml\n", encoding="utf-8")

        p = self.close("--draft-key", key, "--apply")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("多个", p.stdout)
        self.assertEqual(self.trace_doc()["sedimented"]["state"], "submitted")
        self.assertTrue(path.exists())

    def test_approval_stale_blocks_close(self):
        key = self.make_draft()
        self.assess(key, "new_pattern")
        self.decide(key, "new_pattern")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/DRAFT-A.yaml",
                   cid="DRAFT-A", title="HCCL timeout")
        sidecar = assessment_path(self.inbox, key)
        doc = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
        doc["human_decision_valid"] = False
        sidecar.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

        p = self.close("--draft-key", key, "--apply")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("approval-stale", p.stdout)
        self.assertEqual(self.trace_doc()["sedimented"]["state"], "submitted")
        self.assertTrue((self.inbox / f"{key}.case.yaml").exists())

    def test_gate_blocked_blocks_close(self):
        key = self.make_draft()
        self.assess(key, "new_pattern")
        self.decide(key, "new_pattern")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/DRAFT-A.yaml",
                   cid="DRAFT-A", title="HCCL timeout")
        sidecar = assessment_path(self.inbox, key)
        doc = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
        doc["promotion_gate"] = {"allowed": False, "blocked_reason": "stale-snapshot"}
        sidecar.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

        p = self.close("--draft-key", key, "--apply")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("stale-snapshot", p.stdout)
        self.assertEqual(self.trace_doc()["sedimented"]["state"], "submitted")
        self.assertTrue((self.inbox / f"{key}.case.yaml").exists())

    def test_promoted_postmortem_override(self):
        promoted = self.repo / "postmortems" / "2026-Q3" / "CASE-DIR.md"
        promoted.parent.mkdir(parents=True, exist_ok=True)
        promoted.write_text("# 案例\n", encoding="utf-8")
        self.assertEqual(promoted_postmortem(self.repo, "draft-dir", str(promoted)), promoted)
        self.assertIsNone(promoted_postmortem(self.repo, "draft-dir", str(self.inbox / "missing.md")))

    def test_open_pr_blocks_close(self):
        key = self.make_draft()
        self.assess(key, "new_pattern")
        self.decide(key, "new_pattern")
        ledger = pr_status.empty_ledger()
        ledger["prs"][key] = {"platform": "github", "repo": "owner/repo", "number": 7,
                              "url": "https://github.com/owner/repo/pull/7", "state": "open",
                              "source": "ledger", "created_at": "2026-11-04T10:00:00+08:00"}
        pr_status.save_ledger(self.repo, ledger)

        p = self.close("--draft-key", key, "--apply")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("PR 还没合入", p.stdout)
        self.assertTrue((self.inbox / f"{key}.case.yaml").exists())
        self.assertEqual(self.trace_doc()["sedimented"]["state"], "submitted")

        p = self.close("--draft-key", key, "--apply", "--json")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        payload = json.loads(p.stdout)
        self.assertEqual(payload["results"][0]["status"], "error")

    def test_closed_pr_blocks_close(self):
        key = self.make_draft()
        self.assess(key, "new_pattern")
        self.decide(key, "new_pattern")
        ledger = pr_status.empty_ledger()
        ledger["prs"][key] = {"platform": "github", "repo": "owner/repo", "number": 7,
                              "url": "https://github.com/owner/repo/pull/7", "state": "closed",
                              "source": "platform", "created_at": "2026-11-04T10:00:00+08:00"}
        pr_status.save_ledger(self.repo, ledger)

        p = self.close("--draft-key", key, "--apply")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("PR 已关闭、没有合入", p.stdout)
        self.assertTrue((self.inbox / f"{key}.case.yaml").exists())

    def test_bad_ledger_entry_blocks_close(self):
        key = self.make_draft()
        self.assess(key, "new_pattern")
        self.decide(key, "new_pattern")
        ledger = pr_status.empty_ledger()
        ledger["prs"][key] = "broken"
        pr_status.save_ledger(self.repo, ledger)

        p = self.close("--draft-key", key, "--apply")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("PR 还没合入（unknown）", p.stdout)
        self.assertTrue((self.inbox / f"{key}.case.yaml").exists())

    def test_allow_open_pr_is_rejected(self):
        """旧旁路已废弃：合入前不收尾，参数保留但报错。"""
        key = self.make_draft()
        self.assess(key, "new_pattern")
        self.decide(key, "new_pattern")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/DRAFT-A.yaml",
                   cid="DRAFT-A", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="link failure", fix="restore link", tags=("hccl",))
        ledger = pr_status.empty_ledger()
        ledger["prs"][key] = {"platform": "github", "repo": "owner/repo", "number": 7,
                              "url": "https://github.com/owner/repo/pull/7", "state": "open",
                              "source": "ledger", "created_at": "2026-11-04T10:00:00+08:00"}
        pr_status.save_ledger(self.repo, ledger)

        p = self.close("--draft-key", key, "--apply", "--allow-open-pr")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("--allow-open-pr 已不支持", p.stderr)
        self.assertTrue((self.inbox / f"{key}.case.yaml").exists())
        self.assertEqual(self.trace_doc()["sedimented"]["state"], "submitted")

    def test_mixed_closed_and_active_keys_continue(self):
        key = self.make_draft("draft-a")
        self.assess(key, "new_pattern")
        self.decide(key, "new_pattern")
        write_case(self.repo, "knowledge/inference/vllm-ascend/interrupt/DRAFT-A.yaml",
                   cid="DRAFT-A", title="HCCL timeout", symptoms=("HCCL timeout",),
                   root_cause="link failure", fix="restore link", tags=("hccl",))
        (self.inbox / ".done" / "draft-b").mkdir(parents=True)

        p = self.close("--draft-key", "draft-b", "--draft-key", key, "--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("draft-b: 已出队", p.stdout)
        self.assertFalse((self.inbox / f"{key}.case.yaml").exists())

    def test_json_on_empty_inbox(self):
        self.inbox.mkdir(parents=True, exist_ok=True)
        p = self.close("--all", "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        payload = json.loads(p.stdout)
        self.assertEqual(payload["results"], [])


if __name__ == "__main__":
    unittest.main()
