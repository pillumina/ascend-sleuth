#!/usr/bin/env python3
# settle_trace_feedback.py —— 把 traces/*.yaml 的 feedback 事件确定性结算到 case 置信度
#
# 目的：闭合 case 层学习环（与 reference 层 R6 对称）——trace 里记了
#   {action: feedback, case: <case-id>, outcome: resolved|not_resolved|partial}，
#   但没有任何机制把它累积进 knowledge/<ns>/<case>.yaml 的 confidence 字段。
#   结果：命中/反馈不落库，confidence 永远是初始 score，学习环空转。
#
# 结算规则（2026-08-31 设计确认——用户/owner 决策）：
#   - **只有 feedback.resolved 才 hits += 1**——命中（hit 事件）是系统检索行为，
#     不代表 case 有效；可信反馈（用户确认"这个诊断解决了我问题"）才是置信度信号。
#   - feedback.not_resolved / partial → misdiagnoses += 1（负信号，计入误诊）
#   - 同步更新 last_hit（最近一次有反馈的日期）
#   - 不读 hit 事件（命中不计数，见上）
#
# 幂等：结算状态记录在 ingest-state.json 的 sources.<key>.trace_feedback 下
#   （与 issue-ingest 的 processed 同一哲学——read-modify-write 无锁，串行运行）。
#   已结算的 session_id + feedback 事件列表 hash 不再重复累积。
#
# 用法（groom 周批，串行）：
#   python3 scripts/settle_trace_feedback.py --state ingest-state.json \
#     [--dry-run] [--apply]
#   --dry-run（默认）：只输出将要发生的 diff，不写任何文件
#   --apply：写回 case YAML（产出 diff 供走 PR——脚本本身不改 git）
#
# 输出：
#   - diff 清单：每个 case 的 hits/misdiagnoses/last_hit 从哪到哪
#   - 走 PR 时用 knowledge_modification 模板（confidence 字段变更）

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from _stdio import write_text_lf
from exec_log_path import resolve_rel, resolve_traces

TRACES_DIR = Path("traces")   # 相对名；实际取哪一份由 resolve_traces() 决定（主检出共享侧）


def iso_week_now():
    """当前 ISO 周（如 2026-W36），last_hit 用——与 metrics 周批节律一致。"""
    from datetime import date
    d = date.today()
    return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"


def load_case(path: Path):
    """读 case YAML，返回 (doc, case, rel_path)。"""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc, doc["cases"][0], str(path)

# 结算游标：登记的共享运行时件（锚主检出、跨 worktree 共读共写、gitignored）。
# 为什么不写 ingest-state.json：那份是摄取台账（要跨机同步故 tracked、走 PR）；
# 游标只是本地幂等状态，进 git 会让每次结算都变成一次 PR（见 EV-2026-096）。
SETTLE_STATE_REL = Path(".settle-state.json")
LEGACY_CURSOR_KEYS = ("_trace_feedback", "_s2_feedback")

# 来源 session 自己的 resolve 属「自证」，落 confidence 的这个键下，不计入 hits。
# 与 S2 的 validation_record.self_consistent 同一条纪律——如实标注、不虚增置信度。
SELF_RESOLVED_KEY = "self_resolved"


def resolve_default_state(root: Path):
    """默认游标路径 → (path, where)。显式 --state 由调用方覆盖。"""
    return resolve_rel(root, SETTLE_STATE_REL)


def load_cursors(state_path: Path, migrate_from=None):
    """读游标。新文件不存在时，从 legacy tracked 文件（ingest-state.json）迁移既有游标。"""
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8")), None
        except Exception as exc:
            print(f"[warn] 游标文件解析失败（{exc}）——按空游标处理（幂等靠 events hash，不重复计数）")
            return {}, None
    migrated = {}
    if migrate_from and Path(migrate_from).exists():
        try:
            old = json.loads(Path(migrate_from).read_text(encoding="utf-8"))
            for key in LEGACY_CURSOR_KEYS:
                for k, v in (old.get("sources", {}).get(key) or {}).items():
                    migrated.setdefault(key, {})[k] = v
        except Exception:
            pass
    return migrated, (Path(migrate_from) if migrated else None)


def case_source_session(doc):
    """case 的「来源 session」——由 to-postmortem / diagnose 回写；缺则 None。

    无法判定时退回原行为（计入 hits），这是刻意的保守取舍：宁可少识别自证，不误判独立命中。
    """
    try:
        return doc["cases"][0].get("source_session")
    except Exception:
        return None


