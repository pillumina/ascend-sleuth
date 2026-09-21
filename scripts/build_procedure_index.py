#!/usr/bin/env python3
# build_procedure_index.py —— 生成流程选择器索引（references/_procedure-index.yaml + 按 category 分片）
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
# 为什么按 category 分片（2026-09 修；触发条件是本文件自己写下的增长闸门）：
#   单文件形态自带一条闸门注释："流程条数 > 25，或本文件 > 5K token → 按 category 分片"。
#   实测已越界（32 条 / 约 5387 token），而每次走方法缺口都要**整读**这份选择器才挑 1 条——
#   5K token 的固定开销压在推理预算上（原则九），触发得起才谈得上用。分片后本轮只需读
#   "本轮 category 的那一片"（interrupt 约 1.9K / precision 约 2.7K / performance 约 1.3K）。
#   注意这是**成本**论断，不是准确率论断：三轮盲测证明的是"给了 id/title/summary 就能选对"，
#   不含"读全 32 条比读 11 条选得更准"的证据。选择语义不变（仍是按 title/summary 选一条）。
#
# 形态（对齐 case 层 knowledge/_index/<ns>__<category>.yaml 的分片做法）：
#   references/_procedure-index.yaml          选择器：总条数 + category → 分片文件 + 成本
#   references/_procedure-index/<category>.yaml  分片：该 category 的完整选择器行
#   references/_procedure-index/_cross.yaml      不限定类别（applies_to.categories 为空）的流程
# 读侧只需一次：读选择器 → 按本轮 category 打开对应分片（+ `_cross`）。一轮最多加载一条流程。
#
# 用法：
#   python3 scripts/build_procedure_index.py            # 生成选择器 + 全部分片
#   python3 scripts/build_procedure_index.py --check    # 新鲜度 + 可解析（CI：reference-validation job）
#
# 只收 status: active 的 methodology 词条（未验证的先验不进诊断上下文）。

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

from _stdio import write_text_lf

OUT_NAME = "_procedure-index.yaml"
SHARD_DIR_NAME = "_procedure-index"
CROSS_KEY = "_cross"                # 不限定类别的分片键（任何 category 都要一并打开）
SUMMARY_CAP = 200
SELECTOR_CAP_TOKENS = 2000          # 选择器自身的成本上限（它每次都要整读）

_DATE_RE = re.compile(r"# 生成日期：\d{4}-\d{2}-\d{2}")


def _normalize_date(text: str) -> str:
    return _DATE_RE.sub("# 生成日期：<YYYY-MM-DD>", text)


def _tokens(text: str) -> int:
    """成本口径与旧版一致（按字符数 / 2.6 估）——留着是为了这个数可比，不是精确计量。"""
    return round(len(text) / 2.6)


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
                # 一律 POSIX：str(Path) 在 Windows 上给反斜杠，生成物与 Linux 不一致 → --check 永久红
                "file": p.relative_to(refs_dir.parent).as_posix(),
            }
        )
    out.sort(key=lambda e: e["id"])
    return out


def shard_keys(entries) -> list:
    """分片键 = 各流程声明过的 category（保序）+ `_cross`（不限定类别的流程）。

    不从 triage-tree 取全集：那会生成空分片，而空分片是"读了一片什么都没有"的纯成本。
    但**缺片要能被发现**——读侧若按 triage category 找不到分片，就该退回读选择器列出的
    全部分片（诚实退化），而不是静默当作"没有可用流程"。"""
    cats = []
    for e in entries:
        for c in e["categories"]:
            if c not in cats:
                cats.append(c)
    keys = sorted(cats)
    if any(not e["categories"] for e in entries):
        keys.append(CROSS_KEY)                # 排在最后（保序 + 可预测）
    return keys


def entries_for(entries, key):
    if key == CROSS_KEY:
        return [e for e in entries if not e["categories"]]
    return [e for e in entries if key in e["categories"]]


def _render_entries(entries) -> str:
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
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=10 ** 6, default_flow_style=False)


def render_shard(key, entries, root: Path) -> str:
    """分片 = 完整选择器行（title/summary 是选择的依据，不能截得比选择所需更短）。

    **必须整篇经 yaml.safe_dump 输出**：早先逐行拼接 + safe_dump 单个标量会在默认
    width=80 处折行，折出来的续行顶掉缩进 → 产物不是合法 YAML（而 --check 只比文本、
    比的是两次同样错误的生成结果，属自证式校验，CI 全绿也发现不了）。"""
    scope = "不限定类别（applies_to.categories 为空，任何 category 都进入候选）" if key == CROSS_KEY \
        else f"category = {key}"
    body = _render_entries(entries)
    selector = (root / "references" / OUT_NAME).relative_to(root).as_posix()
    header = [
        f"# GENERATED FILE —— 流程选择器分片（{scope}），不要手改。",
        "# 由 scripts/build_procedure_index.py 生成；--check 校验新鲜度 + 可解析性（CI）。",
        "#",
        "# 用法：按 file 打开词条读 **content.flow[] 全文**——摘要行不承载判据，只读摘要等于没加载",
        "#   （反直觉判据会被截断，例：摘要写\"同步比例 > 0.2 则存在慢卡\"，漏掉\"慢卡 = WTR 最小的卡\"）。",
        "#   一轮诊断最多加载一条流程（成本有界）。选择器与全部分片清单见：",
        f"#   {selector}",
        "#",
        f"# 生成日期：{date.today()}    本片流程条数：{len(entries)}    本片加载成本：约 {_tokens(body)} token",
    ]
    return "\n".join(header) + "\n" + body


