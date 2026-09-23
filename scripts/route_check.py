#!/usr/bin/env python3
# route_check.py —— 提交前自查：这条 case 会被哪个**性质**接住，以及它所在的**负载类型**会不会被别侧抢走
#
# 为什么需要它（2026-09-22，起因：设计"独立预核"时发现内容类 PR 缺一个能跑的动作）：
#   CI 查的是路由表**结构**（性质 id 唯一、category 合法、≤30 性质、源与聚合一致、负载类型层完整），
#   它不查"这条 case 的症状实际会被哪个性质接住"。而路由分两层之后多了一类只有它能报的错：
#   **负载类型被写进了症状层**——性质词表是训推共用的，一旦某条正则只在某一负载类型的措辞上成立
#   （`vllm serve`、`训练无法启动` 这类），另一侧的同性质 case 就会掉进别的性质或没命中。
#   分层之前这类错的表现是"跨负载类型误吸"（一个宽词写在两侧、分支顺序决定谁先接住）；
#   分层之后结构上不再可能，但**新写进去的负载类型专属词**仍会以"没命中"的形式静默生效。
#
# 输入是**代理输入**，不是真实输入：真实路由喂的是工程师贴的症状文本，这里拿 case 自己的
# title + symptoms 当代理。所以结论读作"这条 case 的措辞会落在哪里"，不是"诊断时一定这样路由"。
#
# 用法：
#   python3 scripts/route_check.py <case 文件>      # 报告：期望性质 / 首个命中 / 全部命中 / 跨性质重复词
#   python3 scripts/route_check.py --wide-words     # 全库体检：同一正则出现在多个性质的清单
#   python3 scripts/route_check.py --show-workload-types     # 打印负载类型层（合法负载类型 + 每种负载类型的目录面与检索顺序）
#
# 退出码：0 期望性质与首个命中一致（或本条不参与路由，如 common/）；1 不一致、
# 或路由表里有不可编译的正则（那时"没命中"不可信）；2 用法/读取错误。

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
TRIAGE = REPO / "triage-tree.yaml"
SIDE_PLACEHOLDER = "<side>/"  # 聚合里的字面记号（取值为 training / inference），别改名


def load_tree(root: Path):
    """→ (natures, workload_types)。顶层键就是这两个（分层后 `branches:` 桶已退休）。"""
    p = root / "triage-tree.yaml"
    if not p.exists():
        # 用 2（读取错误）而不是 1（判定不一致）：0/1/2 三分是这个脚本的对外契约，
        # 读不到表与"期望性质对不上"在剪贴板和 CI 里必须不同形。
        print(f"读不到 {p}——先跑 `python3 scripts/build_triage_tree.py`", file=sys.stderr)
        raise SystemExit(2)
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return (doc.get("natures") or []), (doc.get("workload_types") or [])


def load_branches(root: Path):
    """兼容只关心性质层的调用点。"""
    return load_tree(root)[0]


def case_text(case: dict) -> str:
    parts = [str(case.get("title") or "")]
    parts += [str(s) for s in (case.get("symptoms") or [])]
    return " ".join(parts)


def effective_branches(branches: list, workload_type: str | None, framework: str | None = None,
                       workload_types: list | None = None):
    """给定负载类型，返回**实际参与判定**的性质分支（`<side>/`（记号）按该负载类型展开成具体目录）。

    这是分层之后"跨负载类型碰撞不可能发生"的机制所在：某一种负载类型的诊断只拿该负载类型的目录面，
    性质词表虽然训推共用，但另一侧的检索面根本不在候选里——"哪一种负载类型"不再是一个
    要靠症状词猜出来的量。

    workload_type 为空 = 负载类型未知：**所有**已声明的负载类型都查（保底，不阻塞诊断）。负载类型列表从聚合的
    `workload_types:` 现取，不在这里写死几个——将来加第三个负载类型时，忘改这里会让负载类型未知的诊断
    静默漏查新负载类型（没命中与漏查在输出上同形）。**聚合没给 `workload_types:` 时不猜**：宁可报错，
    也不退回一对写死的负载类型——那正是删掉 `branches:` 别名时不要的那种"读不到就悄悄用旧口径"。
    """
    side_ids = [str(s.get("id")) for s in (workload_types or []) if isinstance(s, dict) and s.get("id")]
    if not side_ids:
        raise ValueError("聚合里没有 `workload_types:`——负载类型层未落地，无从展开 `<side>/`"
                         "（重跑 `python3 scripts/build_triage_tree.py`）")
    out = []
    for b in branches:
        ns = []
        for raw in b.get("search_namespaces") or []:
            if SIDE_PLACEHOLDER not in raw:
                ns.append(raw)
            elif workload_type:
                ns.append(raw.replace(SIDE_PLACEHOLDER, f"{workload_type}/"))
            else:
                ns += [raw.replace(SIDE_PLACEHOLDER, f"{s}/") for s in side_ids]
        if framework:
            ns = [n.replace("<detected_framework>", framework) for n in ns]
        seen, uniq = set(), []
        for n in ns:
            if n not in seen:
                seen.add(n)
                uniq.append(n)
        out.append({**b, "search_namespaces": uniq})
    return out


