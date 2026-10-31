#!/usr/bin/env python3
"""_trace_state.py —— 诊断状态的唯一判据实现（库）

**为什么需要**：同一套状态判据此前有五处各自实现（升格闸门、沉淀清点、导出意图、
面板 JS、面板 host 计数），面板是 JS、脚本是 Python，代码不能共享，只能靠注释提醒
「改一处必须同步另一处」。本轮把这些判据收进这一个模块：Python 读端 import 它，
面板经 host 读它的投影（`trace_state.py --json`），规则只在一门语言里。

**它不是什么**：不是写入口（写入口见 `trace_transition.py`）；不做语义判断（不判
「该不该入库」）；不读 traces 以外的运行时件。

口径出处都写在函数注释里，改口径前先读那一条对应的既有实现。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from _yaml import load_file, load_text

SCHEME = "ascend-sleuth-trace-state/1"

# 与 `scripts/sediment_batch.py:48-50` 同一组判据：真 case id / 占位串。两处分家会造出
# 「面板说已闭环、闸门拦下」的反例（`verify_case_draft.py` 顶部注释也点了这件事）。
REAL_CASE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
PLACEHOLDER_CASE = re.compile(r"^pending[-_]investigation\b", re.I)

# 状态列配色：表达「这单在哪一步」，不表达「该不该你做事」（见 dsh-plugins/README.md
# 的颜色角色表例外）。`resolved` 用绿是历史选择（列表扫读先看这一列），但反向回报时
# 面板会把它降级成灰——绿色不得与旁边「fix 未生效」的红徽标同时出现。
STATUS_STYLE = {
    "in_progress": {"color": "var(--c-blue)", "accent": "var(--acc-blue)", "order": 10},
    "resolved": {"color": "var(--c-green)", "accent": "var(--acc-green)", "order": 20},
    "escalated": {"color": "var(--c-gray)", "accent": "var(--acc-gray)", "order": 30},
    "archived": {"color": "var(--c-gray)", "accent": "var(--acc-gray)", "order": 40},
    "unknown": {"color": "var(--c-gray)", "accent": "var(--acc-gray)", "order": 50},
}
# 欠账/风险/可复用的颜色语义在面板 README 的颜色角色表里；这里只给状态列。
NEGATIVE_OUTCOMES = {"not_resolved", "partial"}


def _as_list(value) -> list[str]:
    """YAML 里同一个键可能写成标量也可能写成列表；这里统一成列表（标量按单元素处理）。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(x) for x in value]
    return [str(value)]


def load_vocab(root: Path | str) -> dict:
    """读 `trace-status.yaml`：状态、收尾方式、转移表。文件坏了就直接抛（不静默用默认值）。"""
    doc = load_file(Path(root) / "trace-status.yaml") or {}
    statuses = []
    for entry in doc.get("status") or []:
        value = str(entry.get("value") or "")
        if not value:
            continue
        style = STATUS_STYLE.get(value, STATUS_STYLE["unknown"])
        statuses.append({
            "value": value,
            "label": str(entry.get("label") or value),
            "terminal": bool(entry.get("terminal")),
            "resumable": bool(entry.get("resumable")),
            "meaning": str(entry.get("meaning") or ""),
            "color": style["color"],
            "accent": style["accent"],
            "order": style["order"],
        })
    endings = []
    for entry in doc.get("ending_kinds") or []:
        value = str(entry.get("value") or "")
        if not value:
            continue
        endings.append({
            "value": value,
            "label": str(entry.get("label") or value),
            "requires": _as_list(entry.get("requires")),
            "statuses": _as_list(entry.get("statuses")),
        })
    transitions = []
    for entry in doc.get("transitions") or []:
        transitions.append({
            "from": _as_list(entry.get("from")),
            "to": _as_list(entry.get("to")),
            "action": str(entry.get("action") or ""),
            "actionLabel": str(entry.get("action_label") or entry.get("action") or ""),
            "ending": entry.get("ending"),
            "endingChoices": _as_list(entry.get("ending_choices")),
            "requires": _as_list(entry.get("requires")),
            "fillable": _as_list(entry.get("fillable")),
            "mustExist": _as_list(entry.get("must_exist")),
            "mustExistIfCase": _as_list(entry.get("must_exist_if_case")),
            "exceptSame": bool(entry.get("except_same")),
            "sameStatus": bool(entry.get("same_status")),
            "expandsTo": _as_list(entry.get("expands_to")),
        })
    severities = [{"value": str(x.get("value"))} for x in (doc.get("severity") or []) if isinstance(x, dict)]
    if not severities:
        # 严重级词表在 case schema（docs/spec/case-schema.md）；这里不另造，缺省给三档。
        severities = [{"value": "benign"}, {"value": "service-affecting"}, {"value": "data-loss-risk"}]
    return {
        "statuses": statuses,
        "endings": endings,
        "transitions": transitions,
        "severities": severities,
        "stopReasons": [str(x.get("value")) for x in (doc.get("stop_reasons") or []) if isinstance(x, dict)],
    }