def render_selector(entries, keys, root: Path) -> str:
    shard_lines = []
    for key in keys:
        sub = entries_for(entries, key)
        path = f"references/{SHARD_DIR_NAME}/{key}.yaml"
        # 用真实文本量估，不用条目数估：一条长 title 与三条短 title 的成本可以相等
        text = _render_entries(sub)
        shard_lines.append(
            {
                "category": key,
                "shard": path,
                "procedures": len(sub),
                "tokens": _tokens(text),
            }
        )
    doc = {
        "procedures_total": len(entries),
        "shards": shard_lines,
    }
    body = yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=10 ** 6, default_flow_style=False)
    header = [
        "# GENERATED FILE —— 流程选择器（diagnose 方法缺口消费点先读它），不要手改。",
        "# 由 scripts/build_procedure_index.py 生成；--check 校验新鲜度 + 可解析性（CI）。",
        "#",
        "# 用法（形态归 SKILL、内容归词条）：",
        "#   1) 读本选择器的 shards，找本轮 category 那一行（`_cross` 不限定类别，任何 category 都要一并打开）；",
        "#   2) 按 shard 字段打开该分片，用 title/summary 选**一条**最贴合的流程（本选择器只是路由，不是内容）；",
        "#   3) 按该行的 file 打开词条读 **content.flow[] 全文**——摘要行不承载判据，只读摘要等于没加载；",
        "#   4) 一轮诊断最多加载一条流程（成本有界）。",
        "#   5) **本 category 没有对应分片**（索引里没这一行）→ 读本选择器列出的**全部分片**再选，",
        "#      并在 trace 里记下\"本 category 无专用分片\"——空手去深度排查与\"没有可用流程\"是两件事。",
        "#",
        f"# 生成日期：{date.today()}    流程条数：{len(entries)}    分片数：{len(keys)}    "
        f"本文件整体加载成本：约 {_tokens(body)} token",
        "#",
        "# 为什么分片：单文件形态下每次都要整读全部流程行才挑 1 条（5K token 级），这笔固定开销",
        "#   会压低方法缺口消费点的使用意愿；分片后本轮只读自己那一片（判据与数值见 shards）。",
        f"# 分片自身的上限：单片 > 6K token，或单 category 流程 > 30 条 → 该 category 再按",
        "#   platforms 细分（当前未越界，越界时在这里加行而不是加日历）。",
    ]
    return "\n".join(header) + "\n" + body


def parses_shard(text: str) -> str:
    """返回空串 = 可解析；否则返回错误描述。分片形态：{entries: [...]}"""
    try:
        d = yaml.safe_load(text)
    except Exception as e:
        return str(e).splitlines()[0]
    if not isinstance(d, dict) or not isinstance(d.get("entries"), list):
        return "解析结果不是 {entries: [...]}"
    return ""


def parses_selector(text: str) -> str:
    """选择器形态：{procedures_total: int, shards: [...]}——与分片不同形，各自校验。

    两种形态分开校验而不是共用一句"能解析就算过"：只判能解析的话，把选择器写成
    分片形态（或反过来）照样全绿，而读侧拿到的是一个没有 shards 字段的文件。"""
    try:
        d = yaml.safe_load(text)
    except Exception as e:
        return str(e).splitlines()[0]
    if not isinstance(d, dict) or not isinstance(d.get("shards"), list) or not d["shards"]:
        return "解析结果不是 {procedures_total, shards: [...]}"
    for i, s in enumerate(d["shards"]):
        if not isinstance(s, dict) or not {"category", "shard", "procedures", "tokens"} <= set(s):
            return f"shards[{i}] 字段不全（需 category/shard/procedures/tokens）"
        if not str(s["shard"]).startswith("references/"):
            return f"shards[{i}].shard '{s['shard']}' 不是 references/ 下的仓库内路径"
    return ""


