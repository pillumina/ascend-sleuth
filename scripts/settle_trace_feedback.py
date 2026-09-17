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
# **hits 的口径澄清（EV-2026-097）**：hits 记的是「**有人报告这条 case 的 fix 在这个环境解决了**」，
#   不是「这条 case 被别的诊断引用了几次」。后者是另一件事（检索关联 + 该 session 又 resolved），
#   数据都在 traces 里，但**目前没有任何脚本产出它**——别把 hits 读成引用次数。
#   两者都影响候选排序，但语义不同：前者是现场有效性，后者是使用频度。
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


CURSOR_SCHEMA = 2   # v2：逐事件已落地记录（v1 = 整段 hash，见 _plan_cursor 的迁移分支）


def _ev_hash(ev) -> str:
    return hashlib.sha256(json.dumps(ev, sort_keys=True).encode()).hexdigest()[:16]


def _conf_of(case_f: Path):
    """重新读盘取 confidence（写回复核用）——不复用内存里的 doc，复核必须是独立读数。"""
    try:
        _, c, _ = load_case(case_f)
        return c.get("confidence") or {}
    except Exception:
        return None


def _write_conf_fields(case_f: Path, conf: dict) -> bool:
    """写回 confidence 块内的 hits / misdiagnoses / score / last_hit；返回**复核是否通过**。

    复核（EV-2026-109）：写完重新读盘，确认目标字段确实是新值。写回失败却照样推进游标，
    等于把这笔证据永久丢掉（下次不再重试）——这正是 VLLM-ASC-12430 自证丢失的成因。
    """
    text = case_f.read_text(encoding="utf-8")
    lines = text.split("\n")
    conf_idx = next((i for i, ln in enumerate(lines) if ln.strip() == "confidence:"), None)
    if conf_idx is None:
        return False
    vals = {
        "hits": str(conf.get("hits", 0)),
        "misdiagnoses": str(conf.get("misdiagnoses", 0)),
        "score": str(conf.get("score", 0.0)),
        "last_hit": '"' + str(conf.get("last_hit", "")) + '"',
    }
    new_lines = list(lines)
    j = conf_idx + 1
    while j < len(new_lines):
        s = new_lines[j].strip()
        if not s or s.startswith("#"):
            j += 1
            continue
        for key in vals:
            if s.startswith(key + ":"):
                indent = new_lines[j][: len(new_lines[j]) - len(new_lines[j].lstrip())]
                new_lines[j] = indent + key + ": " + vals[key]
        j += 1
        if s and not s.startswith("#") and not new_lines[j].startswith("      "):
            break
    write_text_lf(case_f, "\n".join(new_lines) + "\n", encoding="utf-8")

    back = _conf_of(case_f)
    if back is None:
        return False
    return (int(back.get("hits", 0)) == int(conf.get("hits", 0))
            and int(back.get("misdiagnoses", 0)) == int(conf.get("misdiagnoses", 0)))


def _self_resolved_landed(case_f: Path, sid: str) -> bool:
    back = _conf_of(case_f)
    if back is None:
        return False
    sr = back.get(SELF_RESOLVED_KEY) or {}
    return sid in (sr.get("examples") or [])


def _plan_cursor(prev: dict, cur_hashes: list, sid: str):
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


