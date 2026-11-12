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
import inspect
import json
import re
import sys
from pathlib import Path

MAX_STEPS = 6
SUMMARY_LIMIT = 600
TEXT_LIMIT = 240
MISSING_LIMIT = 160
INCIDENT_LIMIT = 16
FAILURE_NODE_LIMIT = 8
UPSTREAM_LIMIT = 12
REVISION_LIMIT = 24
QUOTE_LIMIT = 320
CHANGE_LIMIT = 200


def _one_line(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _short(text, limit: int) -> str:
    value = _one_line(text)
    if len(value) <= limit:
        return value
    return value[: max(limit - 2, 1)] + "……"


def _safe_int(value, default: int = 0) -> int:
    """整数字段的安全转换。`current_step` 被写成「第三步」或 null 时只让该字段归零，
    不让整条轨迹的其余字段一起失败。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _material_items(text, summary: str = '', limit: int = 8) -> list:
    """把 trace 里「还缺什么」的现成记录拆成清单项。

    只做拆分，不补猜：认 `未提供：A、B` 与 `缺 X；缺 Y` 两种写法；不是「缺 / 未提供」
    开头的分句原样跳过（那些通常是补充事实，不是待补材料）。
    """
    items = []
    value = _one_line(text)
    if not value:
        return items
    for segment in re.split(r"[；;]", value):
        segment = segment.strip(" 。")
        if not segment:
            continue
        match = re.match(
            r"^(?:需要提供|未提供|缺少|缺|未贴|没提供|需提供|需要|还需)[：:]?\s*(.+)$",
            segment,
        )
        if not match:
            continue
        parts = re.split(r"[、,，]", match.group(1))
        for part in parts:
            item = part.strip(" 。")
            if not item:
                continue
            # 后文已经给出的事实不再列为待补（例如 summary 里已写 A3-910C / w8a8c8）。
            if item.startswith("具体硬件") and re.search(r"A[2-5][- ]?9\d{2}|A[2-5]-\d", summary):
                continue
            if item.startswith("量化档") and re.search(r"w[0-9]+a[0-9]+c[0-9]+", summary, re.I):
                continue
            if item not in items:
                items.append(_short(item, 180))
            if len(items) >= limit:
                return items
    return items


def _stamp(value):
    """时间原值转成 JSON 友好的字符串；缺省给 None（面板显示「时点未知」）。

    trace 里的 `at` 可能是 YAML 解析出来的 datetime（作者没加引号），这里统一按
    ISO 8601 写出，不换算时区、不补精度。
    """
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        text = value.isoformat()
    else:
        text = _one_line(value)
    return text or None


def _change_value(value) -> str:
    """修订条目里的旧值 / 新值：标量原样，结构转 JSON 文本。"""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return _short(json.dumps(value, ensure_ascii=False), CHANGE_LIMIT)
    return _short(value, CHANGE_LIMIT)


def _timeline_layers(doc: dict) -> dict:
    """面板详情用的三段时间线 + 修订记录：现场 / 日志过程 / 上游查证 / 修订。

    只搬 trace 里已有的字段，不推断、不回填。`None` 与缺键都按「未记录」给 `null`
    （旧单）；只有 `[]` 才是「查过但为空」。`revisions` 恒为列表。
    每层另给 `*Total`（截断前的条数），面板段头用总数并写明「显示前 N 条」，
    不把截断藏起来。
    """
    incident = None
    incident_total = 0
    raw_incident = doc.get("incident_timeline")
    if raw_incident is not None:
        incident = []
        incident_entries = _as_list(raw_incident)
        incident_total = len(incident_entries)
        for entry in incident_entries[:INCIDENT_LIMIT]:
            if not isinstance(entry, dict):
                continue
            item = {
                "id": _one_line(entry.get("id")),
                "at": _stamp(entry.get("at")),
                "atNote": _short(entry.get("at_note"), 120),
                "what": _short(entry.get("what"), TEXT_LIMIT),
                "source": _one_line(entry.get("source")),
                "step": _safe_int(entry.get("step")),
            }
            evidence = _as_dict(entry.get("evidence"))
            files = [_one_line(x) for x in _as_list(evidence.get("files")) if _one_line(x)][:10]
            detail = {"files": files} if files else {}
            quote = _short(evidence.get("quote"), QUOTE_LIMIT)
            if quote:
                detail["quote"] = quote
            line = evidence.get("line")
            if isinstance(line, int) and not isinstance(line, bool):
                detail["line"] = line
            if detail:
                item["evidence"] = detail
            incident.append(item)

    failure = None
    raw_failure = doc.get("failure_process")
    if isinstance(raw_failure, dict):
        raw_window = _as_dict(raw_failure.get("window"))
        window = None
        if raw_window:
            window = {
                "from": _stamp(raw_window.get("from")) or "",
                "to": _stamp(raw_window.get("to")) or "",
            }
        nodes = []
        for node in _as_list(raw_failure.get("nodes"))[:FAILURE_NODE_LIMIT]:
            if not isinstance(node, dict):
                continue
            item = {
                "id": _one_line(node.get("id")),
                "at": _stamp(node.get("at")),
                "x": node.get("x") if isinstance(node.get("x"), (int, float)) and not isinstance(node.get("x"), bool) else None,
                "what": _short(node.get("what"), TEXT_LIMIT),
                "quote": _short(node.get("quote"), QUOTE_LIMIT),
                "repeat": _short(node.get("repeat"), 160),
            }
            evidence = _as_dict(node.get("evidence"))
            detail = {}
            file_path = _one_line(evidence.get("file"))
            if file_path:
                detail["file"] = file_path
            line = evidence.get("line")
            if isinstance(line, int) and not isinstance(line, bool):
                detail["line"] = line
            if detail:
                item["evidence"] = detail
            nodes.append(item)
        failure = {
            "axis": _one_line(raw_failure.get("axis")) or "time",
            "window": window,
            "clockNote": _short(raw_failure.get("clock_note"), QUOTE_LIMIT),
            "nodes": nodes,
        }

    upstream = None
    upstream_total = 0
    raw_upstream = doc.get("upstream_timeline")
    if raw_upstream is not None:
        upstream = []
        upstream_entries = _as_list(raw_upstream)
        upstream_total = len(upstream_entries)
        for entry in upstream_entries[:UPSTREAM_LIMIT]:
            if not isinstance(entry, dict):
                continue
            item = {
                "id": _one_line(entry.get("id")),
                "at": _stamp(entry.get("at")),
                "what": _short(entry.get("what"), TEXT_LIMIT),
                "source": _one_line(entry.get("source")),
                "ref": _short(entry.get("ref"), 120),
            }
            evidence = _as_dict(entry.get("evidence"))
            files = [_one_line(x) for x in _as_list(evidence.get("files")) if _one_line(x)][:10]
            if files:
                item["evidence"] = {"files": files}
            upstream.append(item)

    revisions = []
    revision_entries = _as_list(doc.get("revisions"))
    revision_total = len(revision_entries)
    # revisions 是 append-only 且不设上限：截断只留最近 REVISION_LIMIT 条（尾部），
    # 取头部会把最新一次修订丢掉；总数另给 revisionsTotal，面板据此显示「N 次修订」。
    for revision in revision_entries[-REVISION_LIMIT:]:
        if not isinstance(revision, dict):
            continue
        changes = []
        for change in _as_list(revision.get("changes")):
            if not isinstance(change, dict):
                continue
            changes.append({
                "target": _one_line(change.get("target")),
                "before": _change_value(change.get("before")),
                "after": _change_value(change.get("after")),
            })
        revisions.append({
            "at": _stamp(revision.get("at")) or "",
            "by": _one_line(revision.get("by")),
            "kind": _one_line(revision.get("kind")),
            "changes": changes,
            "reason": _short(revision.get("reason"), TEXT_LIMIT),
        })

    return {
        "incidentEnv": _short(doc.get("incident_env"), TEXT_LIMIT),
        "incident": incident,
        "incidentTotal": incident_total,
        "failureProcess": failure,
        "upstream": upstream,
        "upstreamTotal": upstream_total,
        "revisions": revisions,
        "revisionsTotal": revision_total,
    }


def _timeline(doc: dict) -> dict:
    """单条 trace 的步骤时间线与三段时间线 + 修订记录：只摘录已有内容，不重排、不推断。"""
    entries = []
    for entry in _as_list(doc.get("trace")):
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "")
        step = entry.get("step")
        item = {
            "role": role,
            "step": int(step) if isinstance(step, int) else 0,
            "action": str(entry.get("action") or ""),
            "output": _short(entry.get("output"), 320),
            "reason": _short(entry.get("reason"), 320),
            "content": _short(entry.get("content"), 240),
        }
        evidence = _as_dict(entry.get("evidence"))
        files = [str(x) for x in _as_list(evidence.get("files")) if x]
        if files:
            item["evidenceFiles"] = files[:10]
        if evidence.get("missing"):
            item["evidenceMissing"] = _short(evidence.get("missing"), 180)
        if entry.get("report_file"):
            item["reportFile"] = str(entry.get("report_file"))
        entries.append(item)
    payload = {
        "sessionId": str(doc.get("session_id") or ""),
        "summary": _short(doc.get("summary"), SUMMARY_LIMIT),
        "updatedAt": _short(doc.get("updated_at"), 40),
        "timeline": entries,
    }
    payload.update(_timeline_layers(doc))
    return payload


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
    evidence_missing_full = ""
    evidence_list = []
    resume_sessions = []
    last_output = ""
    last_reason = ""
    for entry in trace:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "")
        if role == "user":
            user_steps += 1
            evidence = _as_dict(entry.get("evidence"))
            for file_path in _as_list(evidence.get("files")):
                text = str(file_path or "").strip()
                if text and text not in evidence_list:
                    evidence_list.append(text)
            evidence_files += len(_as_list(evidence.get("files")))
            if evidence.get("missing") and not evidence_missing_full:
                evidence_missing_full = _one_line(evidence.get("missing"))
        elif role == "agent":
            agent_steps += 1
            if str(entry.get("action") or "") == "resume":
                resumed = str(entry.get("harness_session") or "").strip()
                if resumed and resumed not in resume_sessions:
                    resume_sessions.append(resumed)
            if entry.get("output"):
                last_output = _short(entry.get("output"), TEXT_LIMIT)
            if entry.get("reason"):
                last_reason = _short(entry.get("reason"), TEXT_LIMIT)

    session_id = str(doc.get("session_id") or "")
    # 报告位置与面板 / 导出脚本同一口径：先顶层 report_file（或 report 事件里的），再同名兜底；
    # 只认 traces/ 下、只写文件名的约定，不拼绝对路径。
    report_path = None
    if session_id:
        report_name = str(doc.get("report_file") or "").strip()
        if not report_name:
            for entry in reversed(trace):
                if isinstance(entry, dict) and entry.get("report_file"):
                    report_name = str(entry["report_file"]).strip()
                    break
        if report_name:
            normalized = report_name.replace("\\", "/")
            match = re.search(r"(?:^|/)traces/(.+)$", normalized)
            name = match.group(1) if match else normalized.lstrip("./")
            candidate = traces / name if name else None
            if candidate is not None and candidate.is_file():
                report_path = candidate
        fallback = traces / (session_id + ".report.md")
        if report_path is None and fallback.is_file():
            report_path = fallback
    report_rel = ""
    if report_path is not None:
        try:
            report_rel = str(report_path.relative_to(traces)).replace("\\", "/")
        except ValueError:
            report_rel = ""
    candidates = []
    for candidate in _as_list(doc.get("sediment_candidates")):
        if not isinstance(candidate, dict) or len(candidates) >= 5:
            continue
        candidates.append({
            "kind": str(candidate.get("kind") or ""),
            "summary": _short(candidate.get("summary") or candidate.get("title") or candidate.get("id"), TEXT_LIMIT),
        })
    result = {
        "currentStep": _safe_int(doc.get("current_step")),
        "maxSteps": MAX_STEPS,
        "eventCount": len([e for e in trace if isinstance(e, dict)]),
        "userSteps": user_steps,
        "agentSteps": agent_steps,
        "fixEmitted": doc.get("fix_emitted"),
        "framework": str(doc.get("detected_framework") or ""),
        "platform": str(doc.get("detected_platform") or ""),
        "category": str(doc.get("detected_category") or ""),
        "excludedCases": [
            str(x.get("id") or x.get("case") or "").strip() if isinstance(x, dict) else str(x).strip()
            for x in _as_list(doc.get("excluded_cases"))
            if x
        ],
        "evidenceFiles": evidence_files,
        "evidenceMissing": _short(evidence_missing_full, MISSING_LIMIT),
        "lastAction": _short(doc.get("last_action"), TEXT_LIMIT),
        "lastOutput": last_output,
        "lastReason": last_reason,
        "harnessSession": str(doc.get("harness_session") or ""),
        "resumeSessions": resume_sessions,
        "hasReport": bool(report_rel),
        "reportFile": ("traces/" + report_rel) if report_rel else "",
        "evidenceList": evidence_list[:20],
        "sedimentCandidates": len([c for c in _as_list(doc.get("sediment_candidates")) if isinstance(c, dict)]),
        "sedimentCandidateList": candidates,
        "missingMaterials": _material_items(evidence_missing_full, _one_line(doc.get("summary"))),
    }
    # 三段时间线 + 修订明细不随薄行下发（80 单最坏会放大到数 MB）：总览详情选中行时再调
    # copilot-timeline 取 layers，步骤仍按「加载步骤」懒加载。
    return result


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
    parser.add_argument("--write-reason-code", default="",
                        help="不可写时的原因码（E_PERM 只读档位；E_POLICY 档位解析不出）")
    parser.add_argument("--write-reason", default="", help="不可写时给界面看的说明")
    parser.add_argument("--timeline", default="", help="只读单条轨迹的步骤时间线与三段时间线 + 修订记录（传文件名，供总览详情按需取）")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not (root / "scripts" / "_trace_state.py").is_file():
        return _fail("E_ROOT", "这个目录不是 ascend-sleuth 检出（缺 scripts/_trace_state.py）：" + str(root))

    sys.path.insert(0, str(root / "scripts"))
    try:
        from exec_log_path import resolve_traces  # noqa: E402
        from _yaml import load_text  # noqa: E402
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

    if args.timeline:
        name = str(args.timeline)
        if name != Path(name).name or not name.endswith(".yaml") or name.startswith("."):
            return _fail("E_SCHEMA", "轨迹文件名不合法")
        trace_file = traces / name
        if not trace_file.is_file():
            return _fail("E_NOT_FOUND", "轨迹文件不存在：" + name)
        # 只读这一单：详情按需取，不能为了一个文件把 traces/ 全解析一遍。
        try:
            raw = trace_file.read_bytes()
        except OSError as exc:
            return _fail("E_LOAD", "读轨迹失败：" + str(exc))
        try:
            doc = _as_dict(load_text(raw.decode("utf-8")))
        except UnicodeDecodeError as exc:
            return _fail("E_LOAD", "读轨迹失败：" + str(exc))
        except Exception as exc:
            return _fail("E_PARSE", "轨迹文件解析失败：" + str(exc))
        if not doc:
            return _fail("E_PARSE", "轨迹文件没有可读的事件：" + name)
        return _ok(_timeline(doc))

    caps = {
        "canWrite": bool(args.can_write),
        "writeRoot": str(args.write_root or ""),
        "reasonCode": "" if args.can_write else str(args.write_reason_code or "E_PERM"),
        "reason": "" if args.can_write else str(args.write_reason or "当前会话没有写权限"),
    }
    try:
        rows = trace_state.load_traces(traces)
        # `_trace_state.project` 若已支持可选预加载 rows，就把刚读到的这份传进去，
        # 免得同一次取数把 traces/ 读两遍（脚本侧还没加这个参数时走旧签名）。
        project_kwargs = {"caps": caps}
        try:
            if "rows" in inspect.signature(trace_state.project).parameters:
                project_kwargs["rows"] = rows
        except (TypeError, ValueError):
            pass
        projection = trace_state.project(traces, root, **project_kwargs)
    except Exception as exc:
        return _fail("E_PROJECT", "状态投影执行失败：" + str(exc))

    by_id = {}
    for row in rows:
        by_id[row.get("sessionId") or row.get("file")] = row
    extras = {}
    for session_id, row in by_id.items():
        try:
            extras[session_id] = _extra(_as_dict(row.get("doc")), traces)
        except Exception:
            # 单条轨迹的派生字段失败只降级这一行：整块状态不因一条坏数据空掉。
            extras[session_id] = {}

    sessions = []
    for session in projection.get("sessions") or []:
        if not isinstance(session, dict):
            continue
        item = dict(session)
        session_id = str(item.get("sessionId") or "")
        extra = extras.get(session_id, {})
        item["extra"] = extra
        item["harnessSession"] = extra.get("harnessSession", "")
        item["resumeSessions"] = extra.get("resumeSessions", [])
        item["summary"] = _short(item.get("summary"), SUMMARY_LIMIT)
        sessions.append(item)

    bound = None
    bound_by = ""
    if args.session:
        for session in sessions:
            if session.get("harnessSession") == args.session:
                bound = session
                bound_by = "origin"
                break
        if bound is None:
            for session in sessions:
                if args.session in (session.get("resumeSessions") or []):
                    bound = session
                    bound_by = "resume"
                    break
    if bound is not None:
        bound = dict(bound)
        bound["boundBy"] = bound_by

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
        """全库列表用的薄行：只留列表与动作判断要用的字段，不带长文本与逐条证据。

        `actions` 原样透传 `_trace_state.actions_for` 的完整结构（动作、目标、必填、候选收尾
        方式、表单字段）——客户端渲染动作菜单不自己再算一遍规则；`fixEmitted` 保留 trace 的
        原值（`true` / `false` / `null` 未记），列表据此显示「给没给可执行修复」。
        """
        extra = _as_dict(session.get("extra"))
        return {
            "sessionId": session.get("sessionId"),
            "file": session.get("file"),
            "contentSha256": session.get("contentSha256"),
            "status": session.get("status"),
            "error": session.get("error"),
            "errorCode": session.get("errorCode"),
            "ending": session.get("ending"),
            "feedback": session.get("feedback"),
            "sedimented": session.get("sedimented"),
            "activeCase": session.get("activeCase"),
            "severity": session.get("severity"),
            "fixEmitted": session.get("fixEmitted"),
            "summary": session.get("summary"),
            "updatedAt": session.get("updatedAt"),
            "displayTone": session.get("displayTone"),
            "derived": session.get("derived"),
            "actions": session.get("actions"),
            "harnessSession": session.get("harnessSession"),
            "resumeSessions": session.get("resumeSessions"),
            "reportFile": extra.get("reportFile"),
            "transitions": session.get("transitions"),
            "reports": session.get("reports"),
            "reviews": session.get("reviews"),
            "extra": {
                "currentStep": extra.get("currentStep"),
                "maxSteps": extra.get("maxSteps"),
                "platform": extra.get("platform"),
                "category": extra.get("category"),
                "framework": extra.get("framework"),
                "excludedCases": extra.get("excludedCases"),
                "evidenceMissing": extra.get("evidenceMissing"),
                "evidenceFiles": extra.get("evidenceFiles"),
                "evidenceList": extra.get("evidenceList"),
                "hasReport": extra.get("hasReport"),
                "reportFile": extra.get("reportFile"),
                "fixEmitted": extra.get("fixEmitted"),
                "sedimentCandidateList": extra.get("sedimentCandidateList"),
                "missingMaterials": extra.get("missingMaterials"),
                "lastAction": extra.get("lastAction"),
                "lastOutput": extra.get("lastOutput"),
                "lastReason": extra.get("lastReason"),
                "harnessSession": extra.get("harnessSession"),
                "resumeSessions": extra.get("resumeSessions"),
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
        # 写入口的 scheme 校验用：词表与脚本同步后才能发现版本错配。
        "schemeVersion": projection.get("schemeVersion"),
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
            # 客户端按目标状态过滤收尾方式（归档的四种只在 statuses 含 archived 时给），
            # 不再在 client.js 里另存一份词表。
            "endings": [
                {"value": e.get("value"), "label": e.get("label"),
                 "requires": _as_list(e.get("requires")), "statuses": _as_list(e.get("statuses"))}
                for e in _as_list(vocab.get("endings"))
            ],
        },
    })


if __name__ == "__main__":
    sys.exit(main())