def is_self_settle(doc, case_id, sid, traces_dir: Path):
    """这笔 feedback 是否「来源 session 自证」——该 session 正是这条 case 的产地。

    两条互证来源（任一成立即算）：case 的 `source_session` 字段；或该 session trace 的
    `sedimented.case_id` 与该 case 相同。
    """
    if case_source_session(doc) == sid:
        return True
    try:
        st = yaml.safe_load((traces_dir / f"{sid}.yaml").read_text(encoding="utf-8"))
        sed = st.get("sedimented") or {}
        # 两种写法都认：schema 文档写 case_id，历史 trace 里有写 caseId 的
        return case_id in (sed.get("case_id"), sed.get("caseId"))
    except Exception:
        return False


def write_self_resolved(case_f: Path, sid: str, week: str):
    """把自证写进 case 的 `confidence.self_resolved`——如实记录，**不动 hits**。"""
    text = case_f.read_text(encoding="utf-8")
    nl = chr(10)
    lines = text.split(nl)
    conf_idx = next((i for i, ln in enumerate(lines) if ln.strip() == "confidence:"), None)
    if conf_idx is None:
        return False

    start = end = None
    i = conf_idx + 1
    while i < len(lines):
        ln = lines[i]
        if ln.strip() and not ln.startswith("      "):
            break
        if ln.strip().startswith(SELF_RESOLVED_KEY + ":"):
            start = i
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith("        ")):
                j += 1
            end = j
            break
        i += 1

    count, examples = 0, []
    if start is not None:
        vals = {}
        for ln in lines[start:end]:
            t = ln.strip()
            for k in ("count", "last", "examples"):
                if t.startswith(k + ":"):
                    vals[k] = t[len(k) + 1:].strip()
        try:
            count = int(vals.get("count", "0") or 0)
        except ValueError:
            count = 0
        try:
            examples = yaml.safe_load(vals.get("examples", "[]")) or []
        except Exception:
            examples = []
    if sid not in examples:
        examples.append(sid)

    block = [
        "      " + SELF_RESOLVED_KEY + ":  # 来源 session 自己的 resolve（自证）——如实标注、不计入 hits",
        "        count: " + str(count + 1),
        '        last: "' + week + '"',
        "        examples: [" + ", ".join(examples) + "]",
    ]
    if start is not None:
        new_lines = lines[:start] + block + lines[end:]
    else:
        j = conf_idx + 1
        while j < len(lines) and (not lines[j].strip() or lines[j].startswith("      ")):
            j += 1
        new_lines = lines[:j] + block + lines[j:]
    write_text_lf(case_f, nl.join(new_lines) + nl, encoding="utf-8")
    return True


