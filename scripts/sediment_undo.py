#!/usr/bin/env python3
# sediment_undo.py —— 撤销一次沉淀动作：草稿出队、评估状态文件清除、来源 trace 还原
#
# 为什么需要：沉淀一次写三处——草稿落 `postmortems/inbox/`、来源 trace 的 `sedimented`
# 置 `submitted`、groom 评估落 sidecar。草稿选错了（重复、来源认错、结论不成立）时，
# 界面只能逐个手改：删草稿、删 sidecar、改 trace。漏一步都不报错，队列会停在
# 「trace 说已交草稿、inbox 里没有」或「草稿没了、评估状态文件还在」这类不一致状态。
# 本脚本把这几步按顺序做完，每步都写进报告。
#
# 撤销只还原 case 的沉淀状态：`sedimented` 回 `none`、草稿出队、评估状态文件删除；诊断状态
# （`resolved` / `in_progress` 等）保持不变。想继续定位时，在诊断面板用「重新打开」。
# 想连 trace 都不动时用 `--keep-trace`。
#
# 批量：`--draft-key` 可重复。逐份建计划、逐份执行，某份被拒不会拦下其他份。计划模式下
# 只要有可撤销的份就退出 0（拒绝项照常列出）；执行模式下任一份失败退出 2。
#
# 与 `groom_close_draft.py` 的分工：那个是「沉淀成立之后的收尾」（升格 / 覆盖 / 归档，
# 草稿移进 `.done/`，trace 改成 `knowledge` / `archived`）；本脚本是「沉淀不成立，
# 撤回这次提交」。
#
# 为什么 trace 可以回 `none`：`groom_close_draft.py` 里那条纪律说 reject / defer 不改
# trace——因为草稿确实提交过、只是没转正，改回 `none` 等于抹掉事实。撤销不同：草稿与
# 评估状态文件一起撤回，重新沉淀会从头开始，`submitted` 已不成立，`none` 才是撤完的真实
# 状态。撤掉的东西在 `.groom/undo-log.jsonl` 留一行（评估 id、人决定、草稿去向、诊断状态变化）。
#
# 边界：
#   - 只处理还在 inbox 的草稿。已出队（`.done/`）的用「恢复草稿」流程；已升格的草稿
#     不在这里删，那会牵动知识库与 PR。
#   - PR 台账里这份草稿有任何记录（open / merged / unknown / closed）就拒绝：PR 是外部
#     事实，删本地草稿不会关掉它，先确认 PR 再谈撤销。
#   - 来源 trace 已经是 `knowledge` / `archived` 时拒绝：升格已经发生，撤回要牵动知识库与
#     PR，走知识库变更流程；这里只处理提交阶段（`submitted`）的草稿。
#   - 草稿移进 `postmortems/inbox/.undone/`（移动不删除，移回即复活）。`find_drafts`
#     不扫点目录，所以移走后不再进队列。撤销后草稿留在 `.undone/`，没有保留期；
#     确认不再需要后手工删。
#   - 来源 trace 缺失或没记来源（外部 issue 来源）时只出队 + 删评估状态文件，回写跳过并写明。
#   - 默认只打印计划；`--apply` 才写。
#
# 用法：
#   python3 scripts/sediment_undo.py --draft-key <key>                 # 计划（不写）
#   python3 scripts/sediment_undo.py --draft-key <key> --apply         # 执行
#   python3 scripts/sediment_undo.py --draft-key a --draft-key b --apply   # 批量
#   python3 scripts/sediment_undo.py --draft-key <key> --apply --json  # 机器可读
#
# 单份的 JSON 是平铺结果；批量是 `{ok, dryRun, results[], summary}`。重复执行同一份会报
# `E_NO_DRAFT`（草稿已出队），批量重跑时跳过这类即可。
#
# 退出码：0 = 计划已打印（批量下至少一份可撤销），或撤销已完成；2 = 被边界拦下 / 执行失败 / 参数错。

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _stdio import pin_utf8_stdio  # noqa: E402
from _yaml import load_text  # noqa: E402
from exec_log_path import log_lock, resolve_traces  # noqa: E402
from groom_close_draft import source_session_of  # noqa: E402
from groom_common import (  # noqa: E402
    assessment_guard, assessment_path, find_drafts, load_assessment,
    now_iso, repo_root, shared_inbox, sanitize_key,
)
import pr_status  # noqa: E402

