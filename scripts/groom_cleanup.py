#!/usr/bin/env python3
# groom_cleanup.py —— 收尾清理：**复核通过 + 绑定一致**后，只清这份 PR 覆盖到的产物。
#
# 与 `groom_snapshot.py --cleanup` 的分工：
#   - 它删「这一个 commit 的快照」，不区分草稿；
#   - 本脚本删「这份 PR body 的 marker 覆盖到的 draft key」的 sidecar，
#     以及不再被任何健康 sidecar 引用的快照。
#
# 安全约束（fail-closed，全部有反例测试）：
#   1. 先跑 groom_recheck；有任何 error → 一个文件都不动，退出 2；
#   2. marker 必须与本地评估**同一次评估、同一份内容、同一个决定**（assessment_id /
#      content hash / human_decision 三者都对得上）——旧 PR 正文不能删掉重评后的新记录；
#   3. 执行阶段持**目录级清理锁**（与 `write_assessment` 共用）：清理期间任何新评估写不进来，
#      所以「引用扫描 → 删快照」之间不会冒出新的引用；
#   4. 单个 sidecar 的删除仍进 `log_lock(sidecar)`；拿不到锁、锁打不开、unlink 失败都不删；
#   5. 执行时引用扫描看**全部现存记录**（不排除本次删掉的路径——同路径可能被另一个进程写回）；
#   6. 任何一份 sidecar 读不出来 → 引用未知，阻塞快照清理并报错；
#   7. 快照还被别的 sidecar 引用、或最近 N 分钟内刚创建 → 不删；只有真的删掉了东西才写进 deleted；
#   8. 删除/日志任何一步失败 → 记 findings、`ok=False`、退出 2，报告照常输出。
#      **可能部分完成**：sidecar/快照先删、日志最后写；日志写失败时删除不可回滚（会在报告里标出）。
#
# 用法（默认直接执行；agent 读完判据后自己决定跑不跑）：
#   python3 scripts/groom_cleanup.py --pr-body-file <body> [--base origin/main] [--head <ref>]
#   python3 scripts/groom_cleanup.py --pr-body-file <body> --dry-run    # 只看计划
#
# 退出码：0 = 复核通过且清理完成；2 = 复核不通过 / 引用未知 / 部分失败；3 = 参数错。

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from _stdio import pin_utf8_stdio
from _yaml import load_file
from exec_log_path import log_lock
from groom_common import (
    assessment_guard, assessment_path, dump_json, load_json, normalize_commit, now_iso,
    repo_root, shared_inbox, short_sha,
)
from groom_recheck import check as recheck_check
from groom_snapshot import cleanup_snapshot

TERMINAL_DECISIONS = ("new_pattern", "variant", "covered")
SNAPSHOT_IN_USE_MINUTES = 30
RUNS_KEEP_DAYS = 1          # 工作单可重生成；超过一天视作上一轮的残留（避开在途 run）
LOCK_KEEP_DAYS = 7          # 只清「对应 sidecar 已不存在」的旧锁；持有中的锁 mtime 会变


def _binding_mismatches(marker, doc):
    human = doc.get("human_decision") or {}
    binding = doc.get("content_binding") or {}
    pairs = (
        ("assessment_id", doc.get("assessment_id"), marker.get("assessment_id")),
        ("content_sha256", binding.get("sha256"), marker.get("assessed_content_sha256")),
        ("human_decision", human.get("decision"), marker.get("human_decision")),
        ("human_assessment_id", human.get("assessment_id"),
         marker.get("human_decision_assessment_id")),
        ("human_content_sha256", human.get("content_sha256"),
         marker.get("human_decision_content_sha256")),
    )
    return [name for name, got, want in pairs if str(got or "") != str(want or "")]


def _eligible(marker):
    if str(marker.get("approval_stale")).lower() == "true":
        return False
    return str(marker.get("human_decision") or "") in TERMINAL_DECISIONS


