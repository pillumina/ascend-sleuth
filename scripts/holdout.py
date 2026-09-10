#!/usr/bin/env python3
# holdout.py —— 维护者独占的对照集（eval/golden/ 中被"封存"的那部分）
#
# 为什么需要它：`eval/golden/` 在 agent（以及任何贡献者）的可写面内，而且
# `docs/eval.md` §套件如何演化 **明确要求 groom 跟着 case 改夹具**（case 的 fix 变了，
# 夹具的期望要同步）。于是"golden 无回归"实际上是一个**可控信号**：改动者既能改被测
# 对象、也能改对照标准。这是"CI 绿 + 测试过 → 就合入"这一做法的根本缺口——
# **检查者不能靠写文字（或改夹具）通过检查，检查才是独立的。**
#
# 做法：把一部分夹具**按内容哈希封存**。封存后：
#   - 任何人改了封存夹具的内容 → `--check` 直接红（不需要比对 diff，哈希就是判据）；
#   - 要合法改（case 的 fix 确实变了）→ 维护者显式 `--reseal`，并在 PR 里带
#     `holdout-change` 标签（CI 闸门），使"改量尺"这件事在评审面上可见。
#
# 判据强度（原则十，如实标注）：
#   - **哈希比对是硬门**：改内容必红，绕不过（除非同时改 eval/holdout.yaml）。
#   - **"谁有权 reseal"是半硬**：标签闸门由 CI 强制，但在 CODEOWNERS/分支保护落实前，
#     有写权限者仍可自行打标签。真正的独立性随 CODEOWNERS 到位（见 CODEOWNERS.example
#     的 eval/holdout.yaml 条目）——在那之前不要把它读成"人已把关"。
#   - **覆盖面报告是软信号**：`--list` 报出"有 case 却没有夹具"的格子（不改 CI 结论），
#     因为补夹具需要真实数据，不能凭空造（原则十：不假装覆盖）。
#
# 用法：
#   python3 scripts/holdout.py --check            # CI：逐条核对哈希（改了即红）
#   python3 scripts/holdout.py --list             # 列对照集 + 覆盖面缺口
#   python3 scripts/holdout.py --json             # 同上，机器可读
#   python3 scripts/holdout.py --reseal --all     # 维护者：重新封存全部
#   python3 scripts/holdout.py --reseal --id <夹具文件名>
#
# 退出码：0 = 一致 / 无对照集；1 = 有夹具被改动或缺失；2 = 用法错。

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import yaml

MANIFEST = "eval/holdout.yaml"
GOLDEN = "eval/golden"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(root: Path):
    p = root / MANIFEST
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def save_manifest(root: Path, doc):
    (root / MANIFEST).write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def entries_of(doc):
    return [e for e in (doc or {}).get("entries") or [] if isinstance(e, dict) and e.get("fixture")]


# ---------------------------------------------------------------- 覆盖面（软信号）
def cell_of(root: Path, path: Path, category) -> tuple:
    """文件路径 + category → (namespace, category)。

    目录分层是 (framework × category)（ADR-0004 容量治理），因此 category 目录
    同时出现在路径末段与 category 字段里——只保留一次，否则会得到
    `inference/vllm-ascend/interrupt/interrupt` 这种自我重复的格子名。
    """
    rel = list(path.relative_to(root).parts[1:-1])   # 去 knowledge/ 与文件名
    cat = str(category if category is not None else "?")
    if rel and rel[-1] == cat:
        rel = rel[:-1]
    return "/".join(rel), cat


