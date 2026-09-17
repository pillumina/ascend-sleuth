#!/usr/bin/env python3
# rank_candidates.py —— 阶段一候选排序：词法相关性优先，score 退居破平（EV-2026-111）
#
# 为什么需要它：diagnose 的 SKILL 正文一直写着「报错原文在场 → signature 立即查」，但索引行里
# 没有签名面字段，于是阶段一的排序只能按 confidence.score——**策略在散文里、排序在数据里**。
# 实测（25 条有 expected case 的 golden fixture，在各自 ns×category 格子内排序）：
#   只按 score：            top1 2 / top3 5  / 中位名次 20
#   本排序器（字面量+token）：top1 9 / top3 13 / 中位名次 3
# 而"把缺失的 score 补全"反而更差（top3 2、中位 33）——排序的问题不是分数缺，是 score 不是相关性信号。
#
# 排序口径（三顺位，全部可在索引行内算出，**不需要读 case 本体**）：
#   ① sig 字面量命中数：case 的 quickly_check 字面量分支有多少条**原样出现**在输入里
#      （"报错原文命中"是最强的相关性信号，且与语言无关）
#   ② token 交集数：输入的 token 类信号（见 _lexical.py）与 case 的 title+symptoms 摘要的交集大小
#   ③ confidence.score（破平），最后按 id 保证稳定
#
# 用法：
#   python3 scripts/rank_candidates.py --text-file <报错/症状文本> --ns inference/vllm-ascend [--category interrupt] [--top 5]
#   echo "报错原文" | python3 scripts/rank_candidates.py --ns inference/vllm-ascend --category interrupt
#   python3 scripts/rank_candidates.py --eval          # 管线同构的量尺：先筛 ≤5 再算名次（判据出处）
#
# `--eval` 的口径（**2026-09 修正**）：早期版本在"整个 ns×category 格子内"排序算名次，与生产管线
# **不同构**——生产是「按相关性筛 ≤5 → 只加载这 5 条 → 用 quickly_check 验证」。两者不可比：
# 用格子内口径曾得出"机械词法键把 top3 从 5 提到 13"，而按同构口径同一数据只能得到
# recall@5 与「≤5 内名次」两组数，且历史记录（agent 判断）本来就是 19/19——即机械键会替掉一个
# 更好的判断者。故现在 --eval 一律输出：**recall@5（期望 case 有没有进候选）** 与
# **top3|≤5（进去之后排第几）**，并附历史(agent)行作参照。排序类改动一律用这个量尺判。
#
# 退出码：0 = 正常；1 = 输入/参数问题（无文本、ns 不存在）。
#
# 强度如实标注：本排序器只解决**排序**——它不判候选是否相关（那是 quickly_check 阶段二的事），
# 也不改任何 case 内容；sig 只覆盖有字面量分支的 case（当前 74/159，覆盖率如实打印）。

import argparse
import json
import statistics
import sys
from pathlib import Path

import yaml

from _lexical import tokens_of

INDEX = Path("knowledge") / "_index.yaml"
GOLDEN = Path("eval") / "golden"


def load_rows(root: Path) -> list:
    """索引全量行（含 sig 字面量）。索引含 ns → category → rows 三层。"""
    idx = root / INDEX
    if not idx.exists():
        raise SystemExit(f"未找到 {INDEX}——先跑 `python3 scripts/build_index.py`")
    doc = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
    rows = []
    for ns, cells in (doc.get("namespaces") or {}).items():
        for cat, entries in (cells or {}).items():
            for e in entries or []:
                if isinstance(e, dict) and e.get("id"):
                    rows.append({"ns": ns, "category": cat, **e})
    return rows


def score_of(row) -> float:
    return ((row.get("confidence") or {}).get("score") if isinstance(row.get("confidence"), dict)
            else None) or -1.0


def rank_rows(rows: list, text: str) -> list:
    """按三顺位排序，返回 [(row, sig_hits, overlap)]。"""
    itok = tokens_of(text or "")
    low = (text or "").lower()
    scored = []
    for r in rows:
        sig = r.get("sig") or []
        hits = sum(1 for s in sig if str(s).lower() in low)
        # 行内 tok 是唯一事实源（覆盖全部症状）；索引未重建时退回按行内文本现算
        toks = set(r["tok"]) if r.get("tok") else tokens_of(
            str(r.get("title", "")) + " " + " ".join(str(s) for s in (r.get("symptoms") or [])))
        overlap = len(itok & toks)
        scored.append((hits, overlap, score_of(r), r))
    scored.sort(key=lambda t: (-t[0], -t[1], -t[2], str(t[3].get("id"))))
    return [(r, h, o) for h, o, _s, r in scored]