UNDONE_DIR = ".undone"
UNDO_LOG_REL = Path(".groom") / "undo-log.jsonl"


class Refused(RuntimeError):
    """被边界拦下或写到一半失败。`done` 记已经发生的步骤，失败报告据此说清现状。"""

    def __init__(self, code: str, message: str, done=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.done = list(done or [])


def _rel(root: Path, path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve())).replace("\\", "/")
    except (ValueError, OSError):
        return str(path)


def _stamp() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y%m%dT%H%M%S")


def _read_trace(path: Path) -> dict:
    """读 trace 的沉淀状态与字节指纹（一次读盘，供计划与 CAS 用）。"""
    raw = path.read_bytes()
    doc = load_text(raw.decode("utf-8-sig")) or {}
    if not isinstance(doc, dict):
        doc = {}
    sed = doc.get("sedimented")
    if isinstance(sed, dict):
        sedimented = str(sed.get("state") or "none")
    elif isinstance(sed, str) and sed.strip():
        sedimented = sed.strip()
    else:
        sedimented = "none"
    return {"sedimented": sedimented, "sha256": hashlib.sha256(raw).hexdigest()}


def _run_transition(root: Path, traces: Path, session: str, extra: list,
                    sha: str, by: str, label: str) -> dict:
    """经 `trace_transition.py` 写一份 trace（唯一写入口），返回它的 JSON 结果。"""
    script = Path(root) / "scripts" / "trace_transition.py"
    if not script.is_file():
        raise Refused("E_NO_TRANSITION", f"检出里缺少 {script}，不能回写 trace")
    cmd = [sys.executable, str(script), session,
           "--root", str(root), "--traces", str(traces),
           "--by", by, "--source", "cli", "--json"] + list(extra)
    if sha:
        cmd += ["--expect-sha256", sha]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    out = (proc.stdout or "").strip()
    try:
        payload = json.loads(out.splitlines()[-1]) if out else {}
    except (ValueError, IndexError):
        payload = {}
    if proc.returncode != 0 or not isinstance(payload, dict) or payload.get("ok") is False:
        message = (payload.get("message") if isinstance(payload, dict) else "") \
            or (proc.stderr or out or "trace_transition.py 没有返回 JSON").strip()
        raise Refused("E_TRACE", label + "失败：" + message)
    return payload