def _scan_references(inbox: Path, repo: Path, exclude_paths=()):
    """返回 (commits, unreadable)。commits 已归一成全长 sha。"""
    commits, unreadable = set(), []
    assess_dir = inbox / ".groom" / "assessments"
    if not assess_dir.is_dir():
        return commits, unreadable
    for path in sorted(assess_dir.glob("*.yaml")):
        if path in exclude_paths:
            continue
        try:
            doc = load_file(path)
        except Exception:
            unreadable.append(path.name)
            continue
        if not isinstance(doc, dict):
            unreadable.append(path.name)
            continue
        raw = (doc.get("provenance") or {}).get("compared_against_commit")
        if not raw:
            continue
        normalized = normalize_commit(repo, str(raw))
        if normalized:
            commits.add(normalized)
    return commits, unreadable


def _snapshot_paths(inbox: Path, snapshot_dir, commit: str, branch: str):
    base = Path(snapshot_dir) if snapshot_dir else (inbox / ".groom" / "snapshots")
    rel = f"{branch.replace('/', '_')}-{short_sha(commit)}"
    return base, base / rel, base / f"{rel}.json"


def _snapshot_in_use(snapshot_dir: Path, commit: str) -> bool:
    """最近一次快照就是它、且刚写不久 → 可能有别的 session 正在用，不删。"""
    latest = snapshot_dir / "latest.json"
    if not latest.exists():
        return False
    try:
        doc = load_json(latest) or {}
    except Exception:
        return True                      # 读不出就当在用，保守
    if str(doc.get("commit") or "") != commit:
        return False
    return (time.time() - latest.stat().st_mtime) < SNAPSHOT_IN_USE_MINUTES * 60


def _delete_sidecars(inbox: Path, eligible, report: dict, apply: bool):
    """返回 (removed_paths, decision_details)。删除失败/锁异常都只记录，不抛出。"""
    removed_paths, details = set(), []
    for marker in eligible:
        key = str(marker.get("draft") or "").strip()
        if not key:
            continue
        sidecar = assessment_path(inbox, key)
        if not sidecar.exists():
            report["deleted"]["kept"].append(key)
            report["kept_reasons"][key] = "sidecar 不存在"
            continue

        def _decide(doc):
            if not isinstance(doc, dict):
                return "读取失败"
            mismatch = _binding_mismatches(marker, doc)
            return ("marker 与本地评估不一致（" + ", ".join(mismatch) + "）") if mismatch else None

        if not apply:
            try:
                reason = _decide(load_file(sidecar))
            except Exception:
                reason = "读取失败"
                report["ok"] = False
                report["findings"].append({"severity": "error", "code": "unreadable-assessment",
                                           "message": f"{sidecar.name}: 预览时读不出，执行会被拦下"})
            if reason:
                report["deleted"]["kept"].append(key)
                report["kept_reasons"][key] = reason
            else:
                report["deleted"]["assessments"].append(key)
                removed_paths.add(sidecar)
            continue

        try:
            lock_ctx = log_lock(sidecar)
            locked = lock_ctx.__enter__()
        except Exception as exc:
            report["ok"] = False
            report["findings"].append({"severity": "error", "code": "lock-error",
                                       "message": f"{sidecar.name}: 打不开写锁（{exc}），不删"})
            report["deleted"]["kept"].append(key)
            report["kept_reasons"][key] = "写锁打不开"
            continue
        try:
            if not locked:
                report["ok"] = False
                report["findings"].append({
                    "severity": "error", "code": "lock-unavailable",
                    "message": f"{sidecar.name}: 没拿到写锁（平台无原语或争用超时），不删"})
                report["deleted"]["kept"].append(key)
                report["kept_reasons"][key] = "没拿到写锁"
                continue
            try:
                doc = load_file(sidecar)
                reason = _decide(doc)
            except Exception as exc:
                report["ok"] = False
                report["findings"].append({"severity": "error", "code": "unreadable-assessment",
                                           "message": f"{sidecar.name}: {exc}"})
                reason = "读取失败"
                doc = {}
            if reason:
                report["deleted"]["kept"].append(key)
                report["kept_reasons"][key] = reason
                continue
            try:
                sidecar.unlink()
            except OSError as exc:
                report["ok"] = False
                report["findings"].append({"severity": "error", "code": "delete-failed",
                                           "message": f"{sidecar.name}: {exc}"})
                report["deleted"]["kept"].append(key)
                report["kept_reasons"][key] = f"删除失败：{exc.__class__.__name__}"
                continue
            human = (doc if isinstance(doc, dict) else {}).get("human_decision") or {}
            details.append({
                "draft": key,
                "by": human.get("by"),
                "decided_at": human.get("decided_at"),
                "note": human.get("note"),
                "applies_to_commit": human.get("applies_to_commit"),
                "history_entries": len((doc or {}).get("human_decision_history") or []),
            })
            removed_paths.add(sidecar)
            report["deleted"]["assessments"].append(key)
        finally:
            lock_ctx.__exit__(None, None, None)
    return removed_paths, details


