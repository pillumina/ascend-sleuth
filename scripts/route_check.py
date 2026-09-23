#!/usr/bin/env python3
# route_check.py —— 提交前自查：这条 case 的症状会被哪个分支接住
#
# 为什么需要它（2026-09-22，起因：设计"独立预核"时发现内容类 PR 缺一个能跑的动作）：
#   CI 查的是路由表**结构**（分支 id 唯一、category 合法、≤30 分支、源与聚合一致），
#   它不查"这条 case 的症状实际会被哪个分支接住"。而路由是**有顺序**的：triage-tree 里
#   `training_interrupt` 排在 `inference_interrupt` 前面，而 `\btimeout\b`、`RuntimeError`
#   这类宽词在两边都有——只写宽词的推理侧 case，症状面会被 training 分支先接住。
#   这类"分支误吸"本来就在路由的入场判据里（三种证据之一），但此前没有任何检查器报出来。
#
# 输入是**代理输入**，不是真实输入：真实路由喂的是工程师贴的症状文本，这里拿 case 自己的
# title + symptoms 当代理。所以结论读作"这条 case 的措辞会落在哪里"，不是"诊断时一定这样路由"。
#
# 用法：
#   python3 scripts/route_check.py <case 文件>      # 报告：期望分支 / 首个命中 / 全部命中 / 宽词
#   python3 scripts/route_check.py --wide-words     # 全库体检：同一正则出现在多个分支的清单
#
# 退出码：0 期望分支与首个命中一致（或本条不参与路由，如 common/）；1 不一致；2 用法/读取错误。

import argparse
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
TRIAGE = REPO / "triage-tree.yaml"


def load_branches(root: Path):
    p = root / "triage-tree.yaml"
    if not p.exists():
        sys.exit(f"读不到 {p}——先跑 `python3 scripts/build_triage_tree.py`")
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return doc.get("branches") or []


def case_text(case: dict) -> str:
    parts = [str(case.get("title") or "")]
    parts += [str(s) for s in (case.get("symptoms") or [])]
    return " ".join(parts)


def hits_for(text: str, branches: list):
    """按分支顺序返回 [(分支 id, 命中的正则), ...]（每个分支只报首个命中）。"""
    out = []
    for b in branches:
        for group in b.get("symptoms") or []:
            for pat in group:
                try:
                    if re.search(pat, text, re.I):
                        out.append((b.get("id"), pat))
                        break
                except re.error:
                    continue
            else:
                continue
            break
    return out


def expected_branch(path: Path, root: Path) -> str:
    """从 case 路径推"它该被哪个分支接住"：knowledge/<training|inference>/<fw>/<cat>/x.yaml。

    common/ 下的共性 case 不参与路由（框架无关），返回空串表示"本条不判"。
    """
    try:
        rel = path.resolve().relative_to((root / "knowledge").resolve())
    except ValueError:
        return ""
    parts = rel.parts
    if len(parts) >= 3 and parts[0] in ("training", "inference"):
        return f"{parts[0]}_{parts[2]}"
    return ""


def wide_words(branches: list):
    """同一正则出现在多个分支 → [(正则, [分支 id, ...]), ...]。

    宽词跨分支本身是设计常态（同一个词在训推两侧都出现），但**顺序**决定了谁先接住；
    交接清单给 reviewer 用：要么确认这个顺序是有意的，要么给更窄的变体。
    """
    where = {}
    for b in branches:
        for group in b.get("symptoms") or []:
            for pat in group:
                where.setdefault(pat, []).append(b.get("id"))
    return [(pat, ids) for pat, ids in sorted(where.items()) if len(set(ids)) > 1]


def main() -> int:
    ap = argparse.ArgumentParser(description="提交前自查：这条 case 会被哪个路由分支接住")
    ap.add_argument("case_file", nargs="?", help="case 文件路径（knowledge/**/*.yaml）")
    ap.add_argument("--wide-words", action="store_true", help="只列跨分支重复的正则（全库体检）")
    ap.add_argument("--root", type=Path, default=REPO)
    args = ap.parse_args()
    root = args.root.resolve()
    branches = load_branches(root)

    if args.wide_words:
        ww = wide_words(branches)
        print(f"跨分支重复的正则：{len(ww)} 条（顺序决定谁先接住；确认是有意的，或给更窄的变体）")
        for pat, ids in ww:
            print(f"  {pat!r:<44} → {', '.join(ids)}")
        return 0

    if not args.case_file:
        ap.error("给一个 case 文件路径，或用 --wide-words")

    path = Path(args.case_file)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        print(f"读不到 {path}", file=sys.stderr)
        return 2
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = doc.get("cases") or []
    if not cases:
        print(f"{path} 里没有 cases", file=sys.stderr)
        return 2
    exp = expected_branch(path, root)
    rel = path.relative_to(root) if path.is_relative_to(root) else path
    all_wide = wide_words(branches)
    mismatch = 0
    for i, case in enumerate(cases):
        hits = hits_for(case_text(case), branches)
        head = f"case：{case.get('id')}" + (f"（{rel} 第 {i + 1}/{len(cases)} 条）" if len(cases) > 1 else f"（{rel}）")
        print(head)
        print(f"期望分支：{exp or '（common/ 或路径不在 knowledge/<训推>/<框架>/<性质>/，本条不判）'}")
        print(f"命中分支（按聚合顺序）：{', '.join(f'{bid}←{pat}' for bid, pat in hits) or '（无命中 → 诊断时走语义兜底）'}")
        dup = [(pat, ids) for pat, ids in all_wide if any(pat == p for _b, p in hits)]
        if dup:
            print("本条用的宽词跨分支重复（顺序先到者接住）：")
            for pat, ids in dup:
                print(f"  {pat!r} → {', '.join(ids)}")
        if exp and hits and hits[0][0] != exp:
            print(f"⚠ 首个命中是 {hits[0][0]}，不是期望的 {exp}——症状里可能缺该分支独有的签名（错误码/算子名/框架特有措辞），"
                  f"或该补一条更窄的变体")
            mismatch += 1
        elif exp and not hits:
            print("（无命中：诊断时会走语义兜底；若这是新形态，按路由入场判据考虑给对应族补词）")
        if i + 1 < len(cases):
            print()
    return 1 if mismatch else 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
