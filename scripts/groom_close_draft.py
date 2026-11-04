#!/usr/bin/env python3
# groom_close_draft.py —— 终态决定的收尾唯一入口（回写 trace 沉淀状态 + 草稿出队）
#
# 为什么需要它：人把草稿定成终态（new_pattern / variant / covered）之后，还有两件确定性
# 动作，以前只写在 SKILL 的一句中文指令里：
#   1. 把来源 trace 的 `sedimented` 从 `submitted` 改成 `knowledge`（升格 Tier 2）或
#      `archived`（covered 只转正 postmortem）——不写，诊断面板的沉淀漏斗停在"已提交待升格"；
#   2. 把已处理的草稿移出 inbox——不移，下一轮 groom 按"没有 sidecar 的草稿先补跑比对"
#      又把它评一遍，队列永远不清。
# 两件都不报错，只是数据慢慢失真。本脚本把"动作发生时写"从纪律变成一次命令。
#
# 它做什么（每份草稿）：
#   1. 读 sidecar 的人决定：只认终态；defer / reject / pending、批准失效、promotion_gate
#      阻塞的草稿一律跳过并给原因。`reject` 没有对应的 sedimented 状态（草稿确实提交过、
#      没有转正），不动 trace，草稿留在队列里等人处理。
#   2. 先取落点证据，再写状态——不声称没发生的沉淀：covered 要求 postmortem 已落在
#      `postmortems/<季>/`（Tier 3）；new_pattern / variant 要求对应 case 已在 `knowledge/` 里。
#   3. 走 `trace_transition.py` 回写来源 trace 的 `sedimented`（它按 trace-status.yaml 校验状态词表）。
#   4. 把草稿移进 `postmortems/inbox/.done/`：移动不删除，移回即复活；`.done` 是点目录，
#      `find_drafts` 不会把它算回队列。
#   5. 追加一行 JSON 到 `.groom/close-log.jsonl`（人决定不可再生，收尾要留痕）。
#
# 边界（不假装）：
#   - 默认 dry-run，`--apply` 才写；
#   - 草稿与 case 里都没有来源 session 时（外部 issue 来源），只出队、不回写，报告写明；
#   - 来源 trace 文件不存在时只出队、不写状态，报告与日志记 `trace-missing`；
#   - **它不是 CI 门**：`traces/` 与 `postmortems/inbox/` 是 .gitignore 的运行时件，PR 与 CI
#     的检出里没有它们，marker 也不带 session id。这道检查只能在本地跑，不塞进
#     `groom_recheck.py` 假硬化。
#   - **PR 没合入不收尾**：读共享 inbox 的 PR 台账，同 key 的 PR 不是 merged（含 open /
#     unknown / closed）时拒绝，避免把「待合入」提前写成「已升格」。确认要提前收尾时用
#     `--allow-open-pr`。
#
# 用法：
#   python3 scripts/groom_close_draft.py --draft-key VLLM-ASC-14152              # 只看计划
#   python3 scripts/groom_close_draft.py --draft-key VLLM-ASC-14152 --apply      # 执行
#   python3 scripts/groom_close_draft.py --all --apply                            # 本轮全部终态决定
#   python3 scripts/groom_close_draft.py --draft-key DRAFT-A --case-id VLLM-ASC-14152 --apply
#
# 退出码：0 = 完成的完成、该跳过的跳过；2 = 有草稿被证据/状态拦下（报告照出）；3 = 仓库或 inbox 不可用。

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - 环境问题，明确报错而不是静默
    sys.exit("需要 PyYAML：pip install pyyaml")

from _stdio import pin_utf8_stdio
from exec_log_path import log_lock, resolve_traces
import pr_status
from groom_common import (
    draft_cases, dump_json, find_drafts, load_assessment, now_iso, repo_root, shared_inbox,
)

# 人决定的终态：只有这三个会触发"知识已落盘"的状态回写。
TERMINAL = ("new_pattern", "variant", "covered")
# sedimented 的目标值：covered 只沉淀成 postmortem（Tier 3），其余进 Tier 2。
TARGET_STATE = {"covered": "archived", "new_pattern": "knowledge", "variant": "knowledge"}
# 草稿头注释与 case 字段里可能出现两种指针写法。
TRACE_REF_RE = re.compile(r"traces[/\\]([A-Za-z0-9._-]+)\.ya?ml")
SESSION_RE = re.compile(r"source_session\s*[:=]\s*[\"']?([A-Za-z0-9._-]+)")
HEADER_LINES = 60


