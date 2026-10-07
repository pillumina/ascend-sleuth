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
#   python3 scripts/rank_candidates.py --write-baseline      # 改动前：把逐条名次存成本地基线
#   python3 scripts/rank_candidates.py --compare-baseline    # 改动后：同口径重算，逐条对照
#
# 自动对照（--write-baseline / --compare-baseline）：索引侧证据（索引行里的字面量与 token）有没有变，
# 用同构口径前后各算一遍名次来对。基线默认写 `.s2-replay/rank-baseline.yaml`，**是本地运行件、不入库**
# （按 `.gitignore:77`）：它是数字快照，进 git 会在并发合并时撞行，而"生成物里不写数字"的前提正是
# 数字不入库（`CLAUDE.md:117`）。
# 它**只报警，不拦合并**：只覆盖阶段一的筛与排。生产流程里排序由 agent 按相关性判断
# （`skills/diagnose/SKILL.md:62`），本脚本的机械键是那份判断的代理——代理指标变差要人看，
# 不据此阻塞合并；本命令**不进 CI**（准入判据见 `CLAUDE.md:127`，机械键与生产结论的相关性还需累积对照）。

#
# `--eval` 的口径（**2026-09 修正**）：早期版本在"整个 ns×category 格子内"排序算名次，与生产管线
# **不同构**——生产是「按相关性筛 ≤5 → 只加载这 5 条 → 用 quickly_check 验证」。两者不可比：
# 用格子内口径曾得出"机械词法键把 top3 从 5 提到 13"，而按同构口径同一数据只能得到
# recall@5 与「≤5 内名次」两组数，且历史记录（agent 判断）本来就是 19/19——即机械键会替掉一个
# 更好的判断者。故现在 --eval 一律输出：**recall@5（期望 case 有没有进候选）** 与
# **top3|≤5（进去之后排第几）**，并附历史(agent)行作参照。排序类改动一律用这个量尺判。
#
# 退出码：0 = 正常；1 = 输入/参数问题（无文本、ns 不存在），或 --compare-baseline 查出变差
# （报警，不是用法错误）；2 = --compare-baseline 不可比、没有读数：缺基线、基线读不出来或不是
# 合法 YAML、基线里没有逐条名次、或口径不符（排序键不同、top_k 不同）。
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
BASELINE_DEFAULT = Path(".s2-replay") / "rank-baseline.yaml"


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
    items, skipped = _fixture_items(root, rows)
    all_fx = [(cid, text) for _n, cid, text in items]
    sub_fx = [(cid, text) for n, cid, text in items if isinstance(hist.get(n), int)]

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


def _fixture_items(root: Path, rows: list) -> tuple:
    """(items, skipped)：items = [(fixture 名, 期望 case_id, 输入文本)]，只收期望 case 在索引里的。

    `cmd_eval` 与 `--compare-baseline` 共用这一份 fixture 集合，否则两处读数不可比。
    """
    ids = {r["id"] for r in rows}
    items, skipped = [], []
    for f in sorted((root / GOLDEN).glob("*.fixture.yaml")):
        d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        exp = d.get("expected") or {}
        cid = str(exp.get("case_id") or exp.get("case") or "")
        if cid not in ids:
            skipped.append(f.name)
            continue
        items.append((f.name, cid, (d.get("input") or {}).get("symptoms") or ""))
    return items, skipped


def evaluate_detail(rows: list, items: list, filter_key, top_k: int = 5) -> dict:
    """逐条名次：先按 filter_key 筛 top_k 候选，再记期望 case 在其中的位置。

    返回 {fixture 名: rank}；rank 从 1 起，没进候选记 None。筛选口径与 `evaluate()` 相同。
    """
    by_cell, by_id = {}, {}
    for r in rows:
        by_cell.setdefault((r["ns"], r["category"]), []).append(r)
        by_id[r["id"]] = r
    out = {}
    for name, cid, text in items:
        tgt = by_id.get(cid)
        if tgt is None:
            continue
        pool = by_cell.get((tgt["ns"], tgt["category"]), [])
        ids = [r["id"] for r in sorted(pool, key=lambda r: filter_key(r, text))[:top_k]]
        out[name] = (ids.index(cid) + 1) if cid in ids else None
    return out


def _coverage_counts(rows: list) -> dict:
    return {"rows": len(rows), "sig": sum(1 for r in rows if r.get("sig")),
            "tok": sum(1 for r in rows if r.get("tok")),
            "blind": sum(1 for r in rows if not r.get("sig") and not r.get("tok"))}


def _rank_text(rank) -> str:
    return "未进候选" if rank is None else f"#{rank}"


