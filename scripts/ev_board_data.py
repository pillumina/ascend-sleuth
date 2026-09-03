#!/usr/bin/env python3
# ev_board_data.py —— 自演进看板数据汇总（EV 卡 + timeline + 容量 + 归因聚合）
#
# 供 DSH 面板（dsh-plugins/ev-panel）host 侧调用：一次性汇总 proposals/ideas/、
# metrics/timeline.yaml、knowledge/_index.yaml 头注、归因事件按需聚合
# （component_tally 逻辑：trace attribution + .s2-replay/attributions.yaml）、
# .s2-replay/attributions.yaml 为 JSON，stdout 输出。确定性逻辑（原则二）：解析与
# 聚合进脚本，agent/面板只读聚合结果。
#
# 用法：python3 scripts/ev_board_data.py [--root <repo>]

import argparse
import glob
import json
import re
import sys
from pathlib import Path

import yaml

# 允许 import 同目录脚本（component_tally 按需聚合复用）
sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_yaml(path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"__error__": str(e)}


def parse_index_header(text):
    """knowledge/_index.yaml 头注容量行：'#   容量(inference/vllm-ascend): interrupt=36/30, ...'"""
    caps = {}
    for line in text.splitlines():
        m = re.match(r"#\s*容量\(([^)]+)\):\s*(.*)$", line.strip())
        if not m:
            continue
        ns = m.group(1)
        cells = {}
        for part in m.group(2).split(","):
            cm = re.match(r"\s*(\w+)=(\d+)/(\d+)", part)
            if cm:
                cells[cm.group(1)] = {"count": int(cm.group(2)), "cap": int(cm.group(3))}
        if cells:
            caps[ns] = cells
    return caps


def collect_ideas(root):
    ideas = []
    for f in sorted((root / "proposals" / "ideas").glob("*.yaml")):
        d = load_yaml(f)
        if not isinstance(d, dict) or "__error__" in d:
            ideas.append({"file": f.name, "error": d.get("__error__", "解析失败")})
            continue
        ideas.append({
            "id": d.get("id"),
            "title": d.get("title"),
            "layer": d.get("layer"),
            "status": d.get("status"),
            "authorization": d.get("authorization"),
            "dimension": d.get("dimension"),
            "risk": d.get("risk"),
            "principle_refs": d.get("principle_refs") or [],
            "source_signals": (d.get("source_signals") or [])[:3],
            "predicted_effect": d.get("predicted_effect"),
            "decisions": d.get("decisions") or [],
            "created_at": d.get("created_at"),
            "supersedes": d.get("supersedes") or [],
            "superseded_by": d.get("superseded_by"),
        })
    return ideas


def collect_timeline(root):
    """只取每期标题/kind/关键指标（路由准确率/候选召回等），供趋势 sparkline。"""
    path = root / "metrics" / "timeline.yaml"
    if not path.exists():
        return []
    d = load_yaml(path)
    if not isinstance(d, dict):
        return []
    out = []
    for p in d.get("periods") or []:
        m = p.get("metrics") or {}
        row = {
            "period": p.get("period"),
            "kind": p.get("kind"),
            "title": (p.get("title") or "")[:60],
        }
        for k in ("routed_accuracy", "candidate_recall", "golden_suite"):
            if k in m:
                v = m[k]
                row[k] = v if not isinstance(v, dict) else v.get("ok", v)
        out.append(row)
    return out


def collect_tally(root):
    """归因事件按需聚合（2026-09 重构：无常驻 metrics/component-tally.yaml 表——
    从 trace attribution + s2 候选现聚合，语义同 component_tally.py）。"""
    # 复用 component_tally 的聚合逻辑（同仓库脚本，直接导入避免双源漂移）
    import component_tally
    entries = component_tally.scan_traces(root) + component_tally.scan_replay_attributions(root)
    if not entries:
        return []
    agg = component_tally.aggregate(entries)
    return [
        {"id": comp, **v, "traces": sorted(v["traces"])}
        for comp, v in sorted(agg.items(), key=lambda x: -(x[1]["trace_mis"] + x[1]["s2_candidate"]))
    ]


def collect_s2_attrib(root):
    path = root / ".s2-replay" / "attributions.yaml"
    if not path.exists():
        return None
    d = load_yaml(path)
    return d.get("attributions") if isinstance(d, dict) else None


def main():
    ap = argparse.ArgumentParser(description="自演进看板数据汇总")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.root.resolve()

    ideas = collect_ideas(root)
    timeline = collect_timeline(root)
    index_path = root / "knowledge" / "_index.yaml"
    capacity = parse_index_header(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    tally = collect_tally(root)
    s2_attrib = collect_s2_attrib(root)

    # 卡状态机分布
    status_count = {}
    for c in ideas:
        st = c.get("status") or "unknown"
        status_count[st] = status_count.get(st, 0) + 1

    payload = {
        "ideas": ideas,
        "idea_count": len(ideas),
        "status_count": status_count,
        "timeline": timeline,
        "capacity": capacity,
        "tally": tally,
        "s2_attrib": s2_attrib,
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }
    print(json.dumps(payload, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