def settle(traces_dir: Path, state_path: Path, apply: bool, kb_root: Path = Path("knowledge"),
           migrate_from=None):
    state, migrated = load_cursors(state_path, migrate_from)
    # 结算游标：{session_id: {"events": hash, "settled_at": iso}}（旧格式在 sources._trace_feedback 下）
    settled = state.setdefault("_trace_feedback", {})
    if migrated:
        print(f"[migrate] 从 {migrated} 迁入 {len(settled)} 条既有游标（防迁移后重复计数）\n")

    # 收集所有 feedback 事件（按 session 聚合）
    pending = []  # (session_id, case_id, outcome, events_hash)
    for f in sorted(traces_dir.glob("*.yaml")):
        sid = f.stem
        try:
            st = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[skip] {f.name}: 解析失败（{e}）——不结算，保持原状")
            continue
        events = []
        for ev in st.get("trace", []):
            if ev.get("action") == "feedback":
                out = ev.get("outcome")
                if out in ("resolved", "not_resolved", "partial"):
                    events.append({"case": ev.get("case"), "outcome": out})
        if not events:
            continue
        # 事件序列 hash（幂等键：同 session 同序列只结算一次）
        h = hashlib.sha256(json.dumps(events, sort_keys=True).encode()).hexdigest()[:16]
        prev = settled.get(sid, {})
        if prev.get("events") == h:
            print(f"[skip] {f.name}: 已结算（hash {h}）")
            continue
        pending.append((sid, events, h))

    if not pending:
        print("无未结算的 feedback 事件。")
        return

    print(f"发现 {len(pending)} 个 session 含未结算 feedback 事件。\n")
    all_diffs = []
    for sid, events, h in pending:
        for ev in events:
            case_id = ev["case"]
            outcome = ev["outcome"]
            if not case_id:
                print(f"[warn] {sid}: feedback 事件缺 case 字段——跳过（outcome={outcome}）")
                continue
            # 定位 case 文件
            target = None
            for case_f in kb_root.rglob("*.yaml"):
                if "_archive" in str(case_f) or case_f.name == "_index.yaml":
                    continue
                try:
                    doc, c, rel = load_case(case_f)
                except Exception:
                    continue
                if c.get("id") == case_id:
                    target = (case_f, doc, c, rel)
                    break
            if not target:
                print(f"[warn] {sid}: case {case_id} 未在 knowledge/ 找到——跳过（可能已归档或删除）")
                continue

            case_f, doc, c, rel = target
            conf = c.setdefault("confidence", {})
            old_h, old_m = conf.get("hits", 0), conf.get("misdiagnoses", 0)

            # 来源 session 自证：如实记 self_resolved，**不计入 hits**（同一证据不数两次）。
            # 依据见 EV-2026-096：hits 的口径是「这条知识的消费者环境是否解决」。
            if outcome == "resolved" and is_self_settle(doc, case_id, sid, traces_dir):
                selfr = conf.get(SELF_RESOLVED_KEY) or {}
                old_s = selfr.get("count", 0)
                delta = (f"{rel}: self_resolved {old_s}→{old_s + 1}（来源 session 自证），"
                         f"hits 保持 {old_h}，outcome={outcome}")
                print(f"  [self] {delta}")
                all_diffs.append((case_f, doc, delta))
                if apply:
                    if write_self_resolved(case_f, sid, iso_week_now()):
                        print(f"  [apply] {rel}: 已写 confidence.{SELF_RESOLVED_KEY}")
                    else:
                        print(f"  [warn] {rel}: 未找到 confidence: 块——自证未写回（仅记录 diff）")
                continue

            if outcome == "resolved":
                conf["hits"] = old_h + 1
            else:
                conf["misdiagnoses"] = old_m + 1
            conf["last_hit"] = iso_week_now()  # 最近有反馈的 ISO 周（结算时的真实日期）
            delta = f"{rel}: hits {old_h}→{conf['hits']}, misdiagnoses {old_m}→{conf['misdiagnoses']}, outcome={outcome}"
            print(f"  [diff] {delta}")
            all_diffs.append((case_f, doc, delta))

            if apply:
                # 写回 case YAML：只替换 confidence 块内的值行（保持原格式/注释/字段顺序）
                text = case_f.read_text(encoding="utf-8")
                lines = text.split("\n")
                conf = c["confidence"]
                # 找 confidence: 行，其后 4 行是 hits/misdiagnoses/score/last_hit
                new_lines = list(lines)
                conf_idx = None
                for i, ln in enumerate(lines):
                    if ln.strip() == "confidence:":
                        conf_idx = i
                        break
                if conf_idx is None:
                    print(f"  [warn] {rel}: 未找到 confidence: 块——跳过写回（仅记录 diff）")
                else:
                    vals = {
                        "hits": str(conf.get("hits", 0)),
                        "misdiagnoses": str(conf.get("misdiagnoses", 0)),
                        "score": str(conf.get("score", 0.0)),
                        "last_hit": '"' + str(conf.get("last_hit", "")) + '"',
                    }
                    # confidence 块 = confidence: 行后到下一个非 4-空格缩进行前
                    j = conf_idx + 1
                    written = {}
                    while j < len(new_lines):
                        s = new_lines[j].strip()
                        if not s or s.startswith("#"):
                            j += 1
                            continue
                        # 只替换这 4 个字段；遇到其他字段行（保持原样）继续
                        for key in vals:
                            if s.startswith(key + ":"):
                                indent = new_lines[j][: len(new_lines[j]) - len(new_lines[j].lstrip())]
                                new_lines[j] = indent + key + ": " + vals[key]
                                written[key] = True
                        j += 1
                        # 离开 confidence 块：下一个非空非注释且不以 6 空格缩进的值行
                        if s and not s.startswith("#") and not new_lines[j].startswith("      "):
                            break
                    write_text_lf(case_f, "\n".join(new_lines) + "\n", encoding="utf-8")

        if apply:
            settled[sid] = {"events": h, "settled_at": iso_week_now()}
            state_path.parent.mkdir(parents=True, exist_ok=True)
            write_text_lf(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  [settled] {sid}（hash {h}）→ {state_path}")

    print(f"\n共 {len(all_diffs)} 条 confidence 变更。")
    if not apply:
        print("--dry-run（默认）：未写任何文件。确认后加 --apply 写回 case YAML，再走 knowledge_modification PR。")
    else:
        print("--apply：case YAML 已写回 + 结算游标已更新。请走 knowledge_modification PR 提交（脚本不改 git）。")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    default_state, where = resolve_default_state(Path.cwd())
    ap.add_argument("--state", default=str(default_state),
                    help=f"结算游标文件（默认落登记的共享运行时件：{default_state}；{where}）")
    ap.add_argument("--migrate-from", default="ingest-state.json",
                    help="游标文件不存在时，从这里迁移既有游标（默认 ingest-state.json）")
    ap.add_argument("--apply", action="store_true", help="写回 case YAML（默认 dry-run）")
    ap.add_argument("--root", default="knowledge", help="knowledge 根目录（默认 knowledge/；测试用副本）")
    args = ap.parse_args()
    settle(resolve_traces(Path.cwd()), Path(args.state), args.apply, Path(args.root),
           migrate_from=Path(args.migrate_from))


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
