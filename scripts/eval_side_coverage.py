#!/usr/bin/env python3
# eval_side_coverage.py —— 回放夹具的**按侧覆盖报告**：路由分侧之后，"哪一侧没有量尺"要能现算
#
# 为什么需要它（2026-09）：路由从"一个分支记住哪一侧 + 什么性质"拆成两层（侧由工程师的事实
# 确定、性质在侧内判）之后，`eval/golden/` 的 26 条夹具里 25 条是推理侧，唯一"训练侧"的那条是
# 构造示例——而它的 `case_id`（MSLLM-EP-HANG-001）从未入 knowledge/，按夹具自己的头注
# "当前不可作为可运行回归"。于是训练侧整条链没有量尺：无论谁把训练侧的性质词表改坏、
# 或把侧的处理写坏，`eval/` 全绿都测不出来。
#
# 这件事此前只能靠人肉数：`eval/holdout.py --list` 报"有 case 却没有夹具的格子"时，
# 报的是 (namespace × category) 六个格子，读不出"训练侧 0/22"这个结论——格子是**结果**，
# 侧是**这一层的量尺单位**。本脚本补的就是这一眼。
#
# 判据强度（如实标注，原则六/十）：
#   - **它不判准确率**，也不判回放有没有重跑过（那是 eval_scorecard 的账本）。
#   - 它判的是**覆盖**：库里有 case 的 (侧 × 性质) 格子里，有没有至少一条夹具钉住它。
#     这是机械可判、确定性后果的（覆盖缺口 = 该侧没有回归保护）。
#   - **它测不到**：夹具覆盖的是"某一条真实输入",不是整份词表。所以"训练侧有夹具了"
#     不等于"训练侧词表被改坏会被测出来"——反例见 EV 卡的检出实验记录。
#
# 用法：
#   python3 scripts/eval_side_coverage.py            # 打印按侧覆盖（人读）
#   python3 scripts/eval_side_coverage.py --check    # 有"真实夹具覆盖不到的侧"即退出 1
#   python3 scripts/eval_side_coverage.py --check --require-side training
#                                                    # 指定侧必须有夹具（用于钉住本次补齐）
#
# 退出码：0 = 报告成立（或 --check 下要求的侧都有夹具）；1 = 有缺口；2 = 读取错误。
#
# 口径说明（别把这三个数混起来读）：
#   - **夹具覆盖的 case**：夹具 `expected.case_id` 指向的、且确实在库里的 case（去重）。
#   - **构造示例**（文件名 `example.*`）不计入覆盖：它按 docs/guide/eval.md 的分类就是格式演示，
#     不指向可运行回归；把它算成"训练侧有覆盖"正是本次要修的误读。

import argparse
import glob
import os
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
GOLDEN = "eval/golden"
SIDES = ("training", "inference")


def load(p: Path):
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"读不动 {p}（{type(e).__name__}：{e}）", file=sys.stderr)
        raise SystemExit(2)


def library_cases(root: Path) -> dict:
    """→ ({(侧, 性质): [case_id, ...]}, [共享池 case_id, ...])。

    两侧与共享池的**目录深度不同**，这不是笔误、也不能用一个 glob 糊过去：
      knowledge/<侧>/<框架>/<性质>/x.yaml     —— 侧判据 = rel[0]、性质 = rel[2]
      knowledge/common/<性质>/x.yaml          —— 框架无关的共性 case，不判侧
    早先这里只写 `knowledge/*/*/*/*.yaml`（四段），结果是 common/ 的 case **一条都取不到**，
    报告把它们印成 0 条——而"共享池 0 条"读起来像事实，实际是这个 glob 够不着。
    所以两条路径分开取，且 common 直接按 rel[0] == "common" 收集。

    顺带如实标注一个既有的分母盲区（不在本次改动面内，但读这份报告要知情）：
    `knowledge/inference/sglang/SGL-PD-HEAP-001.yaml` 这类"有 case、但路径里没有性质段"
    的文件进不了任何 (侧 × 性质) 桶，于是**静默从可判分母里消失**（推理侧分母因此是 124 而不是 125）。
    它不会被算成缺口，也不会被单列——将来新框架先建目录、性质段后补时，同一形态会重演。
    """
    out, common = {}, []
    for f in sorted(glob.glob(str(root / "knowledge/**/*.yaml"), recursive=True)):
        p = Path(f)
        if p.name.startswith("_"):
            continue
        rel = p.relative_to(root / "knowledge").parts
        doc = load(p)
        ids = [str(c.get("id")) for c in (doc.get("cases") or []) if c.get("id")]
        if rel[0] in SIDES and len(rel) >= 4:
            out.setdefault((rel[0], rel[2]), []).extend(ids)
        elif rel[0] == "common" and len(rel) >= 3:
            common.extend(ids)
    return out, common


