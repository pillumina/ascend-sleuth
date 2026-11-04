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

# 投影缓存（`scripts/trace_state.py` 的 `.state-cache.json`）的键含本值：派生量或其判据
# 变化时必须 bump，否则升级后命中旧缓存的面板会继续拿旧判据（筛选恒空或分类错）。
SCHEME = "ascend-sleuth-trace-state/4"

# 与 `scripts/sediment_batch.py:48-50` 同一组判据：真 case id / 占位串。两处分家会造出
# 「面板说已闭环、闸门拦下」的反例（`verify_case_draft.py` 顶部注释也点了这件事）。
REAL_CASE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
PLACEHOLDER_CASE = re.compile(r"^pending[-_]investigation\b", re.I)

# 状态列配色：表达「这单在哪一步」，不表达「该不该你做事」（见 dsh-plugins/README.md
# 的颜色角色表例外）。`resolved` 用绿是历史选择（列表扫读先看这一列），但反向回报时
# 面板会把它降级成灰——绿色不得与旁边「fix 未生效」的红徽标同时出现。
# 颜色/顺序以 `trace-status.yaml` 的 status 段为准；这里只剩「未知状态」的兜底颜色。
FALLBACK_STYLE = {"color": "var(--c-gray)", "accent": "var(--acc-gray)", "order": 99}
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
        style = {
            "color": str(entry.get("color") or FALLBACK_STYLE["color"]),
            "accent": str(entry.get("accent") or FALLBACK_STYLE["accent"]),
            "order": int(entry.get("order") or FALLBACK_STYLE["order"]),
        }
        statuses.append({
            "value": value,
            "label": str(entry.get("label") or value),
            "terminal": bool(entry.get("terminal")),
            "resumable": bool(entry.get("resumable")),
            "meaning": str(entry.get("meaning") or "").replace("**", "").strip(),
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
    severities = [{"value": str(x.get("value")), "label": str(x.get("label") or x.get("value"))}
                  for x in (doc.get("severity") or []) if isinstance(x, dict)]
    if not severities:
        # 词表缺这一段时不让面板空着（旧 trace-status.yaml 兼容）；正常应以文件为准。
        severities = [{"value": "benign", "label": "不影响服务"},
                      {"value": "service-affecting", "label": "影响服务"},
                      {"value": "data-loss-risk", "label": "数据丢失风险"}]
    outcomes = [{"value": str(x.get("value")), "label": str(x.get("label") or x.get("value")),
                 "countsAs": str(x.get("counts_as") or "")}
                for x in (doc.get("outcome") or []) if isinstance(x, dict)]
    sedimented = [{"value": str(x.get("value")), "label": str(x.get("label") or x.get("value"))}
                  for x in (doc.get("sedimented") or []) if isinstance(x, dict)]
    provenance = {
        "by": {"user": "本机用户", "agent": "agent", "cli": "命令行"},
        "source": {"panel": "面板", "cli": "命令行", "agent": "agent", "import": "上一台机器"},
    }
    return {
        "statuses": statuses,
        "outcomes": outcomes,
        "sedimented": sedimented,
        "provenance": provenance,
        "endings": endings,
        "transitions": transitions,
        "severities": severities,
        "stopReasons": [str(x.get("value")) for x in (doc.get("stop_reasons") or []) if isinstance(x, dict)],
        "sedStates": [str(x.get("value")) for x in (doc.get("sedimented") or []) if isinstance(x, dict)],
        "reportSources": [{"value": str(x.get("value")), "label": str(x.get("label") or x.get("value"))}
                          for x in (doc.get("report_sources") or []) if isinstance(x, dict)],
        "reportResults": [{"value": str(x.get("value")), "label": str(x.get("label") or x.get("value")),
                           "outcome": str(x.get("outcome") or ""), "review": bool(x.get("review"))}
                          for x in (doc.get("report_results") or []) if isinstance(x, dict)],
        "reviewVerdicts": [{"value": str(x.get("value")), "label": str(x.get("label") or x.get("value"))}
                           for x in (doc.get("review_verdicts") or []) if isinstance(x, dict)],
    }


def status_meta(vocab: dict, value: str) -> dict:
    for s in vocab["statuses"]:
        if s["value"] == value:
            return s
    return {"value": value, "label": value, "terminal": False, "resumable": False,
            "meaning": "", **FALLBACK_STYLE}


def is_terminal(vocab: dict, value: str) -> bool:
    return bool(status_meta(vocab, value)["terminal"])


def case_kind(active_case) -> str:
    """case / placeholder / none。

    口径与面板 host（`panel-host.js:337-344`）和升格闸门一致：**非空且不是占位串即 case**。
    这里不做 `REAL_CASE` 的格式校验——带注释的 active_case（如 `VLLM-ASC-11312 (see #1)`）
    在 host 侧算命中，判据必须同一口径，否则会出现「面板说已闭环、闸门拦下」。
    """
    raw = "" if active_case is None else str(active_case).strip()
    if not raw or raw.lower() in ("null", "none", "nil", "n/a", "na"):
        return "none"
    if PLACEHOLDER_CASE.match(raw):
        return "placeholder"
    return "case"


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


def derive(doc: dict, kb_case_ids: set[str], kb_cases: dict | None = None) -> dict:
    """派生量。每条口径都标了出处，改之前先读那一处；这里只搬运，不新增判断。

    `kb_cases` 是命中案例在知识库里的那点附加事实（`kb_case_meta`）：目前只有上游锚点。
    不传或没这条案例时，与「等上游」相关的两个字段按"不可判"处理（false / null），不猜。
    """
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

    reports = [r for r in (doc.get("reports") or []) if isinstance(r, dict)]
    latest_report = reports[-1] if reports else None
    reviews = [r for r in (doc.get("reviews") or []) if isinstance(r, dict)]
    latest_review = reviews[-1] if reviews else None
    # 待复核 = 最新一条回报是「换别的方法解决」，且之后还没有复核结论。
    reviewed_after_report = bool(
        latest_review and latest_report
        and str(latest_review.get("at") or "") >= str(latest_report.get("at") or ""))
    need_report_review = bool(latest_report and latest_report.get("result") == "other_way"
                              and not reviewed_after_report)
    vendor_confirmed = any(r.get("source") == "vendor" and r.get("result") in ("from_report", "other_way")
                           for r in reports)
    events = [e for e in (doc.get("transitions") or []) if isinstance(e, dict)]
    time_source = "transitions" if events else "updated_at"
    # 等上游：诊断已收尾、本机没给出可执行修复、且**这条案例的依据在上游**。
    # 它不是新状态，是四个已有事实的现算组合：
    #   ① 收尾轴 `status: resolved`；
    #   ② `fix_emitted` 为假（本机没给可执行修复）；
    #   ③ 案例带 `upstream` 锚点（查得到上游，`docs/spec/case-schema.md` 3.8）；
    #   ④ 案例的 `verification.source` 是 `upstream-` 档——**这一条是防误标的**（见下）。
    # 为什么需要 ④：`fix_emitted: false` 不只表示"等上游"，还表示"只定位到根因"；
    # `data-loss-risk` 更是闸门要求不给 fix（先停、保留现场、通知 owner）。只看 ②③ 会把
    # 「先停」单同时挂上「等上游」，读者把"先停"读成"本机没有待办动作"。所以要求案例本身的
    # 结论依据在上游（upstream-fix-merged / upstream-maintainer-confirmed / upstream-official-doc），
    # 且不是数据风险卡。
    upstream = None
    if active_in_kb and kb_cases:
        info = kb_cases.get(active_case) or {}
        if info.get("anchors"):
            upstream = {"anchors": list(info["anchors"]),
                        "lastVerified": str(info.get("lastVerified") or ""),
                        "verificationSource": str(info.get("verificationSource") or "")}
    fix_flag = _bool_flag(doc, "fix_emitted")
    fix_false = fix_flag is False
    upstream_grounded = bool(upstream and upstream["verificationSource"].startswith("upstream-"))
    upstream_pending = bool(upstream_grounded and status == "resolved" and fix_false
                            and str(doc.get("severity") or "") != "data-loss-risk")

    # 「在等什么」：派生量，不写盘。顶层 `last_action` 是当前提问，优先用它；只有它空着
    # 才退到最近一条 `evidence.missing`（旧 trace 没写 last_action 的兜底）。只对未收尾的单
    # 有意义——收尾后历史缺口不是"还在等"。写入纪律见
    # `skills/diagnose/references/diagnosis-trace.md` 的 last_action 一节。
    waiting_for = ""
    if open_:
        waiting_for = re.sub(r"\s+", " ", str(doc.get("last_action") or "")).strip()
        if not waiting_for:
            for ev in reversed(trace):
                if not isinstance(ev, dict):
                    continue
                evd = ev.get("evidence")
                if isinstance(evd, dict) and evd.get("missing"):
                    waiting_for = re.sub(r"\s+", " ", str(evd["missing"])).strip()
                    break

    # 等谁：一条状态轴上的人读分类，不是新状态。优先级：等上游（已收尾、等外部）>
    # 等现场回报（有真实 case 的 pending）> 已结束 > 等沉淀 > 等现场材料/决定。
    fb_pending_case = bool(fb["outcome"] == "pending" and case_kind(fb.get("case")) == "case")
    if upstream_pending:
        waiting_on = "upstream"
    elif fb_pending_case:
        waiting_on = "user_feedback"
    elif waiting_for:
        waiting_on = "user_material"
    elif need_sed or need_promote:
        waiting_on = "sediment"
    elif not open_:
        waiting_on = "ended"
    else:
        waiting_on = None
    needs_input = waiting_on == "user_material"

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
        "needReportReview": need_report_review,
        "vendorConfirmed": vendor_confirmed,
        "upstreamPending": upstream_pending,
        "upstream": upstream,
        "waitingFor": waiting_for,
        "waitingOn": waiting_on,
        "needsInput": needs_input,
        "lastReview": ({"verdict": latest_review.get("verdict"), "at": latest_review.get("at")}
                       if latest_review else None),
        "heading": "resolved" if status == "resolved" and fb["outcome"] in NEGATIVE_OUTCOMES else None,
    }


def _path_get(doc: dict, path: str):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


YAML_NULLS = {"", "null", "~"}


def _scalar_str(value) -> str:
    """标量转字符串；YAML 的 null 四种写法都返回空串（与 `panel-host.js` 的 scalarStr 同条）。"""
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() in YAML_NULLS else s


def _bool_flag(doc: dict, key: str) -> bool | None:
    """读一个布尔字段（平铺 / `outcome` 下两种写法），**未记返回 None**。

    与 `panel-host.js` 的 hasValue + fixEmitted 同一条：`null` / 空串 / `null` / `~` 都算未记；
    只有记了一个真值（非 `true`）才算「没给 fix」。不能只看 `key in doc`——`trace_begin.py`
    给每条新 trace 写的就是 `fix_emitted: null`，按"键存在"判会把所有新单都算成没给 fix。
    """
    for holder in (doc, doc.get("outcome") if isinstance(doc.get("outcome"), dict) else None):
        if not isinstance(holder, dict):
            continue
        raw = _scalar_str(holder.get(key))
        if raw:
            return raw.lower() == "true"
    return None


def _nonempty(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool):
        return True
    return True


def display_tone(status: str, feedback_outcome, style: dict | None = None) -> dict:
    """状态列的颜色/形状。库里算，面板不判——否则「颜色全来自投影」与「反向回报不用绿」
    两条会互相打架（面板要么自己判、要么实现不了）。

    口径：`resolved` + 反向回报（not_resolved / partial）降成灰，避免与「fix 未生效」的红
    徽标同时出现；`resolved` + pending 用空心琥珀环（「待回报」）；其余按状态本身的颜色。
    """
    meta = style or FALLBACK_STYLE
    if status == "resolved" and feedback_outcome in NEGATIVE_OUTCOMES:
        return {"color": FALLBACK_STYLE["color"], "accent": FALLBACK_STYLE["accent"],
                "hollow": False, "reason": "已定位但回报未生效"}
    if status == "resolved" and feedback_outcome == "pending":
        return {"color": "var(--c-amber)", "accent": "var(--acc-amber)",
                "hollow": True, "reason": "待回报"}
    return {"color": meta["color"], "accent": meta["accent"], "hollow": status == "unknown",
            "reason": ""}


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
        if t["action"] == "correct-ending" and not ending:
            continue  # 没有收尾方式时是「补记」，不是「改」
        if t["sameStatus"]:
            if ending:
                continue
        elif t["exceptSame"]:
            if not ending:
                continue
        elif status in t["to"] and t["action"] != "correct-ending":
            # 普通转移不许目标等于当前状态；`correct-ending` 例外——它就是「换成另一种
            # 收尾方式」，同状态允许（写入口会按单条事件处理，不重开）。
            continue
        kinds = [t["ending"]] if t["ending"] else list(t["endingChoices"])
        if t["action"] == "backfill-ending":
            # 补记只写当前状态的收尾方式：候选按当前状态过滤，否则面板会给出别的状态的 kind。
            kinds = [e["value"] for e in vocab["endings"] if status in e["statuses"]]
        targets = []
        if t["action"] == "correct-ending":
            # 改收尾方式要选「换成哪种收尾」，候选是三个 close 动作的完整描述（含必填与 kind），
            # 面板据此渲染目标选择，不必自己去 vocab 里拼。
            for other in vocab["transitions"]:
                if not other["action"].startswith("close-"):
                    continue
                target_status = other["to"][0]
                targets.append({
                    "to": target_status,
                    "action": other["action"],
                    "label": status_meta(vocab, target_status)["label"]
                             + ("（只改收尾内容）" if target_status == status else ""),
                    "requires": list(other["requires"]),
                    "fillable": list(other["fillable"]),
                    "mustExist": list(other["mustExist"]) + (
                        list(other["mustExistIfCase"]) if derived["caseKind"] == "case" else []),
                    "endingChoices": [
                        {"value": k,
                         "label": next((e["label"] for e in vocab["endings"] if e["value"] == k), k),
                         "requires": next((e["requires"] for e in vocab["endings"] if e["value"] == k), [])}
                        for k in ([other["ending"]] if other["ending"] else list(other["endingChoices"]))
                    ],
                })
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
            "targets": targets,
            "reopenFirst": t["action"] == "correct-ending",
            "formFields": form_fields(t, status, vocab, kinds),
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


FIELD_FORM = {
    "summary": {"label": "问题背景（summary）", "type": "textarea"},
    "severity": {"label": "严重级", "type": "select"},
    "fix_emitted": {"label": "是否给出了可执行的修复", "type": "bool"},
    "resolved_at": {"label": "收尾日期", "type": "auto"},
    "ending.handed_to": {"label": "转交给", "type": "text",
                         "placeholder": "名字 · 团队，或厂商 / 技术支持 / issue 号"},
    "ending.duplicate_of": {"label": "已有单", "type": "text",
                            "placeholder": "case:<id> 或 session:<session_id>"},
    "feedback.outcome": {"label": "现场回报", "type": "action",
                         "hint": "先去回报，再回来收尾"},
}


def form_fields(transition: dict, status: str, vocab: dict, kinds: list[str]) -> list[dict]:
    """编辑器要渲染的字段清单。把「哪一类字段、什么控件」提到投影里，面板不再按字段名硬编码。

    kind 用 select（候选来自 types/endingChoices）；`auto` 表示写入口自填（如 resolved_at），
    面板只显示不给输入；hint 是缺前置条件时的引导（如命中单的反馈）。
    """
    fields = []
    if kinds:
        fields.append({"path": "ending.kind", "label": "收尾方式", "type": "select",
                       "options": [{"value": k, "label": next((e["label"] for e in vocab["endings"]
                                                               if e["value"] == k), k)} for k in kinds],
                       "required": True})
    for key in ("requires", "fillable", "mustExist", "mustExistIfCase"):
        for field in transition[key]:
            base = field.split(".")[0]
            form = FIELD_FORM.get(field) or FIELD_FORM.get(base) or {"label": field, "type": "text"}
            fields.append({"path": field, "required": True, "class": key, **form})
    seen, out = set(), []
    for f in fields:
        if f["path"] in seen:
            continue
        seen.add(f["path"])
        out.append(f)
    return out


def load_traces(traces_root: Path | str) -> list[dict]:
    """读全部 `*.yaml`。坏件、目录、权限错误都只落成该行的 `error`，其它行照常返回。

    面板要能看见坏件（`doc: None` + `error`），而不是整张列表因为一份文件读不了就空掉。
    每份文件算 `contentSha256`：面板写回时拿它做 CAS 令牌，比 status 比较能挡住
    「两个窗口同时收尾、后写覆盖先写」这类丢事件；读不了的件该字段留空串。
    """
    root = Path(traces_root)
    rows = []
    for path in sorted(root.glob("*.yaml")):
        entry = {
            "sessionId": path.stem,
            "file": path.name,
            "contentSha256": "",
            "doc": None,
            "error": None,
        }
        try:
            raw = path.read_bytes()
            entry["contentSha256"] = hashlib.sha256(raw).hexdigest()
            entry["doc"] = load_text(raw.decode("utf-8")) or {}
        except Exception as exc:  # 坏件/目录/权限都只标记该行，不阻断列表
            entry["error"] = str(exc)
        doc = entry["doc"] or {}
        entry["sessionId"] = str(doc.get("session_id") or path.stem)
        rows.append(entry)
    return rows


# `kb_case_meta` 的进程内缓存：{knowledge 目录: (目录 mtime_ns, meta)}。每次投影都 rglob
# 一遍全部 case 文件只为拿几个附加字段，同一进程里重复投影时这层缓存省掉这次扫描。
# 缓存键是 `knowledge/` 目录自身的 mtime：目录下增删文件（新增或退休案例）会刷新，修改已有
# case 的文件内容不会。返回值按只读对待：调用方不改它。
_KB_META_CACHE: dict[str, tuple[int, dict[str, dict]]] = {}


def _knowledge_dir_stamp(root: Path) -> int | None:
    """`knowledge/` 目录的 mtime（纳秒）；目录不存在返回 None。"""
    try:
        return root.stat().st_mtime_ns
    except OSError:
        return None


def kb_case_meta(kb_root: Path | str) -> dict[str, dict]:
    """知识库里每条 case 的派生小事实：{id: {"anchors": [...], "lastVerified": "2026-W42"}}。

    一次遍历取两用：`closed` 与 `needSed` 只要"命中的 case 在不在库里"，「等上游」还要它的
    `upstream` 锚点与 `validation_record.last_verified`。分成两次遍历会把这批 case 文件读两遍。
    没有锚点的案例留一个空 `anchors`（仍然算"在库里"，只是查不了上游）。
    """
    root = Path(kb_root) / "knowledge"
    stamp = _knowledge_dir_stamp(root)
    if stamp is None:
        return {}
    key = str(root)
    cached = _KB_META_CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    out = {}
    for path in root.rglob("*.yaml"):
        if path.name.startswith("_"):
            continue
        # 退休案例不进：与 `scripts/build_index.py` 和 `scripts/verify_upstream_outcomes.py`
        # 同一条（`knowledge/_archive/` 下的 case 不再参与检索、也不再查证）。放进来会让面板
        # 给一条已退休案例挂「等上游」并生成一条必然报「找不到」的查证指令。
        if "_archive" in path.parts:
            continue
        try:
            doc = load_file(path) or {}
        except Exception:
            continue
        for case in doc.get("cases") or []:
            if not isinstance(case, dict) or not case.get("id"):
                continue
            record = case.get("validation_record")
            record = record if isinstance(record, dict) else {}
            verification = case.get("verification")
            verification = verification if isinstance(verification, dict) else {}
            out[str(case["id"])] = {
                "anchors": _upstream_anchor_labels(case),
                "lastVerified": str(record.get("last_verified") or ""),
                "verificationSource": str(verification.get("source") or ""),
            }
    _KB_META_CACHE[key] = (stamp, out)
    return out


def _upstream_anchor_labels(case: dict) -> list[str]:
    """`upstream:` 锚点的一句式标签（`vllm-ascend#10834`），给面板徽标的 title 用。

    `issue` 与 `pr` 二选一（`docs/spec/case-schema.md` 3.8）；两者都缺或整条不是映射时跳过，
    不猜一个编号出来——这里产出的标签会直接出现在人读界面上。
    """
    labels = []
    for anchor in case.get("upstream") or []:
        if not isinstance(anchor, dict):
            continue
        repo = str(anchor.get("repo") or "").strip()
        number = anchor.get("pr") if anchor.get("pr") is not None else anchor.get("issue")
        if number is None:
            continue
        name = repo.rsplit("/", 1)[-1] if repo else ""
        labels.append(f"{name}#{number}" if name else f"#{number}")
    return labels


def provenance_of(doc: dict) -> dict:
    """「谁在何时把状态改成这样」。有转移事件用最后一条，否则退回 `updated_at` 并标明来源；
    标签由词表给（面板不自己映射 by/source 枚举）。"""
    reports = [r for r in (doc.get("reports") or []) if isinstance(r, dict)]
    latest_report = reports[-1] if reports else None
    reviews = [r for r in (doc.get("reviews") or []) if isinstance(r, dict)]
    latest_review = reviews[-1] if reviews else None
    # 待复核 = 最新一条回报是「换别的方法解决」，且之后还没有复核结论。
    reviewed_after_report = bool(
        latest_review and latest_report
        and str(latest_review.get("at") or "") >= str(latest_report.get("at") or ""))
    need_report_review = bool(latest_report and latest_report.get("result") == "other_way"
                              and not reviewed_after_report)
    vendor_confirmed = any(r.get("source") == "vendor" and r.get("result") in ("from_report", "other_way")
                           for r in reports)
    events = [e for e in (doc.get("transitions") or []) if isinstance(e, dict)]
    labels = {"user": "本机用户", "agent": "agent", "cli": "命令行"}
    sources = {"panel": "面板", "cli": "命令行", "agent": "agent", "import": "上一台机器"}
    if events:
        last = events[-1]
        return {"at": last.get("at"), "atSource": "transitions",
                "statusBy": last.get("by"), "byLabel": labels.get(str(last.get("by")), ""),
                "source": last.get("source"), "sourceLabel": sources.get(str(last.get("source")), "")}
    return {"at": doc.get("updated_at"), "atSource": "updated_at",
            "statusBy": None, "byLabel": "", "source": None, "sourceLabel": ""}


def project(traces_root: Path | str, kb_root: Path | str, caps: dict | None = None,
            only: str | None = None, rows: list[dict] | None = None) -> dict:
    """面板与 CLI 共用的投影。`state` 不进 host 的版本缓存（它依赖 KB 与能力位）。

    调用方已经有 `load_traces()` 的结果时把它传进 `rows`，避免同一次请求把 traces 读两遍。
    不传时按 `traces_root` 现读，行为与没有这个参数时一致。
    """
    vocab = load_vocab(Path(kb_root))
    kb_cases = kb_case_meta(kb_root)
    ids = set(kb_cases)
    sessions = []
    for entry in (rows if rows is not None else load_traces(traces_root)):
        if only and entry["sessionId"] != only:
            continue
        doc = entry["doc"] or {}
        derived = derive(doc, ids, kb_cases)
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
            "activeCase": (None if doc.get("active_case") is None else str(doc.get("active_case"))),
            "summary": str(doc.get("summary") or ""),
            "severity": str(doc.get("severity") or ""),
            "fixEmitted": doc.get("fix_emitted"),
            "updatedAt": str(doc.get("updated_at") or ""),
            "provenance": provenance_of(doc),
            "derived": derived,
            "reportFile": str(doc.get("report_file") or ""),
            "reviews": [
                {"at": r.get("at"), "by": r.get("by"), "verdict": r.get("verdict"),
                 "note": str(r.get("note") or "")}
                for r in (doc.get("reviews") or []) if isinstance(r, dict)
            ],
            "reports": [
                {"at": r.get("at"), "by": r.get("by"), "source": r.get("source"),
                 "result": r.get("result"), "note": str(r.get("note") or "")}
                for r in (doc.get("reports") or []) if isinstance(r, dict)
            ],
            "transitions": [
                {"at": e.get("at"), "from": e.get("from"), "to": e.get("to"),
                 "ending": e.get("ending") if isinstance(e.get("ending"), dict) else None,
                 "by": e.get("by"), "source": e.get("source"),
                 "action": e.get("action"), "note": str(e.get("note") or ""),
                 # 折叠后的汇总事件带 `folded`（折叠条数）；普通事件为 0，面板据此区分。
                 "folded": int(e.get("folded") or 0)}
                for e in (doc.get("transitions") or []) if isinstance(e, dict)
            ],
            "displayTone": display_tone(str(doc.get("status") or "unknown"),
                                         feedback_of(doc)["outcome"],
                                         status_meta(vocab, str(doc.get("status") or "unknown"))),
            "actions": [] if entry["error"] else actions_for(doc, vocab, derived),
        }
        if entry["error"]:
            row["error"] = entry["error"]
            row["errorCode"] = "E_PARSE"
            row["derived"]["readable"] = False
        sessions.append(row)
    return {
        "schemeVersion": SCHEME,
        "generatedAt": __import__("datetime").datetime.now().astimezone().replace(microsecond=0).isoformat(),
        "capabilities": caps or {"canWrite": False, "writeRoot": "", "reasonCode": "E_NO_ROOT",
                                  "reason": "未提供能力位"},
        "vocab": {
            "statuses": vocab["statuses"],
            "endings": [{"value": e["value"], "label": e["label"], "requires": e["requires"],
                         "statuses": e["statuses"]}
                        for e in vocab["endings"]],
            "severities": vocab["severities"],
            "outcomes": vocab["outcomes"],
            "reportSources": vocab["reportSources"],
            "reportResults": vocab["reportResults"],
            "reviewVerdicts": vocab["reviewVerdicts"],
            "sedimented": vocab["sedimented"],
            "provenance": vocab["provenance"],
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