def _head_text(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[:HEADER_LINES])


def source_session_of(draft):
    """解析草稿的来源诊断 session。

    返回 (session_id, 原因, 是否歧义)。两个来源：草稿头注释（`traces/<id>.yaml` 或
    `source_session:`）与 case 本体的 `source_session` 字段。出现多个不同值时返回歧义，
    调用方必须拦下这份草稿（不写状态、不出队），交人修草稿头注释。
    """
    found: list[str] = []
    for text in (_head_text(draft.postmortem_path), _head_text(draft.case_path)):
        found += TRACE_REF_RE.findall(text)
        found += SESSION_RE.findall(text)
    try:
        cases = draft_cases(draft)
    except Exception:
        cases = []
    for case in cases:
        sid = str(case.get("source_session") or "").strip()
        if sid:
            found.append(sid)
    uniq = []
    for sid in found:
        if sid and sid not in uniq:
            uniq.append(sid)
    if not uniq:
        return None, "无来源 trace（外部来源）", False
    if len(uniq) > 1:
        return None, "来源 session 有多个（" + "、".join(uniq) + "）：先修草稿头注释只留一个", True
    return uniq[0], None, False


def promoted_postmortem(root: Path, key: str, override: str | None = None) -> Path | None:
    """草稿的 postmortem 是否已转正到季度目录（Tier 3）。inbox 与 .done 不算。

    `override` 给目录形态草稿用：这类草稿的 key 是 uuid、postmortem 文件名可能已改成
    Case ID，按 key 匹配不到，由人显式指到转正后的文件。
    """
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = root / path
        if path.exists() and path.parent.name not in ("inbox", ".done"):
            return path
        return None
    for path in sorted((root / "postmortems").glob(f"*/{key}.md")):
        if path.parent.name in ("inbox", ".done"):
            continue
        return path
    return None


def knowledge_cases(root: Path) -> dict:
    """id → (case, 文件路径)。一次扫完，逐份草稿查表。"""
    index: dict[str, tuple] = {}
    base = root / "knowledge"
    if not base.is_dir():
        return index
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
            if isinstance(case, dict) and case.get("id"):
                index[str(case["id"])] = (case, path)
    return index


def current_sedimented(trace_path: Path) -> dict:
    if not trace_path.exists():
        return {}
    try:
        data = yaml.safe_load(trace_path.read_text(encoding="utf-8-sig", errors="replace"))
    except Exception:
        return {}
    sed = (data or {}).get("sedimented")
    return sed if isinstance(sed, dict) else {}


def writeback_trace(root: Path, traces: Path, session: str, state: str, case_id: str) -> str:
    """走 trace_transition.py 写沉淀状态。返回 written / already / error:<原因>。"""
    trace_path = traces / f"{session}.yaml"
    if not trace_path.exists():
        return "trace-missing"
    current = current_sedimented(trace_path)
    if str(current.get("state") or "") == state and str(current.get("case_id") or "") == case_id:
        return "already"
    cmd = [
        sys.executable, str(root / "scripts" / "trace_transition.py"), session,
        "--field", "sedimented", "--state", state, "--case-id", case_id,
        "--root", str(root), "--traces", str(traces),
        "--by", "agent", "--source", "agent", "--json",
    ]
    proc = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return "error:" + (tail[-1] if tail else f"trace_transition 退出 {proc.returncode}")
    return "written"