def _delete_snapshots(inbox: Path, repo: Path, eligible, report: dict, apply: bool,
                      snapshot_dir, branch: str, cleanup_snapshot_fn, planned_paths=()):
    # 执行阶段已经删完 sidecar，扫描**全部现存**记录（不再排除被删路径：
    # 另一个进程可能刚在同一路径写回一份新评估，排除它就等于忽略新引用）。
    # 预览阶段那些文件还在，按「计划要删的」排除，才与执行结果一致。
    still_used, unreadable = _scan_references(inbox, repo, () if apply else planned_paths)
    if unreadable:
        report["ok"] = False
        report["findings"].append({
            "severity": "error", "code": "unreadable-assessment",
            "message": f"有 {len(unreadable)} 份评估读不出来（{', '.join(unreadable)}），"
                       "无法判断快照是否仍被引用——本轮不删快照"})
        return

    for raw_commit in sorted({str(m.get("assessed_commit") or "") for m in eligible} - {""}):
        commit = normalize_commit(repo, raw_commit)
        if not commit:
            report["ok"] = False
            report["findings"].append({
                "severity": "error", "code": "commit-unresolved",
                "message": f"marker 的 assessed_commit 无法解析：{raw_commit}"})
            continue
        if commit in still_used:
            continue
        snap_dir, worktree, meta = _snapshot_paths(inbox, snapshot_dir, commit, branch)
        if _snapshot_in_use(snap_dir, commit):
            report["skipped_snapshots"].append(
                {"commit": commit[:12], "reason": "最近一次快照就是它且刚创建，可能有 session 在用"})
            continue
        if not (worktree.exists() or meta.exists()):
            report["skipped_snapshots"].append(
                {"commit": commit[:12], "reason": "快照目录/JSON 不存在（参数不一致或已清）"})
            continue
        if not apply:
            report["deleted"]["snapshots"].append(commit[:12])
            continue
        try:
            result = cleanup_snapshot_fn(repo, snapshot_dir=snapshot_dir, commit=commit,
                                         branch=branch)
        except Exception as exc:
            report["ok"] = False
            report["findings"].append({"severity": "error", "code": "snapshot-cleanup-failed",
                                       "message": f"{commit[:12]}: {exc}"})
            continue
        removed = bool(result.get("worktree_removed") or result.get("meta_removed"))
        if result.get("ok") and removed:
            report["deleted"]["snapshots"].append(commit[:12])
        elif result.get("ok"):
            report["skipped_snapshots"].append(
                {"commit": commit[:12], "reason": "清理未删除任何东西"})
        else:
            report["ok"] = False
            report["findings"].append({
                "severity": "error", "code": "snapshot-cleanup-failed",
                "message": f"{commit[:12]}: {result.get('error', '')}"})


def _clean_runs(inbox: Path, apply: bool, report: dict, keep_days: float):
    """删超过 keep_days 的工作单目录（`.groom/runs/<run-id>/`）。可重生成，风险低。"""
    runs_dir = inbox / ".groom" / "runs"
    if not runs_dir.is_dir():
        return
    cutoff = time.time() - keep_days * 86400
    for child in sorted(runs_dir.iterdir()):
        if not child.is_dir():
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        if apply:
            try:
                shutil.rmtree(child)
            except OSError as exc:
                report["ok"] = False
                report["findings"].append({"severity": "error", "code": "runs-cleanup-failed",
                                           "message": f"{child.name}: {exc}"})
                continue
        report["deleted"]["runs"].append(child.name)