def hits_for(text: str, branches: list):
    """→ (hits, broken)：hits = [(性质 id, 命中的正则)]（每个性质只报首个命中），
    broken = [(性质 id, 不可编译的正则)]。

    不可编译的正则**不能静默跳过**：跳过的后果是"该性质根本没参与判定"，而输出读起来像
    "这条 case 没命中任何性质"——两者在界面上同形，等于这个脚本在真空通过（独立预核实测：
    把某性质的正则写成 `[` 后，该负载类型的 case 被报成"无命中"并 exit 0）。
    """
    out, broken = [], []
    for b in branches:
        hit = None
        for group in b.get("symptoms") or []:
            for pat in group:
                try:
                    matched = re.search(pat, text, re.I)
                except re.error:
                    broken.append((b.get("id"), pat))
                    continue
                if matched and hit is None:
                    hit = pat
            if hit is not None:
                break
        if hit is not None:
            out.append((b.get("id"), hit))
    return out, broken


def case_workload_type_and_nature(path: Path, root: Path):
    """从 case 路径取 (负载类型, 性质)：knowledge/<training|inference>/<fw>/<性质>/x.yaml。

    分层之后**性质就是分支名**（interrupt / precision / performance）：负载类型不再进分支 id
    ——它由工程师的事实确定（见 triage-tree.d/00-protocol.md），所以这里只把路径当
    "这条 case 归哪个性质、属于哪一种负载类型"的事实来源，不回答"负载类型怎么判出来的"。
    common/ 下的共性 case 框架无关，两项都返回空串表示"本条不判"。
    """
    try:
        rel = path.resolve().relative_to((root / "knowledge").resolve())
    except ValueError:
        return "", ""
    parts = rel.parts
    if len(parts) >= 3 and parts[0] in ("training", "inference"):
        return parts[0], parts[2]
    return "", ""


def expected_branch(path: Path, root: Path) -> str:
    """兼容旧调用点：只要性质那一段。"""
    return case_workload_type_and_nature(path, root)[1]


def wide_words(branches: list):
    """同一正则出现在多个性质 → [(正则, [性质 id, ...]), ...]。

    分层后这个词单的形状变了：原先列的是"同一个词在训推两处各写一遍"（全库 57 条，
    顺序决定谁先接住）；现在性质词表训推共用，**跨负载类型重复在结构上不存在**，
    所以剩下的这一档才是最该看的：**同一形态被两个性质同时认领**——
    那意味着性质归属要靠性质顺序裁决，而不是靠证据。要么确认顺序是有意的，要么给更窄的变体。
    """
    where = {}
    for b in branches:
        for group in b.get("symptoms") or []:
            for pat in group:
                where.setdefault(pat, []).append(b.get("id"))
    return [(pat, ids) for pat, ids in sorted(where.items()) if len(set(ids)) > 1]


