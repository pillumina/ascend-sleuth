#!/usr/bin/env python3
# eval_workload_type_coverage.py —— 回放夹具的**按负载类型覆盖报告**：路由分负载类型之后，"哪一种负载类型没有量尺"要能现算
#
# 为什么需要它（2026-09）：路由从"一个分支记住负载类型 + 什么性质"拆成两层（负载类型由工程师的事实
# 确定、性质在负载类型内判）之后，`eval/golden/` 的 26 条夹具里 25 条是推理侧，唯一"训练侧"的那条是
# 构造示例——而它的 `case_id`（MSLLM-EP-HANG-001）从未入 knowledge/，按夹具自己的头注
# "当前不可作为可运行回归"。于是训练侧整条链没有量尺：无论谁把训练侧的性质词表改坏、
# 或把负载类型的处理写坏，`eval/` 全绿都测不出来。
#
# 这件事此前只能靠人肉数：`eval/holdout.py --list` 报"有 case 却没有夹具的格子"时，
# 报的是 (namespace × category) 六个格子，读不出"训练侧 0/22"这个结论——格子是**结果**，
# 负载类型是**这一层的量尺单位**。本脚本补的就是这一眼。
#
# 两层判据，**两个开关各管一层**（别把它们混起来——混起来会让"文档描述的门"与
# "实际跑的门"不是同一个，本脚本的第一版就这么错过一次）：
#   - **负载类型层（`--check`）**：库里**有 case 的**某一负载类型一条真实夹具都不剩 → 退出 1。
#     CI 跑的就是这一层。它防的是"整负载类型量尺归零"。只对"有 case 的负载类型"要求夹具——
#     新负载类型先声明、下一条 PR 才补 case 与夹具是正常顺序，那时没有需要保护的东西。
#   - **格层（`--check-cells`）**：某个含 case 的 (负载类型 × 性质) 格子没有夹具 → 退出 1。
#     **默认只报不拦**：本仓对这类缺口的既定动作是如实报出，不是拦下——补夹具需要真实来源、
#     凭空造不出来（同 `holdout.py --list` 对空缺格子的处理）。把它做成硬门等于要求
#     "新 case 落到尚无夹具的格子必须先补一条夹具"，而那时确实拿不出。
#     需要它当门时显式加 `--check-cells`（例如审计轮：`--check --check-cells`）。
#   - **它不判准确率**，也不判回放有没有重跑过（那是 eval_scorecard 的账本）。
#   - **它测不到**：夹具覆盖的是"某一条真实输入"，不是整份词表。所以"训练侧有夹具了"
#     不等于"训练侧词表被改坏会被测出来"——反例见 EV 卡的检出实验记录；
#     哪几条夹具真钉着词表用 `--nature-evidence` 现算现读。
#   - **覆盖格子是 (负载类型 × 性质)，不含框架**：同一负载类型同一性质下的所有框架**共用一格**
#     （实测：`training/fwA/interrupt` 与 `training/fwB/interrupt` 各 1 条 case、只配一个夹具
#     时，报告是 `training interrupt 2 1 有`）。所以别把 `inference 22/124` 读成"逐框架覆盖"。
#
# 用法：
#   python3 scripts/eval_workload_type_coverage.py                  # 打印按负载类型覆盖（人读）
#   python3 scripts/eval_workload_type_coverage.py --check          # 某一负载类型量尺归零即退出 1
#   python3 scripts/eval_workload_type_coverage.py --check-cells    # 格级缺口也当门（默认只报）
#   python3 scripts/eval_workload_type_coverage.py --nature-evidence # 附加：哪几条夹具真钉着词表
#   python3 scripts/eval_workload_type_coverage.py --check --require-workload-type training
#                                                          # 只要求指定负载类型不归零（可多次）
#
# 退出码：0 = 报告成立（未点名任何门，或点名的门都通过）；1 = 点名的门没通过（负载类型层或格层）；2 = 读取错误。
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
WORKLOAD_TYPES = ("training", "inference")


def load(p: Path):
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"读不动 {p}（{type(e).__name__}：{e}）", file=sys.stderr)
        raise SystemExit(2)