def _move_draft(root: Path, inbox: Path, draft, stamp: str, meta: dict) -> Path:
    """把草稿移进 `.undone/<时间>-<key>/`。

    移动用 `os.rename`：`inbox` 与 `.undone` 在同一文件系统，改名是原子的，不会在失败时
    留下复制出的一半。平铺草稿有 case 文件与可选 `.md`，任一失败就回滚已经改名的文件，
    草稿完整留在 inbox，可以直接重试。目录形态整目录改名，只有写 `.undo.json` 这一步
    在改名之后。
    """
    target = inbox / UNDONE_DIR / f"{stamp}-{sanitize_key(draft.key)}"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise Refused("E_MOVE", f"建回收目录失败（{exc}），本次没有移动草稿，可以直接重试") from exc
    if target.exists():
        raise Refused("E_EXISTS", f"回收位置已经存在，先处理它再撤销：{_rel(root, target)}")
    meta_text = json.dumps(meta, ensure_ascii=False, indent=2) + "\n"

    if draft.layout == "directory":
        source_dir = Path(draft.case_path).parent
        try:
            os.rename(str(source_dir), str(target))
        except OSError as exc:
            raise Refused("E_MOVE", f"移草稿失败，草稿仍在 inbox，可以直接重试：{exc}") from exc
        try:
            (target / ".undo.json").write_text(meta_text, encoding="utf-8")
        except OSError as exc:
            try:
                (target / ".undo.json").unlink(missing_ok=True)
            except OSError:
                pass
            try:
                os.rename(str(target), str(source_dir))
            except OSError as rollback_exc:
                raise Refused(
                    "E_MOVE",
                    f"草稿已移到 {_rel(root, target)}，写 undo 元数据失败（{exc}），"
                    f"移回也失败（{rollback_exc}）：先手工移回 inbox 再重试") from exc
            raise Refused("E_MOVE", f"写 undo 元数据失败（{exc}），草稿已移回 inbox，可以直接重试") from exc
        return target

    try:
        target.mkdir(parents=True)
    except OSError as exc:
        raise Refused("E_MOVE", f"建回收目录失败（{exc}），本次没有移动草稿，可以直接重试") from exc
    sources = [Path(draft.case_path)]
    if draft.postmortem_path is not None and Path(draft.postmortem_path).exists():
        sources.append(Path(draft.postmortem_path))
    try:
        (target / ".undo.json").write_text(meta_text, encoding="utf-8")
    except OSError as exc:
        try:
            target.rmdir()
        except OSError:
            pass
        raise Refused("E_MOVE", f"写 undo 元数据失败（{exc}），草稿没有移动，可以直接重试") from exc
    moved = []
    try:
        for src in sources:
            os.rename(str(src), str(target / src.name))
            moved.append(src)
    except OSError as exc:
        try:
            for src in moved:
                os.rename(str(target / src.name), str(src))
            (target / ".undo.json").unlink(missing_ok=True)
            target.rmdir()
        except OSError as rollback_exc:
            raise Refused(
                "E_MOVE",
                f"移草稿失败（{exc}），回滚也失败（{rollback_exc}）。先看 "
                f"{_rel(root, target)} 与 inbox，把草稿凑齐再重试") from exc
        raise Refused("E_MOVE", f"移草稿失败，已回滚、草稿仍在 inbox，可以直接重试：{exc}") from exc
    return target


def _append_undo_log(inbox: Path, entry: dict) -> Path:
    """追加一行 undo-log。拿不到锁就报告失败，不静默丢审计记录。"""
    path = inbox / UNDO_LOG_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    with log_lock(path) as held:
        if not held:
            raise Refused("E_LOCK", "undo-log 的写锁不可用（本平台没有锁原语），审计记录没写成")
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    return path


def _load_ledger(root: Path) -> dict:
    try:
        return pr_status.load_ledger(root)
    except Exception as exc:
        raise Refused("E_LEDGER", f"PR 台账读不了，先确认它没坏再撤销：{exc}") from exc


