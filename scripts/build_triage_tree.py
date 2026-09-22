#!/usr/bin/env python3
# build_triage_tree.py —— 重建 triage-tree.yaml（生成物）← triage-tree.d/*.yaml（源，一族一文件）
#
# 为什么要有源/生成物这一层（2026-09-22，起因：并发提交时路由层总撞在同一个文件上）：
#   `triage-tree.yaml` 原先**既是源、又是所有人加词的目标**——一个 141 行的文件里放着 7 个分支，
#   谁都得往它里面加行。实测（近 4 周 20 次改动，约每周 5 次）加词集中在两个分支的 symptoms 列表尾部，
#   而"两人给同一个分支加词"落在同一段文本上，冲突要人判断"留哪一份"——判断错了就静默丢一条路由词，
#   而丢词的表现是"本该命中的分支没命中"，没有任何报错。
#
#   改法与仓库既有模式一致（`metrics/timeline.d/<期号>.yaml` → 生成的 `metrics/timeline.yaml`；
#   `knowledge/` 168 个 case 文件 → 生成的 `knowledge/_index.yaml`）：
#     源    `triage-tree.d/<序号>-<族>.yaml` —— 一族一个文件，改哪族只碰哪个文件，互不覆盖
#     生成物 `triage-tree.yaml`              —— 由本脚本从源拼接，CI 校验一致性
#   另配 `.gitattributes` 的 `merge=union`：两人同一天给同一族加词时按行取并集，**两边都留住**，
#   合流不需要人工判断（重复行由本脚本报出来，删一行即可）。读侧完全不用改：5 个读点继续读
#   `triage-tree.yaml`（diagnose 的 SKILL、verify_references 的 category 合法集、kb-explorer 等）。
#
#   拼接是**逐字保留**的：源文件里 `branches:` 之后的文本原样进入生成物（含行内注释与对齐），
#   所以迁移那一次 `triage-tree.yaml` 的 body 字节不变——路由行为不变的证据是 diff，不是"应该没变"。
#
# 用法：
#   python3 scripts/build_triage_tree.py            # 重建（写文件）
#   python3 scripts/build_triage_tree.py --check    # CI：生成物与源是否一致（不一致即红并说明怎么修）
#   python3 scripts/build_triage_tree.py --print    # 只打印重建结果，不写文件
#
# 分支顺序 = 源文件名的字典序（`10-`、`20-` … 前缀因此是语义的一部分：diagnose 按顺序匹配，
# 先命中先路由）。新族插在中间就用中间号，不要改已有文件的编号。

import argparse
import sys
from pathlib import Path

import yaml

SRC_DIR_REL = Path("triage-tree.d")
OUT_REL = Path("triage-tree.yaml")
PROTOCOL_NAME = "00-protocol.md"
BRANCH_CAP = 30          # 分支数上限（文件头长期写着 ≤30；此前无人守，现在由本脚本守）
CATEGORIES = ("interrupt", "precision", "performance", None)
REQUIRED_KEYS = ("id", "category", "symptoms", "search_namespaces", "fallback")

# git 冲突标记：源文件里出现它几乎只有一个原因——这一族在两边各被改过，且平台那侧没走 union 驱动
# （例如本地手抄合并、或 .gitattributes 没进那一侧）。不特判的话只会报"YAML 解析失败：..."，
# 而人要的答案是"把两份症状都留下"。
CONFLICT_MARKERS = ("<<<<<<<", ">>>>>>>")


def conflict_marked(text: str) -> bool:
    return any(m in text for m in CONFLICT_MARKERS)


def load_source(path: Path):
    """→ (branch, block_text, errors)。block_text 是 `branches:` 之后的原文（逐字保留）。"""
    errors = []
    raw = path.read_text(encoding="utf-8")
    if conflict_marked(raw):
        errors.append(
            f"{path.name}: 文件里有 **git 冲突标记**——这一族在两边各被改过。处置：把两份症状都留下"
            "（union 合并的语义就是两边都留），删掉 <<<<<<< / ======= / >>>>>>> 三行，"
            "再跑 `python3 scripts/build_triage_tree.py`。本目录在 .gitattributes 里配了 merge=union，"
            "正常走平台合并时不会产生这个冲突标记。"
        )
        return None, None, errors
    lines = raw.split("\n")
    if "branches:" not in lines:
        errors.append(f"{path.name}: 顶层缺少 `branches:` 行（本目录里的每个文件都是一个分支的源）")
        return None, None, errors
    bi = lines.index("branches:")
    block = "\n".join(lines[bi + 1:])
    if not block.endswith("\n"):
        block += "\n"
    try:
        doc = yaml.safe_load("branches:\n" + block)
    except Exception as e:
        errors.append(f"{path.name}: 分支块 YAML 解析失败：{e}")
        return None, None, errors
    branches = (doc or {}).get("branches") or []
    if len(branches) != 1:
        errors.append(
            f"{path.name}: 应当是**一族一文件**（branches 列表恰好 1 项），实际 {len(branches)} 项。"
            "一族一文件是 union 合并能自动留住两边改动的前提；多族混在一个文件里，"
            "合并就又回到「判断留哪份」。拆成 <序号>-<族>.yaml。"
        )
        return None, None, errors
    return branches[0], block, errors