def fixture_rows(root: Path) -> list:
    """→ [{fixture, case_id, covers(namespace), side, nature, constructed}]。"""
    rows = []
    for f in sorted(glob.glob(str(root / GOLDEN / "*.fixture.yaml"))):
        p = Path(f)
        doc = load(p)
        exp = doc.get("expected") or {}
        ns = str(exp.get("namespace") or "").strip("/")
        parts = ns.split("/") if ns else []
        # 命名空间形如 <侧>/<框架>/<性质>；推理侧无性质段时（旧形态）性质记空。
        side = parts[0] if parts and parts[0] in SIDES else ""
        nature = parts[2] if len(parts) >= 3 else ""
        rows.append({
            "fixture": p.name,
            "case_id": str(exp.get("case_id") or doc.get("case_id") or ""),
            "covers": ns,
            "side": side,
            "nature": nature,
            "constructed": p.name.startswith("example."),
        })
    return rows


def report(root: Path):
    lib, common = library_cases(root)
    rows = fixture_rows(root)
    in_lib = {cid for ids in lib.values() for cid in ids} | set(common)
    # 只算"覆盖到库里真实 case"的夹具；构造示例与指向未入库 case 的夹具都单列
    real = [r for r in rows if not r["constructed"] and r["case_id"] in in_lib]
    dead = [r for r in rows if not r["constructed"] and r["case_id"] not in in_lib]
    covered = {}
    for r in real:
        covered.setdefault((r["side"], r["nature"]), set()).add(r["case_id"])
    # 夹具声明的期望格 vs case **实际所在格**：不一致的夹具是把覆盖记到了错的格子上——
    # 声明的那一格看起来"有覆盖"，而 case 真正的格子看起来是缺口。
    # 基准必须取 case 的落盘位置（`lib`），**不能**取 `covered`：`covered` 是按夹具声明落桶的，
    # 拿它与 `lib` 的键比较是"果对果"——只要那个格子碰巧有 case 就永远对得上
    # （本脚本第一版就这么错过一次，被 test_fixture_declaring_the_wrong_cell_is_surfaced 抓住）。
    # 共享池（common/）的 case 不进 `real_cell`，于是按构造不会被判——报告不判共享池。
    real_cell = {cid: k for k, ids in lib.items() for cid in ids}
    mismatched = []
    for r in real:
        head = (r["covers"] or "").split("/")[0]
        if head == "common":
            continue          # 共享池夹具：报告不判共享池
        if not r["side"]:
            # 首段既不是侧也不是 common（namespace 写错一个词）→ 会静默落进"共享池"那一栏，
            # 而那一栏本来不判、没人会去核；同时它声明的那一格显示成缺口。
            mismatched.append(r)
        elif real_cell.get(r["case_id"]) != (r["side"], r["nature"]):
            mismatched.append(r)
    return {"lib": lib, "common": common, "rows": rows, "real": real,
            "dead": dead, "covered": covered, "mismatched": mismatched}