def cmd_rank(args, root: Path) -> int:
    rows = load_rows(root)
    if args.ns:
        rows = [r for r in rows if r["ns"] == args.ns]
        if not rows:
            print(f"ns {args.ns!r} 无 case——用 `--list-ns` 看可用值")
            return 1
    if args.category:
        rows = [r for r in rows if r["category"] == args.category]
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    else:
        text = args.text if args.text is not None else sys.stdin.read()
    if not text or not text.strip():
        print("无输入文本——用 --text / --text-file / stdin 提供症状或报错原文")
        return 1

    ranked = rank_rows(rows, text)
    print(f"候选池 {len(rows)} 条（{args.ns or '全库'}{'/' + args.category if args.category else ''}）；"
          f"字面量命中 → token 交集 → score 排序")
    for i, (r, hits, ov) in enumerate(ranked[: args.top], 1):
        print(f"  #{i:<3} {r['id']:<24} sig命中={hits:<2} token交集={ov:<2} "
              f"score={str(score_of(r) if score_of(r) >= 0 else '-'):<5} {str(r.get('title'))[:56]}")
    if args.json:
        print(json.dumps([{"rank": i, "id": r["id"], "sig_hits": h, "token_overlap": o,
                           "score": score_of(r), "file": r.get("file")}
                          for i, (r, h, o) in enumerate(ranked, 1)], ensure_ascii=False))
    return 0


def evaluate(rows: list, fixtures: list, filter_key, top_k: int = 5) -> dict:
    """管线同构评估：先按 filter_key 筛 top_k 候选，再看期望 case 有没有进、进去后排第几。

    fixtures = [(case_id, 输入文本)]；返回 {n, recall_at_k, top3_given, median_rank_in_loaded}。
    未进候选的条目 recall 记 0，且不计入 top3_given 的分母（分开看：筛漏 vs 排后是两件事）。
    """
    by_cell, by_id = {}, {}
    for r in rows:
        by_cell.setdefault((r["ns"], r["category"]), []).append(r)
        by_id[r["id"]] = r
    got, ranks = 0, []
    for cid, text in fixtures:
        tgt = by_id.get(cid)
        if tgt is None:
            continue
        pool = by_cell[(tgt["ns"], tgt["category"])]
        loaded = sorted(pool, key=lambda r: filter_key(r, text))[:top_k]
        ids = [r["id"] for r in loaded]
        if cid in ids:
            got += 1
            ranks.append(ids.index(cid) + 1)
    n = sum(1 for cid, _t in fixtures if cid in by_id)
    return {"n": n, "recall_at_k": got, "top3_given": sum(1 for r in ranks if r <= 3),
            "loaded": len(ranks), "median_rank_in_loaded": statistics.median(ranks) if ranks else None}


def _key_score(r, _text):
    return (-score_of(r), str(r.get("id")))


def _key_lexical(r, text):
    itok = tokens_of(text or "")
    low = (text or "").lower()
    hits = sum(1 for s in (r.get("sig") or []) if str(s).lower() in low)
    toks = set(r["tok"]) if r.get("tok") else tokens_of(
        str(r.get("title", "")) + " " + " ".join(str(s) for s in (r.get("symptoms") or [])))
    return (-hits, -len(itok & toks), -score_of(r), str(r.get("id")))