def resolve_case_id(doc: dict, draft, decision: str, knowledge: dict,
                    override: str | None) -> tuple[str | None, str | None]:
    """终态决定对应的 Case ID。缺失或指错就返回原因，不猜。"""
    human = doc.get("human_decision") or {}
    candidate = str(human.get("candidate_case") or "").strip()
    if decision in ("covered", "variant"):
        if not candidate:
            return None, f"{decision} 决定没有 candidate_case"
        if candidate not in knowledge:
            return None, f"候选 {candidate} 不在 knowledge/ 里（升格/合并没落盘？）"
        return candidate, None
    # new_pattern：默认用草稿建议 id；升格时改过 id 就用 --case-id 覆盖。
    if override:
        if override not in knowledge:
            return None, f"--case-id {override} 不在 knowledge/ 里"
        return override, None
    suggested = str(doc.get("draft_case_id") or "").strip()
    if not suggested:
        try:
            cases = draft_cases(draft)
            suggested = str((cases[0] or {}).get("id") or "") if cases else ""
        except Exception:
            suggested = ""
    if suggested and suggested in knowledge:
        return suggested, None
    return None, ("new_pattern 的 case 不在 knowledge/ 里（升格时改过 id？带 --case-id 指定）"
                  if suggested else "草稿没有可用 id，带 --case-id 指定")


def move_draft(draft, done_dir: Path, apply: bool) -> list[str]:
    """把草稿移进 .done。移动不删除，移回即复活。"""
    if draft.layout == "directory":
        target = done_dir / draft.key
        if target.exists():
            raise RuntimeError(f"落点已存在：{target}")
        if apply:
            done_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(draft.case_path.parent), str(target))
        return [str(target)]
    target = done_dir / draft.key
    sources = [draft.case_path]
    if draft.postmortem_path and draft.postmortem_path.exists():
        sources.append(draft.postmortem_path)
    moved = []
    for src in sources:
        dst = target / src.name
        if apply:
            target.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        moved.append(str(dst))
    return moved


def append_log(inbox: Path, entry: dict) -> None:
    path = inbox / ".groom" / "close-log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with log_lock(path) as locked:
        if not locked:
            raise RuntimeError("close-log 写锁不可用")
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def plan_one(doc: dict, draft, root: Path, knowledge: dict, override: str | None,
             postmortem: str | None = None) -> dict:
    """算出一份草稿的收尾计划；未通过的项带 status=error + reason。"""
    human = doc.get("human_decision") or {}
    decision = str(human.get("decision") or "")
    result = {
        "draft": draft.key, "decision": decision, "status": "error",
        "case_id": None, "state": None, "session": None,
        "trace": "skipped", "moved": [], "reason": None,
    }
    if not doc:
        result["status"] = "ignored"
        result["reason"] = "没有本地评估（先跑 groom_candidates + 子 agent 比对 + groom_record）"
        return result
    if decision not in TERMINAL:
        result["status"] = "ignored"
        result["reason"] = f"不是终态决定（{decision or '未决定'}），不动 trace、不移动草稿"
        return result
    if not doc.get("human_decision_valid", False):
        result["reason"] = "人的批准没有绑定当前评估/内容（approval-stale），先重新确认"
        return result
    gate = doc.get("promotion_gate") or {}
    if gate.get("blocked_reason"):
        result["reason"] = f"promotion_gate 阻塞：{gate['blocked_reason']}"
        return result

    case_id, why = resolve_case_id(doc, draft, decision, knowledge, override)
    if not case_id:
        result["reason"] = why
        return result
    if decision == "covered" and promoted_postmortem(root, key=draft.key, override=postmortem) is None:
        result["reason"] = ("covered 要求 postmortem 已转正到 postmortems/<季>/（Tier 3 是这条决定"
                            "唯一落盘的知识）；目录形态草稿用 --postmortem 指到转正后的文件")
        return result

    session, why, ambiguous = source_session_of(draft)
    if ambiguous:
        # 来源不唯一时既不回写也不出队：出队就等于放弃这条草稿的状态回写，
        # 正是本脚本要防的静默滞后。交人先修草稿头注释。
        result["reason"] = why
        return result
    result.update({"case_id": case_id, "state": TARGET_STATE[decision], "session": session,
                   "status": "ready", "trace": "skipped" if not session else "pending",
                   "reason": why})
    return result


def blocked_reason(state: str) -> str:
    if state == "closed":
        return ("PR 已关闭、没有合入；从 .done 恢复草稿后重新开 PR，不要收尾。"
                "确实要提前收尾时加 --allow-open-pr。")
    return (f"PR 还没合入（{state}）；先查合入状态，合入后再收尾。"
            f"确实要提前收尾时加 --allow-open-pr。")