def nature_evidence(root: Path, rows: list) -> list:
    """每条夹具的输入**在词法上**命中哪些性质（用路由表自己的正则跑）。

    为什么要有这一栏：`expected.namespace` 只声明"该归哪一侧的哪个性质"，它不保证**输入本身就
    带得出这个性质**——实测 26 条夹具里 16 条的输入对三个性质的正则**零命中**，它们靠的是流程里写明的
    语义兜底（`triage_semantic`），不是词法。两种夹具的"回归保护强度"不是一回事：
    词法命中的那条，改坏词表会当场报；只靠兜底的那条，改坏词表它也照样通过。

    这一栏因此是**读出强度**用的（哪条夹具真的钉着词表），不是门——理由见文件头注。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import route_check as RC  # 局部导入：本脚本的主用途（覆盖报告）不依赖它

    try:
        natures, sides = RC.load_tree(root)
    except SystemExit:
        return []
    out = []
    for r in rows:
        if not r["side"] or not r["nature"]:
            continue
        p = root / GOLDEN / r["fixture"]
        doc = load(p)
        # 侧与性质从夹具声明的 namespace 读；检索面按该侧展开（与诊断时同构）
        branches = RC.effective_branches(natures, r["side"],
                                         framework=(doc.get("input") or {}).get("framework"),
                                         sides=sides)
        text = str((doc.get("input") or {}).get("symptoms") or "")
        hits, _broken = RC.hits_for(text, branches)
        got = [h[0] for h in hits]
        out.append({"fixture": r["fixture"], "side": r["side"], "expected": r["nature"],
                    "matched": got, "lexical": r["nature"] in got})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="回放夹具的按侧覆盖报告")
    ap.add_argument("--check", action="store_true",
                    help="任一含 case 的 (侧 × 性质) 格子缺夹具即退出 1")
    ap.add_argument("--require-side", action="append", default=[],
                    help="要求该侧**至少有一条**真实夹具（不判该侧每个格子；可多次）")
    ap.add_argument("--nature-evidence", action="store_true",
                    help="附加一栏：每条夹具的输入在词法上命中哪些性质（读出「钉住词表」的夹具是哪几条）")
    ap.add_argument("--root", type=Path, default=REPO)
    args = ap.parse_args()
    root = args.root.resolve()
    # 参数错误先报：写错的侧名与"根不存在"是两件事，不能因为根也不在就把前者咽掉
    # （实测过这个顺序错误——`--require-side trainig` 在空根上曾报成"读不到 knowledge"）。
    for side in args.require_side:
        if side not in SIDES:
            print(f"✗ --require-side {side}：不是已声明的侧（{', '.join(SIDES)}）", file=sys.stderr)
            return 2
    # 根不存在时**不能**静默报绿：`glob` 对不存在的根返回空，报告会把"根够不着"印成
    # "库里没有 case / 每侧 0 条"——两栏 0/0 加一句 ✓，正是本脚本要消灭的那类误读。
    # 与文件级读不动（load() 抛 SystemExit(2)）保持同一个退出码契约。
    for rel in ("knowledge", GOLDEN):
        if not (root / rel).is_dir():
            print(f"读不到 {root / rel}——--root 指错了地方（该目录不存在）", file=sys.stderr)
            return 2
    R = report(root)
    lib, covered = R["lib"], R["covered"]

    print(f"夹具总表：{len(R['rows'])} 条"
          f"（真实投影 {len(R['real'])}／构造示例或指向未入库 case {len(R['rows']) - len(R['real'])}）")
    for r in R["rows"]:
        if r["constructed"]:
            print(f"  · 不计入覆盖：{r['fixture']}（构造示例——文件名以 `example.` 开头，"
                  f"按 docs/guide/eval.md 的数据策略属格式演示）")
    for r in R["dead"]:
        print(f"  · 不计入覆盖：{r['fixture']}（case_id {r['case_id'] or '未给'} 不在库索引里"
              f"——case 已退休或从未入库）")
    print()

    gaps = []
    print(f"{'侧':10s} {'性质':12s} {'库里 case':>9s} {'有夹具':>7s}  覆盖")
    print("-" * 62)
    for side in SIDES:
        natures = sorted({k[1] for k in lib if k[0] == side})
        for nature in natures:
            tot = len(lib.get((side, nature), []))
            cov = len(covered.get((side, nature), ()))
            mark = "缺" if cov == 0 else "有"
            print(f"{side:10s} {nature:12s} {tot:9d} {cov:7d}  {mark}")
            if cov == 0:
                gaps.append((side, nature))
    print(f"{'common':10s} {'--':12s} {len(R['common']):9d} "
          f"{len([r for r in R['real'] if r['side'] == '']):7d}  "
          f"（共享池不判侧，单列不计入缺口）")
    print("-" * 62)
    print()
    for side in SIDES:
        tot = sum(len(v) for k, v in lib.items() if k[0] == side)
        cov = len({c for k, v in covered.items() if k[0] == side for c in v})
        pct = f"{cov / tot * 100:.0f}%" if tot else "—"
        print(f"{side:10s} 按 case 覆盖 {cov}/{tot} = {pct}")

    for r in R["mismatched"]:
        declared = f"{r['side']}/{r['nature']}" if r["side"] else f"（首段读不出侧：{r['covers']!r}）"
        print(f"  ! {r['fixture']}：声明 {declared}，"
              f"但它指向的 case {r['case_id']} 不在这一格——期望命名空间写错了，"
              f"或该 case 已挪格（这条覆盖记在了错的格子上）")

    if args.nature_evidence:
        ev = nature_evidence(root, R["rows"])
        if ev:
            lex = [e for e in ev if e["lexical"]]
            print(f"\n性质证据（夹具的输入在词法上命中期望性质的有 {len(lex)}/{len(ev)} 条）：")
            for e in ev:
                mark = "词法命中" if e["lexical"] else "仅语义兜底（改坏词表本条也照样通过）"
                print(f"  {e['fixture']:38s} 期望 {e['side']}/{e['expected']:12s} "
                      f"命中 {e['matched'] or '（无）'}  {mark}")
            print("  · 强度说明：词法命中只覆盖它输入里那几个正则——实测把某条夹具赖以命中的正则"
                  "挪到别的性质，只有该夹具报（如 `RuntimeError` 挪走 → MSLLM-1655 报）；"
                  "挪一条与它无关的正则则零检出。所以这一栏读作「这条夹具钉住了哪几个词」，"
                  "不读作「这一侧的词表被守住了」。")

    if not args.check:
        return 0
    bad = list(gaps)
    for side in args.require_side:
        if not any(k[0] == side for k in covered):
            bad.append((side, "（整侧没有真实夹具）"))
    if bad:
        print(f"\n✗ 覆盖缺口 {len(bad)} 项：")
        for side, nature in bad:
            print(f"   - {side} / {nature}：库里有 case，没有任何真实夹具钉住它")
        print("  （修法：补真实来源的夹具；构造示例不算覆盖——见 docs/guide/eval.md 的数据策略）")
        return 1
    print("\n✓ 每个含 case 的 (侧 × 性质) 格子都有真实夹具")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
