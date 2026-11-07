"""sediment_undo 的边界回归。

护的是「撤销一次沉淀」这条写路径：草稿出队、评估状态文件删除、来源 trace 回写，三处都做过
才叫撤干净；只做一半不会报错，只会留下「trace 说已交草稿、inbox 里没有」或「草稿没了、
评估状态文件还挂着」的不一致状态。另外两条边界也必须拦住：台账里已有 PR 的草稿不能撤，
痕迹（评估 id、人决定、草稿去向）必须留在 undo-log 里。

做法：真实临时 git 仓库 + 真实共享 inbox（`groom_common.shared_inbox` 解析到该仓库），
走脚本 CLI，不 mock 判据。不联网。
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from groom_common import sanitize_key  # noqa: E402
from tests.groom_fixtures import git, init_repo, run_py  # noqa: E402
import pr_status  # noqa: E402
import sediment_undo as su  # noqa: E402

CASE = """cases:
  - id: {cid}
    title: "{title}"
    category: interrupt
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


def write_flat_draft(repo: Path, key: str, cid: str = "DRAFT-A",
                     source_session: str = "") -> Path:
    inbox = repo / "postmortems" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    source = f'    source_session: "{source_session}"\n' if source_session else ""
    path = inbox / f"{key}.case.yaml"
    path.write_text(CASE.format(cid=cid, title="误沉淀的草稿") + source, encoding="utf-8")
    (inbox / f"{key}.md").write_text(f"# {cid}\n\n来源：诊断记录。\n", encoding="utf-8")
    return path


def write_directory_draft(repo: Path, key: str, cid: str = "DRAFT-B") -> Path:
    base = repo / "postmortems" / "inbox" / key
    base.mkdir(parents=True, exist_ok=True)
    (base / "case.yaml").write_text(CASE.format(cid=cid, title="目录形态草稿"), encoding="utf-8")
    (base / "postmortem.md").write_text("# 目录形态草稿\n", encoding="utf-8")
    return base


def write_sidecar(repo: Path, key: str, decision: str = "new_pattern",
                  assessment_id: str = "assess-1") -> Path:
    path = repo / "postmortems" / "inbox" / ".groom" / "assessments" / f"{sanitize_key(key)}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"assessment_id: {assessment_id}\n"
        "assessment:\n"
        "  proposed_novelty: new_pattern\n"
        "human_decision:\n"
        f"  decision: {decision}\n"
        "  by: 张工\n"
        '  decided_at: "2026-11-03T09:00:00+08:00"\n',
        encoding="utf-8",
    )
    return path


def write_trace(repo: Path, sid: str, state: str = "submitted",
                case_id: str = "DRAFT-A", status: str = "resolved") -> Path:
    path = repo / "traces" / f"{sid}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'session_id: "{sid}"\n'
        f'status: {status}\n'
        'updated_at: "2026-11-01T10:00:00+08:00"\n'
        "sedimented:\n"
        f"  state: {state}\n"
        f'  case_id: "{case_id}"\n'
        '  inbox_path: "postmortems/inbox/draft-a.case.yaml"\n'
        "trace:\n"
        '  - {role: user, step: 1, content: "测试"}\n',
        encoding="utf-8",
    )
    return path