def status_meta(vocab: dict, value: str) -> dict:
    for s in vocab["statuses"]:
        if s["value"] == value:
            return s
    return {"value": value, "label": value, "terminal": False, "resumable": False,
            "meaning": "", "color": STATUS_STYLE["unknown"]["color"],
            "accent": STATUS_STYLE["unknown"]["accent"], "order": 99}


def is_terminal(vocab: dict, value: str) -> bool:
    return bool(status_meta(vocab, value)["terminal"])


def case_kind(active_case) -> str:
    """case / placeholder / none。占位串不是 case id（同 `verify_case_draft.py` 的判据）。"""
    raw = "" if active_case is None else str(active_case).strip()
    if REAL_CASE.match(raw):
        return "case"
    if PLACEHOLDER_CASE.match(raw):
        return "placeholder"
    return "none"


def feedback_of(doc: dict) -> dict:
    """`feedback.outcome` 与 `pending_since`。兼容旧写法（`feedback` 是字符串）。"""
    fb = doc.get("feedback")
    if isinstance(fb, dict):
        outcome = str(fb.get("outcome") or "")
        return {"outcome": outcome or None,
                "case": str(fb.get("case") or ""),
                "pendingSince": fb.get("pending_since") or doc.get("feedback_pending_since")}
    if isinstance(fb, str) and fb.strip():
        return {"outcome": fb.strip(), "case": "", "pendingSince": doc.get("feedback_pending_since")}
    return {"outcome": None, "case": "", "pendingSince": doc.get("feedback_pending_since")}


def sed_state(doc: dict) -> str:
    sed = doc.get("sedimented")
    if isinstance(sed, dict):
        return str(sed.get("state") or "none")
    if isinstance(sed, str) and sed.strip():
        return sed.strip()
    return "none"


def derive(doc: dict, kb_case_ids: set[str]) -> dict:
    """派生量。每条口径都标了出处，改之前先读那一处；这里只搬运，不新增判断。"""
    status = str(doc.get("status") or "unknown")
    kind = case_kind(doc.get("active_case"))
    active_case = "" if doc.get("active_case") is None else str(doc.get("active_case"))
    fb = feedback_of(doc)
    sed = sed_state(doc)
    candidates = doc.get("sediment_candidates") or []
    case_candidates = [c for c in candidates if isinstance(c, dict) and str(c.get("kind") or "") == "case"]
    report = doc.get("report_file")
    summary = doc.get("summary")
    trace = doc.get("trace") or []
    steps = len(trace)
    active_in_kb = bool(kind == "case" and active_case in kb_case_ids)

    # 闭环：命中单看 feedback.outcome；无命中单看 status（`verify_case_draft.py:229-236`）。
    closed = fb["outcome"] == "resolved" or (kind != "case" and status == "resolved" and not fb["outcome"])
    open_ = status in ("in_progress", "unknown")
    skeleton = steps == 0 and not (summary or report or candidates)
    submitted = sed == "submitted"
    need_sed = sed == "none" and not active_in_kb and bool(case_candidates)
    need_review = sed == "none" and not active_in_kb and not case_candidates and bool(report or candidates)
    need_promote = submitted and not closed
    need_work = open_ and not skeleton and not need_sed and not need_review and not submitted
    need_confirm = status == "resolved" and fb["outcome"] == "pending"

    # 价值序：`panel-client.js:915-935`。面板排序与侧栏共用，搬过来避免两套。
    if sed != "none":
        value_rank = 5
    elif kind == "case":
        value_rank = 4 if active_in_kb else 3
    elif fb["outcome"] == "resolved":
        value_rank = 2
    elif status == "resolved":
        value_rank = 1
    else:
        value_rank = 0

    events = [e for e in (doc.get("transitions") or []) if isinstance(e, dict)]
    time_source = "transitions" if events else "updated_at"
    return {
        "open": open_,
        "closed": closed,
        "needSed": need_sed,
        "needReview": need_review,
        "needPromote": need_promote,
        "needWork": need_work,
        "skeleton": skeleton,
        "submitted": submitted,
        "needConfirm": need_confirm,
        "caseKind": kind,
        "activeCaseInKb": active_in_kb,
        "sedState": sed,
        "valueRank": value_rank,
        "timeSource": time_source,
        "heading": "resolved" if status == "resolved" and fb["outcome"] in NEGATIVE_OUTCOMES else None,
    }


