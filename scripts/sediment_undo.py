#!/usr/bin/env python3
# sediment_undo.py —— 撤销一次沉淀动作：草稿出队、评估记录清除、来源 trace 回「未沉淀」
#
# 为什么需要：沉淀一次写三处——草稿落 `postmortems/inbox/`、来源 trace 的 `sedimented`
# 置 `submitted`、groom 评估落 sidecar。草稿选错了（重复、来源认错、结论不成立）时，
# 界面只能逐个手改：删草稿、删 sidecar、改 trace。漏一步都不报错，队列会停在
# 「trace 说已交草稿、inbox 里没有」或「草稿没了、评估记录还在」这类不一致状态。
# 本脚本把这三步按顺序做完，每步都写进报告。
#
# 与 `groom_close_draft.py` 的分工：那个是「沉淀成立之后的收尾」（升格 / 覆盖 / 归档，
# 草稿移进 `.done/`，trace 改成 `knowledge` / `archived`）；本脚本是「沉淀不成立，
# 撤回这次提交」（草稿移进 `.undone/`，trace 回 `none`，评估记录删除）。
#
# 为什么 trace 可以回 `none`：`groom_close_draft.py` 里那条纪律说 reject / defer 不改
# trace——因为草稿确实提交过、只是没转正，改回 `none` 等于抹掉事实。撤销不同：草稿与
# 评估记录一起撤回，重新沉淀会从头开始，`submitted` 已不成立，`none` 才是撤完的真实
# 状态。撤掉的东西在 `.groom/undo-log.jsonl` 留一行（评估 id、人决定、草稿去向）。
#
# 边界：
#   - 只处理还在 inbox 的草稿。已出队（`.done/`）的用「恢复草稿」流程；已升格的草稿
#     不在这里删，那会牵动知识库与 PR。
#   - PR 台账里这份草稿有任何记录（open / merged / unknown / closed）就拒绝：PR 是外部
#     事实，删本地草稿不会关掉它，先确认 PR 再谈撤销。
#   - 来源 trace 已经是 `knowledge` / `archived` 时拒绝：升格已经发生，撤回要牵动知识库与
#     PR，走知识库变更流程；这里只处理提交阶段（`submitted`）的草稿。
#   - 草稿移进 `postmortems/inbox/.undone/`（移动不删除，移回即复活）。`find_drafts`
#     不扫点目录，所以移走后不再进队列。
#   - 来源 trace 缺失或没记来源（外部 issue 来源）时只出队 + 删评估记录，回写跳过并写明。
#   - 撤销后草稿留在 `.undone/`，没有保留期；确认不再需要后手工删。
#   - 默认只打印计划；`--apply` 才写。
#
# 用法：
#   python3 scripts/sediment_undo.py --draft-key <key>                 # 计划（不写）
#   python3 scripts/sediment_undo.py --draft-key <key> --apply         # 执行
#   python3 scripts/sediment_undo.py --draft-key <key> --apply --json  # 机器可读
#
# 退出码：0 = 计划已打印，或撤销已完成；2 = 被边界拦下 / 执行失败 / 参数错。

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _stdio import pin_utf8_stdio  # noqa: E402
from _yaml import load_file  # noqa: E402
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


def _trace_state(path: Path) -> str:
    doc = load_file(path) or {}
    sed = doc.get("sedimented") if isinstance(doc, dict) else None
    if isinstance(sed, dict):
        return str(sed.get("state") or "none")
    if isinstance(sed, str) and sed.strip():
        return sed.strip()
    return "none"


def _write_trace_none(root: Path, traces: Path, session: str, sha: str, by: str) -> dict:
    """经 `trace_transition.py` 把这份 trace 的沉淀状态写回 none（唯一写入口）。"""
    script = Path(root) / "scripts" / "trace_transition.py"
    if not script.is_file():
        raise Refused("E_NO_TRANSITION", f"检出里缺少 {script}，不能回写 trace")
    cmd = [sys.executable, str(script), session,
           "--root", str(root), "--traces", str(traces),
           "--field", "sedimented", "--state", "none",
           "--by", by, "--source", "cli", "--json"]
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
        raise Refused("E_TRACE", "来源 trace 回写失败：" + message)
    return payload


