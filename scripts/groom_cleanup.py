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
#   python3 scripts/groom_cleanup.py --pr-body-file <body> [--base <ref>] [--head <ref>]
#   python3 scripts/groom_cleanup.py --pr-body-file <body> --post-merge \
#       --base <合并前 base> --head <合入提交>      # 合入后清理：跳过过期判定
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
    repo_root, sanitize_key, shared_inbox, short_sha,
)
from groom_recheck import check as recheck_check
from groom_snapshot import cleanup_snapshot

TERMINAL_DECISIONS = ("new_pattern", "variant", "covered")
SNAPSHOT_IN_USE_MINUTES = 30
RUNS_KEEP_DAYS = 1          # 工作单可重生成；超过一天视作上一轮的残留（避开在途 run）
LOCK_KEEP_DAYS = 7          # 只清「对应 sidecar 已不存在」的旧锁；持有中的锁 mtime 会变
TEMP_KEEP_HOURS = 24        # `.groom/**/*.tmp` 与 `.groom/tmp/`：超过一天视为残留
SNAPSHOT_ORPHAN_HOURS = 24  # 无主快照：没有任何评估或工作单引用，且超过一天


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


def _find_snapshots(inbox: Path, snapshot_dir, commit: str) -> list:
    """按短 SHA 找出该提交的所有快照（可能多分支）。

    返回 [(branch, base, worktree, meta)]；找不到才允许判「已清」。
    """
    base = Path(snapshot_dir) if snapshot_dir else (inbox / ".groom" / "snapshots")
    short = short_sha(commit)
    if not base.is_dir():
        return []
    suffix = "-" + short
    found = []
    for item in sorted(base.iterdir()):
        if item.is_dir() and item.name.endswith(suffix):
            branch = item.name[: -len(suffix)]
            found.append((branch, base, item, base / (item.name + ".json")))
    for item in sorted(base.iterdir()):
        if item.is_file() and item.name.endswith(suffix + ".json"):
            name = item.name[: -len(suffix + ".json")]
            worktree = base / (name + suffix)
            if not any(entry[2] == worktree for entry in found):
                found.append((name, base, worktree, item))
    return found


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


def _previously_deleted(inbox: Path) -> dict:
    """cleanup-log 里删过的评估：key → {(assessment_id, content_sha256)}。

    只认带身份的记录；旧日志只有 key、没有评估 ID 与内容指纹，不能证明本次该删的
    就是那一份，所以不据此判「已删」。
    """
    path = inbox / ".groom" / "cleanup-log.jsonl"
    done = {}
    if not path.is_file():
        return done
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return done
    for line in lines:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        deleted = obj.get("deleted") if isinstance(obj.get("deleted"), dict) else {}
        for rec in deleted.get("assessment_records") or []:
            key = str(rec.get("draft") or "")
            if not key:
                continue
            done.setdefault(key, set()).add(
                (str(rec.get("assessment_id") or ""), str(rec.get("content_sha256") or "")))
    return done


