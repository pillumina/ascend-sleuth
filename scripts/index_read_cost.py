#!/usr/bin/env python3
# index_read_cost.py —— 现算"阶段一实读成本"（每格多少 token、每行多少 token）
#
# 为什么单独一个脚本（2026-09-29，起因：容量上限的算术偏了 3.4 倍）：
#   ADR-0004 把 hard_cap 定成"每格 60 条 ≈ 60×70 ≈ 4.2K token"，那个 70 token/条是**估的**；
#   实测（同一批 93 条 case）现行 YAML 分片 236 token/条、紧凑行 148 token/条。估小了 3.4 倍，
#   后果是 `inference/vllm-ascend × interrupt` 93 条看起来"只是贴着线"，实际 23.4K token——
#   比诊断会话的常驻指令面（SKILL + CLAUDE + 路由表 ≈ 21K）还大。
#   条数是代理量，token 才是被约束的量（B_ctx）。所以上限要按 token 定，而 token 必须现算。
#
# 两个读法都要给（形态决定成本，`--format` 选）：
#   yaml     现行分片：`knowledge/_index/<ns>__<cat>.yaml` 原样（带缩进/引号/字段名）
#   compact  紧凑行：`id | 标题 | 症状首条 | sig | tok | compat | tags`（同信息，去结构开销）
#   实测（93 条那格）：yaml 23449 → compact 13764（-41%）；全库十格合计 43078 → 25044（-42%）。
#
# 口径（**估 token 的算法**，与 metrics 侧一致）：CJK 字符按 1 token、其余按 3.6 字符 1 token。
#   它不等于任何厂商 tokenizer 的精确值，是量级口径——上限按同一把尺子定与复核即可。
#   不用 bytes/3.4 那类"字节折算"：中文 3 字节/token、ASCII 3~4 字节/token，混在一起必偏。
#
# 用法：
#   python3 scripts/index_read_cost.py                      # 全部格子的人读表
#   python3 scripts/index_read_cost.py --json               # 机器读（面板 / 体检 / 上限判定）
#   python3 scripts/index_read_cost.py --cell inference/vllm-ascend/interrupt [--format compact]
#   python3 scripts/index_read_cost.py --cap 15000          # 越界项单独报（默认按每格硬线判）
#
# 退出码：0 = 全部在硬线内；1 = 有格子越过硬线（`--cap` 可改硬线，默认 15000）。
# 这不是门（未进 CI）：它是给容量裁决与体检脚本读的**尺子**，先量后定。

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_index as BI  # noqa: E402

# 每格阶段一实读的硬线（token）。15000 的来处：诊断会话的常驻指令面（SKILL 11.4K + 仓库指令 5.7K +
# 路由表 4.1K ≈ 21K）与 ~120K 的推理区间的折中——阶段一不该比"每次都要读的指令"还贵。
# 初始估计，服从 roadmap 参数治理：metrics 实测（回放命中率 vs 读入量）后复核。
DEFAULT_HARD_TOK = 15000
SOFT_TOK = 8000   # 到达即触发"能不能再省"的评估（与 ADR-0004 的 soft/hard 两级同构）


def tok(text: str) -> int:
    """估 token：CJK 1 token/字，其余 3.6 字符/token。"""
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", text))
    return cjk + int((len(text) - cjk) / 3.6)


def _flat(s) -> str:
    return " ".join(str(s or "").split())


def _trunc(s, n: int) -> str:
    s = _flat(s)
    return s if len(s) <= n else s[:n] + "…"


def compact_line(row) -> str:
    """一条索引 → 一行紧凑文本（字段与顺序与现行分片行一一对应）。

    刻意不带 `file` / `hash`：`file` 可由 id 推出（全库实测零例外），`hash` 只服务新鲜度门、
    读侧不用。两者留在总表（机器面）里。
    """
    parts = [row.get("id", ""), _trunc(row.get("title"), 160)]
    sym = (row.get("symptoms") or [""])[0]
    if sym:
        parts.append(_trunc(sym, 120))
    if row.get("sig"):
        parts.append("; ".join(map(str, row["sig"])))
    if row.get("tok"):
        parts.append("; ".join(map(str, row["tok"])))
    if row.get("compat"):
        parts.append(str(row["compat"]))
    if row.get("tags"):
        parts.append(" ".join(map(str, row["tags"])))
    return " | ".join(parts)


