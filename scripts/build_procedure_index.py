#!/usr/bin/env python3
# build_procedure_index.py —— 生成 references/_procedure-index.yaml（流程选择器索引）
#
# 为什么单独一个索引（EV-2026-038）：
#   流程类先验知识（type: methodology，kind: flow）的消费与"事实类"不同——
#   它要的不是"读到一句话背景"，而是"选中一条流程、读它全文、按它的判据执行"。
#   实测（三轮盲测）：
#     - 摘要行当内容用 = 与不加载等效（决定性判据会被截断，如"慢卡 = WTR 最小的卡"）；
#     - 只给 id/title/summary 的索引让 agent 自己选 → 7/7 选对。
#   所以本索引的定位是**选择器**：只用来挑"本轮该读哪条流程"，正文必须另读全文。
#   背景类索引（_summary-index.yaml）因此不再收 methodology——同一个文件两种语义
#   迟早被"简化"掉（腐化点），拆开各司其职。
#
# 用法：
#   python3 scripts/build_procedure_index.py            # 生成
#   python3 scripts/build_procedure_index.py --check    # 新鲜度校验（CI：reference-validation job）
#
# 只收 status: active 的 methodology 词条（未验证的先验不进诊断上下文）。

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

OUT_NAME = "_procedure-index.yaml"
SUMMARY_CAP = 200

_DATE_RE = re.compile(r"# 生成日期：\d{4}-\d{2}-\d{2}")


def _normalize_date(text: str) -> str:
    return _DATE_RE.sub("# 生成日期：<YYYY-MM-DD>", text)


def collect(refs_dir: Path):
    out = []
    for p in sorted(refs_dir.rglob("*.yaml")):
        if p.name.startswith("_") or "_archive" in p.parts:
            continue
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if d.get("type") != "methodology" or d.get("status") != "active":
            continue
        ap = d.get("applies_to") or {}
        summary = " ".join(str(d.get("summary", "")).split())
        if len(summary) > SUMMARY_CAP:
            summary = summary[: SUMMARY_CAP - 1] + "…"
        out.append(
            {
                "id": d.get("id", ""),
                "title": " ".join(str(d.get("title", "")).split()),
                "summary": summary,
                "categories": list(ap.get("categories") or []),
                "platforms": list(ap.get("platforms") or []),
                "file": str(p.relative_to(refs_dir.parent)),
            }
        )
    out.sort(key=lambda e: e["id"])
    return out


def render(entries) -> str:
    """生成索引文本。

    **必须整篇经 yaml.safe_dump 输出**：早先逐行拼接 + safe_dump 单个标量会在默认
    width=80 处折行，折出来的续行顶掉缩进 → 产物不是合法 YAML（而 --check 只比文本、
    比的是两次同样错误的生成结果，属自证式校验，CI 全绿也发现不了）。
    """
    header = [
        "# GENERATED FILE —— 流程选择器索引（diagnose 方法缺口消费点读它），不要手改。",
        "# 由 scripts/build_procedure_index.py 生成；--check 校验新鲜度 + 可解析性（CI）。",
        "#",
        "# 用法（形态归 SKILL、内容归词条）：",
        "#   1) 按本轮 category 过滤 categories——**该列为空 = 不限定类别，照常进入候选**；",
        "#   2) 用 title/summary 选**一条**最贴合的流程（本索引只是选择器，不是内容）；",
        "#   3) 按 file 打开该词条读 **content.flow[] 全文**——摘要行不承载判据，只读摘要等于没加载；",
        "#   4) 一轮诊断最多加载一条流程（成本有界）。",
        "#",
        f"# 生成日期：{date.today()}    流程条数：{len(entries)}    本文件整体加载成本：约 "
        f"{round(len(''.join(str(e) for e in entries)) / 2.6)} token（选择器每次都要整读，故单文件 + 记成本）",
        "#",
        "# 增长闸门（原则十一：按闸门不按日历）：流程条数 > 25，或本文件 > 5K token → 按 category 分片",
        "#   （对齐 case 层 knowledge/_index/<ns>__<category>.yaml 的做法）。当前单文件即可。",
    ]
    doc = {
        "entries": [
            {
                "id": e["id"],
                "title": e["title"],
                "summary": e["summary"],
                "categories": e["categories"],
                "platforms": e["platforms"],
                "file": e["file"],
            }
            for e in entries
        ]
    }
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=10 ** 6, default_flow_style=False)
    return "\n".join(header) + "\n" + body


def parses(text: str) -> str:
    """返回空串 = 可解析；否则返回错误描述。"""
    try:
        d = yaml.safe_load(text)
    except Exception as e:
        return str(e).splitlines()[0]
    if not isinstance(d, dict) or not isinstance(d.get("entries"), list):
        return "解析结果不是 {entries: [...]}"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    refs = root / "references"
    out_path = refs / OUT_NAME
    entries = collect(refs)
    text = render(entries)
    if args.check:
        if not out_path.exists():
            print(f"{OUT_NAME} 不存在——运行 scripts/build_procedure_index.py 生成")
            return 1
        old = out_path.read_text(encoding="utf-8")
        # ① 产物必须能解析（防"生成器坏了但 --check 仍是绿的"自证式校验：
        #    只比文本 = 比两次同样错误的生成结果，发现不了结构损坏）
        err = parses(old)
        if err:
            print(f"{OUT_NAME} 不是合法 YAML：{err}")
            return 1
        # ② 新鲜度
        if _normalize_date(old) != _normalize_date(text):
            print(f"{OUT_NAME} 过期——references/ 有变更未重建（运行 scripts/build_procedure_index.py）")
            return 1
        print(f"procedure 索引新鲜且可解析（{len(entries)} 条流程）")
        return 0
    err = parses(text)
    if err:
        print(f"生成失败：产物不是合法 YAML：{err}")
        return 1
    out_path.write_text(text, encoding="utf-8")
    print(f"已生成 {out_path}（{len(entries)} 条流程）")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio

    pin_utf8_stdio()
    sys.exit(main())
