#!/usr/bin/env python3
# index_read_cost.py —— 现算"一次诊断读进来多少字"（一张账：类的、兜底的、先验的、阶段二的）
#
# 为什么单独一个脚本（2026-09-29，起因：容量上限的算术偏了 3.6 倍）：
#   ADR-0004 把 hard_cap 定成"每格 60 条 ≈ 60×70 ≈ 4.2K token"，那个 70 token/条是**估的**。
#   实测：YAML 分片 252 token/条、同信息的读侧视图 177 token/条。估小了 3.6 倍（252/70），后果是
#   `inference/vllm-ascend × interrupt` 93 条看起来"只是贴着线"，实际 23449 token——比诊断会话
#   的常驻指令面（SKILL + CLAUDE + 路由表 ≈ 21K）还大。条数是代理量，token 才是被约束的量（B_ctx）。
#
# 量的是**实际落盘的那份东西**：`knowledge/_index/<ns>__<category>.list`（阶段一真读它）。
#   每条 case 一行，字段与索引行一一对应；省下的是 YAML 的缩进/引号/字段名/嵌套（同信息）。
#   **四个分项分开报，线只加在有证据的地方**（2026-09-29 补）：
#     ① 类视图（category 已定，命中路径）与 ② ns 兜底视图（category 未定才读）——都按同一组
#        推导出来的线（软 8000 / 硬 20000）判，两条线两条 dimension，因为"哪条路径越线"要看得出来；
#     ③ 先验层读入成本（背景索引整读 / 流程选择器 / 流程分片 / 错误表最大族）——**只量不判**：
#        先验层是检索式读取（一次 grep + ≤5 行），成本不随库大小线性涨，它的真实退化是"检索残量"
#        （两刀切完剩多少行，见 `bg_residual`）。给它配一条 token 硬线属假硬化（准入判据第三条：
#        没有复发证据），先把数量出来。
#     ④ 阶段二候选全文（≤5 条）——**只量不判**：上限是"读几条候选"，压低它就是压低证据量。
#   混进同一个分母会让"越线"这件事看不出来；只报一个总数则看不出该治哪一条。
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
# 退出码（对外契约，`--json` 与人读表**同码**）：0 = 全部在硬线内；1 = 有读入视图越过硬线
# （类视图**或兜底视图**——两条路径都算，此前兜底视图不在任何线上，24K token 的一次读没人管）；
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
# 软线 8000 ≈ 该面的 37%（到这里就该问"能不能再省"；与 ADR-0004 的 soft/hard 两级同构）。
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
    """→ {cells:[...], fallbacks:[...], views:[...], total:{...}, missing_views:[...], hard_tok, soft_tok}

    视图缺失时那一格的 `tok` 记 **None**（不是 0）：0 会被下游读成"这格免费"。

    cells     = 类视图（命中路径）
    fallbacks = ns 兜底视图（category 未定才读；单独报，不混进同一个分母）
    views     = cells + fallbacks，每条带 `kind`——两条路径都要判越线，但报告上分得开
    """
    ns = BI.collect(root)
    shard_dir = root / "knowledge" / "_index"
    cells, fallbacks, missing = [], [], []
    for ns_name in sorted(ns):
        for cat in sorted(ns[ns_name]):
            rows = ns[ns_name][cat]
            p = shard_dir / BI.shard_slug(f"{ns_name}__{cat}")
            if not p.exists():
                # 缺读侧视图 ≠ 成本为 0：量不出就记 None（"残缺"与"免费"必须不同形）
                missing.append(p.name)
            cost = _view_cost(p) if p.exists() else None
            cells.append({
                "kind": "cell", "namespace": ns_name, "category": cat, "rows": len(rows),
                "tok": cost, "per_row": (round(cost / len(rows)) if (cost is not None and rows) else None),
                "bytes": p.stat().st_size if p.exists() else 0,
            })
        fb = shard_dir / BI.shard_slug(ns_name)
        if not fb.exists():
            missing.append(fb.name)
        fb_rows = sum(len(v) for v in ns[ns_name].values())
        fb_cost = _view_cost(fb) if fb.exists() else None
        fallbacks.append({
            "kind": "fallback", "namespace": ns_name, "category": None,
            "rows": fb_rows,
            "tok": fb_cost,
            "per_row": (round(fb_cost / fb_rows) if (fb_cost is not None and fb_rows) else None),
        })
    total = {"rows": sum(c["rows"] for c in cells),
             "tok": sum(c["tok"] for c in cells if c["tok"] is not None)}
    return {"cells": cells, "fallbacks": fallbacks, "views": cells + fallbacks, "total": total,
            "hard_tok": DEFAULT_HARD_TOK, "soft_tok": SOFT_TOK, "missing_views": missing}


