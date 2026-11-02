#!/usr/bin/env python3
# sediment_batch.py —— 把 traces/ 里「结论已经有了、但没人回头沉淀」的单一次捞出来
#
# 为什么需要它：诊断收尾把结论写进 trace（`report_file` 与 `sediment_candidates`），沉淀却
#   按单触发，于是"有报告、有候选、没入库"的单会一直堆着（实测 20 单里 7 单是这种）。
#   这是只读清点 + 一次批量入口，不是新的知识写入者：起草仍由 to-postmortem 做。
#
# 它不做三件事（每件都有各自的主人，混进来就会写出两处不一致的读数）：
#   - 不改 `status`：那是"这单还管不管"，诊断侧的事；
#   - 不改 `feedback.outcome`：那是"给出去的 fix 行不行"，只有现场回报能改；
#   - 不判断"该不该入库"：那是知识整理（knowledge-groom）的活。这里只回答"哪些单手里有料、
#     还没沉淀"，把选择权交回去。
#
# 「可沉淀」的判据（任一成立即可，都是 trace 里已经存在的事实，不做推断）：
#   - `status` 是终态（resolved / escalated / archived）：诊断自己说收尾了；
#   - 有 `report_file`：步骤 6 跑过，说明结论已经写成人读报告；
#   - 有 `sediment_candidates`：agent 在收尾时已经列出"这单能沉淀什么"。
#   已经沉淀过的（`sedimented.state` 是 submitted / knowledge / archived）不进清单。
#
# 同一问题的多条 session 归一组（判据：命中同一个 case id；没有 case 时按 session_id 的前三段，
#   如 `2026-08-30-10521-el0008` 与 `2026-08-30-10521-evidence-demo` → `2026-08-30-10521`）。
#   按会话逐条问会让人在脑子里做聚类，成本翻倍；按组问才是人回忆的粒度。
#
# 用法：
#   python3 scripts/sediment_batch.py                 只读：打印可沉淀的组
#   python3 scripts/sediment_batch.py --all           连"无可沉淀"与"已沉淀"的组一起打印
#   python3 scripts/sediment_batch.py --json          机器可读（agent 起草时读它，含候选正文）
#   python3 scripts/sediment_batch.py --mark-submitted <session> [<session>...] \
#           [--inbox-path <相对仓库根的草稿路径>]     草稿真的落到 inbox 之后回写 sedimented.state
#   --dry-run（默认，只对 --mark-submitted 有意义）：打印将要写的内容，不写文件
#   --apply：真写回 trace
#
# 退出码：0 = 成功（含"没有可沉淀的单"）；2 = 参数或环境不可用（trace 读不出、写回校验不通过）。

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from exec_log_path import resolve_traces
from _trace_state import is_terminal as _is_terminal, load_vocab as _load_vocab
from _stdio import write_text_lf

# 终态判定改由判据库给出（`trace-status.yaml` 是唯一来源）；保留常量名给旧调用点。
TERMINAL = {s["value"] for s in _load_vocab(__import__("pathlib").Path(__file__).resolve().parents[1])["statuses"]
            if s["terminal"]}
DONE_SEDIMENT = {"submitted", "knowledge", "archived"}
REAL_CASE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
PLACEHOLDER = re.compile(r"pending-investigation|^$")
SED_LINE = re.compile(r"^sedimented:[^\n]*$", re.M)
SED_STATE_LINE = re.compile(r"^(\s+)state:\s*\S+\s*$", re.M)