def cmd_write_baseline(root: Path, path: Path, top_k: int) -> int:
    """改动前存一份逐条名次，供 --compare-baseline 对照。"""
    rows = load_rows(root)
    items, skipped = _fixture_items(root, rows)
    if not items:
        print("没有可评的 fixture（期望 case 不在索引里）——先跑 python3 scripts/build_index.py",
              file=sys.stderr)
        return 2
    detail = evaluate_detail(rows, items, _key_lexical, top_k)
    with_cov = _coverage_counts(rows)
    doc = {"key": "lexical", "top_k": top_k, "coverage": with_cov, "fixtures": detail}
    path.parent.mkdir(parents=True, exist_ok=True)
    overwrote = path.exists()
    path.write_text(
        "# GENERATED by scripts/rank_candidates.py --write-baseline；阶段一排序的本地基线（运行件，不入库）。\n"
        f"# 口径：lexical(sig→tok→score) 三顺位键，先筛 top_k 候选再看期望 case 的名次；null = 未进候选。\n"
        + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    got = sum(1 for v in detail.values() if v is not None)
    print(f"基线已写入：{path}"
          + ("（覆盖了原有基线——改动前那份读数已不在）" if overwrote else ""))
    print(f"  fixture {len(detail)} 条（skip {len(skipped)} 条：期望 case 不在索引里）"
          f"· recall@{top_k} {got}/{len(detail)}"
          f"· 进前三 {sum(1 for v in detail.values() if v and v <= 3)}")
    print("  改一处索引侧证据后再跑 --compare-baseline；本文件是数字快照，不入库。")
    return 0


def cmd_compare_baseline(root: Path, path: Path, top_k: int) -> int:
    """改动后同口径重算并与基线逐条对照。变差则退 1（报警，不作为合并门槛）。"""
    if not path.exists():
        print(f"没有基线文件：{path}", file=sys.stderr)
        print(f"先在改动前跑：python3 scripts/rank_candidates.py --write-baseline {path}",
              file=sys.stderr)
        return 2
    rewrite = f"重跑 python3 scripts/rank_candidates.py --write-baseline {path} 重写基线"
    try:
        base = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"基线文件读不出来或不是合法 YAML：{path}（{exc}）——不可比，没有读数",
              file=sys.stderr)
        print(rewrite, file=sys.stderr)
        return 2
    if base is None:
        print(f"基线是空文件：{path}——里面没有逐条名次，不可比，没有读数", file=sys.stderr)
        print(rewrite, file=sys.stderr)
        return 2
    if not isinstance(base, dict):
        print(f"基线文件不是一份基线（顶层不是映射）：{path}——不可比，没有读数", file=sys.stderr)
        print(rewrite, file=sys.stderr)
        return 2
    b_fx = base.get("fixtures")
    if not isinstance(b_fx, dict) or not b_fx:
        print(f"基线里没有逐条名次（fixtures 缺失或为空）：{path}——不可比，没有读数",
              file=sys.stderr)
        print(rewrite, file=sys.stderr)
        return 2
    try:
        b_top = int(base.get("top_k"))
    except (TypeError, ValueError):
        b_top = 0
    if b_top != top_k:
        print(f"基线口径是 top_k={base.get('top_k')!r}，本次是 {top_k}——两份名次不可比；"
              f"按同一 top_k 重写基线再对照", file=sys.stderr)
        return 2
    b_key = base.get("key")
    if b_key not in (None, "lexical"):
        print(f"基线的排序键是 {b_key!r}，本次是 'lexical'——两份名次不可比；"
              f"按同一口径重写基线再对照", file=sys.stderr)
        return 2
    rows = load_rows(root)
    items, skipped = _fixture_items(root, rows)
    if not items:
        print("没有可评的 fixture（期望 case 不在索引里）——先跑 python3 scripts/build_index.py",
              file=sys.stderr)
        return 2
    now = evaluate_detail(rows, items, _key_lexical, top_k)
    worse, better, added = [], [], []
    for name in sorted(now):
        rank = now[name]
        if name not in b_fx:
            added.append(name)
            continue
        was = b_fx[name]
        if was == rank:
            continue
        if was is not None and (rank is None or rank > was):
            worse.append((name, was, rank))
        else:
            better.append((name, was, rank))
    gone = [n for n in sorted(b_fx) if n not in now]
    gone_case = [n for n in gone if n in set(skipped)]
    gone_fixture = [n for n in gone if n not in set(skipped)]
    cov, b_cov = _coverage_counts(rows), base.get("coverage") or {}
    cov_drop = [k for k in ("sig", "tok") if k in b_cov and cov[k] < b_cov[k]]
    rows_delta = b_cov.get("rows") != cov["rows"]
    blind_up = isinstance(b_cov.get("blind"), int) and cov["blind"] > b_cov["blind"]

    b_got = sum(1 for v in b_fx.values() if v is not None)
    n_got = sum(1 for v in now.values() if v is not None)
    print(f"rank_candidates --compare-baseline（管线同构：先筛 ≤{top_k} 候选 → 看期望 case 的名次）")
    print(f"  基线 {path}：fixture {len(b_fx)} 条 · recall@{top_k} {b_got}/{len(b_fx)}"
          f" · 行内证据 sig {b_cov.get('sig', '?')}/{b_cov.get('rows', '?')}"
          f"、tok {b_cov.get('tok', '?')}/{b_cov.get('rows', '?')}"
          f"、无线索 {b_cov.get('blind', '?')}")
    print(f"  现状：fixture {len(now)} 条 · recall@{top_k} {n_got}/{len(now)}"
          f" · 行内证据 sig {cov['sig']}/{cov['rows']}、tok {cov['tok']}/{cov['rows']}"
          f"、无线索 {cov['blind']}"
          + (f" · skip {len(skipped)} 条（期望 case 已不在索引里）" if skipped else ""))
    print(f"  变差 {len(worse) + len(gone_case)} 条 · 变好 {len(better)} 条 · 新增 fixture {len(added)} 条"
          + (f" · 基线里的 fixture 现状找不到：{len(gone_fixture)} 条（不计入变差）"
             if gone_fixture else ""))
    for name, was, rank in worse:
        print(f"    - 变差 {name}：基线 {_rank_text(was)} → 现状 {_rank_text(rank)}")
    for name in gone_case:
        print(f"    - 变差 {name}：基线 {_rank_text(b_fx[name])} → 现状 期望 case 已不在索引里")
    for name in gone_fixture:
        print(f"    - 不计入变差 {name}：基线里有这条 fixture，现状 eval/golden 下没有同名文件"
              f"（改名或删除）——这条 fixture 无法对照")
    for name, was, rank in better:
        print(f"    - 变好 {name}：基线 {_rank_text(was)} → 现状 {_rank_text(rank)}")
    for k in cov_drop:
        print(f"    - 行内证据减少：{k} {b_cov[k]} → {cov[k]}"
              + (f"（总行数也从 {b_cov.get('rows')} 变成 {cov['rows']}）" if rows_delta else "")
              + "——索引重建掉了这部分证据，机械排序键据此失据")
    if rows_delta and not cov_drop:
        print(f"    - 总行数变了：{b_cov.get('rows')} → {cov['rows']}——绝对条数相同不代表证据没变；"
              f"以逐条名次为准")
    if blind_up:
        print(f"    - 行内无任何字面量证据的 case 变多：{b_cov.get('blind')} → {cov['blind']}"
              f"（机械键的覆盖面变窄；这是读数，不单独触发退出码）")

    print("  结论：" + ("有变差。" if (worse or gone_case or cov_drop) else "无变差。")
          + "先分清两件事：索引里多了同格子的新 case（竞争变大，生产管线同样更难筛到），"
          "还是索引行本身的字面量/token 证据变了（排序键的依据变了）。")
    print("  本命令的范围：只覆盖阶段一的筛与排；生产排序由 agent 按相关性判断"
          "（skills/diagnose/SKILL.md:62），机械键是那份判断的代理，变差要人看，不据此阻塞合并；"
          "本命令不进 CI（准入判据见 CLAUDE.md:127）。")
    return 1 if (worse or gone_case or cov_drop) else 0


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
    ap.add_argument("--top", type=int, default=5,
                    help="打印前 N 条（默认 5）；--write-baseline/--compare-baseline 拿它当候选窗口"
                         " top_k（写读必须同值），--eval 不使用")
    ap.add_argument("--json", action="store_true", help="额外输出机器可读排序（全量）")
    ap.add_argument("--eval", action="store_true", help="在 eval/golden 上复现排序命中分布")
    ap.add_argument("--write-baseline", nargs="?", const=str(BASELINE_DEFAULT), default=None,
                    metavar="PATH", help=f"把逐条名次存成本地基线（默认 {BASELINE_DEFAULT}）")
    ap.add_argument("--compare-baseline", nargs="?", const=str(BASELINE_DEFAULT), default=None,
                    metavar="PATH", help=f"与基线逐条对照，变差退 1（默认 {BASELINE_DEFAULT}）")
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
    if args.write_baseline:
        return cmd_write_baseline(root, Path(args.write_baseline), args.top)
    if args.compare_baseline:
        return cmd_compare_baseline(root, Path(args.compare_baseline), args.top)
    if args.eval:
        return cmd_eval(root)
    return cmd_rank(args, root)


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
