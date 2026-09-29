#!/usr/bin/env python3
# index_read_cost.py —— 现算"阶段一实读成本"（每格多少 token、每行多少 token）
#
# 为什么单独一个脚本（2026-09-29，起因：容量上限的算术偏了 3.4 倍）：
#   ADR-0004 把 hard_cap 定成"每格 60 条 ≈ 60×70 ≈ 4.2K token"，那个 70 token/条是**估的**。
#   实测：YAML 分片 252 token/条、同信息的读侧视图 173 token/条。估小了 3.4 倍，后果是
#   `inference/vllm-ascend × interrupt` 93 条看起来"只是贴着线"，实际 23449 token——比诊断会话
#   的常驻指令面（SKILL + CLAUDE + 路由表 ≈ 21K）还大。条数是代理量，token 才是被约束的量（B_ctx）。
#
# 量的是**实际落盘的那份东西**：`knowledge/_index/<ns>__<category>.list`（阶段一真读它）。
#   每条 case 一行，字段与索引行一一对应；省下的是 YAML 的缩进/引号/字段名/嵌套（同信息）。
#   **两类视图分开报**：类视图（category 已定，命中路径）与 ns 兜底视图（category 未定才读）。
#   硬线只管前者——后者更贵（vllm-ascend 单文件 3 万余 token），是另一条读取路径，要治得单独立项；
#   把它混进同一个分母会让"越线"这件事看不出来。
#
# 口径（**估 token 的算法**）：CJK 字符按 1 token、其余按 3.6 字符 1 token。
#   它不等于任何厂商 tokenizer 的精确值，是量级口径——上限按同一把尺子定与复核即可。
#   不用 bytes/3.4 那类"字节折算"：中文 3 字节/token、ASCII 3~4 字节/token，混在一起必偏。
#
# 用法：
#   python3 scripts/index_read_cost.py                      # 全部格子的人读表（含兜底视图一节）
#   python3 scripts/index_read_cost.py --json               # 机器读（面板 / 体检 / 上限判定）
#   python3 scripts/index_read_cost.py --cell inference/vllm-ascend/interrupt
#   python3 scripts/index_read_cost.py --cap 12000          # 改硬线（默认 20000）
#
# 退出码（对外契约，`--json` 与人读表**同码**）：0 = 全部在硬线内；1 = 有格子越过硬线；
# 2 = 数据不完整（缺读侧视图，或 `--root` 下没有 knowledge/）——"量不出"不能读成"免费"。
# 这不是门（未进 CI）：它是给容量裁决与体检脚本读的**尺子**，先量后定。

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_index as BI  # noqa: E402

# 每格阶段一实读的硬线（token）。20000 是**推导**来的，不是拍的：诊断会话的常驻指令面
# （SKILL 11.4K + 仓库指令 5.7K + 路由表 4.1K ≈ 21K）是"每次都要读"的量——阶段一不该比它更贵。
# 软线 8000 = 该面的一半：到这里就该问"能不能再省"（与 ADR-0004 的 soft/hard 两级同构）。
# 两个常数服从 roadmap 参数治理：metrics 实测（回放命中率 vs 读入量）后复核。
DEFAULT_HARD_TOK = 20000
SOFT_TOK = 8000