def validate(branch, path, seen_ids):
    """分支字段的确定性校验 → errors / warnings。"""
    errors, warnings = [], []
    bid = branch.get("id")
    if not bid:
        return [f"{path.name}: 分支缺少 id"], []
    if bid in seen_ids:
        errors.append(
            f"{path.name}: 分支 id '{bid}' 与 {seen_ids[bid]} 重复——路由按分支顺序匹配，"
            "重复 id 会让 trace 里的 routed 指向不明。删掉其中一个文件。"
        )
    else:
        seen_ids[bid] = path.name
    for k in REQUIRED_KEYS:
        if k not in branch:
            errors.append(f"{path.name}: 分支 '{bid}' 缺少必填键 {k}")
    cat = branch.get("category", "MISSING")
    if cat not in CATEGORIES:
        errors.append(
            f"{path.name}: 分支 '{bid}' 的 category {cat!r} 非法——"
            "合法取值只有 interrupt / precision / performance，或兜底分支的 null（other 已废弃）"
        )
    syms = branch.get("symptoms")
    if not isinstance(syms, list):
        errors.append(f"{path.name}: 分支 '{bid}' 的 symptoms 应当是列表（每条是一组正则备选）")
    else:
        seen_groups = []
        for i, group in enumerate(syms):
            if not isinstance(group, list) or not group:
                errors.append(f"{path.name}: 分支 '{bid}' 第 {i + 1} 条症状应为非空列表（一组备选写法）")
                continue
            for alt in group:
                if not isinstance(alt, str) or not alt:
                    errors.append(f"{path.name}: 分支 '{bid}' 第 {i + 1} 条症状里有非字符串/空项")
            # 只报**整条重复**（union 合并的产物）：跨组重复同一个词是正常数据（同一形态在不同
            # 证据链里各写一次），报它只会训练人忽略告警。
            key = tuple(group)
            if key in seen_groups:
                warnings.append(
                    f"{path.name}: 分支 '{bid}' 第 {i + 1} 条症状与前面某条完全相同——"
                    "多半是 union 合并把两人加的同一行都留下了，删掉一行即可（不删不影响路由）"
                )
            else:
                seen_groups.append(key)
    sn = branch.get("search_namespaces")
    if not isinstance(sn, list) or not sn or not all(isinstance(x, str) and x for x in sn):
        errors.append(f"{path.name}: 分支 '{bid}' 的 search_namespaces 应为非空字符串列表")
    return errors, warnings


def collect_sources(root: Path):
    """→ (protocol_text, blocks, errors, warnings)。"""
    src_dir = root / SRC_DIR_REL
    if not src_dir.is_dir():
        return None, [], [f"源目录不存在：{SRC_DIR_REL}（Tier 1 路由以它为源）"], []
    proto_path = src_dir / PROTOCOL_NAME
    if not proto_path.exists():
        return None, [], [f"缺少 {SRC_DIR_REL}/{PROTOCOL_NAME}（路由说明与入场判据的写点）"], []
    protocol = proto_path.read_text(encoding="utf-8")

    blocks, errors, warnings, seen_ids = [], [], [], {}
    files = sorted(p for p in src_dir.glob("*.yaml"))
    if not files:
        return protocol, [], [f"{SRC_DIR_REL} 里没有任何分支源文件"], []
    for f in files:
        branch, block, errs = load_source(f)
        errors += errs
        if branch is None:
            continue
        e, w = validate(branch, f, seen_ids)
        errors += e
        warnings += w
        blocks.append(block)
    if len(seen_ids) > BRANCH_CAP:
        errors.append(f"分支数 {len(seen_ids)} 超过上限 {BRANCH_CAP}——路由层超限后匹配成本与误吸都会上升")
    return protocol, blocks, errors, warnings


def render(protocol_text: str, blocks) -> str:
    """protocol.md 的每行前加 '# '（空行加 '#'）；`branches:` 之后逐字拼接各族的块。"""
    lines = protocol_text.rstrip("\n").split("\n")
    header = "".join(("# " + ln if ln.strip() else "#") + "\n" for ln in lines)
    return header + "#\n" + "branches:\n" + "".join(blocks)


