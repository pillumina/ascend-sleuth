#!/usr/bin/env python3
# component_tally.py —— 流程组件失败台账（metrics/component-tally.yaml）
#
# 目的（evolution-pipeline.md §2，L2 流程自演进的数据基座）：
# 把"哪个流程组件反复出错"变成可度量——组件台账是 L2 的"知识库"，
# 语义与 case confidence 相同（只按已回报结果回写、低分浮出 → 触发修复候选）。
#
# 数据源：traces/*.yaml 的 attribution 事件（diagnose 在反馈 not_resolved/partial
# 后写入）。verdict=execution_error 且带 component 字段 → 该组件 mis +1；
# verdict=case_error 不计入组件台账（那是 case 层的问题，走 case confidence）。
# hit 侧：当前 trace 无组件级命中记录，台账只记 mis（如实——组件"被正确执行"没有
# 独立证据，只有"执行错定位到哪个组件"有归因证据；hit 侧留待 diagnose 加组件命中
# 记录后启用，不编造数据）。
#
# 输出：metrics/component-tally.yaml
#   components:
#     - id: triage:vllm-ascend-startup
#       hits: 0          # 留待组件命中记录落地后启用（当前如实为 0）
#       misdiagnoses: 6
#       score: 0.0       # mis 侧：hits/(hits+mis)，当前恒 0——低分即浮出
#       last_mis: "2026-W37"
#       source_traces: [<session 文件>]
# 幂等：按 trace 文件 + attribution 事件索引去重（重复跑不重复累积）。
# 用法：python3 scripts/component_tally.py [--emit] [--root <repo>]
#   --emit 写台账；默认只读 trace 输出统计（dry-run，确认后 --emit）。

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

TALLY_PATH = "metrics/component-tally.yaml"


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def iso_week() -> str:
    # 近似 ISO 周（与 timeline 的 Wnn 格式一致：2026-W37）
    now = datetime.now()
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def scan_traces(root: Path):
    """扫 traces/*.yaml 的 attribution 事件，收集 (session, 事件序, component, 周)。"""
    entries = []  # (session_file, trace_idx, component)
    for f in sorted((root / "traces").glob("*.yaml")):
        doc = load_yaml(f)
        if not isinstance(doc, dict):
            continue
        trace = doc.get("trace") or []
        for i, ev in enumerate(trace):
            if not isinstance(ev, dict):
                continue
            if ev.get("action") == "attribution":
                if ev.get("verdict") == "execution_error" and ev.get("component"):
                    entries.append((f.name, i, ev["component"]))
    return entries


def scan_replay_attributions(root: Path):
    """扫 .s2-replay/attributions.yaml（s2_replay --collect 产出的路由 miss 归因，S1 无关）。

    component = got 分支（把 issue 引向错误方向的 triage 分支），与 traces 的 attribution
    同为组件失败台账的 mis 侧数据源——S2 replay 对照的是外部 ground truth（issue resolution
    预标），非 agent 自我背书。"""
    entries = []  # (source_tag, idx, component)
    attr_path = root / ".s2-replay" / "attributions.yaml"
    doc = load_yaml(attr_path)
    if not isinstance(doc, dict):
        return entries
    for i, ev in enumerate(doc.get("attributions") or []):
        if not isinstance(ev, dict):
            continue
        if ev.get("verdict") == "execution_error" and ev.get("component"):
            entries.append((f"s2-replay#{ev.get('issue', i)}", i, ev["component"]))
    return entries


def load_tally(root: Path):
    path = root / TALLY_PATH
    doc = load_yaml(path)
    if not isinstance(doc, dict) or "components" not in doc:
        return {}
    return {c["id"]: c for c in doc["components"] if isinstance(c, dict) and "id" in c}


def main():
    ap = argparse.ArgumentParser(description="流程组件失败台账")
    ap.add_argument("--emit", action="store_true", help="写 metrics/component-tally.yaml")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()

    root = args.root.resolve()
    entries = scan_traces(root) + scan_replay_attributions(root)
    if not entries:
        print("component_tally: 无 attribution(execution_error + component) 事件——台账无新数据")
        return

    # 按组件聚合（幂等：这里直接重算自 trace；--emit 时合并已有台账避免重复）
    from collections import defaultdict
    by_component = defaultdict(lambda: {"mis": 0, "traces": set()})
    for fname, idx, comp in entries:
        key = comp if isinstance(comp, str) else str(comp)
        by_component[key]["mis"] += 1
        by_component[key]["traces"].add(fname)

    print(f"component_tally: 发现 {len(entries)} 条组件归因事件，{len(by_component)} 个组件")
    for comp, data in sorted(by_component.items(), key=lambda x: -x[1]["mis"]):
        print(f"  {comp}: mis={data['mis']} (traces: {', '.join(sorted(data['traces'])[:3])}{'...' if len(data['traces'])>3 else ''})")

    if not args.emit:
        print("（dry-run：加 --emit 写 metrics/component-tally.yaml）")
        return

    # 幂等写台账：mis 从 trace + .s2-replay 归因全量重算（两源都可全量扫描），
    # 不对旧台账累加（累加会在重复 emit 时翻倍——原有缺陷）；旧台账只迁移 hits 侧
    # （diagnose 组件命中记录未落地前恒为 0，如实保留）。
    old = load_tally(root)
    week = iso_week()
    tally = {}
    for comp, data in sorted(by_component.items()):
        tally[comp] = {
            "id": comp,
            "hits": (old.get(comp) or {}).get("hits", 0),  # hits 侧未落地，迁移旧值
            "misdiagnoses": data["mis"],                   # 全量重算，幂等
            "score": 0.0 if data["mis"] == 0 else 0.0,     # hits 侧为 0 → score 恒 0（如实）
            "last_mis": week,
            "source_traces": sorted(data["traces"]),
        }

    out_path = root / TALLY_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"_comment": "GENERATED by scripts/component_tally.py --emit; 组件失败台账（evolution-pipeline §2）。mis 侧来自 trace attribution(execution_error+component) 与 .s2-replay/attributions.yaml（S2 路由 miss 归因，S1 无关）全量重算——重复 emit 幂等；hits 侧待 diagnose 组件命中记录落地后启用，当前如实为 0。", "components": sorted(tally.values(), key=lambda c: -c.get("misdiagnoses", 0))}
    out_path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"component_tally: 已写 {out_path}（{len(tally)} 个组件，mis 全量重算幂等）")


if __name__ == "__main__":
    main()
