#!/usr/bin/env python3
"""_trace_content.py —— 三段时间线 + 修订记录的 schema 唯一实现（库）

**为什么需要**：`incident_env` / `incident_timeline` / `failure_process` /
`upstream_timeline` / `revisions` 这五个字段由写入口
`trace_transition.py --field content` 写、由 `verify_trace_status.py --all` 校验。
两处各写一套口径，就会出现「写入口放过的值校验器判红」或反过来的反例；所以字段白名单、
枚举、id 正则、时间校验、canonical hash、diff 与校验都只在这里定义。

**它不是什么**：不是写入口（落盘、revision 生成、updated_at 刷新在 `trace_transition.py`）；
不是面板读端（字段投影在 `dsh-plugins/dsh-sleuth-copilot/lib/copilot_state.py`）。

**旧 trace 无这些字段**：整段跳过，不报错，也不回填。

字段语义与写时机见 `skills/diagnose/references/diagnosis-trace.md`；本模块只管机械可判的
形状、diff 与 hash。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime

# 写入口 `set` 允许的字段。`summary` 是既有字段，本轮也收进写入口，面板的问题背景段
# 与三段时间线一起改；其余四个是新字段。
WRITABLE_FIELDS = (
    "summary",
    "incident_env",
    "incident_timeline",
    "failure_process",
    "upstream_timeline",
)

INCIDENT_SOURCES = ("log", "user", "issue", "comment", "commit", "doc", "field_test", "observation")
UPSTREAM_SOURCES = ("issue", "comment", "commit", "doc", "maintainer", "vendor", "field_test",
                    "observation")
FAILURE_AXES = ("time", "step", "request")
REVISION_BY = ("user", "agent", "cli")
REVISION_KINDS = ("fact_corrected", "conclusion_overturned", "scope_changed",
                  "severity_changed", "sediment_changed")

# 三个列表字段的 id：字段内唯一，编号从 1 起。
ID_PATTERNS = {
    "incident_timeline": re.compile(r"^inc-[1-9]\d*$"),
    "failure_process": re.compile(r"^fp-[1-9]\d*$"),
    "upstream_timeline": re.compile(r"^up-[1-9]\d*$"),
}
ID_LABEL = {
    "incident_timeline": "inc-<n>",
    "failure_process": "fp-<n>",
    "upstream_timeline": "up-<n>",
}
REMOVED_TARGET = re.compile(r"^removed:(?:inc-[1-9]\d*|fp-[1-9]\d*|up-[1-9]\d*)$")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# 字段内允许的键。写错键名（`resource` 写成 `source` 之类）不会报错、只会静默丢掉，
# 所以这里按契约做成白名单，多出来的键判红。
INCIDENT_KEYS = {"id", "at", "at_note", "what", "source", "step", "evidence"}
UPSTREAM_KEYS = {"id", "at", "what", "source", "ref", "evidence"}
FAILURE_KEYS = {"axis", "window", "clock_note", "nodes"}
NODE_KEYS = {"id", "at", "x", "what", "quote", "repeat", "evidence"}
WINDOW_KEYS = {"from", "to"}
EVIDENCE_KEYS = {"file", "files", "quote", "line"}
REVISION_KEYS = {"at", "by", "kind", "changes", "reason", "evidence", "hashes"}
CHANGE_KEYS = {"target", "before", "after"}
# 各列表字段的条数上限，与面板的渲染上限对齐：
# 现场 / 上游时间线是列表上限，故障过程是节点上限；revisions 是 append-only，不设上限。
MAX_INCIDENT = 16
MAX_UPSTREAM = 12
MAX_NODES = 8
# 有值时必须被某条 revision 的 hashes 覆盖的字段（summary 不在内：它是既有字段，
# 旧单可能没有修订记录，不能因为一个摘要就整份判红）。
HASH_COVERED_FIELDS = ("incident_env", "incident_timeline", "failure_process",
                       "upstream_timeline")


# ── canonical 表示：深比较与 hash 都走这里 ────────────────────────────────────
def to_jsonable(value):
    """转成可 JSON 序列化的等价值。

    PyYAML 会把不加引号的 ISO 时间解析成 `datetime` / `date`：同一个时刻加不加引号
    是两种 Python 类型。canonical hash 与深比较都先过这里，两种写法算出同一个值，
    否则「手写 trace 没加引号」会被当成内容不一致。
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def canonical_json(value) -> str:
    """字段值的 canonical JSON：键排序、无多余空白、中文不转义。"""
    return json.dumps(to_jsonable(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def canonical_hash(value) -> str:
    """字段内容的 sha256（契约 §1 的 `hashes: {field: "sha256:..."}`）。"""
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def field_equal(before, after) -> bool:
    """深比较。类型不同但 canonical 等价（datetime vs 字符串）视为没变。"""
    return canonical_json(before) == canonical_json(after)


# ── 时间 ────────────────────────────────────────────────────────────────────
def is_valid_time(value, allow_date: bool = True) -> bool:
    """`null` 由调用方放行；这里只判非空值。

    时间精度照材料：契约允许只到日期的 `"YYYY-MM-DD"`，也允许带时区的
    `"YYYY-MM-DDTHH:MM:SS+08:00"`；两者都要能被 `datetime` / `date` 解析。
    """
    if isinstance(value, (datetime, date)):
        return True
    if not isinstance(value, str):
        return False
    if DATE_RE.match(value):
        if not allow_date:
            return False
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True
    if DATETIME_RE.match(value):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True
    return False


# ── diff：写入口据此生成 revision.changes ─────────────────────────────────────
def _clip(text, limit: int = 180) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _compact(value) -> str:
    return canonical_json(value)


def _row_summary(row) -> str:
    """列表条目的 before/after 摘要：优先一句话事实（`what`），没有再用日志原文。"""
    if isinstance(row, dict):
        what = str(row.get("what") or "").strip()
        if what:
            return _clip(what)
        quote = str(row.get("quote") or "").strip()
        if quote:
            return _clip(quote)
    return _clip(_compact(row))


def _text(value) -> str:
    if value is None:
        return ""
    return _clip(value if isinstance(value, str) else _compact(value))


def _diff_rows(field: str, before, after) -> list[dict]:
    old = [r for r in before if isinstance(r, dict)] if isinstance(before, list) else []
    new = [r for r in after if isinstance(r, dict)] if isinstance(after, list) else []
    old_by_id = {str(r.get("id") or ""): r for r in old if r.get("id")}
    new_by_id = {str(r.get("id") or ""): r for r in new if r.get("id")}
    changes = []
    for rid, row in old_by_id.items():
        if rid not in new_by_id:
            changes.append({"target": f"removed:{rid}",
                            "before": _row_summary(row), "after": ""})
        elif not field_equal(row, new_by_id[rid]):
            changes.append({"target": rid,
                            "before": _row_summary(row), "after": _row_summary(new_by_id[rid])})
    for rid, row in new_by_id.items():
        if rid not in old_by_id:
            changes.append({"target": rid, "before": "", "after": _row_summary(row)})
    if not changes and not field_equal(before, after):
        # 没有 id 可对（例如整段被清成 null）时退回字段级一条，不丢改动记录。
        changes.append({"target": field, "before": _text(before), "after": _text(after)})
    return changes


def _diff_failure_process(before, after) -> list[dict]:
    old = before if isinstance(before, dict) else {}
    new = after if isinstance(after, dict) else {}
    changes = []
    struct = [k for k in ("axis", "window", "clock_note")
              if not field_equal(old.get(k), new.get(k))]
    if struct:
        changes.append({
            "target": "failure_process",
            "before": _compact({k: old.get(k) for k in struct}),
            "after": _compact({k: new.get(k) for k in struct}),
        })
    old_nodes = {str(n.get("id") or ""): n for n in (old.get("nodes") or []) if isinstance(n, dict)}
    new_nodes = {str(n.get("id") or ""): n for n in (new.get("nodes") or []) if isinstance(n, dict)}
    for nid, node in old_nodes.items():
        if nid not in new_nodes:
            changes.append({"target": f"removed:{nid}",
                            "before": _row_summary(node), "after": ""})
        elif not field_equal(node, new_nodes[nid]):
            changes.append({"target": nid,
                            "before": _row_summary(node), "after": _row_summary(new_nodes[nid])})
    for nid, node in new_nodes.items():
        if nid not in old_nodes:
            changes.append({"target": nid, "before": "", "after": _row_summary(node)})
    if not changes and not field_equal(before, after):
        changes.append({"target": "failure_process", "before": _text(before), "after": _text(after)})
    return changes


def diff_content(field: str, before, after) -> list[dict]:
    """一个字段的改动条目（contract §2：列表按 id、failure_process 按节点 + 结构字段、
    字符串字段整体）。

    返回 `[{target, before, after}]`：新增条目 `before` 为空串，删除条目
    `target="removed:<id>"`、`after` 为空串。每个被改字段至少一条。
    """
    if field in ("summary", "incident_env"):
        return [{"target": field, "before": _text(before), "after": _text(after)}]
    if field in ("incident_timeline", "upstream_timeline"):
        return _diff_rows(field, before, after)
    if field == "failure_process":
        return _diff_failure_process(before, after)
    raise ValueError(f"不是可写字段：{field!r}")


# ── 校验 ────────────────────────────────────────────────────────────────────
def _check_keys(errs: list[str], where: str, mapping: dict, allowed: set) -> None:
    unknown = [str(k) for k in mapping if k not in allowed]
    if unknown:
        errs.append(f"{where}: 有未定义字段 " + "、".join(unknown)
                    + "（允许：" + "、".join(sorted(allowed)) + "）")


def _check_at(errs: list[str], where: str, value, allow_date: bool = True) -> None:
    if value is None:
        return
    if not is_valid_time(value, allow_date=allow_date):
        kinds = "\"YYYY-MM-DDTHH:MM:SS+08:00\" 或 null" if not allow_date \
            else "\"YYYY-MM-DDTHH:MM:SS+08:00\"、\"YYYY-MM-DD\" 或 null"
        errs.append(f"{where}.at={value!r} 不是可解析的时间（写成 {kinds}）")


def _check_id(errs: list[str], where: str, field: str, value) -> None:
    pattern = ID_PATTERNS[field]
    if not isinstance(value, str) or not pattern.match(value):
        errs.append(f"{where}.id={value!r} 不合法（应为 {ID_LABEL[field]}）")


def _check_enum(errs: list[str], where: str, key: str, value, allowed) -> None:
    if value not in allowed:
        errs.append(f"{where}.{key}={value!r} 不在枚举里（"
                    + " | ".join(allowed) + "）")


def _check_str(errs: list[str], where: str, value, required: bool = False) -> None:
    if value is None:
        if required:
            errs.append(f"{where} 必填")
        return
    if not isinstance(value, str):
        errs.append(f"{where} 应是字符串（当前 {type(value).__name__}）")
        return
    if required and not value.strip():
        errs.append(f"{where} 不能为空")


def _check_evidence(errs: list[str], where: str, value) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        errs.append(f"{where}.evidence 应是映射")
        return
    _check_keys(errs, f"{where}.evidence", value, EVIDENCE_KEYS)
    if "file" in value and not isinstance(value["file"], str):
        errs.append(f"{where}.evidence.file 应是字符串")
    if "files" in value:
        files = value["files"]
        if not isinstance(files, list) or not all(isinstance(x, str) for x in files):
            errs.append(f"{where}.evidence.files 应是字符串列表")
    if "quote" in value and not isinstance(value["quote"], str):
        errs.append(f"{where}.evidence.quote 应是字符串")
    if "line" in value and not _is_int(value["line"]):
        errs.append(f"{where}.evidence.line 应是整数")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_unique_ids(errs: list[str], field: str, rows: list) -> None:
    seen = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if not isinstance(rid, str):
            continue
        if rid in seen:
            errs.append(f"{field}[{i}]: id={rid!r} 重复（同字段内须唯一）")
        seen.add(rid)


def _validate_incident_row(errs: list[str], field: str, i: int, row) -> None:
    where = f"{field}[{i}]"
    if not isinstance(row, dict):
        errs.append(f"{where}: 应是映射")
        return
    _check_keys(errs, where, row, INCIDENT_KEYS)
    _check_id(errs, where, field, row.get("id"))
    _check_at(errs, where, row.get("at"))
    if row.get("at_note") is not None:
        _check_str(errs, f"{where}.at_note", row.get("at_note"))
    _check_str(errs, f"{where}.what", row.get("what"), required=True)
    _check_enum(errs, where, "source", row.get("source"), INCIDENT_SOURCES)
    if row.get("step") is not None and not _is_int(row.get("step")):
        errs.append(f"{where}.step 应是整数")
    _check_evidence(errs, where, row.get("evidence"))


def _validate_upstream_row(errs: list[str], field: str, i: int, row) -> None:
    where = f"{field}[{i}]"
    if not isinstance(row, dict):
        errs.append(f"{where}: 应是映射")
        return
    _check_keys(errs, where, row, UPSTREAM_KEYS)
    _check_id(errs, where, field, row.get("id"))
    _check_at(errs, where, row.get("at"))
    _check_str(errs, f"{where}.what", row.get("what"), required=True)
    _check_enum(errs, where, "source", row.get("source"), UPSTREAM_SOURCES)
    if row.get("ref") is not None:
        _check_str(errs, f"{where}.ref", row.get("ref"))
    _check_evidence(errs, where, row.get("evidence"))


def _validate_row_list(errs: list[str], field: str, value) -> None:
    if not isinstance(value, list):
        errs.append(f"{field} 应是列表")
        return
    limit = MAX_INCIDENT if field == "incident_timeline" else MAX_UPSTREAM
    if len(value) > limit:
        errs.append(f"{field} 有 {len(value)} 条，超过上限 {limit}")
    for i, row in enumerate(value):
        if field == "incident_timeline":
            _validate_incident_row(errs, field, i, row)
        else:
            _validate_upstream_row(errs, field, i, row)
    _check_unique_ids(errs, field, value)


def _validate_node(errs: list[str], i: int, node) -> None:
    where = f"failure_process.nodes[{i}]"
    if not isinstance(node, dict):
        errs.append(f"{where}: 应是映射")
        return
    _check_keys(errs, where, node, NODE_KEYS)
    _check_id(errs, where, "failure_process", node.get("id"))
    _check_at(errs, where, node.get("at"))
    x = node.get("x")
    if x is not None and not (isinstance(x, str) or _is_int(x)):
        errs.append(f"{where}.x 应是整数、字符串或 null（step / request 轴用）")
    _check_str(errs, f"{where}.what", node.get("what"), required=True)
    _check_str(errs, f"{where}.quote", node.get("quote"), required=True)
    if node.get("repeat") is not None:
        _check_str(errs, f"{where}.repeat", node.get("repeat"))
    _check_evidence(errs, where, node.get("evidence"))


def _validate_window(errs: list[str], where: str, window) -> None:
    if window is None:
        return
    if not isinstance(window, dict):
        errs.append(f"{where}.window 应是映射（from / to）")
        return
    _check_keys(errs, f"{where}.window", window, WINDOW_KEYS)
    for key in ("from", "to"):
        if key in window and window[key] is not None and not isinstance(window[key], str):
            errs.append(f"{where}.window.{key} 应是字符串或 null（按材料原值写）")


def _validate_failure_process(errs: list[str], value) -> None:
    where = "failure_process"
    if not isinstance(value, dict):
        errs.append(f"{where} 应是映射（axis / window / clock_note / nodes）")
        return
    _check_keys(errs, where, value, FAILURE_KEYS)
    _check_enum(errs, where, "axis", value.get("axis"), FAILURE_AXES)
    _validate_window(errs, where, value.get("window"))
    if value.get("clock_note") is not None:
        _check_str(errs, f"{where}.clock_note", value.get("clock_note"))
    nodes = value.get("nodes")
    if nodes is None:
        errs.append(f"{where} 缺 nodes（可以是空列表）")
        return
    if not isinstance(nodes, list):
        errs.append(f"{where}.nodes 应是列表")
        return
    if len(nodes) > MAX_NODES:
        errs.append(f"{where}.nodes 有 {len(nodes)} 条，超过上限 {MAX_NODES}")
    for i, node in enumerate(nodes):
        _validate_node(errs, i, node)
    _check_unique_ids(errs, "failure_process", nodes)


def validate_field(field: str, value) -> list[str]:
    """单字段校验。写入口在落盘前用它挡住非法值（不等 `--all` 事后发现）。"""
    errs: list[str] = []
    if field not in WRITABLE_FIELDS:
        return [f"不认识的字段 {field!r}（允许：" + "、".join(WRITABLE_FIELDS) + "）"]
    if value is None:
        return errs  # null = 未记录 / 清空，由读端按「未记录」处理
    if field == "summary":
        _check_str(errs, field, value, required=True)
    elif field == "incident_env":
        if not isinstance(value, str):
            errs.append(f"{field} 应是字符串")
        elif "\n" in value:
            errs.append(f"{field} 应是一行（当前含换行）")
    elif field in ("incident_timeline", "upstream_timeline"):
        _validate_row_list(errs, field, value)
    elif field == "failure_process":
        _validate_failure_process(errs, value)
    return errs


def _valid_change_target(target) -> bool:
    if not isinstance(target, str):
        return False
    if target in WRITABLE_FIELDS:
        return True
    if REMOVED_TARGET.match(target):
        return True
    # 当前 id：只判格式，不判「现在还在不在」——早先修订改过的条目后来被删掉是合法的，
    # 拿当前文档去要求历史 target 仍存在，会把正常的历史修订判红。
    return any(pattern.match(target) for pattern in ID_PATTERNS.values())


def _validate_change(errs: list[str], where: str, change) -> None:
    if not isinstance(change, dict):
        errs.append(f"{where}: 应是映射（target / before / after）")
        return
    _check_keys(errs, where, change, CHANGE_KEYS)
    if not _valid_change_target(change.get("target")):
        errs.append(f"{where}.target={change.get('target')!r} 不合法"
                    "（应为字段名、当前条目 id 或 removed:<id>）")
    for key in ("before", "after"):
        if key not in change:
            errs.append(f"{where} 缺 {key}")
        elif not isinstance(change[key], str):
            errs.append(f"{where}.{key} 应是字符串")


def validate_revision(rev, where: str = "revision") -> list[str]:
    """一条修订记录的形状校验（写入口生成后自查、`--all` 逐条查）。"""
    errs: list[str] = []
    if not isinstance(rev, dict):
        return [f"{where}: 应是映射"]
    _check_keys(errs, where, rev, REVISION_KEYS)
    at = rev.get("at")
    if not is_valid_time(at, allow_date=False):
        errs.append(f"{where}.at={at!r} 不是可解析的时间"
                    "（写成 \"YYYY-MM-DDTHH:MM:SS+08:00\"）")
    _check_enum(errs, where, "by", rev.get("by"), REVISION_BY)
    _check_enum(errs, where, "kind", rev.get("kind"), REVISION_KINDS)
    _check_str(errs, f"{where}.reason", rev.get("reason"), required=True)
    changes = rev.get("changes")
    if not isinstance(changes, list) or not changes:
        errs.append(f"{where}.changes 至少一条")
    else:
        for i, change in enumerate(changes):
            _validate_change(errs, f"{where}.changes[{i}]", change)
    _check_evidence(errs, where, rev.get("evidence"))
    hashes = rev.get("hashes")
    if hashes is not None:
        if not isinstance(hashes, dict):
            errs.append(f"{where}.hashes 应是映射（field → sha256:...）")
        else:
            for field, digest in hashes.items():
                if field not in WRITABLE_FIELDS:
                    errs.append(f"{where}.hashes 有不认识的字段 {field!r}")
                if not isinstance(digest, str) or not HASH_RE.match(digest):
                    errs.append(f"{where}.hashes[{field!r}] 应是 sha256:<hex>")
    return errs


def _check_hash_consistency(doc: dict, revisions: list) -> list[str]:
    """每个被修订过的字段，取**最近一条带该字段 hashes 的修订**，重算当前值。

    这是防「绕过写入口静默改历史」的唯一机械手段：写入口每次都把被改字段的 canonical
    hash 写进该条修订；内容被手动改过、修订记录却没变，这里就会不等。
    """
    errs: list[str] = []
    latest: dict[str, str] = {}
    for rev in reversed(revisions):
        if not isinstance(rev, dict):
            continue
        hashes = rev.get("hashes")
        if not isinstance(hashes, dict):
            continue
        for field, digest in hashes.items():
            if field not in latest and isinstance(digest, str):
                latest[field] = digest
    for field, digest in latest.items():
        if field not in doc:
            errs.append(f"{field}: 修订记录里有它的 hash，但当前字段不存在")
            continue
        actual = canonical_hash(doc[field])
        if actual != digest:
            errs.append(f"{field}: 内容与最近一条修订的 hash 不一致"
                        "（可能绕过写入口改了内容）")
    return errs


def _has_value(value) -> bool:
    """字段算不算「有值」：null 与空串 / 空列表 / 空映射按未记录处理。"""
    return value not in (None, "", [], {})


def _check_hash_coverage(doc: dict, revisions: list) -> list[str]:
    """有值的内容字段必须被**某条** revision 的 hashes 覆盖。

    hash 一致性只比对「有 hash 的字段」，所以「先删掉整个 revisions、再手改内容」能绕过它。
    这里补上另一半：这些字段只能经写入口写，写入口必留 hash；字段有值却没有任何修订覆盖，
    就说明是手写进来的。
    """
    covered: set[str] = set()
    for rev in revisions:
        hashes = rev.get("hashes") if isinstance(rev, dict) else None
        if isinstance(hashes, dict):
            covered.update(str(key) for key in hashes)
    errs: list[str] = []
    for field in HASH_COVERED_FIELDS:
        if field in doc and _has_value(doc[field]) and field not in covered:
            errs.append(f"{field}: 内容字段存在但没有修订 hash（只能经写入口写）")
    return errs


def validate_content(doc) -> list[str]:
    """`verify_trace_status.py --all` 的入口：五个字段 + 修订记录 + hash 覆盖与一致性。

    旧 trace 没有这些字段 → 返回空列表。返回的每条错误都不带 session id，由调用方拼。
    """
    if not isinstance(doc, dict):
        return ["trace 不是映射"]
    errs: list[str] = []
    for field in WRITABLE_FIELDS:
        if field not in doc:
            continue
        errs.extend(validate_field(field, doc[field]))
    revisions = doc.get("revisions")
    if revisions is not None and not isinstance(revisions, list):
        errs.append("revisions 应是列表")
        rev_list: list = []
    else:
        rev_list = revisions or []
        for i, rev in enumerate(rev_list):
            errs.extend(validate_revision(rev, f"revisions[{i}]"))
        errs.extend(_check_hash_consistency(doc, rev_list))
    # 覆盖检查在 revisions 整个缺失时也要跑：「删掉 revisions 再手改」与「首次手写」
    # 的 trace 都有内容字段却没有修订 hash，是同一个缺口。
    errs.extend(_check_hash_coverage(doc, rev_list))
    return errs
