#!/usr/bin/env python3
"""诊断状态条的数据面：把 traces/ 读成「一条当前诊断 + 最多三条最近诊断」的 JSON。

为什么单独一个脚本、而不是在 host 半里解析 YAML：
  「这单算不算已定位 / 还欠不欠回报 / 该不该沉淀」这些判据只在 `scripts/_trace_state.py`
  一门语言里（仓库的同一条纪律：判据不抄第二份）。本脚本只负责挑显示哪一单、按什么顺序，
  不自己推状态。

只读：本脚本不写 traces/，不写知识库。

用法（host 半调用，不面向人）：
  python3 lib/copilot_state.py --root <仓库根> [--session <DSH 会话号>] [--traces <目录>]

输出：stdout 一份 UTF-8 JSON。失败也以 `{"ok": false, ...}` 收场、退出码 0——
  调用方只按 `ok` 分支，不把 stderr 当协议。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MAX_STEPS = 6
SUMMARY_LIMIT = 600
TEXT_LIMIT = 240
MISSING_LIMIT = 160


def _one_line(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _short(text, limit: int) -> str:
    value = _one_line(text)
    if len(value) <= limit:
        return value
    return value[: max(limit - 2, 1)] + "……"


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _extra(doc: dict, traces: Path) -> dict:
    """一条轨迹里状态条与总览要展示、但状态投影不负责的现成事实。

    全部是 trace 里已经写着的内容，这里只做计数与截断，不新增判断。
    """
    trace = _as_list(doc.get("trace"))
    user_steps = 0
    agent_steps = 0
    evidence_files = 0
    evidence_missing = ""
    last_output = ""
    last_reason = ""
    for entry in trace:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "")
        if role == "user":
            user_steps += 1
            evidence = _as_dict(entry.get("evidence"))
            evidence_files += len(_as_list(evidence.get("files")))
            if evidence.get("missing") and not evidence_missing:
                evidence_missing = _short(evidence.get("missing"), MISSING_LIMIT)
        elif role == "agent":
            agent_steps += 1
            if entry.get("output"):
                last_output = _short(entry.get("output"), TEXT_LIMIT)
            if entry.get("reason"):
                last_reason = _short(entry.get("reason"), TEXT_LIMIT)

    session_id = str(doc.get("session_id") or "")
    report = traces / (session_id + ".report.md") if session_id else None
    return {
        "currentStep": int(doc.get("current_step") or 0),
        "maxSteps": MAX_STEPS,
        "eventCount": len([e for e in trace if isinstance(e, dict)]),
        "userSteps": user_steps,
        "agentSteps": agent_steps,
        "framework": str(doc.get("detected_framework") or ""),
        "platform": str(doc.get("detected_platform") or ""),
        "category": str(doc.get("detected_category") or ""),
        "excludedCases": [str(x) for x in _as_list(doc.get("excluded_cases")) if x],
        "evidenceFiles": evidence_files,
        "evidenceMissing": evidence_missing,
        "lastAction": _short(doc.get("last_action"), TEXT_LIMIT),
        "lastOutput": last_output,
        "lastReason": last_reason,
        "harnessSession": str(doc.get("harness_session") or ""),
        "hasReport": bool(report and report.is_file()),
        "sedimentCandidates": len([c for c in _as_list(doc.get("sediment_candidates")) if isinstance(c, dict)]),
    }


def _is_interesting(row: dict) -> bool:
    """最近一单的候选：还开着、欠回报、欠沉淀，或者草稿待升格。其余（已收尾且沉淀完的）不进列表。"""
    derived = _as_dict(row.get("derived"))
    feedback = _as_dict(row.get("feedback"))
    return bool(
        derived.get("open")
        or feedback.get("outcome") == "pending"
        or derived.get("needSed")
        or derived.get("needPromote")
        or derived.get("needReview")
    )


def _fail(code: str, message: str, detail: str = "") -> int:
    print(json.dumps({"ok": False, "code": code, "message": message, "detail": detail},
                     ensure_ascii=False))
    return 0


def _ok(payload: dict) -> int:
    payload["ok"] = True
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="诊断副驾数据面")
    parser.add_argument("--root", required=True, help="ascend-sleuth 检出根目录")
    parser.add_argument("--session", default="", help="当前 DSH 会话号（轨迹的 harness_session）")
    parser.add_argument("--traces", default="", help="traces 目录；省略时按主检出解析")
    parser.add_argument("--recent", type=int, default=3, help="最近一单最多给几条")
    parser.add_argument("--all-limit", type=int, default=80, help="全库薄行最多给几条")
    parser.add_argument("--can-write", action="store_true", help="本会话是否有写权限（由 host 判定后传入）")
    parser.add_argument("--write-root", default="", help="可写的主检出根")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not (root / "scripts" / "_trace_state.py").is_file():
        return _fail("E_ROOT", "这个目录不是 ascend-sleuth 检出（缺 scripts/_trace_state.py）：" + str(root))

    sys.path.insert(0, str(root / "scripts"))
    try:
        from exec_log_path import resolve_traces  # noqa: E402
        import _trace_state as trace_state  # noqa: E402
    except Exception as exc:  # 依赖缺失或脚本损坏：把原因原样交给界面
        return _fail("E_IMPORT", "读不到状态脚本（scripts/_trace_state.py）：" + str(exc))

    try:
        traces = Path(args.traces) if args.traces else Path(resolve_traces(root))
    except Exception as exc:
        return _fail("E_TRACES_RESOLVE", "解析 traces 目录失败：" + str(exc))

    if not traces.is_dir():
        return _ok({
            "tracesDir": str(traces),
            "generatedAt": _one_line(__import__("datetime").datetime.now().astimezone().replace(microsecond=0).isoformat()),
            "bound": None,
            "recent": [],
            "counts": {"open": 0, "pendingFeedback": 0, "toSediment": 0, "needReview": 0},
            "vocab": {},
            "note": "E_TRACES_NOT_FOUND",
        })

    caps = {
        "canWrite": bool(args.can_write),
        "writeRoot": str(args.write_root or ""),
        "reasonCode": "" if args.can_write else "E_PERM",
        "reason": "" if args.can_write else "当前会话没有写权限",
    }
    try:
        rows = trace_state.load_traces(traces)
        projection = trace_state.project(traces, root, caps=caps)
    except Exception as exc:
        return _fail("E_PROJECT", "状态投影执行失败：" + str(exc))

    by_id = {}
    for row in rows:
        by_id[row.get("sessionId") or row.get("file")] = row
    extras = {}
    for session_id, row in by_id.items():
        extras[session_id] = _extra(_as_dict(row.get("doc")), traces)

    sessions = []
    for session in projection.get("sessions") or []:
        if not isinstance(session, dict):
            continue
        item = dict(session)
        session_id = str(item.get("sessionId") or "")
        extra = extras.get(session_id, {})
        item["extra"] = extra
        item["harnessSession"] = extra.get("harnessSession", "")
        item["summary"] = _short(item.get("summary"), SUMMARY_LIMIT)
        sessions.append(item)

    bound = None
    if args.session:
        for session in sessions:
            if session.get("harnessSession") == args.session:
                bound = session
                break

    sessions.sort(key=lambda s: str(s.get("updatedAt") or ""), reverse=True)
    recent = []
    for session in sessions:
        if bound is not None and session.get("sessionId") == bound.get("sessionId"):
            continue
        if not _is_interesting(session):
            continue
        recent.append(session)
        if len(recent) >= max(args.recent, 0):
            break

    def thin(session: dict) -> dict:
        """全库列表用的薄行：只留列表与动作判断要用的字段，不带长文本与逐条证据。"""
        extra = _as_dict(session.get("extra"))
        return {
            "sessionId": session.get("sessionId"),
            "file": session.get("file"),
            "contentSha256": session.get("contentSha256"),
            "status": session.get("status"),
            "ending": session.get("ending"),
            "feedback": session.get("feedback"),
            "sedimented": session.get("sedimented"),
            "activeCase": session.get("activeCase"),
            "severity": session.get("severity"),
            "summary": session.get("summary"),
            "updatedAt": session.get("updatedAt"),
            "displayTone": session.get("displayTone"),
            "derived": session.get("derived"),
            "harnessSession": session.get("harnessSession"),
            "extra": {
                "currentStep": extra.get("currentStep"),
                "maxSteps": extra.get("maxSteps"),
                "platform": extra.get("platform"),
                "category": extra.get("category"),
                "framework": extra.get("framework"),
                "excludedCases": extra.get("excludedCases"),
                "evidenceMissing": extra.get("evidenceMissing"),
                "hasReport": extra.get("hasReport"),
            },
        }

    vocab = projection.get("vocab") or {}
    counts = {
        "open": sum(1 for s in sessions if _as_dict(s.get("derived")).get("open")),
        "pendingFeedback": sum(1 for s in sessions
                               if _as_dict(s.get("feedback")).get("outcome") == "pending"),
        "toSediment": sum(1 for s in sessions if _as_dict(s.get("derived")).get("needSed")),
        "needReview": sum(1 for s in sessions if _as_dict(s.get("derived")).get("needReview")),
    }
    return _ok({
        "tracesDir": str(traces),
        "generatedAt": _one_line(projection.get("generatedAt")),
        "bound": bound,
        "recent": recent,
        "all": [thin(session) for session in sessions[: max(args.all_limit, 0)]],
        "capabilities": caps,
        "counts": counts,
        "vocab": {
            "statuses": [
                {"value": s.get("value"), "label": s.get("label"),
                 "color": s.get("color"), "accent": s.get("accent")}
                for s in _as_list(vocab.get("statuses"))
            ],
            "outcomes": [
                {"value": o.get("value"), "label": o.get("label"), "countsAs": o.get("countsAs")}
                for o in _as_list(vocab.get("outcomes"))
            ],
            "sedimented": [
                {"value": s.get("value"), "label": s.get("label")}
                for s in _as_list(vocab.get("sedimented"))
            ],
            "severities": [
                {"value": s.get("value"), "label": s.get("label")}
                for s in _as_list(vocab.get("severities"))
            ],
            "reportSources": [
                {"value": s.get("value"), "label": s.get("label")}
                for s in _as_list(vocab.get("reportSources"))
            ],
            "reportResults": [
                {"value": r.get("value"), "label": r.get("label"), "outcome": r.get("outcome")}
                for r in _as_list(vocab.get("reportResults"))
            ],
        },
    })


if __name__ == "__main__":
    sys.exit(main())