def build_plan(root: Path, inbox: Path, traces: Path, key: str,
               keep_trace: bool) -> dict:
    drafts = {draft.key: draft for draft in find_drafts(inbox)}
    draft = drafts.get(key)
    if draft is None:
        raise Refused("E_NO_DRAFT",
                      f"inbox 里没有这份草稿（{key}）。已出队的草稿用「恢复草稿」流程，不再撤销。")
    ledger = _load_ledger(root)
    prs = ledger.get("prs") if isinstance(ledger.get("prs"), dict) else {}
    if key in prs:
        entry = prs.get(key)
        if isinstance(entry, dict):
            state = str(entry.get("state") or "unknown")
            url = str(entry.get("url") or "")
            detail = f"state={state}{'，' + url if url else ''}"
        else:
            detail = "记录不是对象，台账可能被手改坏了"
        raise Refused("E_PR_EXISTS",
                      f"这份草稿在 PR 台账里有记录（{detail}）。"
                      "PR 是外部事实，先在平台上处理它，再撤销本地草稿。")
    sidecar = assessment_path(inbox, key)
    sidecar_sha = ""
    try:
        if sidecar.exists():
            sidecar_sha = hashlib.sha256(sidecar.read_bytes()).hexdigest()
        side_doc = load_assessment(inbox, key) if sidecar.exists() else {}
    except Exception as exc:
        raise Refused("E_ASSESSMENT", f"评估状态文件读不了，先确认它没坏再撤销：{exc}") from exc
    human = side_doc.get("human_decision") if isinstance(side_doc.get("human_decision"), dict) else {}
    trace = {"session": "", "path": "", "from": "none", "to": "none", "action": "skip",
             "sha256": "", "warnings": []}
    session, reason, ambiguous = "", "", False
    try:
        session, reason, ambiguous = source_session_of(draft)
    except Exception as exc:
        raise Refused("E_DRAFT", f"草稿读不了，先修草稿再撤销：{exc}") from exc
    if keep_trace:
        trace["warnings"].append("按 --keep-trace 跳过来源 trace 回写（沉淀状态与诊断状态都不动）")
    elif ambiguous:
        raise Refused("E_SESSION_AMBIGUOUS", reason or "来源 session 有多个，先修草稿头注释只留一个")
    elif not session:
        trace["warnings"].append("来源 trace 未记录（外部来源）：只出队并清评估状态文件，不回写 trace")
    else:
        path = traces / (session + ".yaml")
        trace["session"] = session
        trace["path"] = _rel(root, path)
        if not path.is_file():
            trace["warnings"].append(f"来源 trace 不存在（{session}）：只出队并清评估状态文件，不回写 trace")
        else:
            try:
                snap = _read_trace(path)
            except Exception as exc:
                raise Refused("E_TRACE", f"来源 trace 读不了，先确认它没坏再撤销：{exc}") from exc
            trace["from"] = snap["sedimented"]
            if snap["sedimented"] == "none":
                trace["warnings"].append("来源 trace 已经是未沉淀，不需要回写沉淀状态")
            elif snap["sedimented"] in ("knowledge", "archived"):
                raise Refused(
                    "E_ALREADY_PROMOTED",
                    f"来源 trace 的沉淀状态已经是 {snap['sedimented']}（已升格）；撤销只处理提交阶段"
                    "（submitted）的草稿。已升格的牵动知识库与 PR，按知识库变更流程处理。")
            else:
                trace["action"] = "write"

            if trace["action"] == "write":
                trace["sha256"] = snap["sha256"]
    return {
        "root": root, "inbox": inbox, "traces": traces, "key": key,
        "draft": draft, "sidecar": sidecar, "side_doc": side_doc, "human": human,
        "sidecarSha256": sidecar_sha, "trace": trace,
    }


def _trace_plan_view(trace: dict) -> dict:
    """计划里的 trace 段（去掉本机路径，JSON 输出用）。"""
    view = dict(trace)
    view.pop("path", None)
    return view


def plan_report(root: Path, inbox: Path, plan: dict, stamp: str) -> dict:
    """批量计划里一份可撤销草稿的 JSON 视图（与单份 dry-run 的字段对齐）。"""
    return {
        "draft": plan["key"],
        "ok": True,
        "draftPath": _rel(root, plan["draft"].case_path),
        "layout": plan["draft"].layout,
        "assessment": _rel(root, plan["sidecar"]) if plan["sidecar"].exists() else "",
        "trace": _trace_plan_view(plan["trace"]),
        "undoneTo": _rel(root, inbox / UNDONE_DIR) + "/" + stamp + "-"
                    + sanitize_key(plan["key"]),
    }


def describe_plan(root: Path, plan: dict, stamp: str, apply: bool,
                  footer: bool = True) -> str:
    draft = plan["draft"]
    key = plan["key"]
    lines = [("撤销沉淀：" if apply else "将撤销沉淀：") + key]
    lines.append(f"- 草稿：{_rel(root, draft.case_path)}（{draft.layout}）")
    if plan["sidecar"].exists():
        decision = str((plan["human"] or {}).get("decision") or "")
        lines.append(f"- 评估状态文件：{_rel(root, plan['sidecar'])}"
                     + (f"（人决定 {decision}，一并清除）" if decision else ""))
    else:
        lines.append("- 评估状态文件：没有")
    trace = plan["trace"]
    if trace["session"]:
        if trace["action"] == "write":
            lines.append(f"- 来源 trace：{trace['session']} 的 sedimented {trace['from']} → none")
        else:
            lines.append(f"- 来源 trace：{trace['session']}（沉淀状态不写回）")
    lines.append(f"- 草稿去向：{_rel(root, plan['inbox'] / UNDONE_DIR)}/{stamp}-{sanitize_key(key)}/")
    for warning in trace.get("warnings") or []:
        lines.append("- 注意：" + warning)
    if footer and not apply:
        lines.append("这是计划，没有写盘。加 --apply 执行。")
    return "\n".join(lines)


