#!/usr/bin/env python3
"""verify_trace_status.py —— 诊断状态的一致性检查

分三档，跑在不同的地方：

  --check   只查词表自洽 + 面板源码里不许再有状态字面量表。**不需要 traces**，因此能进 CI
            （`traces/` 是 gitignored 的运行时件，CI 里没有它）。
  --all     本机现状：字段一致性与转移事件校验。老数据按 grandfather 规则不判违规
            （只有带 `transitions` 的单才要求「终态必有收尾方式」），导入单（交接包落位）
            ���计入。
  --strict  本机：要求所有非导入终态单都有 `transitions` 与 `ending`。给人看，不进 CI。

口径：终态必有 `ending`；`handed_off` 有 `handed_to`；`duplicate` 有 `duplicate_of`；
`in_progress` 无 `ending`；每条事件 `from`/`to` 合法、与上一条接得上、`at` 是 ISO 8601、
`ending`/`prev_ending` 形状正确。

退出码：0 通过；1 有违规；2 词表自洽失败或环境不可用。
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _trace_state import check_vocab, is_terminal, load_vocab, load_traces  # noqa: E402
from exec_log_path import resolve_traces  # noqa: E402

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)$")
# 面板源码里不许再出现的旧常量与旧文案：这些是「面板自己实现判据」的痕迹。
PANEL_FILES = ["dsh-plugins/ascend-panel/panel-client.js", "dsh-plugins/ascend-panel/panel-host.js"]
FORBIDDEN_PANEL = ["RESUMEABLE", "statusMeta", "STATUS_LABEL", "statusAccent",
                   "'close-fix'", "'close-nofix'", "'close-archive'", "'close-escalate'"]


def check_panel_vocab(root: Path) -> list[str]:
    errs = []
    for rel in PANEL_FILES:
        path = root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_PANEL:
            if token in text:
                errs.append(f"{rel}: 仍有旧的状态常量/动作 id `{token}`（面板应只渲染投影给的 actions）")
    return errs


def check_vocab_file(root: Path) -> int:
    vocab = load_vocab(root)
    errs = check_vocab(vocab) + check_panel_vocab(root)
    if errs:
        print("词表自洽检查失败：")
        for e in errs:
            print("  - " + e)
        return 1
    print(f"词表自洽：{len(vocab['statuses'])} 个状态、{len(vocab['endings'])} 种收尾方式、"
          f"{len(vocab['transitions'])} 个动作；面板源码无旧状态常量")
    return 0


def check_trace(entry: dict, vocab: dict, strict: bool, imported: bool) -> list[str]:
    errs = []
    doc = entry["doc"]
    sid = entry["sessionId"]
    if doc is None:
        return [f"{sid}: YAML 解析失败（{entry['error']}）"]
    status = str(doc.get("status") or "unknown")
    ending = doc.get("ending")
    events = [e for e in (doc.get("transitions") or []) if isinstance(e, dict)]
    terminal = is_terminal(vocab, status)

    if terminal and not ending:
        if strict and not imported:
            errs.append(f"{sid}: 终态 {status} 缺 ending（{len(events)} 条转移事件）")
        elif events:
            # 有事件说明是写入口写过的单：终态却不带收尾方式，一定是写坏或手改过。
            errs.append(f"{sid}: 终态 {status} 缺 ending，但有转移事件")
    if not terminal and ending:
        errs.append(f"{sid}: 非终态 {status} 却带 ending")
    if isinstance(ending, dict):
        kind = str(ending.get("kind") or "")
        kinds = {e["value"]: e for e in vocab["endings"]}
        if kind not in kinds:
            errs.append(f"{sid}: ending.kind={kind!r} 不在 ending_kinds 里")
        else:
            for req in kinds[kind]["requires"]:
                value = ending.get(req.split(".")[-1])
                if not str(value or "").strip():
                    errs.append(f"{sid}: ending.kind={kind} 缺 {req}")
            if status not in kinds[kind]["statuses"]:
                errs.append(f"{sid}: ending.kind={kind} 不能用于状态 {status}")
            if kind == "duplicate":
                dup = str(ending.get("duplicate_of") or "")
                if not (dup.startswith("case:") or dup.startswith("session:")):
                    errs.append(f"{sid}: duplicate_of 要写成 case:<id> 或 session:<id>（当前 {dup!r}）")
    if status == "resolved" and events and not str(doc.get("resolved_at") or "").strip():
        errs.append(f"{sid}: resolved 且有转移事件，但 resolved_at 为空")

    prev_to = None
    for i, ev in enumerate(events):
        where = f"{sid}: transitions[{i}]"
        frm, to = str(ev.get("from") or ""), str(ev.get("to") or "")
        if frm not in {s["value"] for s in vocab["statuses"]}:
            errs.append(f"{where}: from={frm!r} 不是合法状态")
        if to not in {s["value"] for s in vocab["statuses"]}:
            errs.append(f"{where}: to={to!r} 不是合法状态")
        if prev_to is not None and frm != prev_to:
            errs.append(f"{where}: from={frm!r} 与上一条的 to={prev_to!r} 接不上")
        prev_to = to
        at = str(ev.get("at") or "")
        if not ISO.match(at):
            errs.append(f"{where}: at 不是 ISO 8601（{at!r}）")
        if ev.get("ending") is not None and not isinstance(ev.get("ending"), dict):
            errs.append(f"{where}: ending 应是映射或 null")
        if ev.get("prev_ending") is not None and not isinstance(ev.get("prev_ending"), dict):
            errs.append(f"{where}: prev_ending 应是映射或 null")
    if events:
        last = events[-1]
        if str(last.get("to") or "") != status:
            errs.append(f"{sid}: 最后一条事件的 to={last.get('to')!r} 与顶层 status={status!r} 不一致")
    if strict and not imported and terminal and not events:
        errs.append(f"{sid}: 终态 {status} 没有转移事件（--strict）")
    return errs


def imported_ids(traces: Path) -> set[str]:
    """交接包落位过的单：`traces/handoff/<sid>.yaml` 存在即算。这些单的状态由导入写，
    不是本机转移，`--strict` 不要求它有 `transitions`。"""
    ids = set()
    handoff = traces / "handoff"
    if not handoff.is_dir():
        return ids
    for path in handoff.glob("*.yaml"):
        ids.add(path.stem)
    return ids


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="诊断状态一致性检查")
    ap.add_argument("--root", default=None)
    ap.add_argument("--traces", default=None)
    ap.add_argument("--check", action="store_true", help="只查词表自洽（CI 用，不需要 traces）")
    ap.add_argument("--all", action="store_true", help="查本机全部 trace 的字段与事件")
    ap.add_argument("--strict", action="store_true", help="要求所有非导入终态单都有事件与收尾方式")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]
    if args.check:
        return check_vocab_file(root)

    traces = Path(args.traces) if args.traces else resolve_traces(root)
    if not traces.is_dir():
        print(f"traces 目录不存在：{traces}", file=sys.stderr)
        return 2
    vocab = load_vocab(root)
    errs = check_vocab(vocab)
    if errs:
        for e in errs:
            print("  - " + e)
        return 2

    imported = imported_ids(traces)
    entries = load_traces(traces)
    violations = []
    legacy_terminal = 0
    for entry in entries:
        doc = entry["doc"] or {}
        events = [e for e in (doc.get("transitions") or []) if isinstance(e, dict)]
        if not events and is_terminal(vocab, str(doc.get("status") or "")):
            legacy_terminal += 1
        violations.extend(check_trace(entry, vocab, args.strict, entry["sessionId"] in imported))

    print(f"检查 {len(entries)} 份 trace：{len(violations)} 条违规；"
          f"老终态单缺收尾方式 {legacy_terminal} 份（grandfather，不计违规）")
    for v in violations:
        print("  - " + v)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