def _delete_sidecars(inbox: Path, eligible, report: dict, apply: bool,
                     deleted_before: set = None):
    """返回 (removed_paths, decision_details)。删除失败/锁异常都只记录，不抛出。"""
    deleted_before = deleted_before or {}
    removed_paths, details = set(), []
    for marker in eligible:
        key = str(marker.get("draft") or "").strip()
        if not key:
            continue
        sidecar = assessment_path(inbox, key)
        if not sidecar.exists():
            # 上一轮已经删过，且身份与内容指纹都对得上：评估文件本来就不该在，
            # 不能当成本轮失败一直重试。只按 key 匹配会误伤新评估，必须带身份。
            record = (str(marker.get("assessment_id") or ""),
                      str(marker.get("human_decision_content_sha256") or ""))
            if record in (deleted_before.get(key) or set()):
                report["already_deleted"]["assessments"].append(key)
            else:
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
                report["deleted"]["assessment_records"].append({
                    "draft": key,
                    "assessment_id": str(marker.get("assessment_id") or ""),
                    "content_sha256": str(marker.get("human_decision_content_sha256") or ""),
                })
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
            report["deleted"]["assessment_records"].append({
                "draft": key,
                "assessment_id": str(marker.get("assessment_id") or ""),
                "content_sha256": str(marker.get("human_decision_content_sha256") or ""),
            })
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
            report["skipped_snapshots"].append(
                {"commit": commit[:12], "reason": "仍被其他评估引用"})
            continue
        found = _find_snapshots(inbox, snapshot_dir, commit)
        if not found:
            report["already_deleted"]["snapshots"].append(commit[:12])
            continue
        for actual_branch, snap_base, worktree, meta in found:
            if _snapshot_in_use(snap_base, commit):
                report["skipped_snapshots"].append(
                    {"commit": commit[:12], "reason": "最近一次快照就是它且刚创建，可能有 session 在用"})
                continue
            record = {"commit": commit[:12], "branch": actual_branch, "path": str(worktree)}
            if not apply:
                report["deleted"]["snapshots"].append(commit[:12])
                report["deleted"]["snapshot_records"].append(record)
                continue
            try:
                result = cleanup_snapshot_fn(repo, snapshot_dir=snapshot_dir, commit=commit,
                                             branch=actual_branch)
            except Exception as exc:
                report["ok"] = False
                report["findings"].append({"severity": "error", "code": "snapshot-cleanup-failed",
                                           "message": f"{commit[:12]} ({actual_branch}): {exc}"})
                continue
            removed = bool(result.get("worktree_removed") or result.get("meta_removed"))
            if result.get("ok") and removed:
                report["deleted"]["snapshots"].append(commit[:12])
                report["deleted"]["snapshot_records"].append(record)
            elif result.get("ok"):
                report["already_deleted"]["snapshots"].append(commit[:12])
            else:
                report["ok"] = False
                report["findings"].append({
                    "severity": "error", "code": "snapshot-cleanup-failed",
                    "message": f"{commit[:12]} ({actual_branch}): {result.get('error', '')}"})


def _clean_runs(inbox: Path, apply: bool, report: dict, keep_days: float):
    """删超过 keep_days 的工作单目录（`.groom/runs/<run-id>/`）。可重生成，风险低。"""
    runs_dir = inbox / ".groom" / "runs"
    if not runs_dir.is_dir():
        return
    cutoff = time.time() - keep_days * 86400
    for child in sorted(runs_dir.iterdir()):
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        if apply:
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except OSError as exc:
                report["ok"] = False
                report["findings"].append({"severity": "error", "code": "runs-cleanup-failed",
                                           "message": f"{child.name}: {exc}"})
                continue
        report["deleted"]["runs"].append(child.name)


def _clean_temp_files(inbox: Path, apply: bool, report: dict, keep_hours: float):
    """清 `.groom/` 下超过 keep_hours 的临时文件：`*.tmp` 与 `.groom/tmp/` 里的内容。

    这些是写盘中断或旧轮次留下的中间件，不承载判断依据；新生成的临时文件不会
    被同一轮清理碰到（有 keep_hours 窗口）。
    """
    base = inbox / ".groom"
    if not base.is_dir():
        return
    cutoff = time.time() - keep_hours * 3600
    candidates = list(base.rglob("*.tmp"))
    tmp_dir = base / "tmp"
    if tmp_dir.is_dir():
        candidates += [p for p in tmp_dir.rglob("*") if p.is_file()]
    for path in sorted(set(candidates)):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        if apply:
            try:
                path.unlink()
            except OSError as exc:
                report["ok"] = False
                report["findings"].append({"severity": "error", "code": "temp-cleanup-failed",
                                           "message": f"{path}: {exc}"})
                continue
        report["deleted"]["temp_files"].append(
            str(path.relative_to(inbox)).replace("\\", "/"))


def _referenced_snapshot_commits(inbox: Path, repo: Path, base: Path) -> tuple:
    """所有还在被引用的快照 commit：评估记录、工作单、latest.json。"""
    commits, unreadable = _scan_references(inbox, repo)
    runs = inbox / ".groom" / "runs"
    if runs.is_dir():
        for path in sorted(runs.glob("*/work-orders.json")):
            try:
                doc = load_json(path) or {}
            except Exception:
                # 工作单读不出：它可能引用某个快照，视为引用未知，整轮不删无主快照。
                unreadable.append(path.name)
                continue
            raw = (doc.get("snapshot") or {}).get("commit") if isinstance(doc, dict) else None
            if raw:
                normalized = normalize_commit(repo, str(raw))
                if normalized:
                    commits.add(normalized)
    latest = base / "latest.json"
    if latest.exists():
        try:
            doc = load_json(latest) or {}
        except Exception:
            unreadable.append(latest.name)
            doc = {}
        raw = doc.get("commit") if isinstance(doc, dict) else None
        if raw:
            normalized = normalize_commit(repo, str(raw))
            if normalized:
                commits.add(normalized)
    return commits, unreadable