def unmerged_prs(root: Path, keys) -> tuple:
    """台账里没有合入的 PR。返回 (key→state, 错误)。

    closed 在平台语义里也是「没有合入」；缺 state 与未知值按 unknown 处理。
    只有 merged 才放行。收尾会删掉本地评估证据，合入前收尾等于把「待合入」
    提前写成「已升格」。除非显式 --allow-open-pr，否则这里拦下。
    """
    try:
        ledger = pr_status.load_ledger(root)
    except Exception as exc:
        return {}, f"PR 台账读不出：{exc}"
    out = {}
    prs = ledger.get("prs") if isinstance(ledger.get("prs"), dict) else {}
    for key in keys:
        if key not in prs:
            continue
        entry = prs.get(key)
        if not isinstance(entry, dict):
            out[key] = "unknown"      # 台账里有条目但不是对象：按未确认拦下
            continue
        state = str(entry.get("state") or "").strip().lower()
        if state != "merged":
            out[key] = state or "unknown"
    return out, None


def run(args) -> int:
    root = repo_root(Path(args.repo).resolve() if args.repo else Path.cwd())
    inbox = shared_inbox(root)
    if not inbox.is_dir():
        print(f"找不到 inbox：{inbox}", file=sys.stderr)
        return 3
    drafts = {d.key: d for d in find_drafts(inbox)}
    if args.draft_key:
        missing = [k for k in args.draft_key if k not in drafts]
        if missing:
            done = inbox / ".done"
            closed = [k for k in missing if (done / k).exists()]
            if not args.json:
                for key in closed:
                    print(f"{key}: 已出队（{done / key}）")
            unresolved = [k for k in missing if k not in closed]
            if unresolved:
                print(f"inbox 里没有：{'、'.join(unresolved)}", file=sys.stderr)
                return 2
            # 只有整批都已出队才提前返回；混着仍在 inbox 的 key 时继续收尾后者。
            if not [k for k in args.draft_key if k in drafts]:
                if args.json:
                    print(dump_json({"applied": bool(args.apply), "inbox": str(inbox),
                                     "results": [{"draft": key, "status": "closed",
                                                  "reason": "已出队"} for key in closed]}))
                return 0
    selected = list(drafts.values()) if not args.draft_key else [drafts[k] for k in args.draft_key if k in drafts]
    blocked = {}
    if selected and not args.allow_open_pr:
        blocked, ledger_error = unmerged_prs(root, [d.key for d in selected])
        if ledger_error:
            if args.json:
                print(dump_json({"ok": False, "code": "E_LEDGER",
                                 "message": ledger_error, "results": []}))
            else:
                print(ledger_error, file=sys.stderr)
            return 2
        if blocked:
            selected = [d for d in selected if d.key not in blocked]
    if not selected:
        if blocked:
            results = [{"draft": key, "status": "error", "trace": "skipped",
                        "reason": blocked_reason(state)}
                       for key, state in blocked.items()]
            if not args.json:
                print_plan(results, args.apply, inbox)
            if args.json:
                print(dump_json({"applied": bool(args.apply), "inbox": str(inbox),
                                 "results": results}))
            return 2
        if args.json:
            print(dump_json({"applied": bool(args.apply), "inbox": str(inbox), "results": []}))
        else:
            print("inbox 中没有草稿。")
        return 0
    if len(selected) != 1 and (args.case_id or args.postmortem):
        print("--case-id 与 --postmortem 只能配一份 --draft-key（多份时各自落点不同，不猜）",
              file=sys.stderr)
        return 2

    knowledge = knowledge_cases(root)
    traces = Path(args.traces) if args.traces else resolve_traces(root)
    done_dir = inbox / ".done"
    results = [{"draft": key, "status": "error", "trace": "skipped",
                "reason": blocked_reason(state)}
               for key, state in blocked.items()]
    failed = bool(blocked)
    for draft in selected:
        try:
            doc = load_assessment(inbox, draft.key)
        except Exception as exc:
            results.append({"draft": draft.key, "status": "error",
                            "reason": f"评估状态解析失败：{exc}"})
            failed = True
            continue
        plan = plan_one(doc, draft, root, knowledge, args.case_id, args.postmortem)
        if plan["status"] == "ready" and plan["session"]:
            if args.apply:
                plan["trace"] = writeback_trace(root, traces, plan["session"],
                                                plan["state"], plan["case_id"])
            else:
                plan["trace"] = "would-write"
        if plan["status"] == "ready" and plan["trace"] not in ("error",) \
                and not str(plan["trace"]).startswith("error:"):
            try:
                plan["moved"] = move_draft(draft, done_dir, apply=args.apply)
            except Exception as exc:
                plan["status"] = "error"
                plan["reason"] = f"草稿移动失败：{exc}"
        elif str(plan["trace"]).startswith("error:"):
            plan["status"] = "error"
            plan["reason"] = "trace 回写失败，草稿保留在队列：" + str(plan["trace"])[len("error:"):]
        if plan["status"] == "error":
            failed = True
        if args.apply and plan["status"] in ("ready", "error"):
            try:
                append_log(inbox, {
                    "at": now_iso(), "draft": draft.key, "decision": plan["decision"],
                    "case_id": plan["case_id"], "state": plan["state"],
                    "session": plan["session"], "trace": plan["trace"],
                    "moved": plan["moved"],
                    "status": "closed" if plan["status"] == "ready" and plan["moved"] else plan["status"],
                    "reason": plan["reason"],
                })
            except Exception as exc:
                print(f"警告：{draft.key} 的 close-log 写失败（{exc}）", file=sys.stderr)
        results.append(plan)

    if args.json:
        print(dump_json({"applied": bool(args.apply), "inbox": str(inbox), "results": results}))
    else:
        print_plan(results, args.apply, inbox)
    return 2 if failed else 0


