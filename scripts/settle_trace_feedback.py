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

TRACES_DIR = Path("traces")


def iso_week_now():
    """当前 ISO 周（如 2026-W36），last_hit 用——与 metrics 周批节律一致。"""
    from datetime import date
    d = date.today()
    return f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"


def load_case(path: Path):
    """读 case YAML，返回 (doc, case, rel_path)。"""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc, doc["cases"][0], str(path)


def settle(traces_dir: Path, state_path: Path, apply: bool, kb_root: Path = Path("knowledge")):
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"sources": {}}
    # 结算游标：sources.<key>.trace_feedback = {session_id: {"events": hash, "settled_at": iso}}
    settled = state.setdefault("sources", {}).setdefault("_trace_feedback", {})

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
                    case_f.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        if apply:
            settled[sid] = {"events": h, "settled_at": "2026-08-31"}
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [settled] {sid}（hash {h}）→ ingest-state.json")

    print(f"\n共 {len(all_diffs)} 条 confidence 变更。")
    if not apply:
        print("--dry-run（默认）：未写任何文件。确认后加 --apply 写回 case YAML，再走 knowledge_modification PR。")
    else:
        print("--apply：case YAML 已写回 + 结算游标已更新。请走 knowledge_modification PR 提交（脚本不改 git）。")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", default="ingest-state.json", help="结算状态文件（幂等游标）")
    ap.add_argument("--apply", action="store_true", help="写回 case YAML（默认 dry-run）")
    ap.add_argument("--root", default="knowledge", help="knowledge 根目录（默认 knowledge/；测试用副本）")
    args = ap.parse_args()
    settle(TRACES_DIR, Path(args.state), args.apply, Path(args.root))


if __name__ == "__main__":
    main()