def library_cases(root: Path) -> dict:
    """→ ({(负载类型, 性质): [case_id, ...]}, [共享池 case_id, ...])。

    两种负载类型与共享池的**目录深度不同**，这不是笔误、也不能用一个 glob 糊过去：
      knowledge/<负载类型>/<框架>/<性质>/x.yaml     —— 负载类型判据 = rel[0]、性质 = rel[2]
      knowledge/common/<性质>/x.yaml          —— 框架无关的共性 case，不判负载类型
    早先这里只写 `knowledge/*/*/*/*.yaml`（四段），结果是 common/ 的 case **一条都取不到**，
    报告把它们印成 0 条——而"共享池 0 条"读起来像事实，实际是这个 glob 够不着。
    所以两条路径分开取，且 common 直接按 rel[0] == "common" 收集。

    顺带如实标注一个既有的分母盲区（不在本次改动面内，但读这份报告要知情）：
    `knowledge/inference/sglang/SGL-PD-HEAP-001.yaml` 这类"有 case、但路径里没有性质段"
    的文件进不了任何 (负载类型 × 性质) 桶，于是**静默从可判分母里消失**（推理侧分母因此是 124 而不是 125）。
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
        if rel[0] in WORKLOAD_TYPES and len(rel) >= 4:
            out.setdefault((rel[0], rel[2]), []).extend(ids)
        elif rel[0] == "common" and len(rel) >= 3:
            common.extend(ids)
    return out, common


def fixture_rows(root: Path) -> list:
    """→ [{fixture, case_id, covers(namespace), workload_type, nature, constructed}]。"""
    rows = []
    for f in sorted(glob.glob(str(root / GOLDEN / "*.fixture.yaml"))):
        p = Path(f)
        doc = load(p)
        exp = doc.get("expected") or {}
        ns = str(exp.get("namespace") or "").strip("/")
        parts = ns.split("/") if ns else []
        # 命名空间形如 <负载类型>/<框架>/<性质>；推理侧无性质段时（旧形态）性质记空。
        workload_type = parts[0] if parts and parts[0] in WORKLOAD_TYPES else ""
        nature = parts[2] if len(parts) >= 3 else ""
        rows.append({
            "fixture": p.name,
            "case_id": str(exp.get("case_id") or doc.get("case_id") or ""),
            "covers": ns,
            "workload_type": workload_type,
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
        covered.setdefault((r["workload_type"], r["nature"]), set()).add(r["case_id"])
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
        if not r["workload_type"]:
            # 首段既不是负载类型也不是 common（namespace 写错一个词）→ 会静默落进"共享池"那一栏，
            # 而那一栏本来不判、没人会去核；同时它声明的那一格显示成缺口。
            mismatched.append(r)
        elif real_cell.get(r["case_id"]) != (r["workload_type"], r["nature"]):
            mismatched.append(r)
    return {"lib": lib, "common": common, "rows": rows, "real": real,
            "dead": dead, "covered": covered, "mismatched": mismatched}


def nature_evidence(root: Path, rows: list) -> list:
    """每条夹具的输入**在词法上**命中哪些性质（用路由表自己的正则跑）。

    为什么要有这一栏：`expected.namespace` 只声明"该归哪一种负载类型的哪个性质"，它不保证**输入本身就
    带得出这个性质**——实测 26 条夹具里 16 条的输入对三个性质的正则**零命中**，它们靠的是流程里写明的
    语义兜底（`triage_semantic`），不是词法。两种夹具的"回归保护强度"不是一回事：
    词法命中的那条，改坏词表会当场报；只靠兜底的那条，改坏词表它也照样通过。

    这一栏因此是**读出强度**用的（哪条夹具真的钉着词表），不是门——理由见文件头注。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import route_check as RC  # 局部导入：本脚本的主用途（覆盖报告）不依赖它

    try:
        natures, workload_types = RC.load_tree(root)
    except SystemExit:
        # 文件不存在：route_check 用 SystemExit(2) 报"读不到"，这里不重复报
        return []
    except Exception as e:
        # 解析不了（表被改坏）：性质证据是**可选读数**，不该把整份报告带崩，
        # 也不该以退出码 1 出现——本脚本里 1 是"有覆盖缺口"，两种事同形会误导。
        print(f"  （性质证据跳过：{root / 'triage-tree.yaml'} 读不动——"
              f"{type(e).__name__}；先跑 `python3 scripts/build_triage_tree.py`）", file=sys.stderr)
        return []
    out = []
    for r in rows:
        if not r["workload_type"] or not r["nature"]:
            continue
        p = root / GOLDEN / r["fixture"]
        doc = load(p)
        # 负载类型与性质从夹具声明的 namespace 读；检索面按该负载类型展开（与诊断时同构）
        branches = RC.effective_branches(natures, r["workload_type"],
                                         framework=(doc.get("input") or {}).get("framework"),
                                         workload_types=workload_types)
        text = str((doc.get("input") or {}).get("symptoms") or "")
        hits, _broken = RC.hits_for(text, branches)
        # 连命中的**正则**一起留下，不只留性质名：读者要回答的是"这条夹具钉住了哪几个词"，
        # 只印性质名的话，想知道是哪条正则救的就得绕开本脚本自己去 import（实测踩过这个坑——
        # 同一个词可能出现在多个症状组里，`RuntimeError` 在 interrupt 的两组各出现一次，
        # 只删一处夹具照样是"词法命中"）。
        out.append({"fixture": r["fixture"], "workload_type": r["workload_type"], "expected": r["nature"],
                    "matched": [(h[0], h[1]) for h in hits],
                    "lexical": r["nature"] in [h[0] for h in hits]})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="回放夹具的按负载类型覆盖报告")
    ap.add_argument("--check", action="store_true",
                    help="某一负载类型一条真实夹具都不剩即退出 1（负载类型层；CI 跑这一层）")
    ap.add_argument("--check-cells", action="store_true",
                    help="任一含 case 的 (负载类型 × 性质) 格子缺夹具也退出 1（格层；默认只报不拦，"
                         "理由见文件头注：补夹具需要真实来源、凭空造不出来）")
    ap.add_argument("--require-workload-type", action="append", default=[],
                    help="把负载类型层判据限定在这几个负载类型（可多次；不写 = 全部已声明的负载类型）")
    ap.add_argument("--nature-evidence", action="store_true",
                    help="附加一栏：每条夹具的输入在词法上命中哪些性质（读出「钉住词表」的夹具是哪几条）")
    ap.add_argument("--root", type=Path, default=REPO)
    args = ap.parse_args()
    root = args.root.resolve()
    # 参数错误先报：写错的负载类型名与"根不存在"是两件事，不能因为根也不在就把前者咽掉
    # （实测过这个顺序错误——`--require-workload-type trainig` 在空根上曾报成"读不到 knowledge"）。
    for workload_type in args.require_workload_type:
        if workload_type not in WORKLOAD_TYPES:
            print(f"✗ --require-workload-type {workload_type}：不是已声明的负载类型（{', '.join(WORKLOAD_TYPES)}）", file=sys.stderr)
            return 2
    # 根不存在时**不能**静默报绿：`glob` 对不存在的根返回空，报告会把"根够不着"印成
    # "库里没有 case / 每种负载类型 0 条"——两栏 0/0 加一句 ✓，正是本脚本要消灭的那类误读。
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
    print(f"{'负载类型':10s} {'性质':12s} {'库里 case':>9s} {'有夹具':>7s}  覆盖")
    print("-" * 62)
    for workload_type in WORKLOAD_TYPES:
        natures = sorted({k[1] for k in lib if k[0] == workload_type})
        for nature in natures:
            tot = len(lib.get((workload_type, nature), []))
            cov = len(covered.get((workload_type, nature), ()))
            mark = "缺" if cov == 0 else "有"
            print(f"{workload_type:10s} {nature:12s} {tot:9d} {cov:7d}  {mark}")
            if cov == 0:
                gaps.append((workload_type, nature))
    print(f"{'common':10s} {'--':12s} {len(R['common']):9d} "
          f"{len([r for r in R['real'] if r['workload_type'] == '']):7d}  "
          f"（共享池不判负载类型，单列不计入缺口）")
    print("-" * 62)
    print()
    for workload_type in WORKLOAD_TYPES:
        tot = sum(len(v) for k, v in lib.items() if k[0] == workload_type)
        cov = len({c for k, v in covered.items() if k[0] == workload_type for c in v})
        pct = f"{cov / tot * 100:.0f}%" if tot else "—"
        print(f"{workload_type:10s} 按 case 覆盖 {cov}/{tot} = {pct}")

    for r in R["mismatched"]:
        declared = f"{r['workload_type']}/{r['nature']}" if r["workload_type"] else f"（首段读不出负载类型：{r['covers']!r}）"
        print(f"  ! {r['fixture']}：声明 {declared}，"
              f"但它指向的 case {r['case_id']} 不在这一格——期望命名空间写错了，"
              f"或该 case 已挪格（这条覆盖记在了错的格子上）")

    if args.nature_evidence:
        ev = nature_evidence(root, R["rows"])
        if ev:
            lex = [e for e in ev if e["lexical"]]
            skipped = [r for r in R["rows"] if not r["workload_type"] or not r["nature"]]
            print(f"\n性质证据（分母 = {len(ev)} 条 `expected.namespace` 带性质段的夹具；"
                  f"其中词法上命中期望性质的有 {len(lex)} 条）：")
            for e in ev:
                mark = "词法命中" if e["lexical"] else "仅语义兜底（改坏词表本条也照样通过）"
                shown = "、".join(f"{n}←{p}" for n, p in e["matched"]) or "（无）"
                print(f"  {e['fixture']:38s} 期望 {e['workload_type']}/{e['expected']:12s} "
                      f"命中 {shown}  {mark}")
            # 分母少了谁必须点名：只印一个比例，读者会把它读成"全部夹具里 10 条钉住词表"。
            if skipped:
                names = "、".join(r["fixture"] for r in skipped)
                print(f"  · 不参与本栏的 {len(skipped)} 条（`expected.namespace` 没有性质段）：{names}")
            print("  · 强度说明：词法命中只覆盖它输入里命中的那几个正则——同一形态的词若在多个"
                  "症状组里重复出现，夹具是被这**几处共同**锚定的（实测 `RuntimeError` 在 interrupt 的"
                  "两个症状组各出现一次，只挪走一处，夹具照样是「词法命中」）。"
                  "所以这一栏读作「这条夹具此刻钉着哪几个词」，不读作「改哪一处会被抓到」，"
                  "也不读作「这一侧的词表被守住了」。")

    # 两层判据分开算、分开报：读者要能一眼看出"红的是哪一层"
    # （本脚本第一版把两层压在一个 `--check` 里，结果文档描述的门与实际跑的门不是同一个）。
    workload_type_lacking = []
    for workload_type in (args.require_workload_type or list(WORKLOAD_TYPES)):
        # 只对**库里有 case 的负载类型**要求量尺：负载类型层的判据是"这一侧没有回归保护"，
        # 而"新负载类型先在后端声明、下一条 PR 才补 case 与夹具"是正常顺序（路由协议文件里
        # 写明负载类型列表可扩张），那时拦下来是拦错了对象。
        if not any(k[0] == workload_type for k in lib):
            continue
        if not any(k[0] == workload_type for k in covered):
            workload_type_lacking.append(workload_type)
    cell_gaps = list(gaps)

    if args.check and workload_type_lacking:
        print(f"\n✗ 负载类型层：{len(workload_type_lacking)} 个负载类型一条真实夹具都没有——{', '.join(workload_type_lacking)}")
        print("  （该负载类型下的所有 case 都没有回归保护；补真实来源的夹具，构造示例不算覆盖）")
    if args.check_cells and cell_gaps:
        print(f"\n✗ 格层：{len(cell_gaps)} 个 (负载类型 × 性质) 格子有 case 却没有夹具：")
        for workload_type, nature in cell_gaps:
            print(f"   - {workload_type} / {nature}")
    if args.check and not workload_type_lacking:
        print("\n✓ 负载类型层：每个已声明的负载类型都有真实夹具")
    if cell_gaps and not args.check_cells:
        # 这一行是"默认只报不拦"的可执行指引：要说清怎么把它变成门，不能只印一个缺口数。
        print(f"  · 上面 {len(cell_gaps)} 个格级缺口**默认只报不拦**（补夹具需要真实来源）；"
              f"要把它当门就加 `--check-cells`")
    # 未点名 `--check` / `--check-cells` 时一律不拦；两层各自独立判定，互不掩盖。
    return 1 if (args.check and workload_type_lacking) or (args.check_cells and cell_gaps) else 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