BG_PLAT_RE = re.compile(r"platforms: \[([^]]*)\]")
BG_CAT_RE = re.compile(r"categories: \[([^]]*)\]")
CATEGORIES = ("interrupt", "precision", "performance")


def bg_residual(root: Path) -> dict:
    """背景索引的**检索残量**：平台 + 类别两刀切完还剩多少行（**只量不判**）。

    为什么先量这个而不是先给先验层定一条 token 硬线：先验层是检索式读取——一次 grep 加
    ≤5 行上限，token 成本**不随库大小线性涨**，所以"读太多"不是它的退化形态；"翻不到"才是。
    残量（每张卡 × 每个性质要在一堆行里挑）随词条数线性增长，比 token 更早报警。
    没填 platforms 视为跨平台（与 diagnose 步骤 2 的读法一致）。
    """
    p = root / "references" / "_summary-index.yaml"
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        if not line.startswith("- "):
            continue
        mp, mc = BG_PLAT_RE.search(line), BG_CAT_RE.search(line)
        # `[]` 与 `[a, b]` 都要解析成列表：空列表 = 不限定（跨平台 / 不限类别），
        # 不能留成 `['']`——那会被读成"限定在一个叫空字符串的类别下"，静默漏行。
        plats = [x.strip() for x in mp.group(1).split(",") if x.strip()] if mp else []
        cats = [x.strip() for x in mc.group(1).split(",") if x.strip()] if mc else []
        rows.append((plats, cats))
    platforms = sorted({x for plats, _ in rows for x in plats if x and x != "cross"})
    per = []
    for plat in platforms:
        for cat in CATEGORIES:
            n = sum(1 for plats, cats in rows
                    if (not plats or plat in plats or "cross" in plats)
                    and (not cats or cat in cats))
            if n:
                per.append({"platform": plat, "category": cat, "rows": n})
    per.sort(key=lambda x: (-x["rows"], x["platform"], x["category"]))
    return {"entries": len(rows), "whole_read_tok": tok(text),
            "by_platform_category": per,
            "cross_only_by_category": {
                cat: sum(1 for plats, cats in rows
                         if plats == ["cross"] and (not cats or cat in cats))
                for cat in CATEGORIES}}


def reference_costs(root: Path) -> list:
    """先验层读入成本（**只量不判**，见文件头"四个分项"）。量不出（references/ 不在）→ 空表。"""
    ref = root / "references"
    if not ref.is_dir():
        return []
    out = []

    def add(path: Path, label: str, note: str = ""):
        if path.exists():
            out.append({"view": label, "path": str(path.relative_to(root)),
                        "tok": tok(path.read_text(encoding="utf-8")), "note": note})

    add(ref / "_summary-index.yaml", "背景索引（整读）", "别整读：取行用 grep，每轮 ≤5 行")
    add(ref / "_procedure-index.yaml", "流程选择器（每轮整读）")
    if (ref / "_procedure-index").is_dir():
        for shard in sorted((ref / "_procedure-index").glob("*.yaml")):
            add(shard, f"流程分片 {shard.stem}（只开自己那片）", "一轮最多加载一条流程")
    add(ref / "errors" / "_code-gaps.yaml", "错误码缺行索引（键触发未命中时读）")
    errs = [x for x in (ref / "errors").glob("*.yaml") if not x.name.startswith("_")]
    if errs:
        biggest = max(errs, key=lambda x: tok(x.read_text(encoding="utf-8")))
        out.append({"view": f"错误族表最大一族（{biggest.stem} / 共 {len(errs)} 族）",
                    "path": str(biggest.relative_to(root)),
                    "tok": tok(biggest.read_text(encoding="utf-8")),
                    "note": "键触发按族定位后 grep 码，不整读全族"})
    return out


