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

写入是**默认行为**；`--dry-run` 才只校验不写盘。三个子命令语义一致，不沿用
`sediment_batch.py` 那套「默认打印、`--apply` 才写」。

退出码：0 成功；2 参数/必填/转移不合法（E_SCHEMA）；3 状态已变（E_STATE_CHANGED）；
4 写入后校验失败，已回滚（E_IO）；5 主检出不可写（E_PERM）；6 trace 不存在（E_NOT_FOUND）；
7 脚本版本与词表不匹配（E_SCHEMA_VERSION）。
"""

from __future__ import annotations

import argparse
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
           "summary", "severity", "fix_emitted"}
CODE_EXIT = {"E_SCHEMA": 2, "E_STATE_CHANGED": 3, "E_IO": 4, "E_PERM": 5,
             "E_NOT_FOUND": 6, "E_SCHEMA_VERSION": 7}


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


def check_fields(doc: dict, action: dict, args) -> dict:
    """`fillable` 缺失就要本次提供；`mustExist` 缺失直接拒（面板据此给「先去回报」）。"""
    updates = {}
    missing = []
    for field in action["fillable"]:
        value = getattr(args, field.replace(".", "_"), None)
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

    if args.field == "sedimented":
        if not args.state:
            raise Fail("E_SCHEMA", "需要一个 --state", requirements=["sedimented.state"])
        block = sedimented_block(doc, args.state, args.case_id or "", args.inbox_path or "")
        new_text = put_block(text, "sedimented", block)
        new_text = put_block(new_text, "updated_at", scalar_block("updated_at", now_iso()))
        before = doc
    else:
        derived = derive(doc, set())
        allowed = actions_for(doc, vocab, derived)
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
        events = [e for e in (doc.get("transitions") or []) if isinstance(e, dict)]
        at = now_iso()
        by = args.by or "cli"
        source = args.source or "cli"
        prev_ending = doc.get("ending") if isinstance(doc.get("ending"), dict) else None

        if args.reopen:
            events.append({"at": at, "from": cur_status, "to": "in_progress",
                           "ending": None, "prev_ending": prev_ending,
                           "by": by, "source": source, "note": args.note or ""})
            new_status = "in_progress"
            new_text = drop_key(text, "ending")
            new_text = put_block(new_text, "status", scalar_block("status", new_status))
        elif args.backfill_ending:
            events.append({"at": at, "from": cur_status, "to": cur_status,
                           "ending": ending, "prev_ending": prev_ending,
                           "by": by, "source": source, "note": args.note or "补记收尾方式"})
            new_status = cur_status
            new_text = put_block(text, "ending", ending_block(ending))
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
                events.append({"at": at, "from": cur_status, "to": "in_progress",
                               "ending": None, "prev_ending": prev_ending,
                               "by": by, "source": source, "note": "改收尾方式：重新打开"})
                events.append({"at": at, "from": "in_progress", "to": target_status,
                               "ending": ending, "prev_ending": None,
                               "by": by, "source": source, "note": args.note or "改收尾方式：重新收尾"})
            else:
                events.append({"at": at, "from": cur_status, "to": target_status,
                               "ending": ending, "prev_ending": prev_ending,
                               "by": by, "source": source, "note": args.note or ""})
            new_status = target_status
            new_text = put_block(text, "status", scalar_block("status", new_status))
            new_text = put_block(new_text, "ending", ending_block(ending))
            if new_status == "resolved" and cur_status != "resolved":
                new_text = put_block(new_text, "resolved_at", scalar_block("resolved_at", today_iso()))
            if action["id"].startswith("close-") and not doc.get("stop_reason"):
                new_text = put_block(new_text, "stop_reason",
                                     scalar_block("stop_reason", args.stop_reason or "closed_by_user"))

        for field, value in updates.items():
            if field == "fix_emitted":
                value = bool(value) if not isinstance(value, bool) else value
            new_text = put_block(new_text, field, scalar_block(field, value))
        new_text = put_block(new_text, "updated_at", scalar_block("updated_at", now_iso()))
        new_text = put_block(new_text, "transitions", events_block(events))
        before = doc

    if args.dry_run:
        return {"ok": True, "dryRun": True, "changed": ["status", "ending", "transitions"]}

    lock_path = traces / ".transition"
    with log_lock(lock_path):
        tmp = path.with_suffix(".yaml.tmp")
        payload = new_text.replace("\n", newline).encode("utf-8")
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
    ap.add_argument("--to", default=None, choices=["resolved", "escalated", "archived", "in_progress"])
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
    ap.add_argument("--field", default=None, choices=["sedimented", "outcome"])
    ap.add_argument("--state", default=None)
    ap.add_argument("--case-id", default=None)
    ap.add_argument("--inbox-path", default=None)
    ap.add_argument("--by", default="cli", choices=["user", "agent", "cli"])
    ap.add_argument("--source", default="cli", choices=["panel", "cli", "agent", "import"])
    ap.add_argument("--expect-sha256", default=None)
    ap.add_argument("--scheme-version", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

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
    except Exception as exc:  # 未预期错误也要给稳定 code，面板才有一句人话
        payload = {"ok": False, "code": "E_IO", "message": str(exc)}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(str(exc), file=sys.stderr)
        return CODE_EXIT["E_IO"]


if __name__ == "__main__":
    sys.exit(main())