def settle(traces_dir: Path, state_path: Path, apply: bool, kb_root: Path = Path("knowledge"),
           migrate_from=None):
    state, migrated = load_cursors(state_path, migrate_from)
    # 结算游标 v2：{session_id: {"events": [hash...], "applied": [下标...], "settled_at": iso}}
    settled = state.setdefault("_trace_feedback", {})
    if migrated:
        print(f"[migrate] 从 {migrated} 迁入 {len(settled)} 条既有游标（防迁移后重复计数）\n")

    pending = []   # (sid, events, cur_hashes, todo)
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
        seen, applied, todo, problem = _plan_cursor(prev, cur_hashes, sid)
        if problem is not None:
            kind, detail = problem
            if kind == "legacy":
                if _v1_hash(events) == detail:
                    # 旧格式无法区分「已落地」与「当初被跳过」——保守视为已落地（不重放），
                    # 并明确提示：确有个案是这样丢的（VLLM-ASC-12430），可用 --audit 复核。
                    settled[sid] = {"schema": CURSOR_SCHEMA, "events": cur_hashes,
                                    "applied": list(range(len(cur_hashes))),
                                    "settled_at": prev.get("settled_at") or iso_week_now(),
                                    "note": "由 v1 游标迁移：旧格式不区分「已落地」与「跳过」"}
                    print(f"[migrate] {f.name}: v1 游标 → v2（视为已落地，不重放）；"
                          f"如需复核是否真有未落地项，跑 --audit")
                else:
                    print(f"[warn] {f.name}: v1 游标 hash 与当前事件不一致——无法判断哪些已落地，"
                          f"本轮跳过（不重放、不猜）。核对 case 后可删除该 session 的游标条目再结算")
                continue
            print(f"[warn] {f.name}: feedback 事件序列被改写（非追加）——本轮跳过（不重放、不猜）。"
                  f"若是重写历史，请核对 case 的 hits 后手工处理游标")
            continue
        if not todo:
            print(f"[skip] {f.name}: 已结算（{len(cur_hashes)} 条事件全部落地）")
            continue
        pending.append((sid, events, seen, applied, todo))

    if not pending:
        print("无未结算的 feedback 事件。")
        return

    print(f"发现 {len(pending)} 个 session 含待结算 feedback 事件。\n")
    all_diffs = []
    for sid, events, cur_hashes, applied, todo in pending:
        landed = set(applied)
        for i in todo:
            ev = events[i]
            case_id = ev["case"]
            outcome = ev["outcome"]
            if not case_id:
                print(f"[warn] {sid}: feedback 事件缺 case 字段——本次不落地，保持待结算"
                      f"（outcome={outcome}）")
                continue
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
                # 不推进该事件（EV-2026-109）：case 可能稍后才落 knowledge/，下次重试才拿得到
                print(f"[warn] {sid}: case {case_id} 未在 knowledge/ 找到——本次不落地、保持待结算"
                      f"（case 落库后重跑本脚本即会补上）")
                continue

            case_f, doc, c, rel = target
            conf = c.setdefault("confidence", {})
            old_h, old_m = conf.get("hits", 0), conf.get("misdiagnoses", 0)

            if outcome == "resolved" and is_self_settle(doc, case_id, sid, traces_dir):
                selfr = conf.get(SELF_RESOLVED_KEY) or {}
                old_s = selfr.get("count", 0)
                delta = (f"{rel}: self_resolved {old_s}→{old_s + 1}（来源 session 自证），"
                         f"hits 保持 {old_h}，outcome={outcome}")
                print(f"  [self] {delta}")
                all_diffs.append((case_f, doc, delta))
                if apply:
                    if not write_self_resolved(case_f, sid, iso_week_now()):
                        print(f"  [warn] {rel}: 自证写回失败（未找到 confidence: 块）"
                              f"——保持待结算，下次重试")
                        continue
                    if not _self_resolved_landed(case_f, sid):
                        print(f"  [warn] {rel}: 自证写回后复核不通过（读回未看到本 session）"
                              f"——保持待结算，下次重试")
                        continue
                    print(f"  [apply] {rel}: 已写 confidence.{SELF_RESOLVED_KEY}（复核通过）")
                landed.add(i)
                continue

            if outcome == "resolved":
                conf["hits"] = old_h + 1
            else:
                conf["misdiagnoses"] = old_m + 1
            conf["last_hit"] = iso_week_now()
            # 用 .get 取回写后的值：case 的 confidence 块可能只写了部分字段
            # （实测：缺 misdiagnoses 时改前的 f-string 直接 KeyError，整轮结算崩掉）
            delta = (f"{rel}: hits {old_h}→{conf.get('hits', old_h)}, "
                     f"misdiagnoses {old_m}→{conf.get('misdiagnoses', old_m)}, outcome={outcome}")
            print(f"  [diff] {delta}")
            all_diffs.append((case_f, doc, delta))
            if apply:
                if not _write_conf_fields(case_f, conf):
                    print(f"  [warn] {rel}: 写回后复核不通过（读回的 hits/misdiagnoses 与预期不符）"
                          f"——保持待结算，下次重试")
                    continue
                landed.add(i)

        if apply:
            settled[sid] = {"schema": CURSOR_SCHEMA, "events": cur_hashes,
                            "applied": sorted(landed), "settled_at": iso_week_now()}
            state_path.parent.mkdir(parents=True, exist_ok=True)
            write_text_lf(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
            left = len(cur_hashes) - len(landed)
            tail = f"，仍有 {left} 条未落地（下次重试）" if left else ""
            print(f"  [settled] {sid}（{len(landed)}/{len(cur_hashes)} 条已落地{tail}）→ {state_path}")

    print(f"\n共 {len(all_diffs)} 条 confidence 变更。")
    if not apply:
        print("--dry-run（默认）：未写任何文件。确认后加 --apply 写回 case YAML，再走 knowledge_modification PR。")
    else:
        print("--apply：case YAML 已写回 + 结算游标已更新。请走 knowledge_modification PR 提交（脚本不改 git）。")


def audit(traces_dir: Path, state_path: Path, kb_root: Path = Path("knowledge")) -> int:
    """只读复核：游标说"已结算"的事件，case 里看得见效果吗？（EV-2026-109）

    为什么需要：游标推进与写回落地是两件事，此前只记前者——一旦写回没落地，
    这笔证据永久不再重试，而任何读数都看不出来（VLLM-ASC-12430 的自证就是这样丢的）。
    本命令把两者对上：对每个已结算 session 的每条 feedback 事件，检查 case 侧应有的痕迹。

    强度如实标注：这是**弱信号**（检查"有没有"而非"几条"）——同一 case 的 hits 可能来自
    另一台机器的结算，故 hits ≥ 1 不能证明本 session 的这笔一定落过；但"完全没有痕迹"
    足以说明这笔大概没落。v1 游标迁入的 session 同样适用（它们的落地情况本就未知）。
    """
    state, _ = load_cursors(state_path)
    settled = state.get("_trace_feedback") or {}
    if not settled:
        print("settle --audit：游标为空（尚未结算过任何 session）——无可复核项")
        return 0

    conf_by_case, loc = {}, {}
    for case_f in kb_root.rglob("*.yaml"):
        if "_archive" in str(case_f) or case_f.name == "_index.yaml":
            continue
        try:
            doc, c, rel = load_case(case_f)
        except Exception:
            continue
        conf_by_case[c.get("id")] = (c.get("confidence") or {}, doc)
        loc[c.get("id")] = rel

    bad, checked, no_trace = [], 0, []
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
            if not cid or cid not in conf_by_case:
                bad.append(f"{sid} → case {cid or '(缺 case 字段)'}: 游标已结算，但该 case 不在 "
                           f"knowledge/（无法复核）")
                continue
            conf, doc = conf_by_case[cid]
            rel = loc[cid]
            if ev["outcome"] == "resolved" and is_self_settle(doc, cid, sid, traces_dir):
                sr = conf.get(SELF_RESOLVED_KEY) or {}
                if sid not in (sr.get("examples") or []):
                    bad.append(f"{sid} → {rel}: 自证未落地——confidence.self_resolved 里没有本 session")
            elif ev["outcome"] == "resolved":
                if not conf.get("hits"):
                    bad.append(f"{sid} → {rel}: resolved 未落地——confidence.hits 为 0")
            else:
                if not conf.get("misdiagnoses"):
                    bad.append(f"{sid} → {rel}: {ev['outcome']} 未落地——confidence.misdiagnoses 为 0")

    print(f"settle --audit：复核 {len(settled)} 个已结算 session、{checked} 条 feedback 事件"
          f"（弱信号口径：查「有没有痕迹」，不查条数——同一 case 的痕迹可能来自另一台机器）")
    if no_trace:
        print(f"  · {len(no_trace)} 个 session 的本机无 trace 文件（跨机结算或 trace 已清理）——无法复核："
              + "、".join(no_trace[:5]) + ("…" if len(no_trace) > 5 else ""))
    if bad:
        print(f"settle --audit：{len(bad)} 处「游标已结算但 case 无对应效果」——这些证据需要重跑结算：")
        for b in bad:
            print(f"  - {b}")
        print("  处置：删掉该 session 在游标里的条目（或把 applied 清空）后重跑本脚本（--apply）")
        return 1
    print("settle --audit：无「已结算但无效果」的条目")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    default_state, where = resolve_default_state(Path.cwd())
    ap.add_argument("--state", default=str(default_state),
                    help=f"结算游标文件（默认落登记的共享运行时件：{default_state}；{where}）")
    ap.add_argument("--migrate-from", default="ingest-state.json",
                    help="游标文件不存在时，从这里迁移既有游标（默认 ingest-state.json）")
    ap.add_argument("--apply", action="store_true", help="写回 case YAML（默认 dry-run）")
    ap.add_argument("--audit", action="store_true",
                    help="只读复核：游标已结算的事件在 case 里有没有痕迹（不改任何文件）")
    ap.add_argument("--root", default="knowledge", help="knowledge 根目录（默认 knowledge/；测试用副本）")
    args = ap.parse_args()

    traces = resolve_traces(Path.cwd())
    if args.audit:
        raise SystemExit(audit(traces, Path(args.state), Path(args.root)))
    settle(traces, Path(args.state), args.apply, Path(args.root),
           migrate_from=Path(args.migrate_from))


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
