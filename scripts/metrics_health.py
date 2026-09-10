#!/usr/bin/env python3
# metrics_health.py —— 指标闭环体检（新鲜度 / 越界 / 可解读性）
#
# 为什么需要（2026-09-10 审计实测）：
#   `docs/metrics.md` 的周批流程是"跑 trace_metrics → 人复核 → append → verify_metrics"。
#   实测按这个流程走一遍，**不会**被告知三类真问题：
#     ① 结构指标（容量/条数）已 10 天没进快照：快照 `case_total 52` vs 现实 **158**；
#        某格 `interrupt=85/30`（soft_cap 的 2.8 倍），而快照里那次还是 `36/30`；
#     ② 本期没有 live 快照（趋势断档，季度回顾读不到连续 live）；
#     ③ `feedback_capture` 全 0 → 命中率/误诊率**没有分母**，"0/3 = 零误诊"是假绿。
#   `verify_metrics.py` 只验结构（period 唯一 / 字段白名单 / 比例字段合法），
#   不判这三件事 —— 即"数据 → 判据 → 动作"这条腿上**没有检测器**，指标坏了只能靠人
#   季度回顾时想起来。本脚本补这条腿：判据一律读 `metrics/gates.yaml`（数据，不写死）。
#
# 退出码：默认 0（报告即真相）；`--check` 时有越界/陈旧/不可解读 → 非零。
#   **不进 CI**：安静的一周没有新快照是正常状态，硬门会假红；它服务于周批与季度回顾。
#
# 用法：
#   python3 scripts/metrics_health.py            # 人读体检
#   python3 scripts/metrics_health.py --check    # 有 ✗ 则非零（供 groom/回顾脚本判）
#   python3 scripts/metrics_health.py --json

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

import metrics_snapshot as MS


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def age_days(recorded_at):
    if not recorded_at:
        return None
    try:
        return (date.today() - date.fromisoformat(str(recorded_at)[:10])).days
    except ValueError:
        return None


def op_holds(op: str, value, threshold) -> bool:
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    if op == "==":
        return value == threshold
    return False


def latest_by(periods, pred):
    """取"最新"的一期：先比 recorded_at，**同日期时以列表位置为准**（timeline 是 append-only，
    后出现的更新）。实测踩过：两期 recorded_at 同为 2026-08-31，只比日期会挑中较早那期。"""
    cands = [(i, p) for i, p in enumerate(periods) if pred(p)]
    if not cands:
        return None
    return max(cands, key=lambda ip: (str(ip[1].get("recorded_at") or ""), ip[0]))[1]


def check_no_data(periods):
    """一层：数据底座本身有没有东西。"""
    out = []
    live = [p for p in periods if p.get("kind") == "live"]
    structural = [p for p in periods if "case_total" in (p.get("metrics") or {})]
    out.append(("ok" if live else "fail", "live 快照", f"{len(live)} 期" if live else "0 期 —— 趋势与季度回顾都无从谈起"))
    out.append(("ok" if structural else "fail", "结构快照（容量/条数）",
                f"{len(structural)} 期" if structural else "0 期 —— 容量治理没有趋势通道"))
    return out