def _clean_stale_locks(inbox: Path, apply: bool, report: dict, keep_days: float):
    """删「对应 sidecar 已不存在」且超过 keep_days 的锁文件。

    持锁中的文件 mtime 会随写入更新，所以「旧 + 没有对应 sidecar」这两个条件同时成立时，
    基本可以判定是删除 sidecar 后留下的残锁。`.guard.lock` 没有对应文件，不在清理范围。
    """
    assess_dir = inbox / ".groom" / "assessments"
    if not assess_dir.is_dir():
        return
    cutoff = time.time() - keep_days * 86400
    for lock in sorted(assess_dir.glob("*.lock")):
        if lock.name == ".guard.lock":
            continue
        target = lock.with_suffix("")
        if target.exists():
            continue
        try:
            mtime = lock.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        if apply:
            try:
                lock.unlink()
            except OSError as exc:
                report["ok"] = False
                report["findings"].append({"severity": "error", "code": "lock-cleanup-failed",
                                           "message": f"{lock.name}: {exc}"})
                continue
        report["deleted"]["locks"].append(lock.name)


def cleanup(body: str, repo: Path, base: str, head: str, apply: bool = False,
            snapshot_dir=None, check_fn=recheck_check,
            cleanup_snapshot_fn=cleanup_snapshot, branch: str = "main",
            pr_label: str = None, runs_keep_days: float = RUNS_KEEP_DAYS,
            lock_keep_days: float = LOCK_KEEP_DAYS):
    repo = Path(repo).resolve()
    inbox = shared_inbox(repo)
    findings, ctx = check_fn(body, repo, base, head, False)
    blocking = [f for f in findings if f.get("severity") == "error"]
    markers = ctx.get("markers") or []
    report = {
        "schema": "groom-cleanup/v1",
        "checked_at": now_iso(),
        "base": ctx.get("base") or base,
        "head": ctx.get("head") or head,
        "pr": pr_label,
        "ok": not blocking,
        "applied": bool(apply),
        "markers": [{k: m.get(k) for k in ("draft", "human_decision", "approval_stale",
                                           "assessed_commit", "assessment_id")} for m in markers],
        "deleted": {"assessments": [], "snapshots": [], "kept": [],
                    "runs": [], "locks": []},
        "skipped_snapshots": [],
        "kept_reasons": {},
        "findings": blocking,
    }
    if blocking:
        return report
    if not markers:
        report["ok"] = False
        report["findings"] = [{"severity": "error", "code": "no-marker",
                               "message": "PR body 里没有 groom-assessment marker，无从判断删哪几份"}]
        return report

    eligible, kept = [], []
    for m in markers:
        (eligible if _eligible(m) else kept).append(m)
    for m in kept:
        report["deleted"]["kept"].append(m.get("draft"))
        report["kept_reasons"][str(m.get("draft"))] = "非终态决定或审批已过期"

    def _phase():
        removed, details = _delete_sidecars(inbox, eligible, report, apply)
        if details:
            report.setdefault("decision_details", []).extend(details)
        _delete_snapshots(inbox, repo, eligible, report, apply, snapshot_dir, branch,
                          cleanup_snapshot_fn, planned_paths=removed)
        _clean_runs(inbox, apply, report, runs_keep_days)
        _clean_stale_locks(inbox, apply, report, lock_keep_days)

    if apply:
        try:
            guard = log_lock(assessment_guard(inbox))
            locked = guard.__enter__()
        except Exception as exc:
            report["ok"] = False
            report["findings"].append({"severity": "error", "code": "lock-error",
                                       "message": f"清理锁打不开（{exc}），未删任何文件"})
            return report
        if not locked:
            guard.__exit__(None, None, None)
            report["ok"] = False
            report["findings"].append({"severity": "error", "code": "lock-unavailable",
                                       "message": "没拿到清理锁（平台无原语或争用超时），未删任何文件"})
            return report
        try:
            _phase()
        except Exception as exc:
            # 非预期异常（git 超时、权限、stat 失败）：折成 finding，不能让报告和日志一起消失
            report["ok"] = False
            report["findings"].append({
                "severity": "error", "code": "internal-error",
                "message": f"{exc.__class__.__name__}: {exc}"})
        finally:
            guard.__exit__(None, None, None)
    else:
        try:
            _phase()
        except Exception as exc:
            report["ok"] = False
            report["findings"].append({
                "severity": "error", "code": "internal-error",
                "message": f"{exc.__class__.__name__}: {exc}"})

    if apply:
        entry = {
            "at": report["checked_at"],
            "pr": pr_label,
            "base": report["base"], "head": report["head"],
            "applied": True,
            "deleted": report["deleted"],
            "skipped_snapshots": report["skipped_snapshots"],
            "kept_reasons": report["kept_reasons"],
            "decision_details": report.get("decision_details") or [],
            "ok": report["ok"],
            "decisions": [{
                "draft": m.get("draft"),
                "assessment_id": m.get("assessment_id"),
                "assessed_content_sha256": m.get("assessed_content_sha256"),
                "assessed_commit": m.get("assessed_commit"),
                "proposed_novelty": m.get("proposed_novelty"),
                "candidate_case": m.get("candidate_case"),
                "human_decision": m.get("human_decision"),
                "human_decision_assessment_id": m.get("human_decision_assessment_id"),
                "human_decision_content_sha256": m.get("human_decision_content_sha256"),
            } for m in markers],
        }
        log_path = inbox / ".groom" / "cleanup-log.jsonl"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_lock(log_path) as locked:
                if not locked:
                    raise OSError("cleanup-log 写锁不可用")
                with log_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            report["ok"] = False
            report["findings"].append({"severity": "error", "code": "log-write-failed",
                                       "message": f"{log_path}: {exc}"})
    return report


