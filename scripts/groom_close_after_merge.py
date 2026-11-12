#!/usr/bin/env python3
# groom_close_after_merge.py —— 确认 PR 合入后的统一收尾入口。
#
# 为什么需要它：Copilot 查到 PR 已合入后，后台要按同一套证据做收尾：核对 PR body
# 里的评估标记、从合入提交读取产物、写回 trace、把草稿移出 inbox，最后清评估记录与
# 无引用快照。groom 开场发现台账里已是 merged 的事项也走这里，两条入口共用一份实现。
#
# 它与 `groom_close_draft.py` 的分工：后者是「本地决定落盘后直接收尾」（含无 PR 部署），
# 不做 PR body 与合入提交核对；本脚本只处理「已合入」这一档，证据不足不写状态。
#
# 用法：
#   python3 scripts/groom_close_after_merge.py --pr-body-file <body> --merge <sha>
#   python3 scripts/groom_close_after_merge.py --pr-body-file <body> --merge <sha> --apply
#   python3 scripts/groom_close_after_merge.py --pr-body-file <body> --merge <sha> \
#       --draft-key <key> --apply                  # 单条查询只收尾选中的草稿
#
# 默认只打印计划；`--apply` 才写。收尾成功后默认调用 `groom_cleanup.py --post-merge`
# 的同一实现（`--no-cleanup` 可关，用于只补收尾、留给下一轮清理的场景）。
#
# 退出码：0 = 全部处理完（含跳过）；2 = 有证据不足或执行失败。

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - 环境问题，明确报错而不是静默
    sys.exit("需要 PyYAML：pip install pyyaml")

from _stdio import pin_utf8_stdio
from exec_log_path import resolve_traces
from groom_common import (
    canonical_content_sha, dump_json, find_drafts, load_assessment, now_iso,
    repo_root, run_git, sha256_full, shared_inbox,
)
from groom_close_draft import (
    TARGET_STATE, append_log, knowledge_cases, move_draft, plan_one,
    promoted_postmortem, writeback_trace,
)
from groom_recheck import parse_markers, validate_marker

MARKER_SCHEMA = "groom-pr/v2"


def _binding_mismatches(marker: dict, doc: dict) -> list:
    """marker 与本地评估是否同一次评估、同一份内容、同一个决定。"""
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


def _git_show(root: Path, commit: str, rel: str):
    proc = run_git(["show", f"{commit}:{rel}"], cwd=root, check=False)
    if proc.returncode != 0:
        return None, f"读取 {commit}:{rel} 失败：{proc.stderr.strip()}"
    return proc.stdout, None


def _case_path(root: Path, case_id: str):
    """在 knowledge/ 里找最终 case 的仓库相对路径。"""
    base = root / "knowledge"
    if not base.is_dir():
        return None
    for path in sorted(base.rglob("*.yaml")):
        if path.name.startswith("_") or "_archive" in path.parts:
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for case in data.get("cases") or []:
            if isinstance(case, dict) and str(case.get("id") or "") == case_id:
                return path
    return None


def _case_sha_from_text(text: str, case_id: str):
    try:
        data = yaml.safe_load(io.StringIO(text))
    except Exception as exc:
        return None, f"提交内容不是合法 YAML：{exc}"
    if not isinstance(data, dict):
        return None, "提交内容顶层不是对象"
    for case in data.get("cases") or []:
        if isinstance(case, dict) and str(case.get("id") or "") == case_id:
            return canonical_content_sha(case), None
    return None, f"提交内容里找不到 case {case_id}"


def _text_sha(text: str) -> str:
    return sha256_full(text.replace("\r\n", "\n").replace("\r", "\n"))


def _isolated_root(root: Path, merge: str):
    """在合入提交上建隔离检出：内容核对与索引检查都不读当前工作树。

    工作树可能停在合入前的分支，也没有主干 job 重建后的生成物；收尾的判断对象是
    「合入提交里的内容」，所以固定这份 commit 单独检出。临时目录放在共享 inbox 下，
    落在插件 shell 的 workspace-write 根里。
    """
    parent = shared_inbox(root) / ".groom" / "tmp"
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, f"创建临时目录失败：{exc}"
    path = parent / f"close-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    proc = run_git(["worktree", "add", "--detach", "--quiet", str(path), merge],
                   cwd=root, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return None, (detail[-1] if detail else f"git worktree add 退出 {proc.returncode}")
    return path, None


def _remove_isolated(root: Path, path: Path) -> None:
    proc = run_git(["worktree", "remove", "--force", str(path)], cwd=root, check=False)
    if proc.returncode != 0 and path.exists():
        shutil.rmtree(path, ignore_errors=True)
        run_git(["worktree", "prune"], cwd=root, check=False)