def main():
    ap = argparse.ArgumentParser(description="metrics 闭环体检")
    ap.add_argument("--check", action="store_true", help="有 ✗ 时退出码非零")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    root = args.root.resolve()

    gates_doc = load_yaml(root / "metrics" / "gates.yaml")
    gates = gates_doc.get("gates") or []
    fresh = gates_doc.get("freshness") or {}
    readability = gates_doc.get("readability") or []
    timeline = load_yaml(root / "metrics" / "timeline.yaml")
    periods = timeline.get("periods") or []

    findings = []          # (level, 面, 文案, 动作)

    # —— ① 数据底座 ——
    for level, what, text in check_no_data(periods):
        findings.append((level, "数据底座", f"{what}：{text}", None))

    # —— ② 新鲜度 ——
    last_live = latest_by(periods, lambda p: p.get("kind") == "live")
    last_struct = latest_by(periods, lambda p: "case_total" in (p.get("metrics") or {}))
    for label, doc, limit_key in (("诊断侧 live 快照", last_live, "live_snapshot_max_age_days"),
                                  ("结构侧（容量/条数）", last_struct, "structural_max_age_days")):
        limit = fresh.get(limit_key)
        if doc is None:
            findings.append(("fail", "新鲜度", f"{label}：一期都没有", "跑 metrics_snapshot.py 组装后 append"))
            continue
        age = age_days(doc.get("recorded_at"))
        if age is None:
            findings.append(("warn", "新鲜度", f"{label}：recorded_at 不可解析（{doc.get('recorded_at')!r}）", None))
        elif limit is not None and age > limit:
            findings.append(("fail", "新鲜度",
                             f"{label}：最后 {doc.get('period')}（{doc.get('recorded_at')}，{age} 天前）超期 {limit} 天",
                             "跑 metrics_snapshot.py 组装本期快照"))
        else:
            findings.append(("ok", "新鲜度", f"{label}：最后 {doc.get('period')}（{age} 天前，阈值 {limit} 天）", None))

    # —— ③ 越界（判据来自 gates.yaml；容量用**当前现实**，不是快照里的旧值）——
    structural, s_notes = MS.collect_structural(root)
    cells = [(ns, cat, c["count"], c["cap"]) for ns, cs in (structural.get("capacity_by_ns") or {}).items()
             for cat, c in cs.items()]
    prev_cells = {}
    if last_struct:
        for ns, cs in ((last_struct.get("metrics") or {}).get("capacity_by_ns") or {}).items():
            for cat, c in (cs or {}).items():
                if isinstance(c, dict):
                    prev_cells[(ns, cat)] = c.get("count")

    for g in gates:
        gid, dim, op, val = g.get("id"), g.get("dimension"), g.get("op"), g.get("value")
        if dim == "capacity_cell":
            hits = [(ns, cat, n, cap) for ns, cat, n, cap in cells if op_holds(op, n, val)]
            for ns, cat, n, cap in sorted(hits, key=lambda x: -x[2]):
                prev = prev_cells.get((ns, cat))
                drift = f"（上次快照 {prev}）" if prev is not None and prev != n else ""
                findings.append(("fail", f"越界 {gid}",
                                 f"{ns} · {cat} = {n}/{cap}{drift} —— {g.get('meaning')}",
                                 g.get("action")))
            if not hits:
                findings.append(("ok", f"越界 {gid}", f"所有格子均未触发 ({op} {val})", None))
        elif dim == "feedback_capture_total":
            live_m = ((last_live or {}).get("metrics") or {})
            fc = live_m.get("feedback_capture")
            if not isinstance(fc, dict):
                findings.append(("warn", f"越界 {gid}", "最新 live 快照没有 feedback_capture 字段", g.get("action")))
            else:
                total = sum(v for v in fc.values() if isinstance(v, int))
                if op_holds(op, total, val):
                    findings.append(("fail", f"越界 {gid}",
                                     f"最新 live 快照 {last_live.get('period')} 捕获反馈 {total} 条 —— {g.get('meaning')}",
                                     g.get("action")))
                else:
                    findings.append(("ok", f"越界 {gid}", f"捕获反馈 {total} 条", None))
        else:
            findings.append(("warn", "越界", f"gates.yaml 里的 dimension '{dim}' 没有对应评估实现", None))

    # —— ④ 可解读性（分母为 0 的指标必须被标成"不可解读"，不能安静地写成 0）——
    live_m = ((last_live or {}).get("metrics") or {})
    for rule in readability:
        metric, kind, why = rule.get("metric"), rule.get("rule"), rule.get("why")
        v = live_m.get(metric)
        if v is None:
            findings.append(("warn", "可解读性", f"{metric}：最新 live 快照没有该字段（{why}）", None))
            continue
        if kind == "total_gt_0":
            total = (v or {}).get("total") if isinstance(v, dict) else None
            bad = not isinstance(total, int) or total <= 0
            note = why
        elif kind == "any_gt_0":
            bad = not (isinstance(v, dict) and any(x for x in v.values() if isinstance(x, int)))
            note = why
        elif kind == "source_nonzero":
            # 该指标的可信度取决于另一个"来源"指标是否有数据（例：误诊率取决于反馈捕获）
            src = live_m.get(rule.get("source"))
            src_total = sum(x for x in (src or {}).values() if isinstance(x, int)) if isinstance(src, dict) else 0
            bad = src_total <= 0
            note = f"{why}（来源指标 {rule.get('source')} 计数 {src_total}）"
        else:
            findings.append(("warn", "可解读性", f"{metric}：rules 里的 rule '{kind}' 没有对应实现", None))
            continue
        findings.append(("fail" if bad else "ok", "可解读性",
                         f"{metric}：{'不可解读——' + str(note) if bad else '可解读'}", None))

    # —— ⑤ 内容流程侧（exec-log 聚合：本轮刚接进快照的来源）——
    flow, meta = MS.collect_content_flow(root)
    findings.append(("ok" if flow["content_flow_runs"] else "warn", "内容流程侧",
                     f"收尾记录 {flow['content_flow_runs']} 条（evolve-check {flow['evolve_check_runs']} 次，"
                     f"其中无信号 {flow['evolve_check_no_signal']} 次；来源 {meta['where']}）",
                     None if flow["content_flow_runs"] else "内容流程收尾应落记录（各 skill 收尾节）"))

    fails = [f for f in findings if f[0] == "fail"]
    if args.json:
        print(json.dumps({
            "findings": [{"level": l, "face": f, "text": t, "action": a} for l, f, t, a in findings],
            "fail_count": len(fails),
            "last_live": (last_live or {}).get("period"),
            "last_structural": (last_struct or {}).get("period"),
            "current": {"case_total": structural.get("case_total"),
                        "reference_total": structural.get("reference_total"),
                        "content_flow": flow},
        }, ensure_ascii=False, default=str))
        return 1 if (args.check and fails) else 0

    icon = {"ok": "✓", "warn": "!", "fail": "✗"}
    print("metrics 闭环体检（判据：metrics/gates.yaml）")
    face = None
    for level, f, text, action in findings:
        if f != face:
            print(f"\n[{f}]")
            face = f
        print(f"  {icon[level]} {text}")
        if action and level != "ok":
            print(f"      → {action}")
    print(f"\n结论：{'闭环未闭合（%d 项 ✗）' % len(fails) if fails else '本期未发现阻塞项'}")
    if fails:
        print("  ✗ = 有判据被违反但没人处理；行动列即下一步（判据数值在 metrics/gates.yaml）")
    return 1 if (args.check and fails) else 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