def populated_cells(root: Path):
    """knowledge/ 里 (namespace, category) 有 case 的格子。"""
    cells = set()
    for dirpath, _d, files in os.walk(root / "knowledge"):
        if "_archive" in dirpath:
            continue
        for f in files:
            if not f.endswith(".yaml") or f.startswith("_"):
                continue
            p = Path(dirpath) / f
            try:
                d = yaml.safe_load(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            for c in (d or {}).get("cases") or []:
                if isinstance(c, dict) and c.get("id"):
                    cells.add(cell_of(root, p, c.get("category")))
    return cells


def covered_cells(root: Path):
    """eval/golden/ 里夹具覆盖到的格子（按夹具引用的 case 反查）。"""
    where = {}
    for dirpath, _d, files in os.walk(root / "knowledge"):
        if "_archive" in dirpath:
            continue
        for f in files:
            if not f.endswith(".yaml") or f.startswith("_"):
                continue
            p = Path(dirpath) / f
            try:
                d = yaml.safe_load(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            for c in (d or {}).get("cases") or []:
                if isinstance(c, dict) and c.get("id"):
                    where[str(c["id"])] = cell_of(root, p, c.get("category"))
    cells, orphans = set(), []
    for f in sorted((root / GOLDEN).glob("*.fixture.yaml")):
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        cid = str(d.get("case_id") or "")
        if cid in where:
            cells.add(where[cid])
        else:
            orphans.append(f.name)
    return cells, orphans


# ---------------------------------------------------------------- 子命令
def cmd_check(root: Path) -> int:
    doc = load_manifest(root)
    if doc is None:
        print(f"未找到 {MANIFEST}——跳过（对照集未建立）")
        return 0
    entries = entries_of(doc)
    if not entries:
        print(f"{MANIFEST} 无 entries——跳过")
        return 0

    bad = []
    for e in entries:
        fx = root / GOLDEN / str(e["fixture"])
        want = str(e.get("sha256") or "")
        if not fx.exists():
            bad.append(f"{e['fixture']}: 文件不存在（封存的对照夹具被删除）")
            continue
        got = sha256_of(fx)
        if got != want:
            bad.append(f"{e['fixture']}: 内容已变（封存期望 {want[:12]}…／实测 {got[:12]}…）")

    if bad:
        print(f"holdout --check: {len(bad)} 项不一致")
        for b in bad:
            print(f"  - {b}")
        print("  → 封存的对照集是维护者的量尺：改动它需要显式 reseal + PR 带 holdout-change 标签。"
              "若这是 case 内容变更带来的合法同步，请由维护者执行 "
              "`python3 scripts/holdout.py --reseal --all`；否则说明被测行为已改变。")
        return 1
    print(f"holdout --check: OK（{len(entries)} 条封存夹具内容未被改动）")
    return 0


def cmd_reseal(root: Path, all_: bool, fixture: str | None) -> int:
    doc = load_manifest(root)
    if doc is None:
        doc = {"version": 1, "entries": []}
    entries = entries_of(doc)
    if not entries:
        print("对照集为空——请先手工建 eval/holdout.yaml 的 entries（选哪些夹具封存是你的决定）")
        return 2

    changed = []
    for e in entries:
        if not all_ and fixture and str(e["fixture"]) != fixture:
            continue
        if not all_ and not fixture:
            print("需要 --all 或 --id <夹具文件名>")
            return 2
        fx = root / GOLDEN / str(e["fixture"])
        if not fx.exists():
            print(f"  ! {e['fixture']} 不存在——跳过")
            continue
        old, new = str(e.get("sha256") or ""), sha256_of(fx)
        e["sha256"] = new
        if old != new:
            changed.append(f"{e['fixture']}: {old[:12] or '(空)'}… → {new[:12]}…")

    save_manifest(root, doc)
    if changed:
        print(f"holdout --reseal: 更新 {len(changed)} 条封存哈希")
        for c in changed:
            print(f"  - {c}")
        print("  → 请随 PR 带 holdout-change 标签，让'改量尺'在评审面上可见")
    else:
        print("holdout --reseal: 无变化")
    return 0


def cmd_list(root: Path, as_json: bool) -> int:
    doc = load_manifest(root)
    entries = entries_of(doc)
    pop = populated_cells(root)
    cov, orphans = covered_cells(root)
    gaps = sorted(pop - cov)

    if as_json:
        print(json.dumps({
            "holdout": [{"fixture": e["fixture"], "covers": e.get("covers"),
                         "why": e.get("why")} for e in entries],
            "golden_cells": sorted("/".join(c) for c in cov),
            "populated_cells_without_fixture": sorted("/".join(c) for c in gaps),
            "fixtures_without_ingested_case": orphans,
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"封存对照集（{MANIFEST}，{len(entries)} 条）")
    for e in entries:
        print(f"  {e['fixture']:36s} {e.get('covers', '-'):34s} {str(e.get('why') or '')[:44]}")
    if not entries:
        print("  （空——对照集未建立）")
    print(f"\n夹具覆盖的格子（{len(cov)}）: " + "、".join(sorted("/".join(c) for c in cov)))
    if orphans:
        print(f"引用了未入库 case 的夹具: " + "、".join(orphans))
    if gaps:
        print(f"\n⚠ 有 case 但没有夹具的格子（{len(gaps)}）——这段知识没有任何回归保护:")
        for g in sorted("/".join(c) for c in gaps):
            print(f"    {g}")
        print("  （软信号：补夹具需要真实数据，不能凭空造；本项不改 CI 结论）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="维护者独占的对照集（封存夹具哈希）")
    ap.add_argument("--check", action="store_true", help="CI：核对封存哈希")
    ap.add_argument("--list", action="store_true", help="列对照集与覆盖面缺口")
    ap.add_argument("--json", action="store_true", help="配合 --list 输出 JSON")
    ap.add_argument("--reseal", action="store_true", help="维护者：重新封存")
    ap.add_argument("--all", action="store_true", help="配合 --reseal 全量")
    ap.add_argument("--id", dest="fixture", help="配合 --reseal 指定夹具文件名")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()

    root = args.root.resolve()
    if args.reseal:
        return cmd_reseal(root, args.all, args.fixture)
    if args.list:
        return cmd_list(root, args.json)
    if args.check:
        return cmd_check(root)
    ap.error("需要 --check / --list / --reseal 之一")
    return 2


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