def _rebuild_index(root: Path):
    """按固定内容重建生成物，供 cleanup 的 post-merge 索引检查使用。"""
    script = root / "scripts" / "build_index.py"
    if not script.is_file():
        return False, "检出里没有 build_index.py"
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run([sys.executable, str(script)], cwd=str(root),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=180)
    except subprocess.TimeoutExpired:
        return False, "build_index 超时"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, (detail[-1] if detail else f"build_index 退出 {proc.returncode}")
    return True, ""


def plan_marker(root: Path, inbox: Path, marker: dict, merge: str) -> dict:
    """算一份 marker 的收尾计划；证据不足时 status=error 并给原因。"""
    key = str(marker.get("draft") or "")
    result = {"draft": key, "status": "error", "decision": None, "case_id": None,
              "state": None, "target_path": None, "reason": None}
    errors = validate_marker(marker)
    if errors:
        result["reason"] = "marker 无效：" + "；".join(errors)
        return result
    decision = str(marker.get("human_decision") or "")
    if decision not in TARGET_STATE:
        result["reason"] = f"不是终态决定（{decision}），不收尾"
        return result
    result["decision"] = decision
    result["state"] = TARGET_STATE[decision]

    drafts = {d.key: d for d in find_drafts(inbox)}
    draft = drafts.get(key)
    if draft is None:
        result["status"] = "skipped"
        result["reason"] = "草稿不在 inbox（可能已收尾或已撤销）"
        return result
    try:
        doc = load_assessment(inbox, key)
    except Exception as exc:
        result["reason"] = f"评估记录读不出：{exc}"
        return result
    if not doc:
        result["reason"] = "没有本地评估记录"
        return result
    mismatch = _binding_mismatches(marker, doc)
    if mismatch:
        result["reason"] = "marker 与本地评估不一致：" + "、".join(mismatch)
        return result

    if decision == "covered":
        path = promoted_postmortem(root, key=key, override=None)
        if path is None:
            result["reason"] = "covered 缺转正后的 postmortem（目录形草稿用 --postmortem 另行收尾）"
            return result
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        text, why = _git_show(root, merge, rel)
        if why:
            result["reason"] = why
            return result
        sha = _text_sha(text)
        result["target_path"] = rel
        result["content_sha256"] = sha
    else:
        case_id = str(marker.get("submitted_case_id") or marker.get("case_id") or "").strip()
        if not case_id:
            result["reason"] = "marker 没有 case id"
            return result
        path = _case_path(root, case_id)
        if path is None:
            result["reason"] = f"knowledge/ 里找不到 {case_id}"
            return result
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        text, why = _git_show(root, merge, rel)
        if why:
            result["reason"] = why
            return result
        sha, why = _case_sha_from_text(text, case_id)
        if why:
            result["reason"] = why
            return result
        if sha != marker.get("assessed_content_sha256"):
            result["reason"] = ("合入提交里的内容与 marker 记录的指纹不一致（评审可能改过内容），"
                                "保留待收尾，人工核对后再推")
            return result
        result["target_path"] = rel
        result["content_sha256"] = sha
        result["case_id"] = case_id

    knowledge = knowledge_cases(root)
    plan = plan_one(doc, draft, root, knowledge, None, None)
    if plan["status"] == "ignored":
        result["status"] = "skipped"
        result["reason"] = plan["reason"]
        return result
    if plan["status"] != "ready":
        result["reason"] = plan["reason"]
        return result
    if decision != "covered" and plan["case_id"] != result["case_id"]:
        result["reason"] = (f"marker 的 case id 与本地评估不一致（{result['case_id']} ≠ "
                            f"{plan['case_id']}）")
        return result
    result.update({"status": "ready", "case_id": plan["case_id"], "state": plan["state"],
                   "session": plan["session"], "decision": decision, "plan": plan})
    return result


def _closelog_last(inbox: Path, key: str):
    """收尾日志里该草稿的最后一条 closed 记录；评估文件已删时用来续跑清理。"""
    path = inbox / ".groom" / "close-log.jsonl"
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None
    last = None
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if (isinstance(record, dict) and record.get("draft") == key
                and record.get("status") == "closed"):
            last = record
    return last


