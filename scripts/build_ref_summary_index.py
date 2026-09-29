#!/usr/bin/env python3
# build_ref_summary_index.py —— 生成 references/_summary-index.yaml（诊断步骤 2 收尾的背景层索引）
#
# 目的（B1 EV-2026-026）：diagnose 原先为"扫 references/<type-dir>/*.yaml
# 只读 summary+applies_to"，需逐文件读全文找字段；本索引把**背景类
# （platform-fact/software-fact/tool）+ status=active** 词条压缩为**一行一条**
# {id/type/title/summary(≤160c)/applies_to.platforms+categories}，读侧一次 grep 就够
# （一行一条是 2026-09-29 改的：块状 YAML 一条占 5~7 行，一趟 grep 拿不到整条）。
# 体积随词条数线性增长——所以**读侧按 grep 取行 + ≤5 行上限，不整读**（EV-2026-093）。
# categories 入索引（EV-2026-037）：按本轮 category 收窄背景加载，
# 声明了 categories 的词条不再无条件灌进上下文；空列表 = 不限定类别。
# 查表类（error-code/fault-pattern/env-var-table/compat-matrix/command-side-effect）
# 不进 summary 层（签名/名是检索键，走步骤 2 收尾的键触发 grep）——与 skill 口径一致。
#
# 用法：
#   python3 scripts/build_ref_summary_index.py            # 生成 references/_summary-index.yaml
#   python3 scripts/build_ref_summary_index.py --check    # 新鲜度校验（CI：reference-validation job）
# --check 返回非零 = 过期（对称 build_index / verify_references）。

import argparse
import sys
from pathlib import Path

import yaml

from _stdio import write_text_lf

# methodology **不在背景类**（EV-2026-038）：流程类要的不是"读一行背景"而是
# "选中一条、读全文、按判据执行"——摘要行当内容用与不加载等效（决定性判据会被截断）。
# 它走独立的 references/_procedure-index.yaml（选择器，scripts/build_procedure_index.py）。
BG_TYPES = {"platform-fact", "software-fact", "tool"}
OUT_NAME = "_summary-index.yaml"
SUMMARY_CAP = 160

# 生成物里不写日期（原先是「写日期戳 + --check 归一化掉再比」）：那样做每次重建都改同一行，
# 并发合并时必撞，而日期本身的信息量为零——「这份索引什么时候重建的」看 git 历史即可。
# 不写日期之后 --check 就能逐字节比较，反而更强：任何多出来的行都报过期，不必再归一化什么。
def platforms_of(entry) -> list:
    ap = entry.get("applies_to")
    if isinstance(ap, dict):
        pl = ap.get("platforms")
        return list(pl) if isinstance(pl, list) else []
    return []


def categories_of(entry) -> list:
    ap = entry.get("applies_to")
    if isinstance(ap, dict):
        c = ap.get("categories")
        return list(c) if isinstance(c, list) else []
    return []


def _flat(v) -> str:
    """值里的换行折成空格——「一行一条」是硬约束，折行会让 grep 的命中行不再是完整条目。"""
    return " ".join(str(v).split())


def render_row(row) -> str:
    """一条索引 → 一行 YAML（flow style，不折行）。

    为什么强制一行（2026-09-29）：读侧协议是「grep 取行 + ≤5 行上限」，而块状 YAML 一条占 5~7 行——
    按平台 grep 只命中 `platforms:` 那行（拿不到 id/title），按组件词 grep 只命中 title/summary 行
    （拿不到平台），同一条词条要两趟扫才拼得出来，而"两趟的命中各算一条还是算半条"没有答案。
    一行一条之后，一次 grep 命中即整条：id / type / title / summary / 平台 / 类别都在同一行上。
    """
    out = yaml.safe_dump(row, allow_unicode=True, sort_keys=False,
                         default_flow_style=True, width=10 ** 9).strip()
    if "\n" in out:  # 兜底：flow style 仍折行说明有值带换行（_flat 已防，防不住就报出来而不是静默破格式）
        raise ValueError(f"索引行折行了（一行一条是硬约束）：{row.get('id')}")
    return out


def render(doc_entries) -> str:
    rows = []
    for e in sorted(doc_entries, key=lambda x: x.get("id", "")):
        s = _flat(e.get("summary") or "")
        if len(s) > SUMMARY_CAP:
            s = s[:SUMMARY_CAP] + "…"
        # categories 入索引（EV-2026-037）：原只按平台过滤，精度/性能问题会把
        # 无关平台背景全灌进上下文；声明了 categories 的词条可按本轮 category 再收窄。
        # 未声明 categories 的词条 = 不限定类别——**不输出该键**（省行宽，原则九）。
        applies_to = {"platforms": e.get("_platforms", [])}
        cats = e.get("_categories", [])
        if cats:
            applies_to["categories"] = cats
        rows.append({
            "id": e.get("id", ""), "type": e.get("type", ""),
            "title": _flat(e.get("title", "")), "summary": s,
            "applies_to": applies_to,
        })
    n = len(rows)
    header = "\n".join([
        "# GENERATED FILE —— 背景类 summary 索引（diagnose 步骤 2 收尾读取，先于候选加载），不要手改。",
        "# 由 scripts/build_ref_summary_index.py 生成；--check 校验新鲜度（CI）。",
        "# 只含背景类 + status=active；查表类同样在步骤 2 收尾按检索键 grep（口径同 diagnose SKILL）。",
        "# 读法：**一行一条**（`- {id: …, type: …, title: …, summary: …, applies_to: {platforms: […], categories: […]}}`）——",
        "#   一次 grep 命中即整条；先按 applies_to 收窄，再在命中的行上按组件/工具词挑，每轮 ≤5 条。",
        "#   整读等于注入全库背景（索引随词条数增长），别整读。",
        "# applies_to.categories 缺省 = 不限定问题类别（照常加载）；有值则按本轮 category 收窄。",
        f"# 词条数：{n}",
        "# 不写生成日期：日期进 git 会让每次重建都改同一行，并发合并时必撞（口径同 build_index.py）。",
        "",
    ])
    return header + "entries:\n" + "".join(f"- {render_row(r)}\n" for r in rows)


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
        d["_categories"] = categories_of(d)
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
        # 整篇比较，不做任何归一化：生成物里没有日期这类「每次重建都变」的字段，
        # 也就没有要容忍的差异。read_text 会把 CRLF 折成 LF，所以 Windows 检出不会因此假红。
        if out.read_text(encoding="utf-8") != text:
            print(f"{OUT_NAME} 过期（references 变更后需重新生成并提交）")
            sys.exit(1)
        print(f"reference summary 索引新鲜（{len(entries)} 条背景类词条）。")
        return
    write_text_lf(out, text)
    print(f"已生成 {out}（{len(entries)} 条背景类词条）")


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