def _move_draft(root: Path, inbox: Path, draft, stamp: str, meta: dict) -> Path:
    """把草稿移进 `.undone/<时间>-<key>/`。先写 `.undo.json`，再逐个移文件。

    逐个移是为了失败时能回滚：平铺草稿有 case 文件与可选 `.md` 两个文件，Windows 上
    第二个文件被占用时只移走第一个。回滚把已移走的放回原位，草稿完整留在 inbox，
    下次可以直接重试；回滚也失败时报告里指出目标目录，由人手工恢复。
    """
    target = inbox / UNDONE_DIR / f"{stamp}-{sanitize_key(draft.key)}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise Refused("E_EXISTS", f"回收位置已经存在，先处理它再撤销：{_rel(root, target)}")
    target.mkdir(parents=True)
    (target / ".undo.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source_dir = Path(draft.case_path).parent if draft.layout == "directory" else None
    sources = list(source_dir.iterdir()) if source_dir is not None else [Path(draft.case_path)]
    if source_dir is None and draft.postmortem_path is not None and Path(draft.postmortem_path).exists():
        sources.append(Path(draft.postmortem_path))
    moved = []
    try:
        for src in sources:
            shutil.move(str(src), str(target / src.name))
            moved.append(src)
        if source_dir is not None:
            source_dir.rmdir()
    except Exception as exc:
        try:
            for src in moved:
                shutil.move(str(target / src.name), str(src))
            (target / ".undo.json").unlink(missing_ok=True)
            target.rmdir()
        except Exception as rollback_exc:
            raise Refused(
                "E_MOVE",
                f"移草稿失败（{exc}），回滚也失败（{rollback_exc}）。草稿可能有一部分在 "
                f"{_rel(root, target)}，先手工移回 inbox 再重试") from exc
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


def build_plan(root: Path, inbox: Path, traces: Path, key: str, keep_trace: bool) -> dict:
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
    try:
        side_doc = load_assessment(inbox, key) if sidecar.exists() else {}
    except Exception as exc:
        raise Refused("E_ASSESSMENT", f"评估记录读不了，先确认它没坏再撤销：{exc}") from exc
    human = side_doc.get("human_decision") if isinstance(side_doc.get("human_decision"), dict) else {}
    trace = {"session": "", "from": "none", "to": "none", "action": "skip",
             "sha256": "", "path": "", "warnings": []}
    session, reason, ambiguous = "", "", False
    try:
        session, reason, ambiguous = source_session_of(draft)
    except Exception as exc:
        raise Refused("E_DRAFT", f"草稿读不了，先修草稿再撤销：{exc}") from exc
    if keep_trace:
        trace["warnings"].append("按参数跳过 trace 回写（--keep-trace）")
    elif ambiguous:
        raise Refused("E_SESSION_AMBIGUOUS", reason or "来源 session 有多个，先修草稿头注释只留一个")
    elif not session:
        trace["warnings"].append("来源 trace 未记录（外部来源）：只出队并清评估记录，不回写沉淀状态")
    else:
        path = traces / (session + ".yaml")
        trace["session"] = session
        trace["path"] = _rel(root, path)
        if not path.is_file():
            trace["warnings"].append(f"来源 trace 不存在（{session}）：只出队并清评估记录，不回写沉淀状态")
        else:
            try:
                current = _trace_state(path)
            except Exception as exc:
                raise Refused("E_TRACE", f"来源 trace 读不了，先确认它没坏再撤销：{exc}") from exc
            trace["from"] = current
            if current == "none":
                trace["warnings"].append("来源 trace 已经是未沉淀，不需要回写")
            elif current in ("knowledge", "archived"):
                raise Refused(
                    "E_ALREADY_PROMOTED",
                    f"来源 trace 的沉淀状态已经是 {current}（已升格）；撤销只处理提交阶段"
                    "（submitted）的草稿。已升格的牵动知识库与 PR，按知识库变更流程处理。")
            else:
                trace["action"] = "write"
                trace["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "root": root, "inbox": inbox, "traces": traces, "key": key,
        "draft": draft, "sidecar": sidecar, "side_doc": side_doc, "human": human,
        "trace": trace,
    }


def describe_plan(root: Path, plan: dict, stamp: str, apply: bool) -> str:
    draft = plan["draft"]
    key = plan["key"]
    lines = [("撤销沉淀：" if apply else "将撤销沉淀：") + key]
    lines.append(f"- 草稿：{_rel(root, draft.case_path)}（{draft.layout}）")
    if plan["sidecar"].exists():
        decision = str((plan["human"] or {}).get("decision") or "")
        lines.append(f"- 评估记录：{_rel(root, plan['sidecar'])}"
                     + (f"（人决定 {decision}，一并清除）" if decision else ""))
    else:
        lines.append("- 评估记录：没有")
    trace = plan["trace"]
    if trace["session"]:
        if trace["action"] == "write":
            lines.append(f"- 来源 trace：{trace['session']} 的 sedimented {trace['from']} → none")
        else:
            lines.append(f"- 来源 trace：{trace['session']}（不写回）")
    lines.append(f"- 草稿去向：{_rel(root, plan['inbox'] / UNDONE_DIR)}/{stamp}-{sanitize_key(key)}/")
    for warning in trace.get("warnings") or []:
        lines.append("- 注意：" + warning)
    if not apply:
        lines.append("这是计划，没有写盘。加 --apply 执行。")
    return "\n".join(lines)


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="撤销一次沉淀：草稿出队、评估记录清除、来源 trace 回未沉淀")
    ap.add_argument("--draft-key", required=True, help="inbox 草稿的 key（与队列里显示的一致）")
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

    def fail(code: str, message: str, done=None, extra=None) -> int:
        if args.json:
            print(json.dumps({"ok": False, "code": code, "message": message,
                              "done": list(done or []), **(extra or {})}, ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
            for item in done or []:
                print("已完成：" + item, file=sys.stderr)
        return 2

    try:
        root = repo_root(Path(args.root).expanduser() if args.root else Path(__file__).resolve().parents[1])
        inbox = Path(args.inbox).expanduser() if args.inbox else Path(shared_inbox(root))
        traces = Path(args.traces).expanduser() if args.traces else Path(resolve_traces(root))
        plan = build_plan(root, inbox, traces, args.draft_key, args.keep_trace)
    except Refused as exc:
        return fail(exc.code, exc.message, exc.done)
    except Exception as exc:  # 路径/仓库解析失败也要给可读原因，不抛裸 traceback
        return fail("E_INTERNAL", f"撤销失败：{exc}")

    stamp = _stamp()
    if not args.apply:
        if args.json:
            trace = dict(plan["trace"])
            trace.pop("path", None)
            print(json.dumps({
                "ok": True, "dryRun": True, "draft": plan["key"],
                "draftPath": _rel(root, plan["draft"].case_path),
                "layout": plan["draft"].layout,
                "assessment": _rel(root, plan["sidecar"]) if plan["sidecar"].exists() else "",
                "trace": trace,
                "undoneTo": _rel(root, inbox / UNDONE_DIR) + "/" + stamp + "-"
                            + sanitize_key(plan["key"]),
            }, ensure_ascii=False))
        else:
            print(describe_plan(root, plan, stamp, apply=False))
        return 0

    done = []
    moved_to = None
    sidecar = Path(plan["sidecar"])
    sidecar_rel = _rel(root, sidecar) if sidecar.exists() else ""
    assessment_deleted = False
    trace_result = {"session": plan["trace"]["session"], "from": plan["trace"]["from"],
                    "to": plan["trace"]["from"], "written": False}
    try:
        # 目录级锁包住整段：计划与执行之间可能另一个 groom 写了新评估，或另一个
        # 撤销/收尾把草稿移走。拿到锁后先重验草稿还在，再按 trace → 草稿 → 评估记录
        # 的顺序写；每完成一步就记进 done，失败报告据此说清现状。
        with log_lock(assessment_guard(inbox)) as held:
            if not held:
                raise Refused("E_LOCK", "评估记录的目录锁不可用（本平台没有锁原语），本次没有写入")
            if not Path(plan["draft"].case_path).exists():
                raise Refused("E_NO_DRAFT", "草稿在计划之后被移走（可能另一个撤销或收尾在跑），刷新后重试")
            # 计划之后若有人写进了新评估（另一个 groom），不能直接删：它的评估结论与
            # 人决定没进计划，删掉就丢了。在写任何东西之前重读并比对 assessment_id。
            if sidecar.exists():
                try:
                    current = load_assessment(inbox, plan["key"]) if sidecar.exists() else {}
                except Exception as exc:
                    raise Refused("E_ASSESSMENT", f"评估记录读不了，先确认它没坏：{exc}") from exc
                current_id = str(current.get("assessment_id") or "") if isinstance(current, dict) else ""
                planned_id = str(plan["side_doc"].get("assessment_id") or "")
                if current_id != planned_id:
                    raise Refused("E_ASSESSMENT_CHANGED",
                                  "评估记录在计划之后被改过（可能有另一个 groom 在写），先重新跑一次计划")

            if plan["trace"]["action"] == "write":
                _write_trace_none(root, traces, plan["trace"]["session"],
                                  plan["trace"]["sha256"], args.by)
                done.append("来源 trace 回写 none")
                trace_result["to"] = "none"
                trace_result["written"] = True

            meta = {
                "schema": "sediment-undo/v1",
                "at": now_iso(),
                "by": args.by,
                "draft": plan["key"],
                "layout": plan["draft"].layout,
                "source_trace": plan["trace"]["session"],
                "previous_sedimented": plan["trace"]["from"],
                "note": args.note,
            }
            moved_to = _move_draft(root, inbox, plan["draft"], stamp, meta)
            done.append("草稿移入 " + _rel(root, moved_to))

            if sidecar.exists():
                with log_lock(assessment_path(inbox, plan["key"])) as file_held:
                    if not file_held:
                        raise Refused("E_LOCK", "评估记录的文件锁不可用（本平台没有锁原语）", done)
                    sidecar.unlink()
                assessment_deleted = True
                done.append("评估记录已删除")

            human = plan["human"] or {}
            log_entry = {
                "schema": "sediment-undo/v1",
                "at": now_iso(),
                "by": args.by,
                "draft": plan["key"],
                "note": args.note,
                "moved_to": _rel(root, moved_to),
                "trace": {"session": plan["trace"]["session"],
                          "from": plan["trace"]["from"], "to": trace_result["to"],
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
        return fail(exc.code, exc.message, done or exc.done)
    except Exception as exc:
        return fail("E_INTERNAL", f"撤销失败：{exc}", done)

    result = {
        "ok": True, "dryRun": False, "draft": plan["key"],
        "movedTo": _rel(root, moved_to),
        "trace": trace_result,
        "assessmentDeleted": assessment_deleted,
        "undoLog": _rel(root, inbox / UNDO_LOG_REL),
        "warnings": plan["trace"].get("warnings") or [],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"已撤销沉淀：{plan['key']}")
        print(f"- 草稿已移到 {result['movedTo']}（移回原目录即可复活）")
        print(f"- 来源 trace：{trace_result['session'] or '未记录'}"
              + (f" 的 sedimented {trace_result['from']} → none" if trace_result["written"]
                 else "（未回写）"))
        print("- 评估记录：" + ("已删除" if assessment_deleted else "没有"))
        print(f"- undo-log：{result['undoLog']}")
        for warning in result["warnings"]:
            print("- 注意：" + warning)
    return 0


def main(argv=None) -> int:
    pin_utf8_stdio()
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