class _Parser(argparse.ArgumentParser):
    """参数错误按文档退出 3（argparse 默认 2，会和「复核不通过」撞码）。"""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"{self.prog}: 参数错误：{message}", file=sys.stderr)
        raise SystemExit(3)


def main():
    pin_utf8_stdio()
    ap = _Parser(description="Groom 收尾清理（复核通过后按草稿删产物）")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--pr-body-file", required=True)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--branch", default="main", help="建快照时用的分支（默认 main）")
    ap.add_argument("--pr", default=None, help="PR 标识（URL 或编号），写进清理日志")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印计划、不删（默认直接执行）")
    ap.add_argument("--snapshot-dir", default=None)
    ap.add_argument("--keep-runs-days", type=float, default=RUNS_KEEP_DAYS,
                    help=f"工作单超过这么多天就清（默认 {RUNS_KEEP_DAYS}）")
    ap.add_argument("--keep-lock-days", type=float, default=LOCK_KEEP_DAYS,
                    help=f"无对应 sidecar 的锁超过这么多天就清（默认 {LOCK_KEEP_DAYS}）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    body_path = Path(args.pr_body_file)
    if not body_path.exists():
        print(f"groom_cleanup: 找不到 PR body：{body_path}", file=sys.stderr)
        return 3
    root = repo_root(Path(args.repo).resolve() if args.repo else Path.cwd())
    report = cleanup(body_path.read_text(encoding="utf-8"), root, args.base, args.head,
                     apply=not args.dry_run, snapshot_dir=args.snapshot_dir,
                     branch=args.branch, pr_label=args.pr,
                     runs_keep_days=args.keep_runs_days, lock_keep_days=args.keep_lock_days)
    if args.json:
        print(dump_json(report), end="")
    else:
        print(f"Groom 收尾清理：base {str(report['base'])[:12]} · head {str(report['head'])[:12]}"
              f" · {'APPLY' if report['applied'] else 'dry-run'}")
        if report["findings"]:
            print("  未完成/未删的项：")
            for f in report["findings"]:
                print(f"    - [{f.get('code')}] {f.get('message')}")
        d = report["deleted"]
        print(f"  评估: {', '.join(d['assessments']) or '（无）'}"
              f" · 快照: {', '.join(d['snapshots']) or '（无）'}")
        print(f"  工作单: {len(d['runs'])} 个 · 残锁: {len(d['locks'])} 个")
        for s in report["skipped_snapshots"]:
            print(f"  跳过快照 {s['commit']}：{s['reason']}")
        if d["kept"]:
            print("  保留: " + "; ".join(f"{k}（{report['kept_reasons'].get(k, '')}）"
                                        for k in d["kept"]))
        if not report["applied"]:
            print("  （dry-run：未删任何文件）")
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