def print_plan(results: list, applied: bool, inbox: Path) -> None:
    label = {"ready": "收尾", "ignored": "跳过", "error": "拦下"}
    for r in results:
        trace = r.get("trace")
        trace_text = {
            "written": "已回写", "would-write": "将回写", "already": "已是目标状态",
            "skipped": "不回写", "trace-missing": "trace 不存在，未回写", "pending": "待回写",
        }.get(trace, str(trace))
        line = f"{label.get(r['status'], r['status'])} {r['draft']}"
        if r.get("decision"):
            line += f"（{r['decision']}"
            if r.get("case_id"):
                line += f" → {r['case_id']}"
            line += "）"
        line += f" · trace: {trace_text}"
        if r.get("trace") == "trace-missing":
            line += "〔来源 trace 文件不在 traces/，草稿仍会出队〕"
        if r.get("moved"):
            line += f" · 出队 → {Path(r['moved'][0]).parent}"
        elif r["status"] == "ready" and not applied:
            line += " · 将出队"
        print(line)
        if r.get("reason"):
            print(f"    {r['reason']}")
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    verb = "已执行" if applied else "计划（加 --apply 执行）"
    print(f"\n{verb}：收尾 {counts.get('ready', 0)} · 跳过 {counts.get('ignored', 0)}"
          f" · 拦下 {counts.get('error', 0)}")
    if applied and counts.get("ready") and inbox.is_dir():
        print(f"日志：{inbox / '.groom' / 'close-log.jsonl'}")


def main(argv=None) -> int:
    pin_utf8_stdio()
    ap = argparse.ArgumentParser(
        description="终态决定的收尾：回写 trace 沉淀状态并把草稿移出 inbox")
    ap.add_argument("--draft-key", action="append", default=None,
                    help="草稿 key（可重复）；不给则配 --all")
    ap.add_argument("--all", action="store_true", help="处理 inbox 里全部草稿")
    ap.add_argument("--case-id", default=None,
                    help="new_pattern 升格时改过 id 才需要；只配单份 --draft-key")
    ap.add_argument("--postmortem", default=None,
                    help="covered 的转正证据路径（目录形态草稿用）；只配单份 --draft-key")
    ap.add_argument("--repo", default=None, help="仓库根（默认当前目录）")
    ap.add_argument("--traces", default=None, help="traces 目录（默认主检出那一份）")
    ap.add_argument("--apply", action="store_true", help="真正执行；不给只打印计划")
    ap.add_argument("--allow-open-pr", action="store_true",
                    help="PR 台账里不是 merged（含 open/unknown/closed）时也允许收尾（默认拦下）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.draft_key and not args.all:
        ap.error("需要 --draft-key <key> 或 --all")
    if args.draft_key and args.all:
        ap.error("--draft-key 与 --all 二选一")
    try:
        return run(args)
    except RuntimeError as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