def _path_get(doc: dict, path: str):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _nonempty(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        return True
    return True


def actions_for(doc: dict, vocab: dict, derived: dict) -> list[dict]:
    """当前状态允许的动作。面板只渲染它，不再自己算规则。

    过滤规则与 `trace-status.yaml` 的转移表一一对应：
      - 普通动作：当前状态在 `from` 里，且目标不是当前状态（收尾/重新打开）；
      - `except_same`（改收尾方式）：已收尾且有收尾方式时的换一种；
      - `same_status`（补记收尾方式）：已收尾但缺收尾方式时的补记。
    """
    status = str(doc.get("status") or "unknown")
    ending = doc.get("ending") if isinstance(doc.get("ending"), dict) else None
    out = []
    for t in vocab["transitions"]:
        if status not in t["from"]:
            continue
        if t["sameStatus"]:
            if ending:
                continue
        elif t["exceptSame"]:
            if not ending:
                continue
        elif status in t["to"]:
            continue
        kinds = [t["ending"]] if t["ending"] else list(t["endingChoices"])
        must_exist = list(t["mustExist"]) + (list(t["mustExistIfCase"]) if derived["caseKind"] == "case" else [])
        out.append({
            "id": t["action"],
            "label": t["actionLabel"],
            "to": t["to"],
            "requires": list(t["requires"]),
            "fillable": list(t["fillable"]),
            "mustExist": must_exist,
            "endingChoices": [
                {"value": k,
                 "label": next((e["label"] for e in vocab["endings"] if e["value"] == k), k),
                 "requires": next((e["requires"] for e in vocab["endings"] if e["value"] == k), [])}
                for k in kinds
            ],
            "expandsTo": list(t["expandsTo"]),
            "exceptSame": t["exceptSame"],
            "sameStatus": t["sameStatus"],
        })
    order = {"close-resolved": 10, "close-escalated": 20, "close-archived": 30,
             "correct-ending": 40, "backfill-ending": 50, "reopen": 90}
    out.sort(key=lambda a: order.get(a["id"], 60))
    return out


def vocab_actions(vocab: dict) -> list[dict]:
    """面板用的动作词表（camelCase，含收尾方式候选）。与 `actions_for` 同源。"""
    out = []
    for t in vocab["transitions"]:
        kinds = [t["ending"]] if t["ending"] else list(t["endingChoices"])
        out.append({
            "id": t["action"],
            "label": t["actionLabel"],
            "to": t["to"],
            "requires": list(t["requires"]),
            "fillable": list(t["fillable"]),
            "mustExist": list(t["mustExist"]),
            "mustExistIfCase": list(t["mustExistIfCase"]),
            "exceptSame": t["exceptSame"],
            "sameStatus": t["sameStatus"],
            "expandsTo": list(t["expandsTo"]),
            "endingChoices": [
                {"value": k,
                 "label": next((e["label"] for e in vocab["endings"] if e["value"] == k), k),
                 "requires": next((e["requires"] for e in vocab["endings"] if e["value"] == k), [])}
                for k in kinds
            ],
        })
    return out


def load_traces(traces_root: Path | str) -> list[dict]:
    """读全部 `*.yaml`。解析失败的单也返回（`doc: None` 且带 `error`），面板要能看见坏件。

    每份文件算 `contentSha256`：面板写回时拿它做 CAS 令牌，比 status 比较能挡住
    「两个窗口同时收尾、后写覆盖先写」这类丢事件。
    """
    root = Path(traces_root)
    rows = []
    for path in sorted(root.glob("*.yaml")):
        raw = path.read_bytes()
        entry = {
            "sessionId": path.stem,
            "file": path.name,
            "contentSha256": hashlib.sha256(raw).hexdigest(),
            "doc": None,
            "error": None,
        }
        try:
            entry["doc"] = load_text(raw.decode("utf-8")) or {}
        except Exception as exc:  # 坏件不阻断列表，只标记
            entry["error"] = str(exc)
        doc = entry["doc"] or {}
        entry["sessionId"] = str(doc.get("session_id") or path.stem)
        rows.append(entry)
    return rows


def kb_case_ids(kb_root: Path | str) -> set[str]:
    """知识库里已有的 case id（滚 `knowledge/**/*.yaml` 的 id 字段）。

    `closed` 与 `needSed` 都要它：命中的 case 在不在库里决定「还要不要沉淀」。
    """
    ids = set()
    root = Path(kb_root) / "knowledge"
    if not root.is_dir():
        return ids
    for path in root.rglob("*.yaml"):
        if path.name.startswith("_"):
            continue
        try:
            doc = load_file(path) or {}
        except Exception:
            continue
        for case in doc.get("cases") or []:
            if isinstance(case, dict) and case.get("id"):
                ids.add(str(case["id"]))
    return ids


def project(traces_root: Path | str, kb_root: Path | str, caps: dict | None = None,
            only: str | None = None) -> dict:
    """面板与 CLI 共用的投影。`state` 不进 host 的版本缓存（它依赖 KB 与能力位）。"""
    vocab = load_vocab(Path(kb_root))
    ids = kb_case_ids(kb_root)
    sessions = []
    for entry in load_traces(traces_root):
        if only and entry["sessionId"] != only:
            continue
        doc = entry["doc"] or {}
        derived = derive(doc, ids)
        row = {
            "sessionId": entry["sessionId"],
            "file": entry["file"],
            "contentSha256": entry["contentSha256"],
            "status": str(doc.get("status") or "unknown"),
            "ending": doc.get("ending") if isinstance(doc.get("ending"), dict) else None,
            "feedback": feedback_of(doc),
            "sedimented": {
                "state": sed_state(doc),
                "case_id": str((doc.get("sedimented") or {}).get("case_id") or "")
                if isinstance(doc.get("sedimented"), dict) else "",
            },
            "provenance": {
                "statusBy": (doc.get("transitions") or [{}])[-1].get("by") if doc.get("transitions") else None,
                "statusAt": (doc.get("transitions") or [{}])[-1].get("at") if doc.get("transitions") else None,
                "source": (doc.get("transitions") or [{}])[-1].get("source") if doc.get("transitions") else None,
                "timeSource": derived["timeSource"],
            },
            "derived": derived,
            "transitions": [
                {"at": e.get("at"), "from": e.get("from"), "to": e.get("to"),
                 "ending": (e.get("ending") or {}).get("kind") if isinstance(e.get("ending"), dict) else None,
                 "by": e.get("by"), "source": e.get("source")}
                for e in (doc.get("transitions") or []) if isinstance(e, dict)
            ],
            "actions": [a["id"] for a in actions_for(doc, vocab, derived)],
        }
        if entry["error"]:
            row["error"] = entry["error"]
        sessions.append(row)
    return {
        "schemeVersion": SCHEME,
        "capabilities": caps or {"canWrite": False, "writeRoot": "", "reason": "未提供能力位"},
        "vocab": {
            "statuses": vocab["statuses"],
            "endings": [{"value": e["value"], "label": e["label"], "requires": e["requires"]}
                        for e in vocab["endings"]],
            "severities": vocab["severities"],
            "actions": vocab_actions(vocab),
        },
        "sessions": sessions,
    }


def check_vocab(vocab: dict) -> list[str]:
    """词表自洽检查（`trace_state.py --check` 与 `verify_trace_status.py --check` 共用）。"""
    errs = []
    statuses = {s["value"] for s in vocab["statuses"]}
    endings = {e["value"] for e in vocab["endings"]}
    actions = {t["action"] for t in vocab["transitions"]}
    for t in vocab["transitions"]:
        if not t["from"] or any(s not in statuses for s in t["from"]):
            errs.append(f"{t['action']}: from 含未声明的状态 {t['from']}")
        if not t["to"] or any(s not in statuses for s in t["to"]):
            errs.append(f"{t['action']}: to 含未声明的状态 {t['to']}")
        for aid in t["expandsTo"]:
            if aid not in actions:
                errs.append(f"{t['action']}: expands_to 指向未定义的动作 {aid}")
        for key in ("requires", "fillable", "mustExist", "mustExistIfCase"):
            for field in t[key]:
                if "." not in field and field not in {
                        "summary", "severity", "fix_emitted", "resolved_at", "feedback.outcome"}:
                    errs.append(f"{t['action']}: {key} 里的字段 {field} 不在字段清单里")
        kinds = [t["ending"]] if t["ending"] else list(t["endingChoices"])
        for kind in kinds:
            if kind and kind not in endings:
                errs.append(f"{t['action']}: 收尾方式 {kind} 未在 ending_kinds 声明")
        if t["exceptSame"] and t["sameStatus"]:
            errs.append(f"{t['action']}: except_same 与 same_status 不能同时为真")
    seen = [t["action"] for t in vocab["transitions"]]
    dup = sorted({a for a in seen if seen.count(a) > 1})
    if dup:
        errs.append("动作 id 重复：" + "、".join(dup))
    return errs
