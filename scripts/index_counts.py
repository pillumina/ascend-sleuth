#!/usr/bin/env python3
# index_counts.py —— 现算知识库的结构数字（case 总数 / 逐格容量）
#
# 为什么数字不写进生成物（2026-09-22）：
#   原先 `knowledge/_index.yaml` 的头注里写着 "case 总数：168" 和逐格的 "容量(...)=93/30"。
#   那几行是**共享热点**——三人各改一个框架并发提交时，相邻格子的两行各改一行，git 判成同一段
#   冲突；就算不撞，两人各加一条 case 也会把同一行写成同一个数（而后来的真实值是 +2）。
#   数字一进 git，非撞即漂。所以数字改成**按需现算**：谁要看，谁跑本脚本。
#   生成物里的"数字"只剩条目本身，于是可以用 merge=union 自动合并（见 .gitattributes）。
#
# 用法：
#   python3 scripts/index_counts.py            # 人读表格
#   python3 scripts/index_counts.py --json     # 机器读（面板 / 体检 / 快照脚本）
#
# 口径：cap 按 (framework × category) 格子计（docs/adr/0004）。soft 触发拆分评估，hard 强制拆。

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_index as BI  # noqa: E402


def counts(root: Path) -> dict:
    """→ {"total": n, "cells": [{namespace, category, count, soft_cap, hard_cap, over_soft, over_hard}]}"""
    ns = BI.collect(root)
    cells = []
    for ns_name in sorted(ns):
        for cat in sorted(ns[ns_name]):
            n = len(ns[ns_name][cat])
            cells.append({
                "namespace": ns_name,
                "category": cat,
                "count": n,
                "soft_cap": BI.SOFT_CAP,
                "hard_cap": BI.HARD_CAP,
                "over_soft": n > BI.SOFT_CAP,
                "over_hard": n > BI.HARD_CAP,
            })
    return {"total": sum(c["count"] for c in cells), "cells": cells}


def capacity_by_ns(data: dict) -> dict:
    """面板/体检脚本用的旧形状：{ns: {cat: {count, cap}}}（cap = soft_cap，一个格子一条）。"""
    out = {}
    for c in data["cells"]:
        out.setdefault(c["namespace"], {})[c["category"]] = {"count": c["count"], "cap": c["soft_cap"]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="现算知识库结构数字（条数 / 逐格容量）")
    ap.add_argument("--json", action="store_true", help="机器读（含逐格 soft/hard 越界标志）")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    data = counts(args.root.resolve())
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False))
        return 0
    print(f"case 总数：{data['total']}")
    for c in data["cells"]:
        flag = ""
        if c["over_hard"]:
            flag = f"  ← 超 hard_cap {c['hard_cap']}（强制拆）"
        elif c["over_soft"]:
            flag = f"  ← 超 soft_cap {c['soft_cap']}（触发拆分评估）"
        print(f"  {c['namespace']:<26} {c['category']:<12} {c['count']}/{c['soft_cap']}{flag}")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
