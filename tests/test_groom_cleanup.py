"""Groom 收尾清理：复核失败、绑定不一致、锁、删除失败、快照引用、日志与幂等。"""

import contextlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import groom_cleanup  # noqa: E402
import groom_common  # noqa: E402
from groom_cleanup import cleanup  # noqa: E402
from groom_common import assessment_path, atomic_write_text, dump_yaml, sanitize_key, short_sha  # noqa: E402
from tests.groom_fixtures import git, init_repo  # noqa: E402


def _sidecar(inbox: Path, key: str, commit: str, decision="new_pattern",
             assessment_id="AID", content_sha="SHA"):
    doc = {
        "schema": "groom-assessment/v1",
        "draft": key,
        "draft_case_id": key,
        "assessment_id": assessment_id,
        "content_binding": {"sha256": content_sha},
        "provenance": {"compared_against_commit": commit},
        "human_decision": {"decision": decision, "by": "owner",
                           "decided_at": "2026-11-02T00:00:00+08:00",
                           "note": "测试批注",
                           "assessment_id": assessment_id, "content_sha256": content_sha},
        "human_decision_valid": True,
    }
    path = assessment_path(inbox, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, dump_yaml(doc))
    path.with_suffix(path.suffix + ".lock").write_text("0", encoding="utf-8")
    return path


def _marker(key, commit, decision="new_pattern", stale="false",
            assessment_id="AID", content_sha="SHA"):
    return {"draft": key, "human_decision": decision, "approval_stale": stale,
            "assessed_commit": commit, "assessment_id": assessment_id,
            "assessed_content_sha256": content_sha,
            "human_decision_assessment_id": assessment_id,
            "human_decision_content_sha256": content_sha,
            "proposed_novelty": "new_pattern", "candidate_case": None}


def _check_ok(markers):
    def _fn(body, repo, base, head, enforce):
        return [], {"base": base, "head": head, "markers": markers}
    return _fn