def _apply_plan(root: Path, inbox: Path, traces: Path, plan: dict,
                stamp: str, args) -> dict:
    """执行一份计划；失败抛 Refused（带已完成步骤）。返回结果字典。"""
    done = []
    moved_to = None
    sidecar = Path(plan["sidecar"])
    sidecar_rel = _rel(root, sidecar) if sidecar.exists() else ""
    assessment_deleted = False
    trace = plan["trace"]
    trace_result = {"session": trace["session"], "from": trace["from"],
                    "to": trace["from"], "written": False}
    try:
        # 目录级锁包住整段：计划与执行之间可能另一个 groom 写了新评估，或另一个
        # 撤销/收尾把草稿移走。拿到锁后先重验草稿还在，再按 trace → 草稿 → 评估状态文件
        # 的顺序写；每完成一步就记进 done，失败报告据此说清现状。
        with log_lock(assessment_guard(inbox)) as held:
            if not held:
                raise Refused("E_LOCK", "评估状态文件的目录锁不可用（本平台没有锁原语），本次没有写入")
            if not Path(plan["draft"].case_path).exists():
                raise Refused("E_NO_DRAFT", "草稿在计划之后被移走（可能另一个撤销或收尾在跑），刷新后重试")
            # 计划之后若有人改写了评估状态文件（另一个 groom 重评估、或只改了人决定），
            # 不能直接删：它的结论与决定没进计划，删掉就丢了。在写任何东西之前按字节比对。
            # 只比 assessment_id 不够：`groom_decide.py` 改人决定时不换 id。
            try:
                current_sha = (hashlib.sha256(sidecar.read_bytes()).hexdigest()
                               if sidecar.exists() else "")
            except OSError as exc:
                raise Refused("E_ASSESSMENT", f"评估状态文件读不了，先确认它没坏：{exc}") from exc
            if current_sha != plan["sidecarSha256"]:
                raise Refused("E_ASSESSMENT_CHANGED",
                              "评估状态文件在计划之后出现或被改过（可能有另一个 groom 在写），"
                              "先重新跑一次计划")

            if trace["action"] == "write":
                _run_transition(
                    root, traces, trace["session"],
                    ["--field", "sedimented", "--state", "none"], trace["sha256"], args.by,
                    "来源 trace 回写")
                done.append("来源 trace 回写 none")
                trace_result["to"] = "none"
                trace_result["written"] = True

            meta = {
                "schema": "sediment-undo/v1",
                "at": now_iso(),
                "by": args.by,
                "draft": plan["key"],
                "layout": plan["draft"].layout,
                "source_trace": trace["session"],
                "previous_sedimented": trace["from"],
                "note": args.note,
            }
            moved_to = _move_draft(root, inbox, plan["draft"], stamp, meta)
            done.append("草稿移入 " + _rel(root, moved_to))

            if sidecar.exists():
                with log_lock(assessment_path(inbox, plan["key"])) as file_held:
                    if not file_held:
                        raise Refused("E_LOCK", "评估状态文件的文件锁不可用（本平台没有锁原语）", done)
                    sidecar.unlink()
                assessment_deleted = True
                done.append("评估状态文件已删除")

            human = plan["human"] or {}
            log_entry = {
                "schema": "sediment-undo/v1",
                "at": now_iso(),
                "by": args.by,
                "draft": plan["key"],
                "note": args.note,
                "moved_to": _rel(root, moved_to),
                "trace": {"session": trace["session"],
                          "from": trace["from"], "to": trace_result["to"],
                          "written": trace_result["written"]},
                "assessment": {
                    "path": sidecar_rel,
                    "assessment_id": str(plan["side_doc"].get("assessment_id") or ""),
                    "human_decision": str(human.get("decision") or ""),
                    "human_decision_by": str(human.get("by") or ""),
                    "human_decision_at": str(human.get("decided_at") or ""),
                    "human_decision_history": len(plan["side_doc"].get("human_decision_history") or []),
                },
            }
            _append_undo_log(inbox, log_entry)
            done.append("undo-log 已写")
    except Refused as exc:
        if not exc.done:
            exc.done = done
        raise
    except Exception as exc:
        raise Refused("E_INTERNAL", f"撤销失败：{exc}", done) from exc
    return {
        "ok": True, "dryRun": False, "draft": plan["key"],
        "movedTo": _rel(root, moved_to),
        "trace": trace_result,
        "assessmentDeleted": assessment_deleted,
        "undoLog": _rel(root, inbox / UNDO_LOG_REL),
        "warnings": trace.get("warnings") or [],
    }


