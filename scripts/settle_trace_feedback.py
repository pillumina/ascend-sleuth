#!/usr/bin/env python3
# settle_trace_feedback.py —— 把 traces/*.yaml 的 feedback 事件确定性结算成**条目使用记录的计数行**
#
# 目的：闭合 case 层学习环（与 reference 层 R6 对称）——trace 里记了
#   {action: feedback, case: <case-id>, outcome: resolved|not_resolved|partial}，
#   但此前没有任何机制把它累积进一个可上仓、可聚合的地方。
#
# **它不再改知识条目**（这是与旧版最大的区别）：计数过去写回 case 的 `confidence` 块，
#   于是「观测」与「知识本体」混在一起——结算一次就改一次知识文件，而 `hits` 与记录里的
#   `resolved` 是同一个事实的两处表达，迟早对不上，且对不上时没有判据说该信哪一处。
#   现在结算只往 `metrics/entry-activity.d/<周>.yaml` 追加计数行；案例文件不因观测而改。
#   分数由记录派生、只落在索引生成物里。
#
# 结算规则（2026-08-31 设计确认——用户/owner 决策，口径不变）：
#   - **只有 feedback.resolved 才 resolved += 1**——命中（hit 事件）是系统检索行为，
#     不代表 case 有效；可信反馈（用户确认「这个诊断解决了我问题」）才是置信度信号。
#   - feedback.not_resolved / partial → misdiagnosed += 1（负信号，计入误诊）
#   - 来源 session 自己的 resolve（自证）→ self_resolved += 1，**不计入 resolved**
#     （自证是「来源会话自己回报的那个判断」，与外部独立确认不是同一种证据）
#   - `last_hit` 不在这里写：它由记录里最近一次 resolved / misdiagnosed 的运行所处的周推出
#
# 幂等：结算状态记录在 `.settle-state.json` 的 `_trace_feedback` 下
#   （本机运行时件，锚主检出、gitignored——进 git 会让每次结算都变成一次 PR）。
#   已结算的 session_id + feedback 事件列表 hash 不再重复累积。
#
# 用法（groom 周批，串行）：
#   python3 scripts/settle_trace_feedback.py [--dry-run] [--apply]
#   --dry-run（默认）：只输出将要写的行，不写任何文件
#   --apply：追加进记录源文件 + 更新游标
#
# 退出码：0 = 成功；1 = --audit 发现「已结算但无效果」；2 = 参数或环境不可用。

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from _stdio import write_text_lf
from exec_log_path import resolve_rel, resolve_traces
import entry_activity as ea

TRACES_DIR = Path("traces")   # 相对名；实际取哪一份由 resolve_traces() 决定（主检出共享侧）


def iso_week_now():
    """当前 ISO 周（如 2026-W36）——与 metrics 周批节律一致。"""
    from datetime import date
    return ea.iso_week(date.today())


def load_case(path: Path):
    """读 case YAML，返回 (doc, case, rel_path)。"""
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc, doc["cases"][0], str(path)

# 结算游标：登记的共享运行时件（锚主检出、跨 worktree 共读共写、gitignored）。
# 为什么不写 ingest-state.json：那份是摄取台账（要跨机同步故 tracked、走 PR）；
# 游标只是本地幂等状态，进 git 会让每次结算都变成一次 PR（见 EV-2026-096）。
SETTLE_STATE_REL = Path(".settle-state.json")
LEGACY_CURSOR_KEYS = ("_trace_feedback", "_s2_feedback")


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

    无法判定时退回原行为（计入 resolved），这是刻意的保守取舍：宁可少识别自证，不误判独立命中。
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


CURSOR_SCHEMA = 3   # v3：逐事件落地记录 + 落地去向；v2 = 整段索引，v1 = 整段 hash


def _ev_hash(ev) -> str:
    return hashlib.sha256(json.dumps(ev, sort_keys=True).encode()).hexdigest()[:16]


def _plan_cursor(prev: dict, cur_hashes: list):
    """→ (seen, applied:set, todo:list, problem:str|None)

    - `seen`：上一轮见到的事件 hash 序列；`applied`：其中已落地的下标。
    - `todo`：本轮要处理的下标 = 新追加的事件 + 上次未落地的重试项。
    - 序列被**改写**（非追加）时返回 problem——不重放、不猜测（重放会虚增，视为已落地会丢证据）。
    - 旧格式（整段 hash 字符串）保守迁移：hash 一致 → 视为全部已落地（不重放）；不一致 → problem。
    """
    old = prev.get("events")
    if isinstance(old, str):                                     # v1 游标（整段 hash）
        return None, None, None, ("legacy", old)
    seen = list(old or [])
    applied = set(int(i) for i in (prev.get("applied") or []))
    if cur_hashes[: len(seen)] != seen:
        return None, None, None, ("rewritten", seen)
    todo = [i for i in range(len(seen)) if i not in applied] + list(range(len(seen), len(cur_hashes)))
    return cur_hashes, applied, todo, None


