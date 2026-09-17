#!/usr/bin/env python3
# component_tally.py —— 流程组件失败归因的按需聚合报告（无常驻台账表）
#
# 设计变更（2026-09 selfevolve-loop 重构）：原设计维护常驻表
# metrics/component-tally.yaml（"组件失败台账"，docs/mechanism/pipeline.md §2）——
# 该形态是过度设计：①归因事件 0 条时表空转（S1 断供 + S2 无路由 miss，文件从未生成）；
# ②无 hit 侧数据源，score 恒 0，"低分浮出"无从谈起；③把 diagnose 输出与 expected 不符
# 一律硬归因 triage 分支，归因不精确还假装精确。
#
# 第一性替代：归因事件本身就是数据，入 trace（diagnose 现场写 attribution 事件 +
# 可选 component），本脚本在**深度轮/季度自评时按需聚合**——有失败簇才考虑沉淀成
# 修复候选，不预建表（原则十一：数据触发演进）。这是"事件入 trace、报告按需生成"，
# 不是"表常驻、等事件填"。
#
# 数据源（两类，来源诚实标注）：
#   1. 硬归因：traces/*.yaml 的 attribution 事件（verdict=execution_error + component，
#      diagnose 在反馈 not_resolved/partial 后现场写——S1 侧，可信）
#   2. 候选路由 miss：.s2-replay/attributions.yaml（s2_replay --collect 产出——
#      S2 对照外部 ground truth，但只能报"路由 miss 事实"，组件归因是候选，
#      需人/深度轮从 trace 确认后才升级为修复指向；不冒充 execution_error）
#
# 用法：
#   python3 scripts/component_tally.py             # 聚合报告（stdout，人读）
#   python3 scripts/component_tally.py --json      # JSON（agent/面板消费）
# 输出进 proposals/reviews/ 或直接读——本脚本不写任何常驻状态文件（幂等天然成立：
# 每次从 traces + attributions 全量重算，无累积状态）。

import argparse
import json
import sys
from pathlib import Path

import yaml
from exec_log_path import resolve_traces


def scan_traces(root: Path):
    """扫 traces/*.yaml 的 attribution 事件（硬归因，S1 侧）。"""
    entries = []
    for f in sorted(resolve_traces(root).glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        trace = doc.get("trace") or [] if isinstance(doc, dict) else []
        for i, ev in enumerate(trace):
            if not isinstance(ev, dict):
                continue
            if ev.get("action") == "attribution":
                entries.append({
                    "source": "trace",
                    "trace": f.name,
                    "verdict": ev.get("verdict"),
                    # 生产端实际写的是 `attribution_kind`（execution|improvement|design，见
                    # skills/diagnose 的 diagnosis-procedure 与 trace schema），消费端此前只认
                    # `verdict`——于是"硬归因"这条腿从来没有数据（实测：4 条 attribution 事件、
                    # 0 条含 verdict → 合计恒为「硬 0」）。两种写法都收，映射见 is_hard()。
                    "attribution_kind": ev.get("attribution_kind"),
                    "component": ev.get("component"),
                    "evidence": str(ev.get("evidence", ""))[:120],
                })
    return entries


def scan_replay_attributions(root: Path):
    """扫 .s2-replay/attributions.yaml（候选路由 miss——S2 侧，无 S1 职权判 execution_error）。"""
    entries = []
    attr_path = root / ".s2-replay" / "attributions.yaml"
    if not attr_path.exists():
        return entries
    try:
        doc = yaml.safe_load(attr_path.read_text(encoding="utf-8"))
    except Exception:
        return entries
    for i, ev in enumerate(doc.get("attributions") or []):
        if not isinstance(ev, dict):
            continue
        entries.append({
            "source": "s2-replay",
            "trace": f"s2#{ev.get('issue', i)}",
            "verdict": "candidate",          # 候选——S2 只能报 miss 事实，组件归因待确认
            "component": ev.get("component"),
            "evidence": ev.get("note", ""),
        })
    return entries


def is_hard(e):
    """这条 trace 归因算不算"硬归因"（可指向组件修复的）。

    两套词表都收：`verdict == execution_error`（早期 schema）与
    `attribution_kind == execution`（生产端现在实际写的）。只认一套的代价是整条腿静默为零。
    """
    if e.get("source") != "trace":
        return False
    return e.get("verdict") == "execution_error" or e.get("attribution_kind") == "execution"


def aggregate(entries):
    """按 component 聚合（含来源拆分与硬/候选标注）。"""
    from collections import defaultdict
    by_comp = defaultdict(lambda: {"trace_mis": 0, "s2_candidate": 0, "traces": set()})
    for e in entries:
        comp = e.get("component") or "(未归因)"
        agg = by_comp[comp]
        if is_hard(e):
            agg["trace_mis"] += 1
            agg["traces"].add(e["trace"])
        elif e["source"] == "s2-replay":
            agg["s2_candidate"] += 1
            agg["traces"].add(e["trace"])
    return dict(by_comp)


def main():
    ap = argparse.ArgumentParser(description="流程组件失败归因的按需聚合报告（无常驻表）")
    ap.add_argument("--json", action="store_true", help="JSON 输出（agent/面板消费）")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()

    root = args.root.resolve()
    entries = scan_traces(root) + scan_replay_attributions(root)
    if not entries:
        msg = "component_tally: 无归因事件（trace attribution + s2 候选均为空）——按需聚合无数据，如实空转"
        print(msg if not args.json else json.dumps({"entries": [], "note": msg}))
        return

    agg = aggregate(entries)
    if args.json:
        print(json.dumps({
            "entries": entries,
            "components": [
                {"component": k, **v, "traces": sorted(v["traces"])}
                for k, v in sorted(agg.items(), key=lambda x: -(x[1]["trace_mis"] + x[1]["s2_candidate"]))
            ],
        }, ensure_ascii=False, indent=2))
        return

    print("component_tally: 按需聚合报告（数据源：trace attribution 硬归因 + s2 路由 miss 候选）\n")
    for comp, data in sorted(agg.items(), key=lambda x: -(x[1]["trace_mis"] + x[1]["s2_candidate"])):
        tag = "硬归因(S1)" if data["trace_mis"] else "候选(S2)"
        print(f"  {comp}: {tag} mis={data['trace_mis']} 候选={data['s2_candidate']}")
        print(f"     来源: {', '.join(sorted(data['traces'])[:5])}{'…' if len(data['traces']) > 5 else ''}")
    hard = sum(1 for e in entries if is_hard(e))
    cand = sum(1 for e in entries if e["source"] == "s2-replay")
    other = len(entries) - hard - cand
    # 口径自洽：合计必须等于三项之和（此前"合计 4 条（硬 0 / 候选 0）"里那 4 条既不硬也不候选，
    # 读数自相矛盾——读者无法判断"没有归因"和"归因都不算数"）。
    tail = f" / 其他 {other}" if other else ""
    print(f"\n  合计: {len(entries)} 条归因（硬 {hard} / 候选 {cand}{tail}）")
    if other:
        print("  注: 「其他」= 归因事件存在但不属硬归因（如 attribution_kind 为 improvement/design、"
              "或组件不可指认）——它们不指向组件修复，不计入失败簇")
    if hard == 0 and cand > 0:
        print("  注: 仅有 S2 候选——组件归因是推断，需从对应 trace 确认后才可指向修复")
    if hard > 0:
        print("  失败簇 → 可产 L2 修复候选（修订该组件所在 skill 步骤 / triage 分支）")


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