def tok(text: str) -> int:
    """估 token：CJK 1 token/字，其余 3.6 字符/token。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", text))
    return cjk + int((len(text) - cjk) / 3.6)


def _view_cost(p: Path) -> int:
    """一个读侧视图文件的实读成本（含头注：头注是读的人真会看到的字）。"""
    return tok(p.read_text(encoding="utf-8"))


def cell_costs(root: Path) -> dict:
    """→ {cells:[...], fallbacks:[...], total:{...}, missing_views:[...], hard_tok, soft_tok}

    cells     = 类视图（命中路径；硬线只管这一组）
    fallbacks = ns 兜底视图（category 未定才读；单独报，不混进同一个分母）
    """
    ns = BI.collect(root)
    shard_dir = root / "knowledge" / "_index"
    cells, fallbacks, missing = [], [], []
    for ns_name in sorted(ns):
        for cat in sorted(ns[ns_name]):
            rows = ns[ns_name][cat]
            p = shard_dir / BI.shard_slug(f"{ns_name}__{cat}")
            if not p.exists():
                # 缺读侧视图 ≠ 成本为 0：量不出就得说量不出（否则"残缺"会被读成"这格免费"）
                missing.append(p.name)
            cost = _view_cost(p) if p.exists() else 0
            cells.append({
                "namespace": ns_name, "category": cat, "rows": len(rows),
                "tok": cost, "per_row": round(cost / len(rows)) if rows else 0,
                "bytes": p.stat().st_size if p.exists() else 0,
            })
        fb = shard_dir / BI.shard_slug(ns_name)
        if not fb.exists():
            missing.append(fb.name)
        fb_cost = _view_cost(fb) if fb.exists() else 0
        fallbacks.append({
            "namespace": ns_name,
            "rows": sum(len(v) for v in ns[ns_name].values()),
            "tok": fb_cost,
            "per_row": round(fb_cost / max(1, sum(len(v) for v in ns[ns_name].values()))),
        })
    total = {"rows": sum(c["rows"] for c in cells), "tok": sum(c["tok"] for c in cells)}
    return {"cells": cells, "fallbacks": fallbacks, "total": total,
            "hard_tok": DEFAULT_HARD_TOK, "soft_tok": SOFT_TOK, "missing_views": missing}


def main() -> int:
    ap = argparse.ArgumentParser(description="现算阶段一实读成本（每格 token）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cell", default=None, help="只看一格，如 inference/vllm-ascend/interrupt")
    ap.add_argument("--cap", type=int, default=DEFAULT_HARD_TOK, help=f"硬线（token），默认 {DEFAULT_HARD_TOK}")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()
    root = (args.root or Path(__file__).resolve().parents[1]).resolve()
    if not (root / "knowledge").is_dir():
        print(f"{root} 下没有 knowledge/ —— 这不像检出根（`--root` 传错了吗？）", file=sys.stderr)
        return 2
    data = cell_costs(root)
    if data["missing_views"]:
        for m in data["missing_views"]:
            print(f"读侧视图缺失：knowledge/_index/{m}——这一份量不出成本（不是 0），"
                  f"先跑 `python3 scripts/build_index.py`", file=sys.stderr)
        return 2
    cells, fallbacks = data["cells"], data["fallbacks"]
    if args.cell:
        ns, _, cat = args.cell.rpartition("/")
        hit = [c for c in cells if c["namespace"] == ns and c["category"] == cat]
        if not hit:
            keys = "\n  ".join(sorted(f"{c['namespace']}/{c['category']}" for c in cells))
            print(f"没找到格子 {args.cell}。可选：\n  {keys}", file=sys.stderr)
            return 2
        cells = hit
    over = [c for c in cells if c["tok"] > args.cap]
    if args.json:
        out = {"cells": cells, "fallbacks": [] if args.cell else fallbacks,
               "total": data["total"], "cap": args.cap, "soft_tok": data["soft_tok"],
               "over_cap": [f"{c['namespace']}/{c['category']}" for c in over]}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1 if over else 0          # 与人读表同码：机器读的那条路也要能判越线
    print(f"阶段一实读成本（读侧视图；硬线 {args.cap} tok、评估线 {data['soft_tok']} tok）")
    for c in sorted(cells, key=lambda x: -x["tok"]):
        flag = ""
        if c["tok"] > args.cap:
            flag = f"  ← 超硬线 {args.cap}"
        elif c["tok"] > data["soft_tok"]:
            flag = "  ← 超评估线"
        print(f"  {c['namespace'] + ' × ' + c['category']:44s} {c['rows']:4d} 条 "
              f"{c['tok']:6d} tok（{c['per_row']}/条）{flag}")
    if not args.cell:
        print(f"  合计类视图 {data['total']['rows']} 条 / {data['total']['tok']} tok")
        print("兜底视图（category 未定时才读，不在上面的硬线里）：")
        for f in sorted(fallbacks, key=lambda x: -x["tok"]):
            print(f"  {f['namespace']:44s} {f['rows']:4d} 条 {f['tok']:6d} tok（{f['per_row']}/条）")
    return 1 if over else 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