def _v1_hash(events: list) -> str:
    return hashlib.sha256(json.dumps(events, sort_keys=True).encode()).hexdigest()[:16]


def _case_rows_from_cursor(cursor: dict):
    """游标里已落地的事件 → {case_id: {resolved, misdiagnosed, self_resolved}}（复核用）。

    这在跨机时是唯一凭据：记录行写在**执行结算的那台机器**的源文件里，本机复核对不上。
    """
    out = {}
    for rec in (cursor or {}).values():
        for d in (rec.get("landed") or []):
            if not isinstance(d, dict) or not d.get("case"):
                continue
            r = out.setdefault(d["case"], {"resolved": 0, "misdiagnosed": 0, "self_resolved": 0})
            if d.get("self"):
                r["self_resolved"] += 1
            elif d.get("outcome") == "resolved":
                r["resolved"] += 1
            else:
                r["misdiagnosed"] += 1
    return out


def _find_case(kb_root: Path, case_id: str):
    for case_f in kb_root.rglob("*.yaml"):
        if "_archive" in str(case_f) or case_f.name == "_index.yaml":
            continue
        try:
            doc, c, rel = load_case(case_f)
        except Exception:
            continue
        if c.get("id") == case_id:
            return case_f, doc, c, rel
    return None


def settle(traces_dir: Path, state_path: Path, apply: bool, root: Path,
           kb_root: Path = Path("knowledge"), migrate_from=None, run: str | None = None) -> int:
    state, migrated = load_cursors(state_path, migrate_from)
    # 结算游标 v3：{session_id: {"events": [hash...], "applied": [下标...],
    #                            "landed": [{case, outcome, self}...], "settled_at": iso}}
    settled = state.setdefault("_trace_feedback", {})
    if migrated:
        print(f"[migrate] 从 {migrated} 迁入 {len(settled)} 条既有游标（防迁移后重复计数）\n")

    pending = []   # (sid, events, cur_hashes, applied, todo)
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
        cur_hashes = [_ev_hash(e) for e in events]
        prev = settled.get(sid) or {}
        seen, applied, todo, problem = _plan_cursor(prev, cur_hashes)
        if problem is not None:
            kind, detail = problem
            if kind == "legacy":
                if _v1_hash(events) == detail:
                    # 旧格式无法区分「已落地」与「当初被跳过」——保守视为已落地（不重放），
                    # 并明确提示：确有个案是这样丢的（VLLM-ASC-12430），可用 --audit 复核。
                    settled[sid] = {"schema": CURSOR_SCHEMA, "events": cur_hashes,
                                    "applied": list(range(len(cur_hashes))), "landed": [],
                                    "settled_at": prev.get("settled_at") or iso_week_now(),
                                    "note": "由 v1 游标迁移：旧格式不区分「已落地」与「跳过」"}
                    print(f"[migrate] {f.name}: v1 游标 → v{CURSOR_SCHEMA}（视为已落地，不重放）；"
                          f"如需复核是否真有未落地项，跑 --audit")
                else:
                    print(f"[warn] {f.name}: v1 游标 hash 与当前事件不一致——无法判断哪些已落地，"
                          f"本轮跳过（不重放、不猜）。核对记录后可删该 session 的游标条目再结算")
                continue
            print(f"[warn] {f.name}: feedback 事件序列被改写（非追加）——本轮跳过（不重放、不猜）。"
                  f"若是重写历史，请核对记录里的计数后手工处理游标")
            continue
        if not todo:
            print(f"[skip] {f.name}: 已结算（{len(cur_hashes)} 条事件全部落地）")
            continue
        pending.append((sid, events, seen, applied, todo))

    if not pending:
        print("无未结算的 feedback 事件。")
        return 0

    print(f"发现 {len(pending)} 个 session 含待结算 feedback 事件。\n")
    run_id = run or ea.now_run()
    counts, landed_notes, sessions_touched = {}, [], set()
    for sid, events, cur_hashes, applied, todo in pending:
        landed = set(applied)
        rec = settled.setdefault(sid, {})
        rec.setdefault("landed", [])
        for i in todo:
            ev = events[i]
            case_id = ev["case"]
            outcome = ev["outcome"]
            if not case_id:
                print(f"[warn] {sid}: feedback 事件缺 case 字段——本次不落地，保持待结算"
                      f"（outcome={outcome}）")
                continue
            target = _find_case(kb_root, case_id)
            if not target:
                # 不推进该事件：case 可能稍后才落 knowledge/，下次重试才拿得到
                print(f"[warn] {sid}: case {case_id} 未在 knowledge/ 找到——本次不落地、保持待结算"
                      f"（case 落库后重跑本脚本即会补上）")
                continue

            _case_f, doc, _c, rel = target
            is_self = outcome == "resolved" and is_self_settle(doc, case_id, sid, traces_dir)
            slot = counts.setdefault(case_id, {"resolved": 0, "misdiagnosed": 0, "self_resolved": 0})
            if is_self:
                slot["self_resolved"] += 1
                print(f"  [self] {sid} → {rel}: self_resolved += 1（来源 session 自证），"
                      f"resolved 不变，outcome={outcome}")
            elif outcome == "resolved":
                slot["resolved"] += 1
                print(f"  [diff] {sid} → {rel}: resolved += 1，outcome={outcome}")
            else:
                slot["misdiagnosed"] += 1
                print(f"  [diff] {sid} → {rel}: misdiagnosed += 1，outcome={outcome}")
            landed_notes.append((sid, case_id, outcome, is_self))
            rec["landed"].append({"case": case_id, "outcome": outcome, "self": is_self,
                                  "run": run_id})
            landed.add(i)
            sessions_touched.add(sid)

        if apply:
            settled[sid] = {"schema": CURSOR_SCHEMA, "events": cur_hashes,
                            "applied": sorted(landed), "landed": rec.get("landed") or [],
                            "settled_at": iso_week_now()}

    dep = ea.deployment(root)
    rows = []
    for cid in sorted(counts):
        rows.append({"run": run_id, "deployment": dep, "checkout": ea.checkout_rev(root),
                     "kb_rev": ea.kb_rev(root), "sessions": len(sessions_touched),
                     "kind": "case", "id": cid,
                     "selected": 0, "loaded": 0, "excluded": 0, **counts[cid]})
    if rows:
        print(f"\n共 {len(landed_notes)} 条反馈事件、{len(rows)} 个 case 的计数变更。")
        for r in rows:
            print("  " + ea.format_row(r))
    else:
        print("\n没有可落地的计数（事件都缺 case，或 case 还没落库）——"
              "游标照旧记录本轮看到的事件，下次重跑时重试那些未落地的。")
    if not apply:
        print("\n--dry-run（默认）：未写任何文件。确认后加 --apply 追加进记录源文件。")
        return 0

    # 游标**即使一行都没写也要落**：它记的是「这一轮看到了哪些事件」，
    # 不落的话下一轮会把同一批未落地事件当成全新事件（事件序列被改写也就无从判断）。
    f = None
    if rows:
        week = ea.week_of_run(run_id)
        if week is None:
            print(f"run {run_id!r} 归不了周——拒绝写入")
            return 2
        f = ea.append_rows(root, week, rows)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if f:
        print(f"\n[settled] 已追加 {len(rows)} 行 → {f}")
    print(f"[settled] 结算游标已更新 → {state_path}")
    print("接着跑 python3 scripts/trace_entry_activity.py --apply 汇总本轮诊断，"
          "再跑 python3 scripts/build_entry_activity.py 重建生成物。")
    return 0