def load_yaml(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class SedimentUndoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sediment-undo-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = init_repo(self.base / "repo")
        self.inbox = self.repo / "postmortems" / "inbox"

    def run_undo(self, *args):
        proc = run_py(str(self.repo), "scripts/sediment_undo.py", *args)
        payload = None
        out = (proc.stdout or "").strip()
        if out.startswith("{"):
            try:
                payload = json.loads(out)
            except ValueError:
                payload = None
        return proc, payload

    def test_plan_does_not_write(self):
        key = "draft-a"
        write_flat_draft(self.repo, key, source_session="2026-11-01-demo")
        sidecar = write_sidecar(self.repo, key)
        trace = write_trace(self.repo, "2026-11-01-demo")
        before = trace.read_bytes()

        proc, payload = self.run_undo("--draft-key", key, "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(payload and payload.get("dryRun") is True, proc.stdout)
        self.assertIn("undoneTo", payload)
        self.assertTrue((self.inbox / f"{key}.case.yaml").is_file())
        self.assertTrue(sidecar.is_file())
        self.assertEqual(trace.read_bytes(), before)
        self.assertFalse((self.inbox / ".undone").exists())

    def test_apply_moves_draft_clears_assessment_and_trace(self):
        key = "draft-a"
        draft = write_flat_draft(self.repo, key, source_session="2026-11-01-demo")
        md = self.inbox / f"{key}.md"
        sidecar = write_sidecar(self.repo, key)
        trace = write_trace(self.repo, "2026-11-01-demo")

        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json", "--note", "重复草稿")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(payload and payload.get("ok") is True, proc.stdout)
        self.assertFalse(draft.exists())
        self.assertFalse(md.exists())
        self.assertFalse(sidecar.exists())

        moved = list((self.inbox / ".undone").iterdir())
        self.assertEqual(len(moved), 1)
        self.assertTrue((moved[0] / f"{key}.case.yaml").is_file())
        self.assertTrue((moved[0] / f"{key}.md").is_file())
        self.assertTrue((moved[0] / ".undo.json").is_file())

        doc = load_yaml(trace)
        self.assertEqual(doc["sedimented"]["state"], "none")
        self.assertEqual(doc["sedimented"]["case_id"], "")
        self.assertEqual(doc["sedimented"]["inbox_path"], "")

        log = (self.inbox / ".groom" / "undo-log.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(log), 1)
        entry = json.loads(log[0])
        self.assertEqual(entry["draft"], key)
        self.assertEqual(entry["trace"]["written"], True)
        self.assertEqual(entry["assessment"]["human_decision"], "new_pattern")
        self.assertEqual(entry["assessment"]["human_decision_by"], "张工")
        self.assertTrue(entry["assessment"]["path"].endswith(
            "postmortems/inbox/.groom/assessments/" + sanitize_key(key) + ".yaml"),
            entry["assessment"]["path"])
        self.assertEqual(entry["note"], "重复草稿")

    def test_refuses_when_pr_exists(self):
        key = "draft-a"
        draft = write_flat_draft(self.repo, key, source_session="2026-11-01-demo")
        ledger = pr_status.empty_ledger()
        ledger["prs"][key] = {
            "platform": "github", "repo": "pillumina/ascend-sleuth", "number": 418,
            "url": "https://github.com/pillumina/ascend-sleuth/pull/418",
            "state": "open", "source": "platform",
            "created_at": "2026-11-01T10:00:00+08:00",
        }
        pr_status.save_ledger(self.repo, ledger)

        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(payload.get("code"), "E_PR_EXISTS", proc.stdout)
        self.assertIn("open", payload.get("message", ""))
        self.assertTrue(draft.is_file())
        self.assertFalse((self.inbox / ".undone").exists())

    def test_ledger_entry_not_object_is_refused(self):
        key = "draft-a"
        draft = write_flat_draft(self.repo, key)
        ledger = pr_status.empty_ledger()
        ledger["prs"][key] = None
        pr_status.save_ledger(self.repo, ledger)
        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(payload.get("code"), "E_PR_EXISTS")
        self.assertTrue(draft.is_file())

    def test_assessment_appears_after_plan_is_refused(self):
        # 计划时没有评估状态文件、拿锁前另一个 groom 写进一份：也不能删（undo-log 里不会记它）。
        key = "draft-a"
        draft = write_flat_draft(self.repo, key)
        trace = write_trace(self.repo, "2026-11-01-demo", state="submitted")
        before = trace.read_bytes()
        real_plan = su.build_plan

        def plan_then_add(*args, **kwargs):
            plan = real_plan(*args, **kwargs)
            write_sidecar(self.repo, key, assessment_id="assess-race")
            return plan

        buf = io.StringIO()
        with mock.patch.object(su, "build_plan", side_effect=plan_then_add):
            with contextlib.redirect_stdout(buf):
                code = su.run(["--draft-key", key, "--apply", "--json",
                               "--root", str(self.repo)])
        payload = json.loads(buf.getvalue())
        self.assertEqual(code, 2, buf.getvalue())
        self.assertEqual(payload.get("code"), "E_ASSESSMENT_CHANGED")
        self.assertTrue(draft.is_file())
        self.assertTrue((self.inbox / ".groom" / "assessments"
                         / (sanitize_key(key) + ".yaml")).is_file())
        self.assertEqual(trace.read_bytes(), before)

    def test_undone_path_taken_by_file_is_refused(self):
        key = "draft-a"
        draft = write_flat_draft(self.repo, key)
        (self.inbox / ".undone").write_text("占位\n", encoding="utf-8")
        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(payload.get("code"), "E_MOVE")
        self.assertIn("可以直接重试", payload.get("message", ""))
        self.assertTrue(draft.is_file())
        self.assertTrue((self.inbox / ".undone").is_file())

    def test_assessment_changed_after_plan_is_refused(self):
        # 模拟「计划之后、拿到锁之前另一个 groom 改了人决定」：assessment_id 不变，
        # 只改 decision，脚本要按字节比对拦下（只比 id 会漏掉这种真实形状）。
        key = "draft-a"
        draft = write_flat_draft(self.repo, key)
        sidecar = write_sidecar(self.repo, key, decision="new_pattern", assessment_id="assess-1")
        trace = write_trace(self.repo, "2026-11-01-demo")
        before = trace.read_bytes()
        real_plan = su.build_plan

        def plan_then_race(*args, **kwargs):
            plan = real_plan(*args, **kwargs)
            write_sidecar(self.repo, key, decision="variant", assessment_id="assess-1")
            return plan

        buf = io.StringIO()
        with mock.patch.object(su, "build_plan", side_effect=plan_then_race):
            with contextlib.redirect_stdout(buf):
                code = su.run(["--draft-key", key, "--apply", "--json",
                               "--root", str(self.repo)])
        payload = json.loads(buf.getvalue())
        self.assertEqual(code, 2, buf.getvalue())
        self.assertEqual(payload.get("code"), "E_ASSESSMENT_CHANGED")
        self.assertTrue(draft.is_file())
        self.assertTrue(sidecar.is_file())
        self.assertEqual(trace.read_bytes(), before)

    def test_empty_draft_key_is_schema_error(self):
        proc, payload = self.run_undo("--draft-key", "", "--json")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(payload.get("code"), "E_SCHEMA")
        self.assertNotIn("Traceback", proc.stderr)

    def test_trace_changed_after_plan_is_refused(self):
        # 计划拿到的 trace 指纹在写之前被别处改掉：CAS 拦下，三处都不写。
        key = "draft-a"
        draft = write_flat_draft(self.repo, key, source_session="2026-11-01-demo")
        sidecar = write_sidecar(self.repo, key)
        trace = write_trace(self.repo, "2026-11-01-demo", status="resolved")
        plan = su.build_plan(self.repo, self.inbox, self.repo / "traces", key, False, False)
        trace.write_text(trace.read_text(encoding="utf-8").replace("status: resolved", "status: escalated"),
                         encoding="utf-8")
        args = types.SimpleNamespace(by="user", note="")
        with self.assertRaises(su.Refused) as ctx:
            su._apply_plan(self.repo, self.inbox, self.repo / "traces", plan, su._stamp(), args)
        self.assertEqual(ctx.exception.code, "E_TRACE")
        self.assertTrue(draft.is_file())
        self.assertTrue(sidecar.is_file())
        self.assertIn("status: escalated", trace.read_text(encoding="utf-8"))

    def test_batch_middle_refusal_does_not_block_others(self):
        for key, cid, sid in (("draft-a", "DRAFT-A", "2026-11-01-a"),
                              ("draft-c", "DRAFT-C", "2026-11-01-c")):
            write_flat_draft(self.repo, key, cid=cid, source_session=sid)
            write_trace(self.repo, sid, case_id=cid)
        write_flat_draft(self.repo, "draft-b", cid="DRAFT-B", source_session="2026-11-01-b")
        (self.repo / "traces" / "2026-11-01-b.yaml").write_text("status: [unclosed\n", encoding="utf-8")

        proc, payload = self.run_undo("--draft-key", "draft-a", "--draft-key", "draft-b",
                                      "--draft-key", "draft-c", "--apply", "--json")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(payload["summary"], {"total": 3, "applied": 2, "failed": 1})
        self.assertFalse((self.inbox / "draft-a.case.yaml").exists())
        self.assertTrue((self.inbox / "draft-b.case.yaml").is_file())
        self.assertFalse((self.inbox / "draft-c.case.yaml").exists())
        self.assertEqual(load_yaml(self.repo / "traces" / "2026-11-01-a.yaml")["status"], "in_progress")

    def test_partial_move_rolls_back(self):
        # 平铺草稿有两个文件：第二个改名失败时，第一个要改回 inbox，草稿保持完整可重试。
        # 移动走 os.rename（原子），所以这里 mock 掉 rename 的失败形状，不经过复制回退。
        key = "draft-a"
        draft = write_flat_draft(self.repo, key)
        md = self.inbox / f"{key}.md"
        real_rename = os.rename
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("mock: file is busy")
            return real_rename(src, dst)

        buf = io.StringIO()
        with mock.patch.object(su.os, "rename", side_effect=flaky):
            with contextlib.redirect_stdout(buf):
                code = su.run(["--draft-key", key, "--apply", "--json",
                               "--root", str(self.repo)])
        payload = json.loads(buf.getvalue())
        self.assertEqual(code, 2, buf.getvalue())
        self.assertEqual(payload.get("code"), "E_MOVE")
        self.assertTrue(draft.is_file())
        self.assertTrue(md.is_file())
        leftover = self.inbox / ".undone"
        self.assertFalse(leftover.exists() and any(leftover.iterdir()), str(list(leftover.iterdir())))

    def test_no_source_trace_only_queues_out(self):
        key = "draft-a"
        draft = write_flat_draft(self.repo, key)
        sidecar = write_sidecar(self.repo, key)

        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(draft.exists())
        self.assertFalse(sidecar.exists())
        self.assertFalse(payload["trace"]["written"])
        self.assertTrue(any("外部来源" in item for item in payload.get("warnings") or []),
                        json.dumps(payload, ensure_ascii=False))

    def test_refuses_when_trace_already_promoted(self):
        key = "draft-a"
        draft = write_flat_draft(self.repo, key, source_session="2026-11-01-demo")
        trace = write_trace(self.repo, "2026-11-01-demo", state="knowledge")
        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(payload.get("code"), "E_ALREADY_PROMOTED")
        self.assertTrue(draft.is_file())
        self.assertEqual(load_yaml(trace)["sedimented"]["state"], "knowledge")

    def test_keep_trace_leaves_state(self):
        key = "draft-a"
        write_flat_draft(self.repo, key, source_session="2026-11-01-demo")
        trace = write_trace(self.repo, "2026-11-01-demo")

        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json", "--keep-trace")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(payload["trace"]["written"])
        doc = load_yaml(trace)
        self.assertEqual(doc["sedimented"]["state"], "submitted")
        # --keep-trace 是「完全不动 trace」：诊断状态也不重新打开。
        self.assertEqual(doc["status"], "resolved")
        self.assertFalse(payload["trace"]["status_written"])

    def test_directory_layout_moves_whole_folder(self):
        key = "0f3a9c1e-6c1a-4a8e-9d0e-draft"
        draft = write_directory_draft(self.repo, key)
        write_sidecar(self.repo, key)

        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(draft.exists())
        moved = list((self.inbox / ".undone").iterdir())
        self.assertEqual(len(moved), 1)
        self.assertTrue((moved[0] / "case.yaml").is_file())
        self.assertTrue((moved[0] / "postmortem.md").is_file())

    def test_second_apply_is_refused(self):
        key = "draft-a"
        write_flat_draft(self.repo, key, source_session="2026-11-01-demo")
        write_sidecar(self.repo, key)
        write_trace(self.repo, "2026-11-01-demo")
        self.assertEqual(self.run_undo("--draft-key", key, "--apply", "--json")[0].returncode, 0)
        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(payload.get("code"), "E_NO_DRAFT")

    def test_apply_reopens_terminal_diagnosis(self):
        key = "draft-a"
        draft = write_flat_draft(self.repo, key, source_session="2026-11-01-demo")
        sidecar = write_sidecar(self.repo, key)
        trace = write_trace(self.repo, "2026-11-01-demo", status="resolved")

        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(draft.exists())
        self.assertFalse(sidecar.exists())
        doc = load_yaml(trace)
        self.assertEqual(doc["sedimented"]["state"], "none")
        self.assertEqual(doc["status"], "in_progress")
        self.assertEqual((doc.get("transitions") or [])[-1]["action"], "reopen")
        self.assertEqual(payload["trace"]["status_from"], "resolved")
        self.assertEqual(payload["trace"]["status_to"], "in_progress")
        log = json.loads((self.inbox / ".groom" / "undo-log.jsonl").read_text(encoding="utf-8").strip())
        self.assertTrue(log["trace"]["status_written"])
        self.assertEqual(log["trace"]["status_from"], "resolved")

    def test_keep_status_keeps_terminal_diagnosis(self):
        key = "draft-a"
        write_flat_draft(self.repo, key, source_session="2026-11-01-demo")
        trace = write_trace(self.repo, "2026-11-01-demo", status="resolved")
        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json", "--keep-status")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(load_yaml(trace)["status"], "resolved")
        self.assertFalse(payload["trace"]["status_written"])

    def test_in_progress_trace_is_not_reopened(self):
        key = "draft-a"
        write_flat_draft(self.repo, key, source_session="2026-11-01-demo")
        trace = write_trace(self.repo, "2026-11-01-demo", status="in_progress")
        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = load_yaml(trace)
        self.assertEqual(doc["status"], "in_progress")
        self.assertNotIn("transitions", doc)
        self.assertFalse(payload["trace"]["status_written"])

    def test_batch_plan_and_apply(self):
        for key, cid, sid in (("draft-a", "DRAFT-A", "2026-11-01-a"),
                              ("draft-b", "DRAFT-B", "2026-11-01-b")):
            write_flat_draft(self.repo, key, cid=cid, source_session=sid)
            write_sidecar(self.repo, key)
            write_trace(self.repo, sid, case_id=cid)

        proc, payload = self.run_undo("--draft-key", "draft-a", "--draft-key", "draft-b", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(payload["dryRun"])
        self.assertEqual(payload["summary"], {"total": 2, "planned": 2, "refused": 0})
        self.assertFalse((self.inbox / ".undone").exists())

        proc, payload = self.run_undo("--draft-key", "draft-a", "--draft-key", "draft-b",
                                      "--apply", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(payload["summary"], {"total": 2, "applied": 2, "failed": 0})
        self.assertFalse((self.inbox / "draft-a.case.yaml").exists())
        self.assertFalse((self.inbox / "draft-b.case.yaml").exists())
        self.assertEqual(len(list((self.inbox / ".undone").iterdir())), 2)
        log_lines = (self.inbox / ".groom" / "undo-log.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(log_lines), 2)
        for sid in ("2026-11-01-a", "2026-11-01-b"):
            doc = load_yaml(self.repo / "traces" / f"{sid}.yaml")
            self.assertEqual(doc["sedimented"]["state"], "none")
            self.assertEqual(doc["status"], "in_progress")

    def test_batch_refusal_does_not_block_others(self):
        write_flat_draft(self.repo, "draft-a", cid="DRAFT-A", source_session="2026-11-01-a")
        write_trace(self.repo, "2026-11-01-a", case_id="DRAFT-A")
        write_flat_draft(self.repo, "draft-b", cid="DRAFT-B", source_session="2026-11-01-b")
        ledger = pr_status.empty_ledger()
        ledger["prs"]["draft-b"] = {
            "platform": "github", "repo": "x/y", "number": 1,
            "url": "https://github.com/x/y/pull/1", "state": "open", "source": "platform",
        }
        pr_status.save_ledger(self.repo, ledger)

        proc, payload = self.run_undo("--draft-key", "draft-a", "--draft-key", "draft-b", "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(payload["summary"], {"total": 2, "planned": 1, "refused": 1})

        proc, payload = self.run_undo("--draft-key", "draft-a", "--draft-key", "draft-b",
                                      "--apply", "--json")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(payload["summary"], {"total": 2, "applied": 1, "failed": 1})
        self.assertFalse((self.inbox / "draft-a.case.yaml").exists())
        self.assertTrue((self.inbox / "draft-b.case.yaml").is_file())
        self.assertEqual(load_yaml(self.repo / "traces" / "2026-11-01-a.yaml")["status"], "in_progress")

    def test_ambiguous_source_is_refused(self):
        key = "draft-a"
        write_flat_draft(self.repo, key)
        head = self.inbox / f"{key}.md"
        head.write_text("来源：traces/2026-11-01-a.yaml 与 traces/2026-11-02-b.yaml\n", encoding="utf-8")
        proc, payload = self.run_undo("--draft-key", key, "--apply", "--json")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertEqual(payload.get("code"), "E_SESSION_AMBIGUOUS")
        self.assertTrue((self.inbox / f"{key}.case.yaml").is_file())


if __name__ == "__main__":
    unittest.main()
