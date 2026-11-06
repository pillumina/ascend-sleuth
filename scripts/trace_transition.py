#!/usr/bin/env python3
"""trace_transition.py —— 诊断状态转移的唯一写入口

**为什么需要**：`status` / `ending` / `sedimented` 目前由三处各写各的（agent 照一句中文
指令改 YAML、面板的行拼接、沉淀批量的行拼接），没有校验、没有事件、没有并发保护。
本脚本是唯一写入口：按 `trace-status.yaml` 的转移表校验必填、原子写入、追加一条
transition 事件；面板、skill、终端都调它。

**它不做什么**：不判断「该不该收尾」（那是人的动作）；不改 `trace[]` 事件流；不改
`feedback` 之外的任何轴（`--field outcome` 排 PR2）。

用法：

  python3 scripts/trace_transition.py <sid> --to resolved [--summary …] [--severity …] [--fix-emitted true]
  python3 scripts/trace_transition.py <sid> --to escalated --handed-to "张工 · CANN 组"
  python3 scripts/trace_transition.py <sid> --to archived --kind duplicate --duplicate-of case:VLLM-ASC-11312
  python3 scripts/trace_transition.py <sid> --reopen
  python3 scripts/trace_transition.py <sid> --field sedimented --state submitted --inbox-path …
  python3 scripts/trace_transition.py <sid> --to archived --kind withdrawn --expect-sha256 <hex> --json
  python3 scripts/trace_transition.py <sid> --json --payload-base64 <b64>
  （`--payload-base64` 是给「复制到任意终端」用的：base64 是纯 ASCII 单行，bash / zsh /
    PowerShell / cmd.exe 都不用管引号与 here-doc，也就不存在选错 shell 写法的问题）

写入是**默认行为**；`--dry-run` 才只校验不写盘。三个子命令语义一致，不沿用
`sediment_batch.py` 那套「默认打印、`--apply` 才写」。

退出码：0 成功；2 参数/必填/转移不合法（E_SCHEMA）；3 状态已变（E_STATE_CHANGED）；
4 写入后校验失败，已回滚（E_IO）；5 文件操作被系统拒绝（E_PERM，带路径与系统原因）；
6 trace 不存在（E_NOT_FOUND）；7 脚本版本与词表不匹配（E_SCHEMA_VERSION）。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from _stdio import write_text_lf  # noqa: E402
from _trace_state import (  # noqa: E402
    SCHEME, actions_for, case_kind, derive, is_terminal, load_vocab, status_meta,
)
from _yaml import load_text  # noqa: E402
from exec_log_path import log_lock, resolve_traces  # noqa: E402

TOUCHED = {"status", "ending", "resolved_at", "updated_at", "stop_reason", "transitions",
           "sedimented", "summary", "severity", "fix_emitted"}
CODE_EXIT = {"E_SCHEMA": 2, "E_STATE_CHANGED": 3, "E_IO": 4, "E_PERM": 5,
             "E_NOT_FOUND": 6, "E_SCHEMA_VERSION": 7, "E_NO_CHANGE": 8}

# 主文件里最多留几条转移记录。超出后把最早的一段折叠成一条汇总，完整记录另存本机
# （`traces/.transition-history/<session>.jsonl`）。理由：状态文件是给人看与给脚本读的，
# 反复来回改状态会让它变成一本流水账；审计需要的那份不该压在同一个文件里。
MAX_INLINE_TRANSITIONS = 8
HISTORY_DIR = ".transition-history"


class Fail(Exception):
    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def today_iso() -> str:
    return datetime.now().astimezone().date().isoformat()


# ── 文本定点替换：用 YAML 的 compose() 拿 mark，不靠正则找 `^status:` ──────────────
# 为什么不用正则：trace 里有块标量（`summary: >-`、`reason: |`），正文里完全可能有一行
# 以 `status: ` 开头。正则会把正文改掉，把一单记录写坏且不报错。
def top_level_spans(text: str) -> dict[str, tuple[int, int]]:
    node = yaml.compose(text)
    if not isinstance(node, yaml.MappingNode):
        raise Fail("E_SCHEMA", "这份 trace 不是 YAML 映射，拒绝写入")
    spans = {}
    for key_node, value_node in node.value:
        if not isinstance(key_node, yaml.ScalarNode):
            continue
        key = str(key_node.value)
        start = text.rfind("\n", 0, key_node.start_mark.index) + 1
        end = value_node.end_mark.index
        # 块结构的 end_mark 落在**下一行行首**（下一行的键或文件尾），此时不能顺着
        # find("\n") 往后走——那会把下一行的键一起吞掉（实测把 `ending:` 整行吃进
        # transitions 块里，文件从此解析不了）。落点在本行行首就退到上一行行尾。
        line_start = text.rfind("\n", 0, end) + 1
        if text[line_start:end].strip() == "":
            end = line_start
        else:
            nl = text.find("\n", end)
            end = len(text) if nl == -1 else nl + 1
        spans[key] = (start, end)
    return spans


def put_block(text: str, key: str, block: str) -> str:
    spans = top_level_spans(text)
    if key in spans:
        start, end = spans[key]
        return text[:start] + block + text[end:]
    sep = "" if text.endswith("\n") else "\n"
    return text + sep + block


def drop_key(text: str, key: str) -> str:
    spans = top_level_spans(text)
    if key not in spans:
        return text
    start, end = spans[key]
    return text[:start] + text[end:]


def ending_block(ending: dict) -> str:
    return ("ending:\n"
            f"  kind: {json.dumps(ending.get('kind') or '', ensure_ascii=False)}\n"
            f"  handed_to: {json.dumps(ending.get('handed_to') or '', ensure_ascii=False)}\n"
            f"  duplicate_of: {json.dumps(ending.get('duplicate_of') or '', ensure_ascii=False)}\n"
            f"  note: {json.dumps(ending.get('note') or '', ensure_ascii=False)}\n")


def scalar_block(key: str, value) -> str:
    if isinstance(value, bool):
        return f"{key}: {'true' if value else 'false'}\n"
    if value is None:
        return f"{key}: \"\"\n"
    return f"{key}: {json.dumps(str(value), ensure_ascii=False)}\n"


def events_block(events: list[dict]) -> str:
    # 每个事件用 flow mapping（JSON 是 YAML 子集），省的自己处理引号与换行。
    body = "".join("  - " + json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n" for e in events)
    return "transitions:\n" + body


def block_mapping(key: str, mapping: dict) -> str:
    return key + ":\n" + "".join(
        f"  {k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in mapping.items())


def list_block(key: str, rows: list[dict]) -> str:
    return key + ":\n" + "".join(
        "  - " + json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)


def apply_report(doc: dict, text: str, args, vocab: dict) -> tuple[str, dict]:
    """现场回报：只记事实。source=field 才写 feedback.outcome；厂商答复单独存，不进解决率。"""
    src = str(args.report_source or "")
    res = str(args.report_result or "")
    sources = {x["value"] for x in vocab.get("reportSources") or []}
    results = {x["value"]: x for x in vocab.get("reportResults") or []}
    if src not in sources:
        raise Fail("E_SCHEMA", "回报来源只能是现场验证或厂商答复", requirements=sorted(sources))
    if res not in results:
        raise Fail("E_SCHEMA", "回报结果不在词表里", requirements=sorted(results))
    entry = {"at": now_iso(), "by": args.by or "cli", "source": src, "result": res,
             "note": str(args.report_note or "")}
    reports = [r for r in (doc.get("reports") or []) if isinstance(r, dict)] + [entry]
    new_text = put_block(text, "reports", list_block("reports", reports))
    if src == "field":
        outcome = results[res].get("outcome") or ""
        fb = doc.get("feedback") if isinstance(doc.get("feedback"), dict) else {}
        merged = dict(fb)
        merged["outcome"] = outcome
        new_text = put_block(new_text, "feedback", block_mapping("feedback", merged))
    new_text = put_block(new_text, "updated_at", scalar_block("updated_at", now_iso()))
    return new_text, doc


def apply_review(doc: dict, text: str, args, vocab: dict) -> tuple[str, dict]:
    """复核结论：只落一条记录。它不改状态、不改知识库；修订报告本身由 agent 做。"""
    verdict = str(args.verdict or "")
    allowed = {x["value"] for x in vocab.get("reviewVerdicts") or []}
    if verdict not in allowed:
        raise Fail("E_SCHEMA", "复核结论不在词表里", requirements=sorted(allowed))
    reviews = [r for r in (doc.get("reviews") or []) if isinstance(r, dict)] + [{
        "at": now_iso(), "by": args.by or "cli", "verdict": verdict,
        "note": str(args.review_note or "")}]
    new_text = put_block(text, "reviews", list_block("reviews", reviews))
    new_text = put_block(new_text, "updated_at", scalar_block("updated_at", now_iso()))
    return new_text, doc


def sedimented_block(doc: dict, state: str, case_id: str, inbox_path: str) -> str:
    current = doc.get("sedimented") if isinstance(doc.get("sedimented"), dict) else {}
    merged = dict(current)
    merged["state"] = state
    if case_id:
        merged["case_id"] = case_id
    else:
        merged.setdefault("case_id", "")
    if inbox_path:
        merged["inbox_path"] = inbox_path
    else:
        merged.setdefault("inbox_path", "")
    order = ["state", "case_id", "inbox_path"]
    keys = order + [k for k in merged if k not in order]
    body = "".join(f"  {k}: {json.dumps('' if merged.get(k) is None else str(merged.get(k)), ensure_ascii=False)}\n"
                   for k in keys)
    return "sedimented:\n" + body


def find_entry(doc: dict, key: str) -> bool:
    return key in top_level_spans(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))


# ── 校验 ────────────────────────────────────────────────────────────────────
def pick_action(doc: dict, vocab: dict, derived: dict, args, allowed: list | None = None) -> dict:
    allowed = allowed if allowed is not None else actions_for(doc, vocab, derived)
    if args.to == "in_progress" and not args.reopen:
        args.reopen = True
    if args.reopen:
        for a in allowed:
            if a["id"] == "reopen":
                return a
        raise Fail("E_SCHEMA", "这单还没收尾，不能重新打开", requirements=["reopen"])
    if args.correct_ending:
        for a in allowed:
            if a["id"] == "correct-ending":
                return a
        raise Fail("E_SCHEMA", "只有已收尾的单能改收尾方式", requirements=["correct-ending"])
    if args.backfill_ending:
        for a in allowed:
            if a["id"] == "backfill-ending":
                return a
        raise Fail("E_SCHEMA", "只有缺收尾方式的已收尾单能补记", requirements=["backfill-ending"])
    target = args.to
    candidates = [a for a in allowed if target in a["to"]]
    if not candidates:
        raise Fail("E_SCHEMA", "当前状态不允许转到该状态", requirements=[a["id"] for a in allowed])
    if len(candidates) > 1 and not args.kind:
        raise Fail("E_SCHEMA", "这个目标有多个动作，请指定 --kind",
                   requirements=[a["id"] for a in candidates])
    return candidates[0]


def build_ending(choices: list[str], args) -> dict:
    kind = args.kind
    if not kind and len(choices) == 1:
        kind = choices[0]
    if not kind:
        raise Fail("E_SCHEMA", "需要指定收尾方式（--kind）", requirements=["ending.kind"])
    if choices and kind not in choices:
        raise Fail("E_SCHEMA", f"收尾方式 {kind} 不适用于这个动作", requirements=choices)
    ending = {
        "kind": kind,
        "handed_to": args.handed_to or "",
        "duplicate_of": args.duplicate_of or "",
        "note": args.note or "",
    }
    if kind == "handed_off" and not ending["handed_to"].strip():
        raise Fail("E_SCHEMA", "转交他人跟进需要填「转交给谁」", requirements=["ending.handed_to"])
    if kind == "duplicate" and not ending["duplicate_of"].strip():
        raise Fail("E_SCHEMA", "与已有单重复需要填被重复的那一单", requirements=["ending.duplicate_of"])
    if kind == "duplicate" and not (ending["duplicate_of"].startswith("case:")
                                    or ending["duplicate_of"].startswith("session:")):
        raise Fail("E_SCHEMA", "重复对象要写成 case:<id> 或 session:<id>", requirements=["ending.duplicate_of"])
    return ending


def kind_requires(vocab: dict, kind: str | None) -> list[str]:
    """所选收尾方式自带的必填（`handed_off → ending.handed_to`、`duplicate → ending.duplicate_of`）。
    补记老 `escalated` 单时同样要这些字段，否则会写出缺接手方的记录。"""
    for e in vocab["endings"]:
        if e["value"] == kind:
            return list(e["requires"])
    return []


def check_enums(doc: dict, vocab: dict, args) -> None:
    """写入口也要查枚举：不在词表里的值一旦落盘，`--all` 只能事后发现，而它当时还是「合法」的。"""
    summary = getattr(args, "summary", None)
    if summary is not None:
        if not str(summary).strip():
            raise Fail("E_SCHEMA", "summary 不能为空", requirements=["summary"])
        if "summary" not in action_ids(doc, vocab):
            pass
    severity = getattr(args, "severity", None)
    if severity is not None:
        allowed = {s["value"] for s in vocab["severities"]}
        if severity not in allowed:
            raise Fail("E_SCHEMA", f"severity={severity!r} 不在词表里", requirements=sorted(allowed))
    when = getattr(args, "stop_reason", None)
    if when is not None:
        allowed = set(vocab.get("stopReasons") or []) | {"closed_by_user"}
        if when not in allowed:
            raise Fail("E_SCHEMA", f"stop_reason={when!r} 不在词表里", requirements=sorted(allowed))
    if args.field == "sedimented":
        allowed = set(vocab.get("sedStates") or []) or {"none", "submitted", "knowledge", "archived"}
        if args.state not in allowed:
            raise Fail("E_SCHEMA", f"sedimented.state={args.state!r} 不在词表里", requirements=sorted(allowed))


def action_ids(doc: dict, vocab: dict) -> set:
    return {t["action"] for t in vocab["transitions"]}


def check_fields(doc: dict, action: dict, args) -> dict:
    """`fillable` 缺失就要本次提供；`mustExist` 缺失直接拒（面板据此给「先去回报」）。"""
    updates = {}
    missing = []
    for field in action["fillable"]:
        value = getattr(args, field.replace(".", "_"), None)
        if field == "fix_emitted" and isinstance(value, str):
            if value not in ("true", "false"):
                raise Fail("E_SCHEMA", "fix_emitted 只接受 true / false", requirements=["fix_emitted"])
            value = value == "true"
        if value is not None:
            updates[field] = value
        elif not _present(doc, field):
            missing.append(field)
    for field in action["mustExist"]:
        if not _present(doc, field):
            missing.append(field)
    if missing:
        raise Fail("E_SCHEMA", "缺少必填项：" + "、".join(missing), requirements=missing)
    return updates


def _present(doc: dict, field: str) -> bool:
    cur = doc
    for part in field.split("."):
        if not isinstance(cur, dict):
            return False
        cur = cur.get(part)
    if isinstance(cur, str):
        return bool(cur.strip())
    return cur is not None


# ── 主流程 ──────────────────────────────────────────────────────────────────
def apply_transition(root: Path, traces: Path, sid: str, args) -> dict:
    """锁必须包住「读 → CAS → 生成 → 写 → 校验」整段。

    只锁写那一步时，两个窗口拿同一份 sha 都能通过 CAS，后写者用自己的旧快照覆盖前者的
    事件（评审复现：两次调用都 ok，文件里只剩 1 条事件）。所以这里先取锁再读文件。
    """
    if args.dry_run:
        return _apply_locked(root, traces, sid, args)
    with log_lock(traces / ".transition-write") as held:
        # `log_lock` 的契约是 yield True/False：False 表示本平台连降级原语都没有。
        # 不加锁写状态会丢事件：两次并发收尾都通过 CAS，后写覆盖前写。
        # 这里拒绝写入，由调用方按 E_IO 报给用户。
        if not held:
            raise Fail("E_IO", "写锁不可用：本机既没有 fcntl 也没有 msvcrt，"
                              "拒绝在不加锁的情况下写状态")
        return _apply_locked(root, traces, sid, args)


def _apply_locked(root: Path, traces: Path, sid: str, args) -> dict:
    vocab = load_vocab(root)
    if args.scheme_version and args.scheme_version != SCHEME:
        raise Fail("E_SCHEMA_VERSION", f"面板期望 {args.scheme_version}，脚本是 {SCHEME}")
    path = traces / (sid + ".yaml")
    if not path.exists():
        raise Fail("E_NOT_FOUND", "这一单不在这台机器上")
    raw = path.read_bytes()
    import hashlib
    sha = hashlib.sha256(raw).hexdigest()
    bom = raw.startswith(b"\xef\xbb\xbf")
    body = raw[3:] if bom else raw
    newline = "\r\n" if b"\r\n" in body else "\n"
    text = body.decode("utf-8").replace("\r\n", "\n")
    doc = load_text(text) or {}
    if args.expect_sha256 and args.expect_sha256 != sha:
        last = (doc.get("transitions") or [{}])[-1] if doc.get("transitions") else {}
        raise Fail("E_STATE_CHANGED", "这单在别处被改过",
                   current={"status": doc.get("status"), "sha256": sha,
                            "at": last.get("at"), "by": last.get("by"), "source": last.get("source")})

    if args.to and args.to not in {x["value"] for x in vocab["statuses"]}:
        raise Fail("E_SCHEMA", "目标状态不在词表里", requirements=[x["value"] for x in vocab["statuses"]])
    if args.field == "review":
        new_text, before = apply_review(doc, text, args, vocab)
    elif args.field == "report":
        new_text, before = apply_report(doc, text, args, vocab)
    elif args.field == "sedimented":
        if not args.state:
            raise Fail("E_SCHEMA", "需要一个 --state", requirements=["sedimented.state"])
        block = sedimented_block(doc, args.state, args.case_id or "", args.inbox_path or "")
        new_text = put_block(text, "sedimented", block)
        new_text = put_block(new_text, "updated_at", scalar_block("updated_at", now_iso()))
        before = doc
    else:
        derived = derive(doc, set())
        allowed = actions_for(doc, vocab, derived)
        check_enums(doc, vocab, args)
        action = pick_action(doc, vocab, derived, args, allowed)
        cur_status = str(doc.get("status") or "unknown")
        # 「改收尾方式」与「补记收尾方式」在转移表里没有写死 kind：前者取目标收尾动作的
        # 候选，后者取当前状态允许的 ending_kinds。两处都在这里归一，面板拿到的仍是候选列表。
        if action["id"] == "correct-ending":
            # 目标收尾动作在 vocab 里（不在 allowed 里：allowed 只含当前状态合法的动作，
            # 终态时 close-* 都不在其中）。
            base = next((t for t in vocab["transitions"] if t["action"] == "close-" + str(args.to)), None)
            if base is None:
                raise Fail("E_SCHEMA", "改收尾方式需要一个具体的目标收尾动作", requirements=[])
            kinds = [base["ending"]] if base["ending"] else list(base["endingChoices"])
            action = {**action, "requires": base["requires"], "fillable": base["fillable"],
                      "mustExist": list(base["mustExist"]) + (
                          list(base["mustExistIfCase"]) if derived["caseKind"] == "case" else [])}
            choices = list(kinds)
        elif action["id"] == "backfill-ending":
            choices = [e["value"] for e in vocab["endings"] if cur_status in e["statuses"]]
        else:
            choices = [c["value"] for c in action["endingChoices"]]
        ending = build_ending(choices, args) if choices else None
        if ending:
            action = {**action,
                      "requires": list(action["requires"]) + kind_requires(vocab, ending["kind"])}
        updates = check_fields(doc, action, args)
        if ending is not None and not args.backfill_ending and not args.correct_ending:
            current_ending = doc.get("ending") if isinstance(doc.get("ending"), dict) else {}
            same = {k: str(current_ending.get(k) or "") for k in ("kind", "handed_to", "duplicate_of", "note")}
            new = {k: str(ending.get(k) or "") for k in ("kind", "handed_to", "duplicate_of", "note")}
            if action["id"] != "reopen" and target_status_of(action, args) == cur_status and same == new and not updates:
                raise Fail("E_NO_CHANGE", "这次的收尾内容和当前记录一样，没有写入")
        events = [e for e in (doc.get("transitions") or []) if isinstance(e, dict)]
        at = now_iso()
        by = args.by or "cli"
        source = args.source or "cli"
        prev_ending = doc.get("ending") if isinstance(doc.get("ending"), dict) else None

        if args.reopen:
            events.append({"action": "reopen", "at": at, "from": cur_status, "to": "in_progress",
                           "ending": None, "prev_ending": prev_ending,
                           "by": by, "source": source, "note": args.note or ""})
            new_status = "in_progress"
            new_text = drop_key(text, "ending")
            new_text = put_block(new_text, "status", scalar_block("status", new_status))
        elif args.backfill_ending:
            events.append({"action": "backfill-ending", "at": at, "from": cur_status, "to": cur_status,
                           "ending": ending, "prev_ending": prev_ending,
                           "by": by, "source": source, "note": args.note or "补记收尾方式"})
            new_status = cur_status
            new_text = put_block(text, "ending", ending_block(ending))
            if cur_status == "resolved" and not str(doc.get("resolved_at") or "").strip():
                # 老 resolved 单常见缺 resolved_at；补记时一并补上（取补记时刻的日期），
                # 否则补出来的记录会被自己的 --all 判成「有事件但缺 resolved_at」。
                new_text = put_block(new_text, "resolved_at", scalar_block("resolved_at", today_iso()))
        else:
            if action["id"] == "correct-ending":
                target_status = str(args.to)
            else:
                target = [s for s in action["to"] if s != cur_status]
                if not target:
                    raise Fail("E_SCHEMA", "目标状态与当前状态相同")
                target_status = target[0]
            if target_status == cur_status and action["id"] != "correct-ending":
                raise Fail("E_SCHEMA", "目标状态与当前状态相同")
            if action["id"] == "correct-ending" and target_status != cur_status:
                # 跨状态：重开 + 收尾两条事件（历史可回放，不是原地改一个字）
                events.append({"action": "reopen", "at": at, "from": cur_status, "to": "in_progress",
                               "ending": None, "prev_ending": prev_ending,
                               "by": by, "source": source, "note": "改收尾方式：重新打开"})
                events.append({"action": action["id"], "at": at, "from": "in_progress", "to": target_status,
                               "ending": ending, "prev_ending": None,
                               "by": by, "source": source, "note": args.note or "改收尾方式：重新收尾"})
            else:
                events.append({"action": action["id"], "at": at, "from": cur_status, "to": target_status,
                               "ending": ending, "prev_ending": prev_ending,
                               "by": by, "source": source, "note": args.note or ""})
            new_status = target_status
            new_text = put_block(text, "status", scalar_block("status", new_status))
            new_text = put_block(new_text, "ending", ending_block(ending))
            if new_status == "resolved" and (cur_status != "resolved" or not str(doc.get("resolved_at") or "").strip()):
                new_text = put_block(new_text, "resolved_at", scalar_block("resolved_at", today_iso()))
            if action["id"].startswith("close-") and not doc.get("stop_reason"):
                new_text = put_block(new_text, "stop_reason",
                                     scalar_block("stop_reason", args.stop_reason or "closed_by_user"))

        for field, value in updates.items():
            if field == "fix_emitted":
                value = bool(value) if not isinstance(value, bool) else value
            new_text = put_block(new_text, field, scalar_block(field, value))
        new_text = put_block(new_text, "updated_at", scalar_block("updated_at", now_iso()))
        history_path = append_history(traces, sid, events[-2:] if action["id"] == "correct-ending" and target_status != cur_status else events[-1:])
        folded_events, folded = fold_events(events)
        if folded:
            result_note = "折叠了 %d 条较早记录（完整历史：%s）" % (folded, history_path or "写入失败")
        else:
            result_note = ""
        new_text = put_block(new_text, "transitions", events_block(folded_events))
        before = doc

    if args.dry_run:
        changed = [k for k in ("status", "ending", "sedimented", "resolved_at", "stop_reason",
                               "summary", "severity", "fix_emitted") if getattr(args, k, None) is not None]
        return {"ok": True, "dryRun": True, "changed": changed}

    if True:
        tmp = path.with_suffix(".yaml.tmp")
        out_text = new_text
        if not text.endswith("\n") and out_text.endswith("\n"):
            out_text = out_text[:-1]
        payload = out_text.replace("\n", newline).encode("utf-8")
        if bom:
            payload = b"\xef\xbb\xbf" + payload
        tmp.write_bytes(payload)
        if tmp.read_bytes() != payload:
            tmp.unlink(missing_ok=True)
            raise Fail("E_IO", "写盘后的内容与内存不一致，已放弃")
        os.replace(tmp, path)
    after_raw = path.read_bytes()
    after_body = after_raw[3:] if after_raw.startswith(b"\xef\xbb\xbf") else after_raw
    after = load_text(after_body.decode("utf-8")) or {}
    if not verify_untouched(before, after):
        path.write_bytes(raw)
        raise Fail("E_IO", "写入后校验失败，已回滚")
    last = (after.get("transitions") or [{}])[-1]
    return {"ok": True,
            "from": before.get("status"),
            "to": after.get("status"),
            "changed": sorted([k for k in TOUCHED if before.get(k) != after.get(k)]),
            "event": last,
            "current": {"status": after.get("status"), "ending": after.get("ending"),
                        "sha256": __import__("hashlib").sha256(
                            path.read_bytes()).hexdigest()}}


def target_status_of(action: dict, args) -> str:
    if action["id"] == "correct-ending":
        return str(args.to or "")
    return action["to"][0] if action["to"] else ""


def append_history(traces: Path, sid: str, events: list[dict]) -> str:
    """把新事件追加到本机完整历史（JSON 行）。失败不阻断状态写入，但要在结果里说出来。"""
    try:
        folder = traces / HISTORY_DIR
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (sid + ".jsonl")
        with path.open("a", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev, ensure_ascii=False, sort_keys=True) + "\n")
        return str(path)
    except OSError:
        return ""


def fold_events(events: list[dict], keep: int = MAX_INLINE_TRANSITIONS) -> tuple[list[dict], int]:
    """主文件只留最近 `keep` 条；更早的折叠成一条汇总（保留起点状态与折叠条数）。"""
    if len(events) <= keep:
        return events, 0
    head = events[: len(events) - keep + 1]
    tail = events[len(events) - keep + 1:]
    summary = {
        "at": head[0].get("at"), "from": head[0].get("from"), "to": head[-1].get("to"),
        "folded": len(head), "note": "更早的 %d 次转移已折叠（完整记录见 .transition-history/）" % len(head),
    }
    return [summary] + tail, len(head)


def _payload_from_base64(token: str):
    """base64 → JSON 对象。返回 (payload, err)；err 是给人看的一句，三种手误分开说。"""
    raw = str(token or "")
    if not raw:
        return None, "base64 参数是空的"
    try:
        body = base64.b64decode(raw, validate=True).decode("utf-8")
    except Exception as exc:
        return None, "base64 参数解不开：" + str(exc)
    try:
        payload = json.loads(body)
    except Exception as exc:
        return None, "base64 解出来不是 JSON：" + str(exc)
    if not isinstance(payload, dict):
        return None, "payload 必须是对象，解出来是 " + type(payload).__name__
    return payload, None


def verify_untouched(before: dict, after: dict) -> bool:
    for key, value in before.items():
        if key in TOUCHED:
            continue
        if after.get(key) != value:
            return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="诊断状态转移的唯一写入口")
    ap.add_argument("session_id")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本上一级；读 trace-status.yaml）")
    ap.add_argument("--traces", default=None, help="traces 目录（默认由主检出解析；测试与多检出不带 git 时用）")
    # 不加 choices：状态集合的唯一来源是 trace-status.yaml。这里只做语法层接收，
    # 合法性由 actions_for/转移表判定（加一个状态不必改这个文件）。
    ap.add_argument("--to", default=None)
    ap.add_argument("--kind", default=None, help="收尾方式（见 trace-status.yaml 的 ending_kinds）")
    ap.add_argument("--handed-to", default=None)
    ap.add_argument("--duplicate-of", default=None)
    ap.add_argument("--note", default=None)
    ap.add_argument("--summary", default=None)
    ap.add_argument("--severity", default=None)
    ap.add_argument("--fix-emitted", default=None, choices=["true", "false"])
    ap.add_argument("--stop-reason", default=None)
    ap.add_argument("--reopen", action="store_true")
    ap.add_argument("--correct-ending", action="store_true")
    ap.add_argument("--backfill-ending", action="store_true")
    ap.add_argument("--field", default=None, choices=["sedimented", "outcome", "report", "review"])
    ap.add_argument("--verdict", default=None)
    ap.add_argument("--review-note", default=None)
    ap.add_argument("--report-source", default=None)
    ap.add_argument("--report-result", default=None)
    ap.add_argument("--report-note", default=None)
    ap.add_argument("--state", default=None)
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--inbox-path", default=None)
    ap.add_argument("--by", default="cli", choices=["user", "agent", "cli"])
    ap.add_argument("--source", default="cli", choices=["panel", "cli", "agent", "import"])
    ap.add_argument("--expect-sha256", default=None)
    ap.add_argument("--scheme-version", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--payload-file", default=None,
                    help="从 JSON 文件读参数（面板写入用：避免把所有值拼进命令行）")
    ap.add_argument("--payload-base64", default=None,
                    help="从命令行读 base64 编码的 JSON 参数（复制命令用：单行 ASCII，与 shell 无关）")
    ap.add_argument("--payload-stdin", action="store_true",
                    help="从标准输入读 JSON 参数（复制命令用：here-doc）")
    args = ap.parse_args(argv)

    payload = None
    if args.payload_file:
        try:
            payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload 必须是对象")
        except Exception as exc:
            print(json.dumps({"ok": False, "code": "E_SCHEMA", "message": "参数文件读不了：" + str(exc)},
                             ensure_ascii=False) if args.json else "参数文件读不了：" + str(exc), file=sys.stdout if args.json else sys.stderr)
            return CODE_EXIT["E_SCHEMA"]
        finally:
            try:
                Path(args.payload_file).unlink()
            except OSError:
                pass
    elif args.payload_base64 is not None:
        # base64 先解成 UTF-8 字节再交给 json：不经过终端编码，中文不会被打成问号。
        # 三段分开报错——「解不开」「解出来不是 JSON」「不是对象」是三种不同的手误，
        # 合成一句读者只能猜。空串也走这里（`is not None`，不用真值判断：空串会被跳过，
        # 最后报成「不允许转到该状态」，看不出是参数没带）。
        payload, err = _payload_from_base64(args.payload_base64)
        if err:
            print(json.dumps({"ok": False, "code": "E_SCHEMA", "message": err}, ensure_ascii=False)
                  if args.json else err, file=sys.stdout if args.json else sys.stderr)
            return CODE_EXIT["E_SCHEMA"]
    elif args.payload_stdin:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except Exception as exc:
            print(json.dumps({"ok": False, "code": "E_SCHEMA", "message": "标准输入的 JSON 读不了：" + str(exc)},
                             ensure_ascii=False) if args.json else "标准输入的 JSON 读不了：" + str(exc), file=sys.stdout if args.json else sys.stderr)
            return CODE_EXIT["E_SCHEMA"]
    if isinstance(payload, dict):
        # 命令行显式给的优先；payload 只补空位
        for key, value in payload.items():
            attr = {"to": "to", "kind": "kind", "handed_to": "handed_to", "duplicate_of": "duplicate_of",
                    "summary": "summary", "severity": "severity", "fix_emitted": "fix_emitted",
                    "note": "note", "stop_reason": "stop_reason", "by": "by", "source": "source",
                    "expect_sha256": "expect_sha256",
                    "report_source": "report_source", "report_result": "report_result",
                    "report_note": "report_note", "verdict": "verdict",
                    "review_note": "review_note"}.get(key)
            if attr and getattr(args, attr, None) in (None, ""):
                setattr(args, attr, value)
        if payload.get("reopen"):
            args.reopen = True

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]
    if args.field == "outcome":
        print("PR2 才实现回报轴写入口；本 PR 只开放 --field sedimented", file=sys.stderr)
        return CODE_EXIT["E_SCHEMA"]
    try:
        traces = Path(args.traces) if args.traces else resolve_traces(root)
        result = apply_transition(root, traces, args.session_id, args)
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"已记录：{result.get('from')} → {result.get('to')}（{args.session_id}）")
        return 0
    except Fail as exc:
        payload = {"ok": False, "code": exc.code, "message": exc.message, **exc.extra}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(exc.message, file=sys.stderr)
        return CODE_EXIT.get(exc.code, 2)
    except PermissionError as exc:
        # 文件级 PermissionError 不只来自「写不进去」：读 trace、开锁文件失败也走这里。
        # 消息说清是文件操作被拒，并带出路径与系统原因，读者才知道该修哪一处；
        # 面板再按 E_PERM 给「生成指令」兜底（会话里的 shell 可能仍能写）。
        where = str(exc.filename) if exc.filename else ""
        reason = exc.strerror or str(exc)
        message = ("文件操作被系统拒绝：" + where + "（" + reason + "）") if where \
            else ("文件操作被系统拒绝（" + reason + "）")
        payload = {"ok": False, "code": "E_PERM", "message": message}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
        return CODE_EXIT["E_PERM"]
    except Exception as exc:  # 未预期错误也要给稳定 code，面板才有一句人话
        payload = {"ok": False, "code": "E_IO", "message": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(str(exc), file=sys.stderr)
        return CODE_EXIT["E_IO"]


if __name__ == "__main__":
    sys.exit(main())