def _markers_from_sidecars(inbox: Path, keys: list, merge: str = "") -> tuple:
    """没有 PR body 时，用本地评估记录构造 marker。

    A 方案：评估本身就在本地 sidecar 里，PR body 只是给评审看的副本；
    收尾只需要 sidecar 的评估 ID、内容指纹与人决定。
    """
    markers = []
    for key in keys:
        try:
            doc = load_assessment(inbox, key)
        except Exception as exc:
            return [], f"评估记录读不出：{key}：{exc}"
        if not doc:
            # 收尾已成功、评估文件已被首轮清理删除：用收尾日志续跑，
            # 否则被引用而没有删掉的快照永远清不到。
            record = _closelog_last(inbox, key)
            if not record:
                return [], f"没有本地评估记录，也没有收尾记录：{key}"
            recorded_merge = str(record.get("merge") or "")
            if not recorded_merge or (merge and recorded_merge != merge):
                return [], (f"收尾日志的合入提交与本次不一致（记录 "
                            f"{recorded_merge[:12] or '空'}，本次 {merge[:12] or '空'}）；"
                            "不跨合入 SHA 复用清理记录")
            case_id = str(record.get("case_id") or key)
            markers.append({
                "schema": MARKER_SCHEMA,
                "category": str(record.get("category") or ""),
                "review_required": str(record.get("review_required") or "false"),
                "candidate_case": str(record.get("candidate_case") or ""),
                "draft": key,
                "human_decision": record.get("decision"),
                "approval_stale": False,
                "assessed_commit": str(record.get("assessed_commit")
                                        or record.get("merge") or ""),
                "assessment_id": str(record.get("assessment_id") or ""),
                "assessed_content_sha256": str(record.get("assessed_content_sha256") or ""),
                "human_decision_assessment_id": str(record.get("assessment_id") or ""),
                "human_decision_content_sha256": str(record.get("assessed_content_sha256") or ""),
                "submitted_case_id": case_id,
                "case_id": case_id,
                "proposed_novelty": "new_pattern",
            })
            continue
        human = doc.get("human_decision") or {}
        binding = doc.get("content_binding") or {}
        provenance = doc.get("provenance") or {}
        decision = str(human.get("decision") or "")
        candidate = str(human.get("candidate_case")
                        or doc.get("candidate_case") or "")
        # variant / duplicate 的落点是候选 case，不是草稿自己的 ID。
        case_id = (candidate if decision in ("variant", "duplicate") and candidate
                   else str(doc.get("draft_case_id") or key))
        markers.append({
            "schema": MARKER_SCHEMA,
            "category": str(doc.get("category") or ""),
            "review_required": "true" if doc.get("review_required") is True else "false",
            "candidate_case": candidate,
            "draft": key,
            "human_decision": human.get("decision"),
            "approval_stale": False,
            "assessed_commit": str(provenance.get("compared_against_commit") or ""),
            "assessment_id": str(doc.get("assessment_id") or ""),
            "assessed_content_sha256": str(binding.get("sha256") or ""),
            "human_decision_assessment_id": str(human.get("assessment_id") or ""),
            "human_decision_content_sha256": str(human.get("content_sha256") or ""),
            "submitted_case_id": case_id,
            "case_id": case_id,
            "proposed_novelty": "new_pattern",
        })
    return markers, None