def cmd_eval(root: Path) -> int:
    """管线同构的量尺（见文件头注）：先筛 ≤5，再算名次；附历史(agent)行作参照。

    三行必须同分母才有意义，故：
      - 第一段：全部"expected 在索引里"的 fixture（机械键能评的都在这）；
      - 第二段：**两个机械键与 agent 历史记录都覆盖的那个子集**——只有这里才谈得上谁更好。
        agent 的历史名次来自 eval/scorecard.yaml（按 fixture 名对齐，因为多条 fixture 可指向同一个 case）。
    """
    rows = load_rows(root)
    hist = _history_by_fixture(root)          # {fixture 名: 历史名次}
    all_fx, sub_fx, skipped = [], [], []
    for f in sorted((root / GOLDEN).glob("*.fixture.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        cid = str((d.get("expected") or {}).get("case_id") or (d.get("expected") or {}).get("case") or "")
        if not any(r["id"] == cid for r in rows):
            skipped.append(f.name)
            continue
        item = (cid, (d.get("input") or {}).get("symptoms") or "")
        all_fx.append(item)
        if isinstance(hist.get(f.name), int):
            sub_fx.append(item)

    def row_line(label, key, fixtures):
        e = evaluate(rows, fixtures, key)
        med = "—" if e["median_rank_in_loaded"] is None else f"{e['median_rank_in_loaded']:.1f}"
        print(f"  {label:<28} {e['recall_at_k']:>5}/{e['n']:<3} {e['top3_given']:>6}/{e['loaded']:<3} {med:>10}")

    print(f"rank_candidates --eval（管线同构：先筛 ≤5 候选 → 看期望 case 进没进、排第几）"
          f"  fixtures={len(all_fx)}" + (f" skipped={len(skipped)}" if skipped else ""))
    print(f"  {'筛选键（全部 fixture）':<26} {'recall@5':>10} {'top3|≤5':>10} {'≤5内中位':>9}")
    row_line("score-only（改前）", _key_score, all_fx)
    row_line("lexical(sig→tok→score)", _key_lexical, all_fx)

    if sub_fx:
        sub_hist = [hist[n] for n, r in _fixture_names(root).items() if isinstance(hist.get(n), int)]
        print(f"  {'—— 同子集对照（{0} 条：三者都有记录）'.format(len(sub_fx)):<24}"
              f"{'recall@5':>10} {'top3|≤5':>10} {'≤5内中位':>9}")
        row_line("agent 历史记录", None, sub_fx) if False else None
        print(f"  {'agent 历史记录（同子集）':<24} {sum(1 for r in sub_hist if r <= 5):>6}/{len(sub_hist):<3}"
              f" {sum(1 for r in sub_hist if r <= 3):>6}/{len(sub_hist):<3} {'—':>10}")
        row_line("score-only", _key_score, sub_fx)
        row_line("lexical", _key_lexical, sub_fx)
    print("  口径：只排不改；筛选键是 agent 判断的**机械代理**，不是替代品。"
          "recall@5 与 top3|≤5 分开读——筛漏与排后是两件事，修法不同。")
    blind = [r for r in rows if not r.get("sig") and not r.get("tok")]
    print(f"  另：行内 sig/tok 覆盖 {_coverage(rows)}；**行内无任何字面量证据的 case {len(blind)}/{len(rows)}**"
          f"——这批在机械筛选里不可达（只能靠 agent 语义判断），它是机械键的硬天花板，不是调参问题")
    return 0


def _fixture_names(root: Path) -> dict:
    """{fixture 文件名: expected case_id}——用于把历史记录按 fixture 对齐。"""
    out = {}
    for f in sorted((root / GOLDEN).glob("*.fixture.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        exp = d.get("expected") or {}
        out[f.name] = str(exp.get("case_id") or exp.get("case") or "")
    return out


def _history_by_fixture(root: Path) -> dict:
    """历史记录（agent 回放的观测名次，来自 eval/scorecard.yaml）→ {fixture 名: rank}。"""
    p = root / "eval" / "scorecard.yaml"
    if not p.exists():
        return {}
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = {}
    for e in doc.get("entries") or []:
        r = (e.get("observed") or {}).get("rank")
        if isinstance(r, int):
            out[str(e.get("fixture"))] = r
    return out


def _coverage(rows: list) -> str:
    sig = sum(1 for r in rows if r.get("sig"))
    tok = sum(1 for r in rows if r.get("tok"))
    return f"sig {sig}/{len(rows)}、tok {tok}/{len(rows)}"


def main() -> int:
    ap = argparse.ArgumentParser(description="阶段一候选排序（词法相关性优先，score 破平）")
    ap.add_argument("--text", default=None, help="症状/报错原文（不给则读 --text-file 或 stdin）")
    ap.add_argument("--text-file", default=None, help="从文件读症状/报错原文")
    ap.add_argument("--ns", default=None, help="限定 namespace（如 inference/vllm-ascend）")
    ap.add_argument("--category", default=None, help="限定 category（interrupt/precision/performance）")
    ap.add_argument("--top", type=int, default=5, help="打印前 N 条（默认 5）")
    ap.add_argument("--json", action="store_true", help="额外输出机器可读排序（全量）")
    ap.add_argument("--eval", action="store_true", help="在 eval/golden 上复现排序命中分布")
    ap.add_argument("--list-ns", action="store_true", help="列出索引里的 ns×category 与条数")
    ap.add_argument("--root", default=None, help="仓库根（默认脚本上两级）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    if args.list_ns:
        rows = load_rows(root)
        counts = {}
        for r in rows:
            counts[(r["ns"], r["category"])] = counts.get((r["ns"], r["category"]), 0) + 1
        for (ns, cat), n in sorted(counts.items()):
            print(f"  {ns}/{cat}: {n}")
        return 0
    if args.eval:
        return cmd_eval(root)
    return cmd_rank(args, root)


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