def _clean_orphan_snapshots(inbox: Path, repo: Path, apply: bool, report: dict,
                            snapshot_dir, branch: str, cleanup_snapshot_fn,
                            keep_hours: float):
    """删没有任何评估或工作单引用的旧快照（别的轮次留下的无主目录）。"""
    base = Path(snapshot_dir) if snapshot_dir else (inbox / ".groom" / "snapshots")
    if not base.is_dir():
        return
    referenced, unreadable = _referenced_snapshot_commits(inbox, repo, base)
    if unreadable:
        report["ok"] = False
        report["findings"].append({
            "severity": "error", "code": "orphan-snapshot-scan-skipped",
            "message": f"有 {len(unreadable)} 份评估或工作单读不出，无法判断快照是否仍被引用——本轮不删无主快照"})
        return
    cutoff = time.time() - keep_hours * 3600
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        meta = base / f"{child.name}.json"
        if not meta.exists():
            continue
        try:
            doc = load_json(meta) or {}
        except Exception:
            report["ok"] = False
            report["findings"].append({"severity": "error", "code": "orphan-snapshot-meta",
                                       "message": f"{meta.name}: 读不出，跳过"})
            continue
        commit = normalize_commit(repo, str((doc or {}).get("commit") or ""))
        if not commit or commit in referenced:
            continue
        # 目录可能是别的分支留下的：优先用元数据里的实际分支，其次从目录名
        # `<safe_branch>-<short_sha>` 回退。不能拿本轮 branch 去猜，否则会去删
        # 另一条路径，原目录还在而 cleanup_snapshot 仍返回成功。
        actual_branch = str((doc or {}).get("branch") or "").strip()
        if not actual_branch:
            actual_branch = child.name.rsplit("-", 1)[0] if "-" in child.name else branch
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        if not apply:
            report["deleted"]["orphan_snapshots"].append(commit[:12])
            continue
        try:
            result = cleanup_snapshot_fn(repo, snapshot_dir=base, commit=commit,
                                         branch=actual_branch)
        except Exception as exc:
            report["ok"] = False
            report["findings"].append({"severity": "error", "code": "orphan-snapshot-failed",
                                       "message": f"{commit[:12]}（{actual_branch}）：{exc}"})
            continue
        if not isinstance(result, dict) or not result.get("ok"):
            report["ok"] = False
            detail = result.get("error") if isinstance(result, dict) else ""
            report["findings"].append({"severity": "error", "code": "orphan-snapshot-failed",
                                       "message": f"{commit[:12]}（{actual_branch}）：{detail or '清理失败'}"})
            continue
        # cleanup_snapshot 找不到路径也会返回成功；以实际目录是否消失为准。
        if child.exists():
            report["ok"] = False
            report["findings"].append({"severity": "error", "code": "orphan-snapshot-still-there",
                                       "message": f"{child.name}：清理函数返回成功但目录仍在"})
            continue
        report["deleted"]["orphan_snapshots"].append(commit[:12])