def _render_marker_body(markers: list) -> str:
    """把本地评估构造的 marker 渲染成 cleanup 能重新解析的 body。"""
    fields = ("schema", "draft", "case_id", "submitted_case_id", "category",
              "assessed_commit", "assessment_id", "assessed_content_sha256",
              "proposed_novelty", "candidate_case", "human_decision",
              "human_decision_assessment_id", "human_decision_content_sha256",
              "review_required")
    blocks = []
    for marker in markers:
        lines = ["<!-- groom-assessment"]
        for name in fields:
            value = marker.get(name)
            lines.append(f"{name}: {'' if value is None else value}")
        lines.append("-->")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def run(args) -> int:
    root = repo_root(Path(args.repo).resolve() if args.repo else Path.cwd())
    inbox = shared_inbox(root)
    if not inbox.is_dir():
        print(f"找不到 inbox：{inbox}", file=sys.stderr)
        return 2
    merge = args.merge or ""
    if not merge:
        print("需要 --merge（合入提交 SHA）", file=sys.stderr)
        return 2
    body = ""
    markers = []
    if args.pr_body_file:
        body_path = Path(args.pr_body_file)
        if not body_path.is_file():
            print(f"读不到 PR body：{body_path}", file=sys.stderr)
            return 2
        body = body_path.read_text(encoding="utf-8-sig", errors="replace")
        markers = parse_markers(body)
        if args.draft_key:
            wanted = set(args.draft_key)
            markers = [m for m in markers if str(m.get("draft") or "") in wanted]
    else:
        if not args.draft_key:
            print("需要 --pr-body-file，或用 --draft-key 从本地评估记录收尾", file=sys.stderr)
            return 2
        markers, why = _markers_from_sidecars(inbox, args.draft_key, merge)
        if why:
            print(why, file=sys.stderr)
            return 2
    if not markers:
        if args.json:
            print(dump_json({"applied": bool(args.apply), "results": []}))
        else:
            print("PR body 里没有可处理的评估标记。")
        return 0

    content, why = _isolated_root(root, merge)
    if content is None:
        print(f"无法在合入提交 {merge[:12]} 上建立隔离检出：{why}", file=sys.stderr)
        return 2

    traces = Path(args.traces) if args.traces else resolve_traces(root)
    results = []
    failed = False
    cleanup_report = None
    try:
        if not args.no_cleanup:
            # cleanup 的 post-merge 索引检查读的是这份隔离检出；先按固定内容重建生成物。
            rebuilt, rebuild_why = _rebuild_index(content)
            if not rebuilt:
                print(f"警告：隔离检出的索引重建失败：{rebuild_why}", file=sys.stderr)
        for marker in markers:
            plan = plan_marker(content, inbox, marker, merge)
            if plan["status"] == "ready" and args.apply:
                draft = {d.key: d for d in find_drafts(inbox)}[plan["draft"]]
                try:
                    if plan.get("session"):
                        plan["trace"] = writeback_trace(content, traces, plan["session"],
                                                        plan["state"], plan["case_id"])
                    plan["moved"] = move_draft(draft, inbox / ".done", apply=True)
                    append_log(inbox, {
                        "at": now_iso(), "draft": plan["draft"], "decision": plan["decision"],
                        "case_id": plan["case_id"], "state": plan["state"],
                        "session": plan.get("session"), "trace": plan.get("trace", "skipped"),
                        "moved": plan["moved"], "status": "closed",
                        "mode": "after-merge", "merge": merge,
                        "assessed_commit": marker.get("assessed_commit"),
                        "assessment_id": marker.get("assessment_id"),
                        "assessed_content_sha256": marker.get("assessed_content_sha256"),
                        "category": marker.get("category"),
                        "review_required": marker.get("review_required"),
                        "candidate_case": marker.get("candidate_case"),
                    })
                except Exception as exc:
                    plan["status"] = "error"
                    plan["reason"] = f"收尾失败：{exc}"
            if plan["status"] == "error":
                failed = True
            results.append({k: v for k, v in plan.items() if k != "plan"})

        if args.apply and not args.no_cleanup and not failed:
            try:
                from groom_cleanup import cleanup as cleanup_fn
                cleanup_report = cleanup_fn(body or _render_marker_body(markers), content,
                                            args.base or f"{merge}^1", merge,
                                            apply=True, post_merge=True)
            except Exception as exc:
                cleanup_report = {"ok": False, "error": str(exc)}
            if isinstance(cleanup_report, dict) and cleanup_report.get("ok") is False:
                failed = True

        if args.json:
            print(dump_json({"ok": not failed, "applied": bool(args.apply), "merge": merge,
                             "results": results, "cleanup": cleanup_report}))
        else:
            for r in results:
                print(f"{r['status']:<8} {r['draft']}"
                      + (f" → {r['state']}" if r.get("state") else "")
                      + (f" · {r['reason']}" if r.get("reason") else ""))
            if cleanup_report is not None:
                kept = cleanup_report.get("deleted", {}).get("kept", []) if isinstance(cleanup_report, dict) else []
                print(f"\n清理：{'完成' if cleanup_report.get('ok') else '未完成'}"
                      + (f"（保留 {len(kept)} 项）" if kept else ""))
                if not cleanup_report.get("ok"):
                    for finding in cleanup_report.get("findings") or []:
                        print(f"清理失败：{finding.get('code')} {finding.get('message')}")
                    if cleanup_report.get("error"):
                        print(f"清理失败：{cleanup_report['error']}")
        return 2 if failed else 0
    finally:
        _remove_isolated(root, content)


def main(argv=None) -> int:
    pin_utf8_stdio()
    ap = argparse.ArgumentParser(description="PR 合入后的统一收尾入口")
    ap.add_argument("--pr-body-file", default=None,
                    help="PR body 文件（含 groom marker）；不给时用 --draft-key 从本地评估收尾")
    ap.add_argument("--merge", required=True, help="合入提交 SHA")
    ap.add_argument("--base", default=None, help="合入前 base（默认 <merge>^1）")
    ap.add_argument("--draft-key", action="append", default=None,
                    help="只处理这些草稿 key（可重复）")
    ap.add_argument("--repo", default=None, help="仓库根（默认当前目录）")
    ap.add_argument("--traces", default=None, help="traces 目录（默认主检出那一份）")
    ap.add_argument("--apply", action="store_true", help="真正执行；不给只打印计划")
    ap.add_argument("--no-cleanup", action="store_true",
                    help="收尾成功后不调用清理（留给下一轮 groom 补清）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except RuntimeError as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