def expected_outputs(root: Path):
    """返回 {相对路径: 文本}。生成与 --check 共用同一份真值，避免两处各算一遍。"""
    refs = root / "references"
    entries = collect(refs)
    keys = shard_keys(entries)
    outs = {OUT_NAME: render_selector(entries, keys, root)}
    for key in keys:
        outs[f"{SHARD_DIR_NAME}/{key}.yaml"] = render_shard(key, entries_for(entries, key), root)
    return outs, entries, keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root", default=None)
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    refs = root / "references"
    outs, entries, keys = expected_outputs(root)

    if args.check:
        problems = []
        for rel, text in outs.items():
            p = refs / rel
            if not p.exists():
                problems.append(f"{rel} 不存在——运行 scripts/build_procedure_index.py 生成")
                continue
            old = p.read_text(encoding="utf-8")
            # ① 产物必须能解析（防"生成器坏了但 --check 仍是绿的"自证式校验：
            #    只比文本 = 比两次同样错误的生成结果，发现不了结构损坏）
            err = parses_selector(old) if rel == OUT_NAME else parses_shard(old)
            if err:
                problems.append(f"{rel} 形态不合法：{err}")
                continue
            # ② 新鲜度
            if _normalize_date(old) != _normalize_date(text):
                problems.append(f"{rel} 过期——references/ 有变更未重建（运行 scripts/build_procedure_index.py）")
        # ②b 选择器指向的分片必须存在（生成路径拿到的是还没写盘的文件，故这条只在 --check 判）
        sel_problems = []
        sel_doc = yaml.safe_load(outs[OUT_NAME])
        for s in sel_doc["shards"]:
            if not (root / s["shard"]).exists():
                sel_problems.append(f"选择器指向的分片不存在：{s['shard']}")
        problems += sel_problems
        # ③ 残留分片：词条的 categories 被改过之后，旧分片不会被上面的循环看到——
        #    它会留在目录里被读侧当成"本轮 category 有专用分片"，是一处静默误导。
        shard_dir = refs / SHARD_DIR_NAME
        if shard_dir.exists():
            expected = {r for r in outs if r.startswith(SHARD_DIR_NAME)}
            for p in sorted(shard_dir.glob("*.yaml")):
                rel = p.relative_to(refs).as_posix()
                if rel not in expected:
                    problems.append(f"{rel} 是残留分片（该 category 已无流程）——删除后重建索引")
        # ④ 完整性：每条 active methodology 必须在**它声明的每个 category**的分片里出现。
        #    分片最危险的失败模式是"某条流程既不在这片也不在那片"——索引全绿而流程静默消失。
        #    多 category 的流程**有意**出现在多片（读侧只打开本轮那一片，不会重复加载）；
        #    所以这里按 (分片, 条目) 判，而不是全局去重。
        for key in keys:
            got = {e["id"] for e in yaml.safe_load(outs[f"{SHARD_DIR_NAME}/{key}.yaml"])["entries"]}
            want = {e["id"] for e in entries_for(entries, key)}
            if want - got:
                problems.append(f"分片 {key} 缺条目（流程静默消失）：{sorted(want - got)}")
            if got - want:
                problems.append(f"分片 {key} 混入不属于它的条目：{sorted(got - want)}")
        # ④b 选择器声明的 category 集合必须与分片集合一致（防"选择器漏了一行 → 那一片没人读"）
        sel = yaml.safe_load(outs[OUT_NAME])
        sel_cats = [s["category"] for s in sel["shards"]]
        if sel_cats != keys:
            problems.append(f"选择器的 shards 顺序/集合与分片不一致：{sel_cats} != {keys}")
        if sel.get("procedures_total") != len(entries):
            problems.append(
                f"选择器 procedures_total={sel.get('procedures_total')} 与实收 {len(entries)} 条不符"
            )
        # ⑤ 选择器自身成本上限：它是每次都要整读的那一份
        sel_tokens = _tokens(outs[OUT_NAME])
        if sel_tokens > SELECTOR_CAP_TOKENS:
            problems.append(
                f"{OUT_NAME} 约 {sel_tokens} token > 上限 {SELECTOR_CAP_TOKENS}——"
                f"选择器每次都要整读，涨到这一步就该把 category 分组再收一层"
            )
        if problems:
            print("\n".join(problems))
            return 1
        print(
            f"procedure 索引新鲜且可解析（{len(entries)} 条流程 / {len(keys)} 片，"
            f"选择器约 {sel_tokens} token）"
        )
        return 0

    for rel, text in outs.items():
        err = parses_selector(text) if rel == OUT_NAME else parses_shard(text)
        if err:
            print(f"生成失败：{rel} 形态不合法：{err}")
            return 1
    # 先写分片再写选择器：选择器是读侧的入口，中途失败时宁可是"入口指向还没写的片"
    # （下一次 --check 会红），也不要"片齐了但入口还是旧的"
    (refs / SHARD_DIR_NAME).mkdir(parents=True, exist_ok=True)
    for rel, text in sorted(outs.items(), key=lambda kv: kv[0] == OUT_NAME):
        write_text_lf(refs / rel, text, encoding="utf-8")
    # 残留分片清理：只动本目录内的 *.yaml，且只删不在预期集合里的（避免手写文件被误删时无声）
    shard_dir = refs / SHARD_DIR_NAME
    removed = []
    for p in sorted(shard_dir.glob("*.yaml")):
        rel = p.relative_to(refs).as_posix()
        if rel not in outs:
            p.unlink()
            removed.append(rel)
    print(
        f"已生成 {refs / OUT_NAME}（{len(entries)} 条流程 / {len(keys)} 片）"
        + (f"，清理残留分片 {removed}" if removed else "")
    )
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio

    pin_utf8_stdio()
    sys.exit(main())