def cell_costs(root: Path) -> dict:
    """→ {"cells": [{namespace, category, rows, yaml_tok, compact_tok, bytes}], "total": {...}}"""
    ns = BI.collect(root)
    cells = []
    for ns_name in sorted(ns):
        for cat in sorted(ns[ns_name]):
            rows = ns[ns_name][cat]
            p = root / "knowledge" / "_index" / BI.shard_slug(f"{ns_name}__{cat}")
            y = tok(p.read_text(encoding="utf-8")) if p.exists() else 0
            c = tok("\n".join(compact_line(r) for r in rows))
            cells.append({
                "namespace": ns_name, "category": cat, "rows": len(rows),
                "yaml_tok": y, "compact_tok": c,
                "yaml_per_row": round(y / len(rows)) if rows else 0,
                "compact_per_row": round(c / len(rows)) if rows else 0,
                "bytes": p.stat().st_size if p.exists() else 0,
            })
    tot = {
        "rows": sum(c["rows"] for c in cells),
        "yaml_tok": sum(c["yaml_tok"] for c in cells),
        "compact_tok": sum(c["compact_tok"] for c in cells),
    }
    if tot["yaml_tok"]:
        tot["saving_pct"] = round(100 - 100 * tot["compact_tok"] / tot["yaml_tok"])
    return {"cells": cells, "total": tot, "hard_tok": DEFAULT_HARD_TOK, "soft_tok": SOFT_TOK}


def main() -> int:
    ap = argparse.ArgumentParser(description="现算阶段一实读成本（每格 token）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cell", default=None, help="只看一格，如 inference/vllm-ascend/interrupt")
    ap.add_argument("--format", choices=["yaml", "compact"], default="yaml",
                    help="报哪种读法的成本（默认 yaml=现行分片）")
    ap.add_argument("--cap", type=int, default=DEFAULT_HARD_TOK, help="硬线（token），默认 15000")
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args()
    root = (args.root or Path(__file__).resolve().parents[1]).resolve()
    data = cell_costs(root)
    cells = data["cells"]
    if args.cell:
        ns, _, cat = args.cell.rpartition("/")
        hit = [c for c in cells if c["namespace"] == ns and c["category"] == cat]
        if not hit:
            keys = "\n  ".join(sorted(f"{c['namespace']}/{c['category']}" for c in cells))
            print(f"没找到格子 {args.cell}。可选：\n  {keys}", file=sys.stderr)
            return 2
        cells = hit
    if args.json:
        out = dict(data)
        out["cells"] = cells
        out["format"] = args.format
        out["cap"] = args.cap
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    key, per_row_key = ("yaml_tok", "yaml_per_row") if args.format == "yaml" else ("compact_tok", "compact_per_row")
    print(f"阶段一实读成本（{args.format} 读法；硬线 {args.cap} tok、评估线 {SOFT_TOK} tok）")
    for c in sorted(cells, key=lambda x: -x[key]):
        flag = ""
        if c[key] > args.cap:
            flag = f"  ← 超硬线 {args.cap}"
        elif c[key] > SOFT_TOK:
            flag = "  ← 超评估线"
        print(f"  {c['namespace'] + ' × ' + c['category']:44s} {c['rows']:4d} 条 "
              f"{c[key]:6d} tok（{c[per_row_key]}/条）{flag}")
    if not args.cell:
        print(f"  合计 {data['total']['rows']} 条：yaml {data['total']['yaml_tok']} tok → "
              f"紧凑行 {data['total']['compact_tok']} tok（可省 {data['total'].get('saving_pct', 0)}%）")
    over = [c for c in cells if c[key] > args.cap]
    return 1 if over else 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