def main() -> int:
    ap = argparse.ArgumentParser(description="提交前自查：这条 case 会归到哪个性质分支")
    ap.add_argument("case_file", nargs="?", help="case 文件路径（knowledge/**/*.yaml）")
    ap.add_argument("--wide-words", action="store_true", help="只列跨性质重复的正则（全库体检）")
    ap.add_argument("--show-workload-types", action="store_true", help="打印负载类型层（合法负载类型 + 每种负载类型的目录面与检索顺序）")
    ap.add_argument("--root", type=Path, default=REPO)
    args = ap.parse_args()
    root = args.root.resolve()
    branches, workload_types = load_tree(root)

    if args.show_workload_types:
        if not workload_types:
            print("路由表里没有 `workload_types:`——分层未落地（重跑 `python3 scripts/build_triage_tree.py`）")
            return 1
        print(f"合法负载类型：{len(workload_types)} 个")
        for s in workload_types:
            print(f"  {str(s.get('id')):<12} {s.get('label', '')}"
                  f"  检索面：{', '.join(s.get('namespaces') or [])}")
        return 0

    if args.wide_words:
        # **路由层缺失时不能静默报"0 条"**：`wide_words([])` 也是 []，与"真的没有重复词"同形，
        # 而这条命令正是 to-postmortem 让加词的人"扫一眼"的那条——把"没读着"读成"没问题"
        # 的代价是加词的人以为扫过了。同 `--show-workload-types` 的守卫。
        if not branches:
            print("路由表里没有 `natures:`——分层未落地（重跑 `python3 scripts/build_triage_tree.py`）")
            return 1
        ww = wide_words(branches)
        print(f"跨性质重复的正则：{len(ww)} 条（同一形态被两个性质同时认领；确认是有意的，或给更窄的变体）")
        for pat, ids in ww:
            print(f"  {pat!r:<44} → {', '.join(ids)}")
        return 0

    if not args.case_file:
        ap.error("给一个 case 文件路径，或用 --wide-words / --show-workload-types")

    path = Path(args.case_file)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        print(f"读不到 {path}", file=sys.stderr)
        return 2
    if path.is_dir():
        print(f"{path} 是目录——给一个 case 文件（knowledge/**/*.yaml）", file=sys.stderr)
        return 2
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"{path} 读不动（{type(e).__name__}：{e}）", file=sys.stderr)
        return 2
    cases = doc.get("cases") or []
    if not cases:
        print(f"{path} 里没有 cases", file=sys.stderr)
        return 2

    workload_type, exp = case_workload_type_and_nature(path, root)
    known = [str(b.get("id")) for b in branches]
    if exp and exp not in known:
        print(f"⚠ {path} 所在目录的性质段 '{exp}' 不是任何路由性质（路由里有：{', '.join(known)}）"
              f"——目录与路由表对不上，先确认这条 case 该归哪一类", file=sys.stderr)
        return 2

    try:
        cand = effective_branches(branches, workload_type, workload_types=workload_types)   # 负载类型已知 → 只拿该负载类型；负载类型未知 → 所有负载类型都查
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    rel = path.relative_to(root) if path.is_relative_to(root) else path
    all_wide = wide_words(branches)
    mismatch = 0
    for i, case in enumerate(cases):
        hits, broken = hits_for(case_text(case), cand)
        head = f"case：{case.get('id')}" + (f"（{rel} 第 {i + 1}/{len(cases)} 条）" if len(cases) > 1 else f"（{rel}）")
        print(head)
        print(f"负载类型：{workload_type or '（不在 knowledge/<负载类型>/ 下——本条不判负载类型）'}"
              f"    期望性质：{exp or '（common/ 或路径不在 knowledge/<负载类型>/<框架>/<性质>/，本条不判）'}")
        if workload_type and cand:
            print(f"本条检索面（只含本条负载类型）：{', '.join(cand[0].get('search_namespaces') or [])}")
        print(f"命中性质（按聚合顺序）：{', '.join(f'{bid}←{pat}' for bid, pat in hits) or '（无命中 → 诊断时走语义兜底）'}")
        dup = [(pat, ids) for pat, ids in all_wide if any(pat == p for _b, p in hits)]
        if dup:
            print("本条用的宽词跨性质重复（顺序先到者接住）：")
            for pat, ids in dup:
                print(f"  {pat!r} → {', '.join(ids)}")
        if broken:
            for bid, pat in broken:
                print(f"⚠ 性质 {bid} 的正则 {pat!r} 不可编译，该性质**未参与判定**——这条结论不等于"
                      f"「没命中该性质」；先修路由表（重跑 `python3 scripts/build_triage_tree.py`）")
            mismatch += 1
        if exp and hits and hits[0][0] != exp:
            print(f"⚠ 首个命中是 {hits[0][0]}，不是期望的 {exp}——症状里可能缺该性质独有的签名"
                  f"（错误码/算子名/框架特有措辞），或该补一条更窄的变体；另一种可能是这条词"
                  f"只在某一边的措辞上成立（性质词表训推共用，写进某一边专属的措辞会让另一边的同性质 case 掉出去）")
            mismatch += 1
        elif exp and not hits:
            print("（无命中：诊断时会走语义兜底；若这是新形态，按路由入场判据考虑给对应性质补词）")
        if i + 1 < len(cases):
            print()
    return 1 if mismatch else 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