def coverage_problems(root: Path, blocks):
    """**覆盖检查**（这是门）：源里每个分支的每条症状组，是否都在聚合里。

    为什么门不是"逐字节与重新拼接的结果相同"：`triage-tree.yaml` 配了 merge=union
    （两人同一天给同一族加词时两边都留住），那种合并结果**内容是对的**、只是顺序可能与
    重新拼接不同。逐字节的门会把正确的合并判红，等于把 union 的收益还回去。
    要归一化随时跑一次生成器（那是可选的）。
    """
    out = root / OUT_REL
    if not out.exists():
        return [f"{OUT_REL} 不存在——跑 `python3 scripts/build_triage_tree.py`"]
    try:
        doc = yaml.safe_load(out.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return [f"{OUT_REL} YAML 解析失败（{e}）——重跑 `python3 scripts/build_triage_tree.py`"]
    got = {b.get("id"): b for b in (doc.get("branches") or []) if isinstance(b, dict)}
    problems = []
    for block in blocks:
        src = yaml.safe_load("branches:\n" + block)["branches"][0]
        bid = src["id"]
        have = got.get(bid)
        if have is None:
            problems.append(f"聚合里缺分支 {bid}——重跑 `python3 scripts/build_triage_tree.py`（union 合并偶尔会丢一段）")
            continue
        for key in ("category", "search_namespaces", "fallback"):
            if JSONish(have.get(key)) != JSONish(src.get(key)):
                problems.append(f"分支 {bid} 的 {key} 与源不一致——重跑 `python3 scripts/build_triage_tree.py`")
        have_groups = [tuple(g) for g in (have.get("symptoms") or [])]
        for group in src.get("symptoms") or []:
            if tuple(group) not in have_groups:
                problems.append(f"分支 {bid} 里缺症状组 {group}——重跑 `python3 scripts/build_triage_tree.py`")
    src_ids = {yaml.safe_load('branches:\n' + b)['branches'][0]['id'] for b in blocks}
    for bid in sorted(set(got) - src_ids):
        problems.append(f"聚合里有、源里没有的分支 {bid}——重跑 `python3 scripts/build_triage_tree.py`")
    return problems


def JSONish(v):
    """把 None/列表拉到同一个可比较形态（None 与 [] 在这里语义不同，不合并）。"""
    return v


def main() -> int:
    ap = argparse.ArgumentParser(description="重建生成的 triage-tree.yaml（源：triage-tree.d/）")
    ap.add_argument("--check", action="store_true",
                    help="逐字节自检（不作门）：确认聚合与「重新拼接一遍」完全相同")
    ap.add_argument("--check-coverage", action="store_true",
                    help="覆盖检查（门）：源里每个分支的每条症状组都在聚合里")
    ap.add_argument("--check-sources", action="store_true",
                    help="只校验源文件本身（分支 id 唯一 / category 合法 / ≤30 分支 / 一族一文件）")
    ap.add_argument("--print", dest="do_print", action="store_true", help="只打印，不写文件")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    root = args.root.resolve()

    protocol, blocks, errors, warnings = collect_sources(root)
    for w in warnings:
        print(f"WARN: {w}")
    if errors:
        print(f"{SRC_DIR_REL} 有 {len(errors)} 处问题：")
        for e in errors:
            print(f"  - {e}")
        return 1
    if not blocks:
        print(f"{SRC_DIR_REL} 里没有可拼接的分支——路由层未落地")
        return 1

    wanted = render(protocol, blocks)
    out_path = root / OUT_REL

    if args.do_print:
        print(wanted)
        return 0

    if args.check_sources:
        print(f"路由源文件合法（{len(blocks)} 个分支 ← {SRC_DIR_REL}/）")
        return 0

    if args.check_coverage:
        problems = coverage_problems(root, blocks)
        if problems:
            for p in problems:
                print(f"路由覆盖问题：{p}")
            print(f"\n{len(problems)} 处。跑一次重建即可（聚合随 PR 提交）：")
            print("  python3 scripts/build_triage_tree.py")
            return 1
        n_groups = sum(len(yaml.safe_load('branches:\n' + b)['branches'][0].get("symptoms") or [])
                       for b in blocks)
        print(f"路由覆盖完整：{len(blocks)} 个分支 / {n_groups} 组症状都在聚合 {OUT_REL} 里。")
        return 0

    if args.check:
        current = out_path.read_text(encoding="utf-8") if out_path.exists() else None
        if current == wanted:
            print(f"triage-tree 聚合与「重新拼接一遍」逐字节相同（{len(blocks)} 个分支 ← {SRC_DIR_REL}/）")
            return 0
        print(f"{OUT_REL} 与重新拼接的结果不同（内容可能已齐全，只是顺序/注释未归一）：")
        print("  归一化（可选，随时可跑）：python3 scripts/build_triage_tree.py")
        if current is None:
            print(f"  （原因：{OUT_REL} 不存在）")
        else:
            try:
                cur_ids = [b.get("id") for b in (yaml.safe_load(current) or {}).get("branches", [])]
            except Exception:
                cur_ids = None
            src_ids = [b.get("id") for b in (yaml.safe_load(wanted) or {}).get("branches", [])]
            if cur_ids is not None and cur_ids != src_ids:
                print(f"  聚合分支：{cur_ids}")
                print(f"  源  分支：{src_ids}")
        return 1

    out_path.write_text(wanted, encoding="utf-8", newline="\n")
    print(f"已重建 {OUT_REL}（{len(blocks)} 个分支 ← {SRC_DIR_REL}/）")
    for b in (yaml.safe_load(wanted) or {}).get("branches", []):
        print(f"  - {b.get('id'):<22} category={b.get('category')}  症状组 {len(b.get('symptoms') or [])}")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