def audit(traces_dir: Path, state_path: Path, root: Path) -> int:
    """只读复核：游标说「已结算」的事件，记录里看得见效果吗？

    为什么需要：游标推进与落地是两件事，此前只记前者——一旦落地没发生，这笔证据永久不再重试，
    而任何读数都看不出来（VLLM-ASC-12430 的自证就是这样丢的）。本命令把两者对上：对每个已结算
    session 的每条 feedback 事件，检查记录源文件里有没有对应的计数，或搬运行有没有带上它。

    强度如实标注：这是**弱信号**（检查「有没有」而非「几条」）——同一 case 的计数可能来自
    另一台机器的结算，故 `resolved ≥ 1` 不能证明本 session 的这笔一定落过；但「完全没有痕迹」
    足以说明这笔大概没落。v1 游标迁入的 session 同样适用（它们的落地情况本就未知）。
    """
    state, _ = load_cursors(state_path)
    settled = state.get("_trace_feedback") or {}
    if not settled:
        print("settle --audit：游标为空（尚未结算过任何 session）——无可复核项")
        return 0

    rows, _problems = ea.read_source(root)
    baseline = {str(r.get("id")) for r in rows if r.get("kind") == "baseline"}
    landed = {}
    for r in rows:
        if r.get("kind") != "case":
            continue
        cur = landed.setdefault(str(r.get("id")), {"resolved": 0, "misdiagnosed": 0, "self_resolved": 0})
        for k in cur:
            cur[k] += int(r.get(k, 0) or 0)
    # 游标里记的落地去向也算一处痕迹：记录行写在**执行结算的那台机器**的源文件里，
    # 跨机复核时它看不到那份文件，游标里的 landed 是唯一的凭据。
    from_cursor = _case_rows_from_cursor(settled)

    bad, checked, no_trace = [], 0, []
    kb_root = Path(root) / "knowledge"
    for sid in sorted(settled):
        tf = traces_dir / f"{sid}.yaml"
        if not tf.exists():
            no_trace.append(sid)
            continue
        try:
            st = yaml.safe_load(tf.read_text(encoding="utf-8")) or {}
        except Exception as e:
            bad.append(f"{sid}: trace 解析失败（{e}）——无法复核")
            continue
        events = [{"case": ev.get("case"), "outcome": ev.get("outcome")}
                  for ev in (st.get("trace") or [])
                  if ev.get("action") == "feedback"
                  and ev.get("outcome") in ("resolved", "not_resolved", "partial")]
        for ev in events:
            checked += 1
            cid = ev["case"]
            if not cid:
                bad.append(f"{sid} → (缺 case 字段): 游标已结算，但事件没写 case（无法复核）")
                continue
            if cid in baseline:
                continue
            seen = landed.get(cid) or from_cursor.get(cid)
            want_self = False
            tgt = _find_case(kb_root, cid)
            if tgt and ev["outcome"] == "resolved":
                want_self = is_self_settle(tgt[1], cid, sid, traces_dir)
            if want_self:
                if not (seen and seen.get("self_resolved")):
                    bad.append(f"{sid} → {cid}: 自证未落地——记录里没有 self_resolved 计数")
            elif ev["outcome"] == "resolved":
                if not (seen and seen.get("resolved")):
                    bad.append(f"{sid} → {cid}: resolved 未落地——记录里没有 resolved 计数")
            elif not (seen and seen.get("misdiagnosed")):
                bad.append(f"{sid} → {cid}: {ev['outcome']} 未落地——记录里没有 misdiagnosed 计数")

    print(f"settle --audit：复核 {len(settled)} 个已结算 session、{checked} 条 feedback 事件"
          f"（弱信号口径：查「有没有痕迹」，不查条数——同一 case 的痕迹可能来自另一台机器）")
    if no_trace:
        print(f"  · {len(no_trace)} 个 session 的本机无 trace 文件（跨机结算或 trace 已清理）——无法复核："
              + "、".join(no_trace[:5]) + ("…" if len(no_trace) > 5 else ""))
    if bad:
        print(f"settle --audit：{len(bad)} 处「游标已结算但记录无对应计数」——这些证据需要重跑结算：")
        for b in bad:
            print(f"  - {b}")
        print("  处置：删掉该 session 在游标里的条目（或把 applied 清空）后重跑本脚本（--apply）")
        return 1
    print("settle --audit：无「已结算但无效果」的条目")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="把 traces 的 feedback 事件结算成条目使用记录的计数行")
    default_state, where = resolve_default_state(Path.cwd())
    ap.add_argument("--state", default=str(default_state),
                    help=f"结算游标文件（默认落登记的共享运行时件：{default_state}；{where}）")
    ap.add_argument("--migrate-from", default="ingest-state.json",
                    help="游标文件不存在时，从这里迁移既有游标（默认 ingest-state.json）")
    ap.add_argument("--apply", action="store_true", help="追加进记录源文件（默认 dry-run）")
    ap.add_argument("--audit", action="store_true",
                    help="只读复核：游标已结算的事件在记录里有没有痕迹（不改任何文件）")
    ap.add_argument("--root", default=None, help="检出根（默认：脚本上两级）")
    ap.add_argument("--traces-dir", default=None, help="显式指定 traces/（默认解析到主检出）")
    ap.add_argument("--run", default=None, help="本次运行的标识（默认取当前时间）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    traces = Path(args.traces_dir).resolve() if args.traces_dir else resolve_traces(root)
    if args.audit:
        raise SystemExit(audit(traces, Path(args.state), root))
    raise SystemExit(settle(traces, Path(args.state), args.apply, root,
                            kb_root=root / "knowledge",
                            migrate_from=Path(args.migrate_from), run=args.run))


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