def print_apply_result(result: dict) -> None:
    trace = result["trace"]
    print(f"已撤销沉淀：{result['draft']}")
    print(f"- 草稿已移到 {result['movedTo']}（移回原目录即可复活）")
    print(f"- 来源 trace：{trace['session'] or '未记录'}"
          + (f" 的 sedimented {trace['from']} → none" if trace["written"]
             else "（沉淀状态未回写）"))
    print("- 评估状态文件：" + ("已删除" if result["assessmentDeleted"] else "没有"))
    print(f"- undo-log：{result['undoLog']}")
    for warning in result["warnings"]:
        print("- 注意：" + warning)


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="撤销一次沉淀：草稿出队、评估状态文件清除、来源 trace 还原")
    ap.add_argument("--draft-key", action="append", required=True,
                    help="inbox 草稿的 key（与队列里显示的一致）；批量时重复给多次")
    ap.add_argument("--root", default=None, help="仓库根（默认本脚本上一级）")
    ap.add_argument("--inbox", default=None, help="共享 inbox（默认由主检出解析）")
    ap.add_argument("--traces", default=None, help="traces 目录（默认由主检出解析）")
    ap.add_argument("--apply", action="store_true", help="执行；不带时只打印计划")
    ap.add_argument("--keep-trace", action="store_true",
                    help="不回写来源 trace 的沉淀状态（手工修过 trace 后重跑时用）")
    ap.add_argument("--by", default="user", choices=["user", "agent", "cli"], help="undo-log 里记谁做的")
    ap.add_argument("--note", default="", help="写进 undo-log 的备注")
    ap.add_argument("--json", action="store_true", help="输出 JSON（机器可读）")
    args = ap.parse_args(argv)
    keys = []
    for key in args.draft_key:
        key = str(key or "").strip()
        if key and key not in keys:
            keys.append(key)

    def fail(code: str, message: str, done=None, extra=None) -> int:
        if args.json:
            print(json.dumps({"ok": False, "code": code, "message": message,
                              "done": list(done or []), **(extra or {})}, ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
            for item in done or []:
                print("已完成：" + item, file=sys.stderr)
        return 2

    if not keys:
        return fail("E_SCHEMA", "至少给一个 --draft-key（空的 key 不算）")

    try:
        root = repo_root(Path(args.root).expanduser() if args.root else Path(__file__).resolve().parents[1])
        inbox = Path(args.inbox).expanduser() if args.inbox else Path(shared_inbox(root))
        traces = Path(args.traces).expanduser() if args.traces else Path(resolve_traces(root))
    except Refused as exc:
        return fail(exc.code, exc.message, exc.done)
    except Exception as exc:  # 路径/仓库解析失败也要给可读原因，不抛裸 traceback
        return fail("E_INTERNAL", f"撤销失败：{exc}")

    stamp = _stamp()
    if len(keys) > 1:
        return _run_batch(args, root, inbox, traces, keys, stamp, fail)

    key = keys[0]
    try:
        plan = build_plan(root, inbox, traces, key, args.keep_trace)
    except Refused as exc:
        return fail(exc.code, exc.message, exc.done)
    except Exception as exc:
        return fail("E_INTERNAL", f"撤销失败：{exc}")

    if not args.apply:
        if args.json:
            print(json.dumps({
                "ok": True, "dryRun": True, "draft": plan["key"],
                "draftPath": _rel(root, plan["draft"].case_path),
                "layout": plan["draft"].layout,
                "assessment": _rel(root, plan["sidecar"]) if plan["sidecar"].exists() else "",
                "trace": _trace_plan_view(plan["trace"]),
                "undoneTo": _rel(root, inbox / UNDONE_DIR) + "/" + stamp + "-"
                            + sanitize_key(plan["key"]),
            }, ensure_ascii=False))
        else:
            print(describe_plan(root, plan, stamp, apply=False))
        return 0

    try:
        result = _apply_plan(root, inbox, traces, plan, stamp, args)
    except Refused as exc:
        return fail(exc.code, exc.message, exc.done)
    except Exception as exc:
        return fail("E_INTERNAL", f"撤销失败：{exc}")
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print_apply_result(result)
    return 0


def _run_batch(args, root: Path, inbox: Path, traces: Path, keys: list,
               stamp: str, fail) -> int:
    total = len(keys)
    if not args.apply:
        results, plans = [], {}
        for key in keys:
            try:
                plan = build_plan(root, inbox, traces, key, args.keep_trace)
                plans[key] = plan
                results.append(plan_report(root, inbox, plan, stamp))
            except Refused as exc:
                results.append({"draft": key, "ok": False,
                                "code": exc.code, "message": exc.message})
            except Exception as exc:
                results.append({"draft": key, "ok": False,
                                "code": "E_INTERNAL", "message": str(exc)})
        planned = [item for item in results if item["ok"]]
        refused = [item for item in results if not item["ok"]]
        if args.json:
            print(json.dumps({
                "ok": bool(planned), "dryRun": True, "results": results,
                "summary": {"total": total, "planned": len(planned), "refused": len(refused)},
            }, ensure_ascii=False))
        else:
            print(f"批量撤销沉淀：{total} 份（计划，不写盘）")
            for index, key in enumerate(keys, 1):
                print(f"\n[{index}/{total}] {key}")
                if key in plans:
                    print(describe_plan(root, plans[key], stamp, apply=False, footer=False))
                else:
                    item = next(entry for entry in results if entry["draft"] == key)
                    print("不可撤销：" + item["message"])
            print(f"\n可撤销 {len(planned)} 份，拒绝 {len(refused)} 份。"
                  + ("" if not planned else "确认后加 --apply 执行。"))
        return 0 if planned else 2

    results = []
    applied = 0
    for key in keys:
        try:
            plan = build_plan(root, inbox, traces, key, args.keep_trace)
            result = _apply_plan(root, inbox, traces, plan, stamp, args)
            applied += 1
            results.append(dict(result, draft=key))
        except Refused as exc:
            results.append({"draft": key, "ok": False, "code": exc.code,
                            "message": exc.message, "done": exc.done})
        except Exception as exc:
            results.append({"draft": key, "ok": False, "code": "E_INTERNAL",
                            "message": str(exc), "done": []})
    failed = total - applied
    if args.json:
        print(json.dumps({
            "ok": failed == 0, "dryRun": False, "results": results,
            "summary": {"total": total, "applied": applied, "failed": failed},
        }, ensure_ascii=False))
    else:
        for index, item in enumerate(results, 1):
            print(f"\n[{index}/{total}] {item['draft']}")
            if item["ok"]:
                print_apply_result(item)
            else:
                print(f"不可撤销：{item['message']}")
                for step in item.get("done") or []:
                    print("已完成：" + step)
        print(f"\n已撤销 {applied} 份，失败 {failed} 份。")
    return 0 if failed == 0 else 2


def main(argv=None) -> int:
    pin_utf8_stdio()
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