def stage2_costs(root: Path) -> dict:
    """阶段二候选全文（≤5 条）：单条成本的中位与最贵 5 条合计（**只量不判**）。

    上限是"读几条候选"，不是"读多少字"——压低字数是压低证据量。所以这里只报数：
    候选全文的最坏 5 条与阶段一最贵的格子是同一量级，这笔账此前完全没记。
    """
    kdir = root / "knowledge"
    if not kdir.is_dir():
        return None
    files = [x for x in kdir.rglob("*.yaml") if not x.name.startswith("_")]
    if not files:
        return None
    toks = sorted((tok(x.read_text(encoding="utf-8")) for x in files), reverse=True)
    return {"cases": len(toks), "max": toks[0], "median": toks[len(toks) // 2],
            "top5": sum(toks[:5])}


def _row_line(v: dict, cap: int, soft: int) -> str:
    """人读表一行。越线的话术照实说「超了哪条线」，不混成一句。"""
    name = f"{v['namespace']} × {v['category']}" if v["kind"] == "cell" else v["namespace"]
    flag = ""
    if v["tok"] is None:
        flag = "  ← 量不出（视图缺失）"
    elif v["tok"] > cap:
        flag = f"  ← 超硬线 {cap}"
    elif v["tok"] > soft:
        flag = "  ← 超评估线"
    return (f"{name:43s} {v['rows']:4d} 条 "
            f"{'—' if v['tok'] is None else v['tok']:>6} tok"
            f"（{'—' if v['per_row'] is None else v['per_row']}/条）{flag}")


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
    # 越线判在**所有读入视图**上：类视图与兜底视图同一条硬线（两条读取路径都要判）。
    # 此前兜底视图被排除在外（"不在上面的硬线里"）——于是全系统最贵的一次读（vllm-ascend
    # 兜底视图 2.4 万 token）不在任何判据里，`--json` 也退 0。
    views = cells if args.cell else data["views"]
    over = [v for v in views if v["tok"] is not None and v["tok"] > args.cap]
    label = lambda v: (f"{v['namespace']}/{v['category']}" if v["kind"] == "cell" else f"{v['namespace']}（兜底）")
    if args.json:
        out = {"cells": cells, "fallbacks": [] if args.cell else fallbacks,
               "views": views if not args.cell else cells,
               "total": data["total"], "cap": args.cap, "soft_tok": data["soft_tok"],
               "over_cap": [label(v) for v in over]}
        if not args.cell:
            # 先验层与阶段二：**只量不判**（没有判据，见文件头的"四个分项"）
            out["reference"] = reference_costs(root)
            out["reference_residual"] = bg_residual(root)
            out["stage2"] = stage2_costs(root)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1 if over else 0          # 与人读表同码：机器读的那条路也要能判越线
    print(f"一次诊断的读入账（硬线 {args.cap} tok、评估线 {data['soft_tok']} tok）")
    print("① 类视图（category 已定，命中路径）：")
    for c in sorted(cells, key=lambda x: -(x["tok"] or 0)):
        print("  " + _row_line(c, args.cap, data["soft_tok"]))
    if not args.cell:
        print(f"  合计类视图 {data['total']['rows']} 条 / {data['total']['tok']} tok")
        print("② 兜底视图（category 未定才读；同一条线——它此前不在任何线上）：")
        for f in sorted(fallbacks, key=lambda x: -(x["tok"] or 0)):
            print("  " + _row_line(f, args.cap, data["soft_tok"]))
        refs, stage2, residual = reference_costs(root), stage2_costs(root), bg_residual(root)
        if refs:
            print("③ 先验层（只量不判：检索式读取，成本不随库大小涨；退化量是检索残量）：")
            for r in sorted(refs, key=lambda x: -x["tok"]):
                note = f" —— {r['note']}" if r["note"] else ""
                print(f"  {r['view']:52s} {r['tok']:>6} tok{note}")
            if residual:
                top = residual["by_platform_category"][:3]
                hot = "；".join(f"{x['platform']}×{x['category']} {x['rows']} 行" for x in top)
                print(f"  检索残量（两刀切完剩多少行，{residual['entries']} 条背景）：{hot}"
                      f"（跨平台行 interrupt {residual['cross_only_by_category']['interrupt']} / "
                      f"precision {residual['cross_only_by_category']['precision']} / "
                      f"performance {residual['cross_only_by_category']['performance']}）")
        if stage2:
            print("④ 阶段二候选全文（只量不判：上限是「读几条候选」，压低字数等于压低证据量）：")
            print(f"  {stage2['cases']} 条 case：单条中位 {stage2['median']} tok、最贵 {stage2['max']} tok"
                  f"，最贵 5 条合计 {stage2['top5']} tok")
    return 1 if over else 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