def load_trace(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None


def group_key(doc: dict, sid: str) -> str:
    """同一问题的多条 session 归一组。

    判据只用两样已有事实，不做语义聚类：
      1. 命中了同一个 case id → 同一组；
      2. 否则看 session 名：`<日期>-<issue 号>-<短名>` 这种形态里，日期之后第一个纯数字段就是
         issue 号（如 `2026-08-30-10521-el0008` 与 `2026-08-30-10521-evidence-demo` → 同一组）。
         日期之后没有数字段的名字（如 `2026-09-21-upstream-vllm-ascend-sweep`）各自成组——
         按名字前缀合会把不同问题并到一起。
    """
    active = doc.get("active_case")
    if active and REAL_CASE.match(str(active).strip()):
        return "case:" + str(active).strip()
    parts = sid.split("-")
    if len(parts) >= 4 and all(re.fullmatch(r"20\d\d|\d\d", x) for x in parts[:3]):
        for seg in parts[3:]:
            if seg.isdigit():
                return "session:" + "-".join(parts[:3]) + "-" + seg
    return "session:" + sid


def sed_state(doc: dict) -> str:
    sed = doc.get("sedimented")
    if isinstance(sed, dict):
        return str(sed.get("state") or "none")
    if isinstance(sed, str) and sed.strip():
        return sed.strip()
    return "none"


def why_actionable(doc: dict) -> str:
    st = str(doc.get("status") or "unknown")
    report = doc.get("report_file")
    cands = doc.get("sediment_candidates") or []
    bits = []
    if st in TERMINAL:
        bits.append(f"已收尾（{st}）")
    if report:
        bits.append("有报告")
    if cands:
        bits.append(f"{len(cands)} 条候选")
    return "、".join(bits)


def collect(traces_dir: Path):
    groups = {}
    unreadable = []
    for path in sorted(Path(traces_dir).glob("*.yaml")):
        sid = path.stem
        doc = load_trace(path)
        if doc is None:
            unreadable.append(sid)
            continue
        if not doc.get("session_id"):
            doc = dict(doc, session_id=sid)
        key = group_key(doc, sid)
        g = groups.setdefault(key, {
            "key": key, "sessions": [], "candidates": [], "reports": [],
            "statuses": set(), "states": set(), "updated": "",
        })
        g["sessions"].append(sid)
        g["candidates"].extend(doc.get("sediment_candidates") or [])
        if doc.get("report_file"):
            g["reports"].append({"session": sid, "file": str(doc["report_file"])})
        g["statuses"].add(str(doc.get("status") or "unknown"))
        g["states"].add(sed_state(doc))
        upd = str(doc.get("updated_at") or "")
        if upd > g["updated"]:
            g["updated"] = upd
        g.setdefault("docs", []).append({
            "session": sid, "status": doc.get("status"),
            "report_file": doc.get("report_file"),
            "active_case": doc.get("active_case"),
            "sediment_candidates": doc.get("sediment_candidates") or [],
            "why": why_actionable(doc),
        })
    rows = []
    for g in groups.values():
        has_material = bool(g["reports"] or g["candidates"])
        actionable = has_material and not (g["states"] & DONE_SEDIMENT)
        g["sedimented"] = sorted(g["states"])
        g["statuses"] = sorted(g["statuses"])
        rows.append({
            "key": g["key"], "sessions": g["sessions"], "statuses": g["statuses"],
            "sedimented": g["sedimented"], "reports": g["reports"],
            "candidates": g["candidates"], "docs": g["docs"],
            "updated": g["updated"], "actionable": actionable,
            "why": "；".join(d["why"] for d in g["docs"] if d["why"]),
        })
    rows.sort(key=lambda r: r["updated"], reverse=True)
    rows.sort(key=lambda r: not r["actionable"])
    return rows, unreadable


def render_text(rows, unreadable, show_all: bool):
    sel = rows if show_all else [r for r in rows if r["actionable"]]
    out = []
    if unreadable:
        out.append(f"[warn] {len(unreadable)} 份 trace 解析失败，未计入：" + "、".join(unreadable[:5]))
    if not sel:
        out.append("没有可沉淀的单：有结论的都沉淀过了，或者结论还没落到报告与候选上。")
        return "\n".join(out)
    out.append(f"可沉淀 {len([r for r in sel if r['actionable']])} 组 / 共 {len(sel)} 组"
               + ("（含已沉淀与无可沉淀）" if show_all else ""))
    out.append("")
    for i, r in enumerate(sel, 1):
        flag = "可沉淀" if r["actionable"] else ("已沉淀" if set(r["sedimented"]) - {"none"} else "无素材")
        why = r["why"] or "—"
        if not r["actionable"] and not (set(r["sedimented"]) - {"none"}):
            why += "（没有报告与候选，起草前得先读 trace 事件）"
        out.append(f"[{i}] {flag}  {why}")
        out.append(f"    session: {' '.join(r['sessions'])}")
        out.append(f"    状态: {'/'.join(r['statuses'])}   沉淀: {'/'.join(r['sedimented'])}   更新: {r['updated'][:16]}")
        for rep in r["reports"]:
            out.append(f"    报告: {rep['file']}")
    act = [r for r in sel if r["actionable"]]
    if act:
        ids = [s for r in act for s in r["sessions"]]
        out.append("")
        out.append("下一步（一次交给 to-postmortem，它按单起草、批量确认命名空间）：")
        out.append("  用 /skill:to-postmortem 批量沉淀这些 session：" + "、".join(ids))
        out.append("  草稿落 inbox 后回写：python3 scripts/sediment_batch.py --mark-submitted "
                   + " ".join(ids) + " --inbox-path <草稿路径> --apply")
    return "\n".join(out)


# ── 回写 sedimented.state（动作发生时写；零推断） ─────────────────────────────
def rewrite_sedimented(text: str, inbox_path: str):
    """把顶层 `sedimented` 改成 submitted。返回 (新文本, 是否改过)。

    只做定点替换，不整份 dump：trace 是 agent 写的 YAML，带注释与块标量（`>`/`|`），
    yaml.safe_dump 会把它们全部抹平——回写一次就毁掉一份现场记录。
    """
    val = f'sedimented: {{state: submitted, inboxPath: "{inbox_path}"}}' if inbox_path else \
          "sedimented: {state: submitted}"
    m = SED_LINE.search(text)
    if m:
        line = m.group(0)
        if line.strip() == "sedimented:":
            # 块写法：只改块里的 state 那一行，保留 case_id / inbox_path 等其余键
            head = text[:m.end()]
            tail = text[m.end():]
            sm = SED_STATE_LINE.search(tail)
            if sm and sm.start() < (tail.find("\n" + "\n") if "\n\n" in tail else len(tail)):
                indent = sm.group(1)
                new_tail = tail[:sm.start()] + f"{indent}state: submitted" + tail[sm.end():]
                return head + new_tail, True
            return text, False
        return text[:m.start()] + val + text[m.end():], True
    sep = "" if text.endswith("\n") else "\n"
    return text + sep + val + "\n", True


def mark_submitted(traces_dir: Path, sessions, inbox_path: str, apply: bool):
    written, skipped, failed = [], [], []
    for sid in sessions:
        p = Path(traces_dir) / (sid + ".yaml")
        if not p.exists():
            failed.append((sid, "trace 不存在"))
            continue
        before = p.read_text(encoding="utf-8")
        after, changed = rewrite_sedimented(before, inbox_path)
        if not changed:
            skipped.append((sid, "没找到可改的 sedimented 块（块写法里缺 state 行）"))
            continue
        try:
            doc = yaml.safe_load(after) or {}
        except Exception as exc:
            failed.append((sid, f"改完解析失败：{exc}"))
            continue
        if sed_state(doc) != "submitted":
            failed.append((sid, "改完读回来不是 submitted，按未落地处理"))
            continue
        if apply:
            write_text_lf(p, after)
        written.append(sid)
    return written, skipped, failed


def main(argv=None):
    ap = argparse.ArgumentParser(description="清点 traces/ 里可沉淀但未沉淀的单，并可回写沉淀状态")
    ap.add_argument("--root", default=".", help="检出目录（默认当前目录）")
    ap.add_argument("--all", action="store_true", help="连已沉淀与无可沉淀的组一起打印")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--mark-submitted", nargs="+", metavar="SESSION", help="把这些 session 的 sedimented.state 置 submitted")
    ap.add_argument("--inbox-path", default="", help="草稿相对仓库根的路径（写进 sedimented.inboxPath）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件（默认）")
    ap.add_argument("--apply", action="store_true", help="真写回 trace")
    args = ap.parse_args(argv)

    root = Path(args.root)
    traces_dir = resolve_traces(root)

    if args.mark_submitted:
        written, skipped, failed = mark_submitted(traces_dir, args.mark_submitted, args.inbox_path, args.apply)
        for sid in written:
            print(("[写入] " if args.apply else "[将写] ") + sid)
        for sid, why in skipped:
            print(f"[跳过] {sid}：{why}")
        for sid, why in failed:
            print(f"[失败] {sid}：{why}")
        if not args.apply:
            print("（默认只打印；加 --apply 才写回 trace）")
        return 2 if failed else 0

    rows, unreadable = collect(traces_dir)
    if args.json:
        print(json.dumps({
            "traces_dir": str(traces_dir),
            "groups": rows,
            "unreadable": unreadable,
            "actionable": [r["key"] for r in rows if r["actionable"]],
        }, ensure_ascii=False, indent=2))
    else:
        print(render_text(rows, unreadable, args.all))
    return 0


if __name__ == "__main__":
    sys.exit(main())
