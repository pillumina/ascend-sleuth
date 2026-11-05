#!/usr/bin/env python3
"""sediment_state.py —— 沉淀队列的数据面（只读，给 Host 端点 `copilot-sediment` 用）

为什么单独一个脚本、而不是在 Host 半里解析 YAML：
  「这份草稿评过没有、过期没有、人决定了没有、PR 合入没有」这些判据只在 `scripts/` 里
  各写一份（groom_status 的新鲜度、groom_common 的草稿发现、pr_status 的台账）。界面若
  自己判一次，就会出现第二份口径——skill 改了、界面没改，两边说法不一致。所以本脚本
  只做三件事：**取**（复用那些函数）、**并**（inbox 草稿、`.done/` 出队草稿、close-log、
  trace 与 PR 台账合并成一份队列）、**投影**（状态、下一步、五类 prompt）。不新增判据。

  队列的对象是「沉淀事项」，不是 inbox 草稿：草稿进了 `.done/` 但 PR 还没合入时，
  仍然有一行，状态由 PR 台账决定。

只读边界：不写任何文件；不 fetch；git 只用只读命令（rev-parse / symbolic-ref 等）。
所有失败（读不出 git、inbox 解析失败）都以 `{"ok": false, "code": ..., "message": ...}`
收场并退出 0——调用方只按 `ok` 分支，不把 stderr 当协议。

用法（Host 半调用，不面向人）：
  python3 lib/sediment_state.py --root <仓库根> [--json] [--only <诊断 session>]

输出：stdout 一份 UTF-8 JSON；`--only` 只保留来源为该诊断 session 的草稿。
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

# 人读阶段名与色板角色（与设计 5.2/5.4 的队列文案一致；不改 UI 的判断只看这张表）。
STATE_META = {
    "unassessed": ("已交草稿 · 未评估", "gray"),
    "need_decision": ("待决定", "warn"),
    "need_rerun": ("需重跑", "bad"),
    "decided": ("待提 PR", "accent"),
    "pr_open": ("已提 PR · 合入未确认", "accent"),
    "pr_merged": ("已合入 · 待收尾", "ok"),
    "pr_closed": ("PR 已关闭", "bad"),
    "deferred": ("已延后", "gray"),
    "rejected": ("已否决", "gray"),
    "orphan": ("孤儿状态", "bad"),
    "done": ("已升格", "ok"),
}

# 批次级动作的文案（next 与 primary 共用一份，界面不再自己拼）。
ACTION_LABEL = {
    "groom": "继续 groom",
    "pr": "生成提 PR 指令",
    "check": "查合入状态",
    "close": "合入后收尾",
    "none": "",
}

NEXT_KIND = {
    "unassessed": "groom",
    "need_decision": "groom",
    "need_rerun": "groom",
    "decided": "pr",
    "pr_open": "check",
    "pr_merged": "close",
    "pr_closed": "groom",
}

TERMINAL_DECISIONS = ("new_pattern", "variant", "covered")
OVERDUE_DAYS = 14
PR_STATES = ("open", "merged", "closed", "unknown")

TRACE_REF_RE = re.compile(r"^#?\s*(.+)$")


class SedimentError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- 依赖：复用 scripts/ 的实现

def _scripts(root: Path):
    """把 `<root>/scripts` 放进 sys.path 后取模块；缺脚本直接报 E_SCRIPTS。

    不把 import 提到模块顶层：本文件在插件 lib/ 下，仓库根由 --root 决定；顶层 import
    会在「root 还没解析」时失败，还会让测试导入本模块时被迫先有仓库。

    顺序与本文开头一致：先 `--root` 指向的检出，它没有 scripts/ 时退回本文件所在仓库的
    scripts/（宿主把脚本装在插件目录、root 指主检出时，两处其实是同一份源码）。sys.path
    按先后顺序取第一个命中的模块，所以倒序插到最前面，两个候选都在时 --root 那一份仍排第一。
    """
    local_repo = Path(__file__).resolve().parents[3]
    candidates = [Path(root) / "scripts", local_repo / "scripts"]
    for candidate in reversed(candidates):
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    try:
        return {
            "gm": importlib.import_module("groom_common"),
            "gs": importlib.import_module("groom_status"),
            "pr": importlib.import_module("pr_status"),
            "ts": importlib.import_module("_trace_state"),
            "el": importlib.import_module("exec_log_path"),
        }
    except Exception as exc:
        raise SedimentError("E_SCRIPTS", f"读不到 scripts/ 下的判据脚本：{exc}") from exc


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_iso(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _age_days(created_at, path) -> tuple:
    """(天数, 来源)。created_at 优先；没有就文件 mtime；都没有 unknown。"""
    parsed = _parse_iso(created_at)
    if parsed is not None:
        delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
        return max(int(delta.total_seconds() // 86400), 0), "created_at"
    if path is not None:
        try:
            mtime = datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc)
        except OSError:
            return 0, "unknown"
        delta = datetime.now(timezone.utc) - mtime
        return max(int(delta.total_seconds() // 86400), 0), "mtime"
    return 0, "unknown"


def _relpath(root: Path, path: Path) -> str:
    try:
        return str(os.path.relpath(str(path), str(root))).replace("\\", "/")
    except (ValueError, OSError):
        return str(path)


def _posix(value) -> str:
    return str(value or "").replace("\\", "/").strip()


def _q(value) -> str:
    """把值安全地拼进一条可复制的 shell 命令。

    草稿 key 由文件名派生、落点路径来自 knowledge/ 与 postmortems/，中间可能含空格与引号；
    这些字符串会出现在给人复制的命令里，逐段手工加引号容易漏，统一交给 shlex.quote。
    """
    return shlex.quote(str(value if value is not None else ""))


# ---------------------------------------------------------------- 目标 commit / 轨迹 / 知识库

def _target_commit(gm, root: Path, ledger: dict) -> str:
    """目标知识版本：优先台账 target 的 remote/base，其次 origin/main，最后 HEAD。"""
    refs = []
    target = ledger.get("target") if isinstance(ledger, dict) else None
    if isinstance(target, dict) and target.get("remote") and target.get("base"):
        refs.append(f"refs/remotes/{target['remote']}/{target['base']}")
    refs += ["refs/remotes/origin/main", "HEAD"]
    for ref in refs:
        commit = gm.normalize_commit(root, ref)
        if commit:
            return commit
    raise SedimentError("E_GIT", "取不到目标 commit（git 仓库不可用，或还没有任何提交）")


def _trace_index(ts, traces: Path) -> list:
    """全部轨迹的沉淀三字段 + 跳会话用的 harness 会话号。读不出的单跳过（队列不因一条坏 trace 空掉）。"""
    rows = []
    try:
        entries = ts.load_traces(traces)
    except Exception:
        return rows
    for entry in entries:
        doc = entry.get("doc") or {}
        sedimented = doc.get("sedimented")
        block = sedimented if isinstance(sedimented, dict) else {}
        rows.append({
            "sessionId": str(entry.get("sessionId") or ""),
            "harnessSession": str(doc.get("harness_session") or "").strip(),
            "state": ts.sed_state(doc),
            "case_id": str(block.get("case_id") or block.get("caseId") or ""),
            # 两种写法都读：trace_transition 写 inbox_path，sediment_batch 写 inboxPath。
            "inbox_path": _posix(block.get("inbox_path") or block.get("inboxPath") or ""),
        })
    return rows


def _match_trace(trace_rows: list, draft_rel: str, case_id: str, source_session: str):
    """按契约顺序匹配：inbox_path → case_id → 草稿 case 的 source_session。"""
    for row in trace_rows:
        if draft_rel and row["inbox_path"] and row["inbox_path"] == draft_rel:
            return row
    if case_id:
        for row in trace_rows:
            if row["case_id"] and row["case_id"] == case_id:
                return row
    if source_session:
        for row in trace_rows:
            if row["sessionId"] == source_session:
                return row
    return None


def _find_case_path(root: Path, case_id: str) -> str:
    if not case_id:
        return ""
    knowledge = root / "knowledge"
    if not knowledge.is_dir():
        return ""
    for path in knowledge.rglob(f"{case_id}.yaml"):
        if "__pycache__" in path.parts:
            continue
        return _relpath(root, path)
    return ""


def _find_postmortem_path(root: Path, key: str) -> str:
    if not key:
        return ""
    base = root / "postmortems"
    if not base.is_dir():
        return ""
    for path in sorted(base.glob(f"*/{key}.md")):
        return _relpath(root, path)
    return ""


def _done_draft(inbox: Path, key: str, gm):
    """读 `.done/<key>/` 里的出队草稿。close_draft 的两种落点都认。"""
    base = inbox / ".done" / key
    candidates = (
        (base / f"{key}.case.yaml", "flat", base / f"{key}.md"),
        (base / "case.yaml", "directory", base / "postmortem.md"),
    )
    for case_path, layout, postmortem in candidates:
        if case_path.is_file():
            return gm.Draft(key=key, case_path=case_path, layout=layout,
                            postmortem_path=postmortem if postmortem.is_file() else None)
    return None


def _read_close_log(inbox: Path) -> list:
    """读全量 close-log。坏行跳过；同一 key 的先后由调用方取最后一条。"""
    path = inbox / ".groom" / "close-log.jsonl"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        key = str(obj.get("draft") or obj.get("key") or "").strip()
        at = str(obj.get("at") or "").strip()
        state = str(obj.get("state") or "").strip()
        if not key or not at or not state:
            continue
        out.append({
            "key": key, "at": at, "state": state,
            "status": str(obj.get("status") or ""),
            "decision": str(obj.get("decision") or ""),
            "case_id": str(obj.get("case_id") or ""),
            "session": str(obj.get("session") or ""),
        })
    return out


def _close_index(entries: list) -> dict:
    """同 key 取最后一条：close-log 只追加，最后一条才是当前状态。"""
    out = {}
    for entry in entries:
        out[entry["key"]] = entry
    return out


def _restore_prompt(inbox: Path, key: str, draft) -> str:
    """把 `.done/<key>` 移回 inbox 的可复制命令。平铺与目录两种草稿分开处理。"""
    base = inbox / ".done" / key
    if draft is not None and draft.layout == "directory":
        return ("把已出队的草稿移回 inbox，再继续 groom：\n"
                f"mv {_q(str(base))} {_q(str(inbox / key))}")
    files = [path for path in sorted(base.glob("*")) if path.is_file()] if base.is_dir() else []
    lines = ["把已出队的草稿移回 inbox，再继续 groom："]
    for path in files:
        lines.append(f"mv {_q(str(path))} {_q(str(inbox / path.name))}")
    if base.is_dir():
        lines.append(f"rmdir {_q(str(base))}")
    return "\n".join(lines)


def _pr_view(entry):
    if not isinstance(entry, dict):
        return None
    url = str(entry.get("url") or "").strip()
    if not re.match(r"^https?://", url, re.IGNORECASE):
        # 台账可能被手改或来自旧数据；URL 只放行 http/https，别让它进 href。
        url = ""
    return {"number": entry.get("number"), "url": url,
            "repo": str(entry.get("repo") or ""),
            "platform": str(entry.get("platform") or ""),
            "state": _pr_state(entry), "source": str(entry.get("source") or ""),
            "checkedAt": str(entry.get("checked_at") or "")}


def _title_of(gm, draft, key: str) -> str:
    try:
        cases = gm.draft_cases(draft) if draft is not None else []
    except Exception:
        cases = []
    if cases:
        title = str(cases[0].get("title") or "").strip()
        if title:
            return title
    if draft is not None and draft.postmortem_path and draft.postmortem_path.exists():
        try:
            text = draft.postmortem_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            text = ""
        for line in text.splitlines():
            line = line.strip()
            if line:
                return TRACE_REF_RE.match(line.lstrip("#").strip()).group(1).strip() or key
    return key


# ---------------------------------------------------------------- 状态合并

def _promotion(root: Path, gm, key: str, trace, human: dict, cases: list, kb_ids: set) -> dict:
    """升格落点：case id 依次取 trace 的 case_id、人决定（variant/covered 的候选、
    new_pattern 的既有 id）；路径扫 knowledge/ 与 postmortems/，不猜。"""
    case_id = str(trace["case_id"]) if trace else ""
    if not case_id:
        decision = str(human.get("decision") or "")
        if decision in ("variant", "covered"):
            case_id = str(human.get("candidate_case") or "")
        elif decision == "new_pattern" and cases:
            suggested = str(cases[0].get("id") or "")
            if suggested and suggested in kb_ids:
                case_id = suggested
    case_path = _find_case_path(root, case_id)
    return {"caseId": case_id, "casePath": case_path,
            "postmortemPath": _find_postmortem_path(root, key)}


def _landing_exists(state: str, promotion: dict, kb_ids: set) -> bool:
    if state == "knowledge":
        return bool(promotion["casePath"] or promotion["caseId"] in kb_ids)
    if state == "archived":
        return bool(promotion["postmortemPath"])
    return False


def _pr_state(entry: dict) -> str:
    state = str(entry.get("state") or "unknown").lower()
    return state if state in PR_STATES else "unknown"


def _classify(row: dict, pr_entry, done: bool) -> str:
    """状态优先级（契约 §2）：orphan → 评估/决定分支 → PR 覆盖 → done。

    PR 是 open/unknown 时，过期或批准失效压过「待合入」：评估已经不能用了，
    先去重跑 groom，PR 记录仍在详情里。
    """
    if row.get("orphan"):
        return "orphan"
    if not row.get("assessed"):
        state = "unassessed"
    elif row.get("stale") or row.get("needs_reapproval"):
        state = "need_rerun"
    else:
        decision = str(row.get("human_decision") or "")
        valid = bool(row.get("human_decision_valid"))
        if not valid or not decision:
            state = "need_decision"
        elif decision == "reject":
            state = "rejected"
        elif decision == "defer":
            state = "deferred"
        elif decision in TERMINAL_DECISIONS:
            state = "decided"
        else:
            state = "need_decision"
    if pr_entry is not None:
        pr_state = _pr_state(pr_entry)
        if pr_state == "merged":
            state = "pr_merged"
        elif pr_state == "closed":
            state = "pr_closed"
        elif state == "need_rerun":
            state = "need_rerun"
        else:
            state = "pr_open"
    if done:
        state = "done"
    return state


def _source(trace, done: bool, promotion: dict, kb_ids: set, draft_in_inbox: bool) -> dict:
    """trace 的沉淀状态 + 与队列的差异（mismatch）。

    契约的三条差异规则都在这里；`draft_left_behind` 是补充的第四种：trace 已经说升格、
    落点也在，草稿却还在 inbox——队列落后于 trace，界面要能提示（Lead 补充）。

    `harnessSession` 与 `sessionId` 是两个值：前者是 DSH 会话号，后者是 trace 单号。只有前者
    能拿去 `sessions.open`；界面显示 trace 单号，跳转用会话号，缺会话号时该项不可点。
    """
    if trace is None:
        return {"sessionId": "", "harnessSession": "", "mismatch": "none", "sedimented": "none"}
    sedimented = trace["state"]
    case_exists = bool(promotion["casePath"] or promotion["caseId"] in kb_ids)
    mismatch = "none"
    if sedimented == "submitted" and not draft_in_inbox:
        mismatch = "stale_trace" if case_exists else "missing_draft"
    elif sedimented == "knowledge" and not case_exists:
        mismatch = "missing_case"
    if done:
        mismatch = "draft_left_behind"
    return {"sessionId": trace["sessionId"], "harnessSession": trace.get("harnessSession", ""),
            "mismatch": mismatch, "sedimented": sedimented}


def _writeback(mismatch: str, session: str, case_id: str, draft_key: str = "") -> str:
    """按差异给一条能真的修正的指令；missing_* 缺证据，不给必然报错的命令。"""
    if mismatch == "draft_left_behind":
        target = f"--draft-key {_q(draft_key)} --apply" if draft_key else "--all --apply"
        return ("草稿已升格但还在 inbox：按 /knowledge-groom 收尾。\n"
                f"python3 scripts/groom_close_draft.py {target}\n"
                "（落点证据不在时停；不要手删草稿）")
    if mismatch != "stale_trace" or not session or not case_id:
        return ""
    return ("回写来源 trace：\n"
            f"python3 scripts/trace_transition.py {_q(session)} --field sedimented "
            f"--state knowledge --case-id {_q(case_id)} --json")


# ---------------------------------------------------------------- 四条批次 prompt 与明细

def _inbox_rel(root: Path, inbox: Path) -> str:
    return _relpath(root, inbox)


def _ledger_rel(root: Path, inbox: Path) -> str:
    return _relpath(root, inbox / ".groom" / "pr-state.json")


def _target_target(target_info: dict) -> dict:
    target = target_info.get("target") if isinstance(target_info, dict) else None
    return target if isinstance(target, dict) else {}


def _platform_name(adapters: list, platform_id: str) -> str:
    for adapter in adapters:
        if adapter.get("id") == platform_id:
            return str(adapter.get("name") or platform_id)
    return ""


def _label_text(target_info: dict) -> str:
    target = _target_target(target_info)
    labels = target.get("labels") if isinstance(target.get("labels"), dict) else {}
    if not labels:
        return "目标没有配置标签就不加"
    pairs = "、".join(f"{key}={value}" for key, value in labels.items())
    return f"标签按目标配置加（{pairs}）"


def _prompt_groom(inbox_rel: str, rows: list) -> str:
    """批次 prompt：草稿总数、待决定数、过期数与共享 inbox 路径；决定权留给人。"""
    need = len([r for r in rows if r["state"] == "need_decision"])
    overdue = len([r for r in rows if r["ageDays"] > OVERDUE_DAYS])
    return ("对 " + inbox_rel + " 里的 " + str(len(rows)) + " 份草稿做知识 groom。\n"
            + "待决定 " + str(need) + " 份；超过 " + str(OVERDUE_DAYS) + " 天 " + str(overdue) + " 份。\n"
            + "按 /knowledge-groom 执行，逐条问我，不替我决定。")


def _prompt_pr(root: Path, inbox: Path, target_info: dict, adapters: list, rows: list) -> str:
    if not rows:
        return ""
    target = _target_target(target_info)
    inbox_rel = _inbox_rel(root, inbox)
    if target.get("remote"):
        head = (f"对 {inbox_rel} 里已决定的 {len(rows)} 份草稿，"
                f"提到 {target['remote']}/{target.get('base') or 'main'}"
                f"（{_platform_name(adapters, str(target.get('platform') or '')) or '无适配器'}），"
                f"按 /knowledge-groom 的「PR provenance 与合入前复核」一节提一个 PR"
                f"（PR body 带每份草稿的 groom marker；groom_recheck.py 通过才继续）。")
    else:
        head = (f"对 {inbox_rel} 里已决定的 {len(rows)} 份草稿提一个 PR。"
                f"本机还没有 PR 目标：先问我远端、base、平台，别猜；确认后按 /knowledge-groom 的"
                f"「PR provenance 与合入前复核」一节提一个 PR"
                f"（PR body 带每份草稿的 groom marker；groom_recheck.py 通过才继续）。")
    lines = [head, ""]
    for index, row in enumerate(rows, 1):
        decision = row["decision"]
        if decision == "variant" and row["candidate"]:
            decision_text = f"variant_of {row['candidate']}；整篇替换已有 case"
        elif decision == "covered" and row["candidate"]:
            decision_text = f"covered_by {row['candidate']}"
        else:
            decision_text = decision
        landing = row["promotion"]["casePath"] or row["promotion"]["postmortemPath"] or "未落盘"
        lines.append(f"{index}. {row['key']} — {decision_text}；落点 {landing}")
    lines += [
        "",
        "边界：先落盘并过升格检查；groom_recheck.py 不通过就停；PR 开完就停，不自行合入，也不要跑 close / cleanup；"
        + _label_text(target_info) + "。",
        "开完 PR 后用 `python3 scripts/pr_status.py --set` 写台账，不要手编 JSON；",
        f"台账：{_ledger_rel(root, inbox)}。",
    ]
    return "\n".join(lines)


def _prompt_check(root: Path, inbox: Path, adapters: list, rows: list) -> str:
    if not rows:
        return ""
    lines = ["查以下 PR 的合入状态（PR 落在哪个平台由 URL 判断）：", ""]
    for row in rows:
        pr = row["pr"] or {}
        url = pr.get("url") or "（台账缺 URL）"
        adapter = _adapter_for_url(adapters, url)
        if adapter is None:
            platform = "本机没有对应工具"
        else:
            platform = f"{adapter.get('name')}（适配器 {adapter.get('id')}）"
        lines.append(f"- {row['key']}：{url}（{platform}）")
    lines += ["",
              "查到后用脚本写台账，不要手编 JSON：",
              "  python3 scripts/pr_status.py --root . --check --draft <key>",
              "本机没有对应工具时手动确认：",
              "  python3 scripts/pr_status.py --root . --mark --draft <key> --state open|merged|closed|unknown",
              f"台账：{_ledger_rel(root, inbox)}；查不到就写 unknown，不推断。"]
    return "\n".join(lines)


def _prompt_close(rows: list) -> str:
    if not rows:
        return ""
    lines = [f"以下 {len(rows)} 份 PR 已合入，做收尾：", ""]
    for row in rows:
        pr = row["pr"] or {}
        lines.append(f"- {row['key']}：{pr.get('url') or '（台账缺 URL）'}")
    to_close = [row for row in rows if not row.get("closedDraft")]
    lines += ["", "先取每份 PR 的合并提交，再取它的第一个父提交：",
              "  MERGE=$(gh pr view <n> --json mergeCommit --jq .mergeCommit.oid)  # GitHub",
              '  BASE=$(git rev-parse "$MERGE^1")',
              "base 不要用 `baseRefOid`：它是 PR 头更新时的 base 分支头，不是合并前的 base。"]
    if to_close:
        keys = " ".join(f"--draft-key {_q(row['key'])}" for row in to_close)
        lines += ["草稿还在 inbox 的，先跑：",
                  f"  python3 scripts/groom_close_draft.py {keys} --apply"]
    lines += ["再对每份 PR 的 body 各跑一次：",
              "  python3 scripts/groom_cleanup.py --pr-body-file <该 PR 的 body 文件> "
              '--post-merge --base "$BASE" --head "$MERGE"',
              "body 用已合入 PR 的原文（含 groom marker）；证据不在就停。"]
    return "\n".join(lines)


def _groom_detail() -> str:
    return "\n".join([
        "python3 scripts/shared_dir.py inbox",
        "python3 scripts/groom_snapshot.py --list-remotes",
        "python3 scripts/groom_snapshot.py [--remote <远端>] --require-fresh --json > <快照 meta.json>",
        "python3 scripts/groom_candidates.py --snapshot <快照 meta.json> --all",
        "python3 scripts/groom_status.py --decision-prompt",
    ])


def _adapter_for_url(adapters: list, url: str):
    host = ""
    try:
        host = str((parse_remote_url(url)).get("host") or "")
    except Exception:
        host = ""
    for adapter in adapters:
        if host and host in (adapter.get("hosts") or []):
            return adapter
    return None


def parse_remote_url(url: str) -> dict:
    """远端/PR URL → {host}。这里只读 host；完整解析在 pr_status.parse_remote_url。"""
    text = str(url or "").strip()
    if not text:
        return {"host": ""}
    match = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://([^/]+)", text)
    if match:
        hostpart = match.group(1).rsplit("@", 1)[-1]
        if hostpart.startswith("["):
            hostpart = hostpart.split("]")[0].lstrip("[")
        else:
            hostpart = hostpart.rsplit(":", 1)[0]
        return {"host": hostpart.lower()}
    if "@" in text and ":" in text.split("@", 1)[1]:
        return {"host": text.split("@", 1)[1].split(":", 1)[0].lower()}
    return {"host": ""}


def _create_hint(root: Path, target_info: dict, adapters: list) -> str:
    target = _target_target(target_info)
    platform_id = str(target.get("platform") or "")
    adapter = next((a for a in adapters if a.get("id") == platform_id), None)
    if adapter is None:
        return "本机没有对应平台的适配器：按平台文档手动创建 PR，不要猜命令。"
    repo = ""
    if target.get("url"):
        parsed = _full_parse(str(target["url"]))
        repo = parsed.get("repo") or ""
    repo = repo or "<owner/repo>"
    base = str(target.get("base") or "main")
    if adapter.get("kind") == "http":
        spec = (adapter.get("spec") or {}).get("create_hint") or ""
        text = str(spec)
        owner, name = _split_repo(repo)
        text = text.replace("{owner}", owner).replace("{repo}", name).replace("{base}", base)
        return text or "按平台文档用 REST API 创建 PR。"
    module = adapter.get("module")
    fn = getattr(module, "create_hint", None)
    if not callable(fn):
        return f"按 {adapter.get('name')} 的文档创建 PR。"
    try:
        return str(fn({"repo": repo, "base": base, "labels": target.get("labels") or {}}))
    except Exception as exc:
        return f"适配器生成创建命令失败（{type(exc).__name__}: {exc}），按平台文档手动创建。"


def _split_repo(repo: str):
    parts = [p for p in str(repo or "").split("/") if p]
    if not parts:
        return "", ""
    return parts[0], "/".join(parts[1:]) if len(parts) > 1 else parts[0]


def _full_parse(url: str) -> dict:
    """只给 prompt 取 owner/repo：复用 pr_status 的解析（通过 importlib 已加载的模块）。"""
    text = str(url or "").strip()
    match = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://(?P<rest>.+)$", text)
    if not match:
        return {"host": "", "repo": ""}
    rest = match.group("rest")
    hostpart, _, path = rest.partition("/")
    host = hostpart.rsplit("@", 1)[-1].rsplit(":", 1)[0].lower()
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return {"host": host, "repo": "/".join(p for p in path.split("/") if p)}


def _display_url(spec_url: str, adapter: dict, repo: str, number) -> str:
    """把适配器 URL 变成可直接粘贴的 curl 地址：token 只留 `$环境变量`，不出现明文。"""
    owner, name = _split_repo(repo)
    text = str(spec_url or "")
    text = text.replace("{owner}", owner).replace("{repo}", name)
    text = text.replace("{number}", "" if number is None else str(number))

    def repl(match):
        key = match.group(1)
        if key.startswith("env:"):
            return "${" + key[4:] + "}"
        return "${" + key + "}"

    return re.sub(r"\{([A-Za-z0-9_:]+)\}", repl, text)


def _http_check_command(adapter: dict, pr: dict) -> str:
    spec = (adapter.get("spec") or {}).get("check") or {}
    repo = str(pr.get("repo") or "")
    number = pr.get("number")
    url = _display_url(str(spec.get("url") or ""), adapter, repo, number)
    query = spec.get("query") or {}
    if isinstance(query, dict) and query:
        pairs = []
        for key, value in query.items():
            display = _display_url(str(value), adapter, repo, number)
            pairs.append(f"{key}={display}")
        url += ("&" if "?" in url else "?") + "&".join(pairs)
    headers = spec.get("headers") or {}
    header_args = ""
    for key, value in headers.items():
        header = key + ": " + _display_url(str(value), adapter, repo, number)
        header_args += " -H " + _q(header)
    method = str(spec.get("method") or "GET").upper()
    method_arg = "" if method == "GET" else f" -X {method}"
    return f"curl -sS{header_args}{method_arg} " + _q(url)


def _pr_detail(root: Path, target_info: dict, adapters: list, rows: list) -> str:
    if not rows:
        return ""
    lines = []
    for row in rows:
        lines.append("python3 scripts/verify_case_draft.py --gate " + _q(row["path"]))
        final_id = row["promotion"]["caseId"] or "<final-id>"
        lines.append("python3 scripts/groom_record.py --pr-marker --draft-key " + _q(row["key"])
                     + " --submitted-case-id " + _q(final_id))
    target = _target_target(target_info)
    base_ref = f"{target.get('remote') or 'origin'}/{target.get('base') or 'main'}"
    lines.append("python3 scripts/groom_recheck.py --pr-body-file <pr-body.md> --base "
                 + _q(base_ref) + " --head <head>")
    lines.append("按目标平台创建 PR：")
    lines.append("  " + _create_hint(root, target_info, adapters))
    lines.append("开完 PR 后写台账（每份一条，不要手编 JSON）：")
    lines.append("  python3 scripts/pr_status.py --root . --set --draft <key> --platform <platform> "
                 "--repo <owner/repo> --number <n> --url <url> --remote <remote>")
    return "\n".join(lines)


def _check_detail(adapters: list, rows: list) -> str:
    if not rows:
        return ""
    lines = []
    for row in rows:
        pr = row["pr"] or {}
        url = pr.get("url") or ""
        adapter = _adapter_for_url(adapters, url)
        if adapter is None:
            lines.append(f"# {row['key']}：本机没有对应工具，手动打开确认：{url}")
            continue
        if adapter.get("kind") == "http":
            lines.append(_http_check_command(adapter, pr))
            continue
        module = adapter.get("module")
        fn = getattr(module, "check_hint", None)
        if callable(fn):
            try:
                lines.append(str(fn({"repo": pr.get("repo"), "number": pr.get("number"),
                                     "url": url})))
                continue
            except Exception:
                pass
        lines.append(f"# {row['key']}：本机没有对应工具，手动打开确认：{url}")
    return "\n".join(lines)


def _close_detail(target_info: dict, rows: list) -> str:
    if not rows:
        return ""
    lines = []
    if any(not row.get("closedDraft") for row in rows):
        lines.append("python3 scripts/groom_close_draft.py --all --apply")
    target = _target_target(target_info)
    base_ref = f"{target.get('remote') or 'origin'}/{target.get('base') or 'main'}"
    lines += [
        "python3 scripts/groom_cleanup.py --pr-body-file <pr-body.md> --post-merge "
        '--base "$(git rev-parse "$MERGE^1")" --head "$MERGE"',
        "合入提交取法：GitHub 用 `gh pr view <n> --json mergeCommit --jq .mergeCommit.oid`；"
        "其他平台按平台文档取。base 用 `git rev-parse <merge>^1`，不要用 baseRefOid。",
        f"合并前 base 的引用（没取到 merge 提交时用）：{base_ref}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- 主流程

def _history(inbox: Path, done_drafts: dict, ledger: dict, gm) -> list:
    """最近 5 条收尾记录，带 PR 链接。坏行不挡住整段历史（行为与旧版一致）。"""
    path = inbox / ".groom" / "close-log.jsonl"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    prs = ledger.get("prs") if isinstance(ledger.get("prs"), dict) else {}
    for line in lines[-5:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        key = str(obj.get("draft") or obj.get("key") or "").strip()
        at = str(obj.get("at") or "").strip()
        state = str(obj.get("state") or "").strip()
        if not key or not at or not state:
            continue
        draft = done_drafts.get(key)
        out.append({
            "key": key,
            "title": _title_of(gm, draft, key) if draft is not None else "",
            "decision": str(obj.get("decision") or ""),
            "state": state,
            "at": at,
            "pr": _pr_view(prs.get(key)),
        })
    return out


def _draft_record(root: Path, gm, row: dict, draft, inbox: Path,
                  ledger: dict, trace_rows: list, kb_ids: set) -> dict:
    key = str(row.get("draft") or "")
    orphan = bool(row.get("orphan"))
    cases = []
    if draft is not None:
        try:
            cases = gm.draft_cases(draft)
        except Exception:
            cases = []
    # 人决定（by / decided_at）status_rows 不投影，这里按契约复用 load_assessment 取一次。
    if orphan:
        sidecar_path = inbox / ".groom" / "assessments" / f"{key}.yaml"
        try:
            doc = gm.load_yaml(sidecar_path) if sidecar_path.is_file() else {}
        except Exception:
            doc = {}
    else:
        try:
            doc = gm.load_assessment(inbox, key)
        except Exception:
            doc = {}
    human = doc.get("human_decision") if isinstance(doc.get("human_decision"), dict) else {}
    source_session = ""
    if cases:
        source_session = str(cases[0].get("source_session") or "")
    draft_rel = _relpath(root, draft.case_path) if draft is not None else ""
    case_id = str(cases[0].get("id") or "") if cases else ""
    trace = _match_trace(trace_rows, draft_rel, case_id, source_session)
    promotion = _promotion(root, gm, key, trace, human, cases, kb_ids)
    draft_in_inbox = draft is not None and draft.case_path.exists()
    trace_state = trace["state"] if trace else "none"
    done = bool(trace and trace_state in ("knowledge", "archived")
                and draft_in_inbox and _landing_exists(trace_state, promotion, kb_ids))
    pr_entry = ledger["prs"].get(key) if isinstance(ledger.get("prs"), dict) else None
    if not isinstance(pr_entry, dict):
        pr_entry = None
    state = _classify(row, pr_entry, done)
    stage, tone = STATE_META.get(state, (state, "gray"))

    created_at = ""
    if draft is not None:
        try:
            draft_doc = gm.load_yaml(draft.case_path) or {}
            if isinstance(draft_doc, dict):
                created_at = str(draft_doc.get("created_at") or "")
        except Exception:
            created_at = ""
    age_path = draft.case_path if draft is not None else (
        inbox / ".groom" / "assessments" / f"{key}.yaml")
    age_days, age_source = _age_days(created_at, age_path)

    source = _source(trace, done, promotion, kb_ids, draft_in_inbox)
    kind = NEXT_KIND.get(state, "none")
    pr = _pr_view(pr_entry)
    return {
        "key": key,
        "title": _title_of(gm, draft, key),
        "path": draft_rel,
        "caseId": case_id,
        "state": state,
        "stage": stage,
        "stageTone": tone,
        "ageDays": age_days,
        "ageSource": age_source,
        "novelty": row.get("proposed_novelty") or None,
        "confidence": row.get("confidence") or None,
        "candidate": str(row.get("candidate_case") or ""),
        "rationale": str(row.get("rationale") or ""),
        "reviewReasons": list(row.get("review_reasons") or []),
        "stale": bool(row.get("stale")),
        "staleReasons": list(row.get("stale_reasons") or []),
        "decision": str(row.get("human_decision") or ""),
        "decisionValid": bool(row.get("human_decision_valid")),
        "decisionBy": str(human.get("by") or ""),
        "decisionAt": str(human.get("decided_at") or ""),
        "assessed": bool(row.get("assessed")),
        "assessedShort": str(row.get("assessed_short") or ""),
        "assessedCommit": str(row.get("assessed_commit") or ""),
        "createdAt": created_at,
        "closedDraft": False,
        "restore": "",
        "source": source,
        "promotion": promotion,
        "pr": pr,
        "next": {"kind": kind, "label": ("重新评估（继续 groom）" if state == "pr_closed" else ACTION_LABEL.get(kind, "")), "prompt": ""},
        "writeback": _writeback(source["mismatch"], source["sessionId"],
                                promotion["caseId"], key),
    }


def _closed_record(root: Path, gm, key: str, close_entry: dict, draft, inbox: Path,
                   ledger: dict, trace_rows: list, kb_ids: set) -> dict:
    """已出队草稿的队列行：标题从 `.done/` 读，决定从 close-log 读，PR 从台账读。

    评估状态文件可能已经被 cleanup 删掉，所以 `assessed` 以 close-log 的 closed 记录为准。
    """
    cases = []
    if draft is not None:
        try:
            cases = gm.draft_cases(draft)
        except Exception:
            cases = []
    case_id = str(cases[0].get("id") or "") if cases else str(close_entry.get("case_id") or "")
    source_session = (str(cases[0].get("source_session") or "") if cases
                      else str(close_entry.get("session") or ""))
    trace = _match_trace(trace_rows, "", case_id, source_session)
    decision = str(close_entry.get("decision") or "")
    assessed = str(close_entry.get("status") or "") == "closed"
    human = {"decision": decision, "by": "", "decided_at": str(close_entry.get("at") or "")}
    promotion = _promotion(root, gm, key, trace, human, cases, kb_ids)
    pr_entry = ledger["prs"].get(key) if isinstance(ledger.get("prs"), dict) else None
    if not isinstance(pr_entry, dict):
        pr_entry = None
    row = {
        "draft": key, "orphan": False, "assessed": assessed,
        "stale": False, "stale_reasons": [], "proposed_novelty": None,
        "candidate_case": None, "confidence": None, "rationale": "",
        "review_reasons": [], "human_decision": decision,
        "human_decision_valid": assessed, "assessed_short": "", "assessed_commit": "",
    }
    state = _classify(row, pr_entry, False)
    source = _source(trace, False, promotion, kb_ids, False)
    if state == "pr_open":
        # PR 还没合入：草稿本来就已出队，case 只在 PR 分支上。此时 trace 的
        # submitted / knowledge 都可能是正常的，不报「回写」差异。
        source = dict(source, mismatch="none")
    kind = NEXT_KIND.get(state, "none")
    if state == "pr_closed":
        kind = "restore" if draft is not None else "none"
    created_at = str(close_entry.get("at") or "")
    age_path = draft.case_path if draft is not None else None
    age_days, age_source = _age_days(created_at, age_path)
    stage, tone = STATE_META.get(state, (state, "gray"))
    return {
        "key": key,
        "title": _title_of(gm, draft, key),
        "path": "",
        "caseId": case_id,
        "state": state,
        "stage": stage,
        "stageTone": tone,
        "ageDays": age_days,
        "ageSource": age_source,
        "novelty": None,
        "confidence": None,
        "candidate": "",
        "rationale": "",
        "reviewReasons": [],
        "stale": False,
        "staleReasons": [],
        "decision": decision if assessed else "",
        "decisionValid": assessed,
        "decisionBy": "",
        "decisionAt": str(close_entry.get("at") or ""),
        "assessed": assessed,
        "assessedShort": "",
        "assessedCommit": "",
        "createdAt": created_at,
        "closedDraft": True,
        "assessmentCleared": not (inbox / ".groom" / "assessments"
                                  / f"{gm.sanitize_key(key)}.yaml").is_file(),
        "restore": _restore_prompt(inbox, key, draft) if kind == "restore" else "",
        "source": source,
        "promotion": promotion,
        "pr": _pr_view(pr_entry),
        "next": {"kind": kind,
                 "label": ("恢复草稿" if kind == "restore" else ACTION_LABEL.get(kind, "")),
                 "prompt": ""},
        "writeback": _writeback(source["mismatch"], source["sessionId"],
                                promotion["caseId"], key),
    }


def _counts(rows: list) -> dict:
    counts = {"total": len(rows), "unassessed": 0, "needDecision": 0, "needRerun": 0,
              "decided": 0, "prOpen": 0, "prMerged": 0, "overdue": 0, "oldestDays": 0}
    key_map = {"unassessed": "unassessed", "need_decision": "needDecision",
               "need_rerun": "needRerun", "decided": "decided",
               "pr_open": "prOpen", "pr_merged": "prMerged"}
    for row in rows:
        name = key_map.get(row["state"])
        if name:
            counts[name] += 1
        if row["ageDays"] > OVERDUE_DAYS:
            counts["overdue"] += 1
        counts["oldestDays"] = max(counts["oldestDays"], int(row["ageDays"]))
    return counts


def _primary(rows: list, prompts: dict) -> dict:
    for kind in ("groom", "pr", "check", "close", "restore"):
        if any(row["next"]["kind"] == kind for row in rows):
            label = "恢复草稿" if kind == "restore" else ACTION_LABEL[kind]
            return {"kind": kind, "label": label, "prompt": prompts.get(kind, "")}
    return {"kind": "none", "label": "", "prompt": ""}


def _attach_prompts(root: Path, rows: list, target_info: dict, adapters: list,
                    inbox: Path) -> dict:
    groom_rows = [r for r in rows if r["state"] in ("unassessed", "need_decision", "need_rerun", "pr_closed")]
    decided = [r for r in rows if r["state"] == "decided"]
    checking = [r for r in rows if r["state"] == "pr_open"]
    closing = [r for r in rows if r["state"] == "pr_merged"]
    restoring = [r for r in rows if r["next"]["kind"] == "restore"]
    prompts = {
        "groom": _prompt_groom(_inbox_rel(root, inbox), rows) if groom_rows else "",
        "pr": _prompt_pr(root, inbox, target_info, adapters, decided),
        "check": _prompt_check(root, inbox, adapters, checking),
        "close": _prompt_close(closing),
        "restore": "\n\n".join(r.get("restore") or "" for r in restoring).strip(),
        "groomDetail": _groom_detail() if groom_rows else "",
        "prDetail": _pr_detail(root, target_info, adapters, decided),
        "checkDetail": _check_detail(adapters, checking),
        "closeDetail": _close_detail(target_info, closing),
    }
    for row in rows:
        kind = row["next"]["kind"]
        row["next"]["prompt"] = row.get("restore") or "" if kind == "restore" else prompts.get(kind, "")
    return prompts


def collect(root, only: str = "") -> dict:
    """队列投影。只读：不写文件、不 fetch；失败抛 SedimentError。"""
    root = Path(root).expanduser().resolve()
    deps = _scripts(root)
    gm, gs, prs, ts = deps["gm"], deps["gs"], deps["pr"], deps["ts"]
    try:
        root = gm.repo_root(root)
    except Exception:
        pass
    try:
        inbox = Path(gm.shared_inbox(root))
    except Exception as exc:
        raise SedimentError("E_INBOX", f"解析共享 inbox 失败：{exc}") from exc
    ledger_error = ""
    try:
        ledger = prs.load_ledger(root)
    except Exception as exc:
        # 坏台账不让队列空掉：PR 列显示不了，队列其余部分照出。
        # 已出队的条目用「未确认」占一行，避免在途事项整条消失。
        ledger = prs.empty_ledger()
        ledger_error = str(exc)
    target_commit = _target_commit(gm, root, ledger)
    try:
        rows = gs.status_rows(root, target_commit, inbox)
    except Exception as exc:
        raise SedimentError("E_GROOM", f"groom 状态计算失败：{exc}") from exc
    traces = Path(deps["el"].resolve_traces(root))
    trace_rows = _trace_index(ts, traces)
    try:
        kb_ids = set(ts.kb_case_meta(root))
    except Exception:
        kb_ids = set()
    drafts = {draft.key: draft for draft in gm.find_drafts(inbox)}
    close_index = _close_index(_read_close_log(inbox))
    # orphan 行的 key 来自评估状态文件名（sanitize_key 加了哈希），要能对回 close-log 的原始 key。
    close_by_sanitized = {gm.sanitize_key(key): key for key in close_index}
    done_drafts = {key: _done_draft(inbox, key, gm) for key in close_index}
    target_info = prs.list_targets(root)
    adapters = prs.load_adapters()
    target = _target_target(target_info)
    platform_id = str(target.get("platform") or "")
    target_info["platformName"] = _platform_name(adapters, platform_id) if platform_id else ""
    ledger_prs = ledger.get("prs") if isinstance(ledger.get("prs"), dict) else {}
    if ledger_error:
        for key, entry in close_index.items():
            if entry.get("status") == "closed" and not isinstance(ledger_prs.get(key), dict):
                ledger_prs[key] = {"state": "unknown", "source": "ledger", "url": "",
                                   "platform": "", "repo": "", "number": None}
    ledger_by_sanitized = {gm.sanitize_key(key): key for key in ledger_prs}
    for key in ledger_prs:
        done_drafts.setdefault(key, _done_draft(inbox, key, gm))
    records, seen = [], set()
    orphan_terminal = set()
    for row in rows:
        key = str(row.get("draft") or "")
        raw = key if key in close_index else close_by_sanitized.get(
            key, key if key in ledger_prs else ledger_by_sanitized.get(key, key))
        closed = close_index.get(raw)
        if row.get("orphan"):
            # 正常出队（close-log 有 closed 记录）不算孤儿；台账里有 PR 时也交给
            # 下面的 PR 行，避免同一个 key 出现孤儿 + PR 两行。
            if closed and closed.get("status") == "closed":
                continue
            if raw in ledger_prs:
                entry = ledger_prs[raw]
                if isinstance(entry, dict):
                    if _pr_state(entry) in ("merged", "closed"):
                        # 终态 PR 没有 close-log 时，台帐行本身没有动作；但残留的
                        # assessment 还需要按 PR body 清理一次，先留一行给它。
                        orphan_terminal.add(raw)
                    continue
                # 台账里是一个坏值（不是对象）：保留孤儿行，至少让人看见评估残留。
        records.append(_draft_record(root, gm, row, drafts.get(key),
                                     inbox, ledger, trace_rows, kb_ids))
        seen.add(key)
    # 已出队、但 PR 还没走完的：一行不丢，状态由 PR 决定。
    for key, close_entry in close_index.items():
        if key in seen or close_entry.get("status") != "closed":
            continue
        pr_entry = ledger_prs.get(key)
        if not isinstance(pr_entry, dict):
            continue
        if _pr_state(pr_entry) == "merged":
            continue                       # 已合入且已收尾，进历史
        records.append(_closed_record(root, gm, key, close_entry, done_drafts.get(key),
                                      inbox, ledger, trace_rows, kb_ids))
        seen.add(key)
    # 台账里有 PR、本地既没有草稿也没有 close-log 的（换机器、手工出队、评估残留）：
    # 只收未终态的 PR。merged / closed 没有本地记录，也没有可执行的本地动作，
    # 不进队列（平台是唯一事实来源），避免留一行永远消不掉。
    for key, pr_entry in ledger_prs.items():
        if key in seen or key in close_index or not isinstance(pr_entry, dict):
            continue
        if _pr_state(pr_entry) not in ("open", "unknown") and key not in orphan_terminal:
            continue
        close_entry = {
            "key": key, "at": str(pr_entry.get("created_at") or ledger.get("updated_at") or ""),
            "state": "", "status": "", "decision": "", "case_id": "", "session": "",
        }
        records.append(_closed_record(root, gm, key, close_entry, done_drafts.get(key),
                                      inbox, ledger, trace_rows, kb_ids))
        seen.add(key)
    row_keys = {r["key"] for r in records}
    if only:
        records = [r for r in records if r["source"]["sessionId"] == only]
    prompts = _attach_prompts(root, records, target_info, adapters, inbox)
    counts = _counts(records)
    return {
        "generatedAt": now_iso(),
        "root": str(root),
        "targetCommit": target_commit,
        "targetCommitShort": gm.short_sha(target_commit),
        "inbox": str(inbox),
        "counts": counts,
        "target": target_info,
        "ledgerError": ledger_error,
        "primary": _primary(records, prompts),
        "prompts": prompts,
        "drafts": records,
        "history": [item for item in _history(inbox, done_drafts, ledger, gm)
                    if item["key"] not in row_keys],
    }


def print_human(payload: dict) -> None:
    counts = payload["counts"]
    print(f"目标知识版本 {payload['targetCommitShort']} · inbox {payload['inbox']}")
    print(f"事项 {counts['total']} 条：未评估 {counts['unassessed']}"
          f" · 待决定 {counts['needDecision']} · 需重跑 {counts['needRerun']} · 待提 PR "
          f"{counts['decided']} · PR 待合入 {counts['prOpen']} · PR 已合入 {counts['prMerged']}")
    if not payload["drafts"]:
        print("队列为空。")
        return
    for row in payload["drafts"]:
        print(f"{row['key']:<40} {row['stage']:<18} {row['ageDays']:>3}d  "
              f"next={row['next']['kind'] or '—'}")
    primary = payload["primary"]
    if primary.get("kind") != "none":
        print(f"下一步：{primary['label']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="沉淀队列数据面（只读）")
    parser.add_argument("--root", required=True, help="ascend-sleuth 检出根目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON（默认人读一屏）")
    parser.add_argument("--only", default="", help="只保留来源为该诊断 session 的草稿")
    args = parser.parse_args(argv)
    try:
        payload = collect(args.root, only=args.only)
    except SedimentError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "message": exc.message},
                         ensure_ascii=False))
        return 0
    except Exception as exc:  # 未预期异常也走 JSON：调用方只看 ok
        print(json.dumps({"ok": False, "code": "E_INTERNAL",
                          "message": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 0
    payload["ok"] = True
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print_human(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