def _clean_stale_locks(inbox: Path, apply: bool, report: dict, keep_days: float):
    """删「对应 sidecar 已不存在」的锁文件。

    两种残锁直接清：评估记录已归档到 `.done/<key>/assessment.yaml` 的（评估走了，
    锁不可能再被持有），以及超过 keep_days 的旧锁。持锁中的文件 mtime 会随写入更新，
    所以「旧 + 没有对应 sidecar」同时成立时判定为残锁。`.guard.lock` 不清。
    """
    assess_dir = inbox / ".groom" / "assessments"
    if not assess_dir.is_dir():
        return
    archived = set()
    done_dir = inbox / ".done"
    if done_dir.is_dir():
        for child in done_dir.iterdir():
            if child.is_dir() and (child / "assessment.yaml").exists():
                archived.add(sanitize_key(child.name))
    cutoff = time.time() - keep_days * 86400
    for lock in sorted(assess_dir.glob("*.lock")):
        if lock.name == ".guard.lock":
            continue
        target = lock.with_suffix("")
        if target.exists():
            continue
        sanitized = lock.name[: -len(".yaml.lock")]
        if sanitized not in archived:
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
            lock_keep_days: float = LOCK_KEEP_DAYS,
            snapshot_orphan_hours: float = SNAPSHOT_ORPHAN_HOURS,
            temp_keep_hours: float = TEMP_KEEP_HOURS, post_merge: bool = False):
    repo = Path(repo).resolve()
    inbox = shared_inbox(repo)
    findings, ctx = check_fn(body, repo, base, head, False, post_merge=post_merge)
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
                    "assessment_records": [], "snapshot_records": [],
                    "orphan_snapshots": [], "temp_files": [], "runs": [], "locks": []},
        "already_deleted": {"assessments": [], "snapshots": []},
        "skipped_snapshots": [],
        "kept_reasons": {},
        "findings": blocking,
        "complete": False,
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
        removed, details = _delete_sidecars(inbox, eligible, report, apply,
                                            deleted_before=_previously_deleted(inbox))
        if details:
            report.setdefault("decision_details", []).extend(details)
        _delete_snapshots(inbox, repo, eligible, report, apply, snapshot_dir, branch,
                          cleanup_snapshot_fn, planned_paths=removed)
        _clean_runs(inbox, apply, report, runs_keep_days)
        _clean_stale_locks(inbox, apply, report, lock_keep_days)
        _clean_orphan_snapshots(inbox, repo, apply, report, snapshot_dir, branch,
                                cleanup_snapshot_fn, snapshot_orphan_hours)
        _clean_temp_files(inbox, apply, report, temp_keep_hours)

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

    report["complete"] = bool(report["ok"] and not report["findings"]
                              and not report["deleted"]["kept"]
                              and not report["skipped_snapshots"])

    if apply:
        entry = {
            "at": report["checked_at"],
            "pr": pr_label,
            "base": report["base"], "head": report["head"],
            "applied": True,
            "deleted": report["deleted"],
            "already_deleted": report["already_deleted"],
            "skipped_snapshots": report["skipped_snapshots"],
            "kept_reasons": report["kept_reasons"],
            "decision_details": report.get("decision_details") or [],
            "ok": report["ok"],
            "complete": report["complete"],
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
    ap.add_argument("--base", default=None,
                    help="比较基准 ref（默认按 settings 的 target，未配置用归属仓默认分支，"
                         "解析不到用 origin/main）")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--branch", default="main", help="建快照时用的分支（默认 main）")
    ap.add_argument("--pr", default=None, help="PR 标识（URL 或编号），写进清理日志")
    ap.add_argument("--post-merge", action="store_true",
                    help="PR 已合入后清理：跳过评估过期判定，保留 marker 与内容绑定检查")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印计划、不删（默认直接执行）")
    ap.add_argument("--snapshot-dir", default=None)
    ap.add_argument("--keep-runs-days", type=float, default=RUNS_KEEP_DAYS,
                    help=f"工作单超过这么多天就清（默认 {RUNS_KEEP_DAYS}）")
    ap.add_argument("--keep-lock-days", type=float, default=LOCK_KEEP_DAYS,
                    help=f"无对应 sidecar 的锁超过这么多天就清（默认 {LOCK_KEEP_DAYS}）")
    ap.add_argument("--keep-snapshot-hours", type=float, default=SNAPSHOT_ORPHAN_HOURS,
                    help=f"无主快照超过这么多小时就清（默认 {SNAPSHOT_ORPHAN_HOURS}）")
    ap.add_argument("--keep-temp-hours", type=float, default=TEMP_KEEP_HOURS,
                    help=f".groom 下的临时文件超过这么多小时就清（默认 {TEMP_KEEP_HOURS}）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    body_path = Path(args.pr_body_file)
    if not body_path.exists():
        print(f"groom_cleanup: 找不到 PR body：{body_path}", file=sys.stderr)
        return 3
    root = repo_root(Path(args.repo).resolve() if args.repo else Path.cwd())
    base = args.base
    if base is None:
        try:
            from pr_status import effective_base
            base = effective_base(root)
        except Exception:
            base = "origin/main"
    report = cleanup(body_path.read_text(encoding="utf-8"), root, base, args.head,
                     apply=not args.dry_run, snapshot_dir=args.snapshot_dir,
                     branch=args.branch, pr_label=args.pr,
                     runs_keep_days=args.keep_runs_days, lock_keep_days=args.keep_lock_days,
                     snapshot_orphan_hours=args.keep_snapshot_hours,
                     temp_keep_hours=args.keep_temp_hours,
                     post_merge=args.post_merge)
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
              f" · 快照: {', '.join(d['snapshots']) or '（无）'}"
              f" · 无主快照: {', '.join(d['orphan_snapshots']) or '（无）'}"
              f" · 临时文件: {len(d['temp_files'])}")
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