def _check_fail(body, repo, base, head, enforce):
    return ([{"severity": "error", "code": "assessment-stale", "message": "评估过期"}],
            {"base": base, "head": head, "markers": []})


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="groom-cleanup-")
        self.addCleanup(self.tmp.cleanup)
        self.repo = init_repo(Path(self.tmp.name) / "repo", {
            "knowledge/common/interrupt/CASE-A.yaml": dict(cid="CASE-A", sig="CASE-A"),
        })
        self.commit = git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.inbox = self.repo / "postmortems" / "inbox"
        self.snap_dir = self.inbox / ".groom" / "snapshots"

    # —— 工具 ——
    def _run(self, markers, apply=True, **kw):
        return cleanup("body", self.repo, "origin/main", "HEAD", apply=apply,
                       check_fn=_check_ok(markers), **kw)

    def _make_snapshot(self):
        wt = self.snap_dir / f"main-{short_sha(self.commit)}"
        (wt / "knowledge").mkdir(parents=True, exist_ok=True)
        (wt / "knowledge" / "x.yaml").write_text("x", encoding="utf-8")
        meta = self.snap_dir / f"main-{short_sha(self.commit)}.json"
        meta.write_text("{}", encoding="utf-8")
        return wt, meta

    # —— fail-closed ——
    def test_blocking_recheck_deletes_nothing(self):
        sidecar = _sidecar(self.inbox, "draft-a", self.commit)
        report = cleanup("body", self.repo, "origin/main", "HEAD", apply=True, check_fn=_check_fail)
        self.assertFalse(report["ok"])
        self.assertTrue(sidecar.exists())

    def test_no_marker_is_fail_closed(self):
        a = _sidecar(self.inbox, "draft-a", self.commit)
        self.assertFalse(self._run([])["ok"])
        self.assertTrue(a.exists())

    # —— 按 key 隔离 ——
    def test_only_marker_keys_are_deleted(self):
        a = _sidecar(self.inbox, "draft-a", self.commit)
        b = _sidecar(self.inbox, "draft-b", self.commit)
        report = self._run([_marker("draft-a", self.commit)])
        self.assertTrue(report["ok"], report)
        self.assertFalse(a.exists())
        self.assertTrue(b.exists())

    def test_non_terminal_decision_kept(self):
        a = _sidecar(self.inbox, "draft-a", self.commit, decision="defer")
        report = self._run([_marker("draft-a", self.commit, decision="defer")])
        self.assertTrue(a.exists())
        self.assertEqual(report["deleted"]["kept"], ["draft-a"])

    def test_stale_approval_kept(self):
        a = _sidecar(self.inbox, "draft-a", self.commit)
        report = self._run([_marker("draft-a", self.commit, stale="true")])
        self.assertTrue(a.exists())
        self.assertEqual(report["deleted"]["kept"], ["draft-a"])

    # —— 绑定一致性 ——
    def test_old_marker_does_not_delete_new_assessment(self):
        a = _sidecar(self.inbox, "draft-a", self.commit, assessment_id="NEW")
        report = self._run([_marker("draft-a", self.commit, assessment_id="OLD")])
        self.assertTrue(a.exists())
        self.assertIn("assessment_id", report["kept_reasons"]["draft-a"])

    def test_old_marker_does_not_delete_when_local_decision_changed(self):
        a = _sidecar(self.inbox, "draft-a", self.commit, decision="defer")
        report = self._run([_marker("draft-a", self.commit, decision="new_pattern")])
        self.assertTrue(a.exists())
        self.assertIn("human_decision", report["kept_reasons"]["draft-a"])

    def test_content_change_keeps_sidecar(self):
        a = _sidecar(self.inbox, "draft-a", self.commit, content_sha="NEW_CONTENT")
        report = self._run([_marker("draft-a", self.commit)])
        self.assertTrue(a.exists())
        self.assertIn("content_sha256", report["kept_reasons"]["draft-a"])

    # —— 锁与删除失败 ——
    def test_lock_unavailable_keeps_sidecar(self):
        a = _sidecar(self.inbox, "draft-a", self.commit)

        @contextlib.contextmanager
        def _no_lock(_path):
            yield False

        with mock.patch.object(groom_cleanup, "log_lock", _no_lock):
            report = self._run([_marker("draft-a", self.commit)])
        self.assertTrue(a.exists())
        codes = [f["code"] for f in report["findings"]]
        self.assertIn("lock-unavailable", codes)

    def test_delete_failure_reports_and_keeps(self):
        _sidecar(self.inbox, "draft-a", self.commit)
        with mock.patch.object(Path, "unlink", side_effect=PermissionError("busy")):
            report = self._run([_marker("draft-a", self.commit)])
        codes = [f["code"] for f in report["findings"]]
        self.assertIn("delete-failed", codes)
        self.assertFalse(report["ok"])

    def test_lock_file_is_not_deleted(self):
        a = _sidecar(self.inbox, "draft-a", self.commit)
        lock = a.with_suffix(a.suffix + ".lock")
        self._run([_marker("draft-a", self.commit)])
        self.assertTrue(lock.exists())

    def _patched_lock(self, guard_fails=False, sidecar_raises=False):
        real = groom_cleanup.log_lock

        @contextlib.contextmanager
        def _fake(path):
            name = Path(path).name
            if name == ".guard" and guard_fails:
                yield False
                return
            if name.endswith(".yaml") and sidecar_raises:
                raise OSError("lock dir not writable")
            with real(path) as ok:
                yield ok

        return mock.patch.object(groom_cleanup, "log_lock", _fake)

    def test_guard_lock_unavailable_deletes_nothing(self):
        a = _sidecar(self.inbox, "draft-a", self.commit)
        self._make_snapshot()
        with self._patched_lock(guard_fails=True):
            report = self._run([_marker("draft-a", self.commit)])
        self.assertTrue(a.exists())
        self.assertFalse(report["ok"])
        self.assertIn("lock-unavailable", [f["code"] for f in report["findings"]])

    def test_sidecar_lock_open_error_reports_and_continues(self):
        a = _sidecar(self.inbox, "draft-a", self.commit)
        b = _sidecar(self.inbox, "draft-b", self.commit)
        with self._patched_lock(sidecar_raises=True):
            report = self._run([_marker("draft-a", self.commit), _marker("draft-b", self.commit)])
        self.assertTrue(a.exists())
        self.assertTrue(b.exists())
        self.assertFalse(report["ok"])
        self.assertIn("lock-error", [f["code"] for f in report["findings"]])

    def test_guard_lock_is_taken(self):
        _sidecar(self.inbox, "draft-a", self.commit)
        self._run([_marker("draft-a", self.commit)])
        self.assertTrue((self.inbox / ".groom" / "assessments" / ".guard.lock").exists())

    def test_write_assessment_refuses_without_guard(self):
        from groom_common import write_assessment

        @contextlib.contextmanager
        def _no_lock(_path):
            yield False

        with mock.patch.object(groom_common, "log_lock", _no_lock):
            with self.assertRaises(RuntimeError):
                write_assessment(self.inbox, "draft-x", {"draft": "draft-x"})

    def test_unexpected_error_is_reported_and_logged(self):
        _sidecar(self.inbox, "draft-a", self.commit)
        with mock.patch.object(groom_cleanup, "_delete_sidecars",
                               side_effect=RuntimeError("boom")):
            report = self._run([_marker("draft-a", self.commit)])
        self.assertFalse(report["ok"])
        self.assertIn("internal-error", [f["code"] for f in report["findings"]])
        # 报告不能消失，日志也要留一行（这是删掉 sidecar 后唯一的本地记录）
        self.assertTrue((self.inbox / ".groom" / "cleanup-log.jsonl").exists())

    # —— 工作单与残锁 ——
    def _make_run(self, name, age_days):
        run = self.inbox / ".groom" / "runs" / name
        run.mkdir(parents=True, exist_ok=True)
        (run / "work-orders.json").write_text("{}", encoding="utf-8")
        old = time.time() - age_days * 86400
        os.utime(run, (old, old))
        return run

    def _make_lock(self, name, age_days, with_sidecar=False):
        lock = self.inbox / ".groom" / "assessments" / name
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("0", encoding="utf-8")
        if with_sidecar:
            lock.with_suffix("").write_text("cases: []\n", encoding="utf-8")
        old = time.time() - age_days * 86400
        os.utime(lock, (old, old))
        return lock

    def test_runs_cleaned_only_when_old(self):
        old = self._make_run("run-old", 2)
        fresh = self._make_run("run-fresh", 0.01)
        _sidecar(self.inbox, "draft-a", self.commit)
        report = self._run([_marker("draft-a", self.commit)])
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())
        self.assertEqual(report["deleted"]["runs"], ["run-old"])

    def test_stale_locks_cleaned_only_when_orphan_and_old(self):
        stale = self._make_lock("GONE-1234.yaml.lock", 10)
        fresh_orphan = self._make_lock("NEW-5678.yaml.lock", 0.01)
        live = self._make_lock("LIVE-9999.yaml.lock", 30, with_sidecar=True)
        _sidecar(self.inbox, "draft-a", self.commit)
        report = self._run([_marker("draft-a", self.commit)])
        self.assertFalse(stale.exists())
        self.assertTrue(fresh_orphan.exists(), "不到期的残锁不清")
        self.assertTrue(live.exists(), "有对应 sidecar 的锁不清")
        self.assertIn("GONE-1234.yaml.lock", report["deleted"]["locks"])

    def test_guard_lock_never_cleaned(self):
        guard = self._make_lock(".guard.lock", 30)
        _sidecar(self.inbox, "draft-a", self.commit)
        self._run([_marker("draft-a", self.commit)])
        self.assertTrue(guard.exists())

    def test_sidecar_deleted_directly(self):
        a = _sidecar(self.inbox, "draft-a", self.commit)
        self._run([_marker("draft-a", self.commit)])
        self.assertFalse(a.exists())
        self.assertFalse((self.inbox / ".groom" / "trash").exists())

    # —— 预览/执行一致 ——
    def test_preview_matches_apply(self):
        _sidecar(self.inbox, "draft-a", self.commit)
        self._make_snapshot()
        preview = self._run([_marker("draft-a", self.commit)], apply=False)
        applied = self._run([_marker("draft-a", self.commit)], apply=True)
        self.assertEqual(preview["deleted"]["snapshots"], applied["deleted"]["snapshots"])
        self.assertEqual(preview["deleted"]["assessments"], applied["deleted"]["assessments"])

    def test_preview_unreadable_also_fails(self):
        sidecar = assessment_path(self.inbox, "draft-a")
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text("not: [valid", encoding="utf-8")
        report = self._run([_marker("draft-a", self.commit)], apply=False)
        self.assertFalse(report["ok"])
        codes = [f["code"] for f in report["findings"]]
        self.assertIn("unreadable-assessment", codes)

    # —— 快照 ——
    def test_snapshot_deleted_only_after_last_reference_gone(self):
        _sidecar(self.inbox, "draft-a", self.commit)
        wt, meta = self._make_snapshot()
        report = self._run([_marker("draft-a", self.commit)])
        self.assertEqual(report["deleted"]["snapshots"], [short_sha(self.commit)])
        self.assertFalse(wt.exists())
        self.assertFalse(meta.exists())

    def test_snapshot_kept_while_other_sidecar_references_it(self):
        _sidecar(self.inbox, "draft-a", self.commit)
        _sidecar(self.inbox, "draft-b", self.commit)
        self._make_snapshot()
        report = self._run([_marker("draft-a", self.commit)])
        self.assertEqual(report["deleted"]["snapshots"], [])

    def test_unreadable_sidecar_blocks_snapshot_cleanup(self):
        _sidecar(self.inbox, "draft-a", self.commit)
        self._make_snapshot()
        bad = self.inbox / ".groom" / "assessments" / f"{sanitize_key('draft-b')}.yaml"
        bad.write_text("not: [valid", encoding="utf-8")
        report = self._run([_marker("draft-a", self.commit)])
        self.assertFalse(report["ok"])
        self.assertEqual(report["deleted"]["snapshots"], [])

    def test_snapshot_skipped_when_it_is_fresh_latest(self):
        _sidecar(self.inbox, "draft-a", self.commit)
        self._make_snapshot()
        (self.snap_dir / "latest.json").write_text(
            json.dumps({"commit": self.commit}), encoding="utf-8")
        report = self._run([_marker("draft-a", self.commit)])
        self.assertEqual(report["deleted"]["snapshots"], [])
        self.assertEqual(len(report["skipped_snapshots"]), 1)

    def test_unresolvable_commit_blocks_snapshot(self):
        _sidecar(self.inbox, "draft-a", self.commit)
        self._make_snapshot()
        report = self._run([_marker("draft-a", "deadbeef")])
        codes = [f["code"] for f in report["findings"]]
        self.assertIn("commit-unresolved", codes)
        self.assertEqual(report["deleted"]["snapshots"], [])

    def test_snapshot_failure_reports_partial(self):
        _sidecar(self.inbox, "draft-a", self.commit)
        self._make_snapshot()

        def _fail(repo, snapshot_dir=None, commit=None, branch="main"):
            return {"ok": False, "error": "模拟删除失败"}

        report = self._run([_marker("draft-a", self.commit)], cleanup_snapshot_fn=_fail)
        self.assertFalse(report["ok"])
        self.assertEqual(report["deleted"]["snapshots"], [])

    # —— 日志 ——
    def test_cleanup_log_is_jsonl_with_decision_details(self):
        _sidecar(self.inbox, "draft-a", self.commit)
        self._run([_marker("draft-a", self.commit)])
        _sidecar(self.inbox, "draft-b", self.commit)
        self._run([_marker("draft-b", self.commit)])
        log = self.inbox / ".groom" / "cleanup-log.jsonl"
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        entry = json.loads(lines[0])
        self.assertTrue(entry["applied"])
        decision = entry["decisions"][0]
        self.assertEqual(decision["assessment_id"], "AID")
        self.assertEqual(decision["human_decision"], "new_pattern")


if __name__ == "__main__":
    unittest.main()
