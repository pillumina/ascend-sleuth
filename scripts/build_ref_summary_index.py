#!/usr/bin/env python3
# build_ref_summary_index.py —— 生成 references/_summary-index.yaml（诊断 2.5 背景层索引）
#
# 目的（B1 EV-2026-026）：diagnose 阶段 2.5 ②（平台背景 summary 层）原"扫
# references/<type-dir>/*.yaml 只读 summary+applies_to"需逐文件读全文找字段；
# 本索引把**背景类（platform-fact/software-fact/tool/methodology）+ status=active**
# 词条压缩为每行 {id/type/title/summary(≤160c)/applies_to.platforms}，单文件 ~20KB 封顶，
# 且随词条数线性增长的只是索引行（远小于逐文件扫描）。
# 查表类（error-code/fault-pattern/env-var-table/compat-matrix/command-side-effect）
# 不进 summary 层（签名/名是检索键，走 diagnose 2.5 ③ 按需 grep）——与 skill 口径一致。
#
# 用法：
#   python3 scripts/build_ref_summary_index.py            # 生成 references/_summary-index.yaml
#   python3 scripts/build_ref_summary_index.py --check    # 新鲜度校验（CI：reference-validation job）
# --check 返回非零 = 过期（对称 build_index / verify_references）。

import argparse
import sys
from datetime import date
from pathlib import Path

import yaml

BG_TYPES = {"platform-fact", "software-fact", "tool", "methodology"}
OUT_NAME = "_summary-index.yaml"
SUMMARY_CAP = 160


def platforms_of(entry) -> list:
    ap = entry.get("applies_to")
    if isinstance(ap, dict):
        pl = ap.get("platforms")
        return list(pl) if isinstance(pl, list) else []
    return []


def render(doc_entries) -> str:
    rows = []
    for e in sorted(doc_entries, key=lambda x: x.get("id", "")):
        s = e.get("summary") or ""
        if len(s) > SUMMARY_CAP:
            s = s[:SUMMARY_CAP] + "…"
        rows.append({
            "id": e.get("id", ""), "type": e.get("type", ""),
            "title": e.get("title", ""), "summary": s,
            "applies_to": {"platforms": e.get("_platforms", [])},
        })
    n = len(rows)
    header = "\n".join([
        "# GENERATED FILE —— 背景类 summary 索引（diagnose 2.5 ② 读取），不要手改。",
        "# 由 scripts/build_ref_summary_index.py 生成；--check 校验新鲜度（CI）。",
        "# 只含背景类 + status=active；查表类走 2.5 ③ 按需 grep（口径同 diagnose SKILL）。",
        f"# 生成日期：{date.today().isoformat()}    词条数：{n}",
        "",
    ])
    return header + yaml.safe_dump({"entries": rows}, allow_unicode=True,
                                   sort_keys=False, default_flow_style=False, width=100)


def collect(refs_dir: Path):
    out = []
    for p in sorted(refs_dir.rglob("*.yaml")):
        if p.name.startswith("_"):
            continue
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if d.get("type") not in BG_TYPES:
            continue
        if d.get("status") not in (None, "active"):
            continue
        d["_platforms"] = platforms_of(d)
        out.append(d)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    refs = root / "references"
    out = refs / OUT_NAME
    entries = collect(refs)
    text = render(entries)
    if args.check:
        if not out.exists():
            print(f"{OUT_NAME} 不存在 —— 先运行 scripts/build_ref_summary_index.py 生成")
            sys.exit(1)
        if out.read_text(encoding="utf-8") != text:
            print(f"{OUT_NAME} 过期（references 变更后需重新生成并提交）")
            sys.exit(1)
        print(f"reference summary 索引新鲜（{len(entries)} 条背景类词条）。")
        return
    out.write_text(text, encoding="utf-8")
    print(f"已生成 {out}（{len(entries)} 条背景类词条）")


if __name__ == "__main__":
    sys.exit(main())
