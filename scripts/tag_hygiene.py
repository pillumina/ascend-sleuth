#!/usr/bin/env python3
# tag_hygiene.py —— case tag 归一 + R8 共性提炼候选聚类（机械环节，M5 脚本先行）
#
# 通用性设计（2026-09-09 review 后重构）：本脚本只做**通用处理**（解析/改写/聚类），
# 词表（同义词、类别、保留项）全部从 `docs/tag-vocabulary.yaml` 读取——新增一个同义词
# 或模型名是**改数据**，不是改代码。与 case 字段重复的 tag（category 值 / namespace
# 叶子名）由脚本**自动识别**，随 KB 增长自动跟进，无需登记。
#
# 职责：
#   1) --normalize [--apply]：按词表归一 knowledge/** 的 case tags（行级改写，保留原格式）
#   2) --check：校验 tag 是否已全部归一（残留 alias / 非 ASCII / 违反 keep_separate 则非零退出）
#   3) 默认：输出 R8 候选组（同 tag ≥N 条且 ≥N 条未被 reference 收录），带 tag 类别标注
#
# 为什么需要归一：R8 是 tag 驱动的机械信号，但 tag 有三类污染——
#   ① category / namespace 名混进 tag（与字段重复，零信息）；
#   ② 同义分裂（同一现象多种拼法，互相检索不到）；
#   ③ 拼写 / 语言变体（fusedmoe、混部）。
# 归一前 507 个不同 tag、70 个出现 ≥3 次，R8 几乎不筛（2026-09-09 实测）。
#
# 用法：
#   python3 scripts/tag_hygiene.py                      # R8 候选组（默认 --min 3）
#   python3 scripts/tag_hygiene.py --min 4
#   python3 scripts/tag_hygiene.py --normalize          # 干跑
#   python3 scripts/tag_hygiene.py --normalize --apply  # 实际改写
#   python3 scripts/tag_hygiene.py --check              # 归一完备性校验
#
# 依赖：PyYAML（pip install pyyaml）

import argparse
import re
import sys

from _stdio import write_text_lf
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：pip install pyyaml")

DEFAULT_VOCAB = "docs/tag-vocabulary.yaml"


# ---- 词表加载 ----

def load_vocab(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"缺少 tag 词表：{path}")
    v = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        "synonyms": v.get("synonyms") or {},
        "kinds": v.get("kinds") or {},
        "drop": set(v.get("drop") or []),
        "keep_separate": v.get("keep_separate") or [],
    }


# ---- 扫描 ----

def iter_case_files(root: Path):
    kdir = root / "knowledge"
    for p in sorted(kdir.rglob("*.yaml")):
        rel = p.relative_to(kdir)
        if rel.parts[0] in ("_archive", "_index") or p.name.startswith("_"):
            continue
        yield p


def load_cases(root: Path):
    """→ [(path, case_dict), ...]"""
    out = []
    for p in iter_case_files(root):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for c in doc.get("cases") or []:
            if isinstance(c, dict):
                out.append((p, c))
    return out


def ns_of(rel: Path) -> str:
    """目录 → namespace 名（与 build_index.py 的折叠规则一致）。"""
    parts = rel.parts
    if len(parts) >= 3 and parts[0] in ("inference", "training"):
        return parts[1]
    if len(parts) >= 2 and parts[0] == "common":
        return "common"
    return parts[0] if parts else ""


def auto_drop(root: Path) -> set:
    """与 case 字段重复的 tag：category 值 + namespace 名（自动识别，无需登记）。"""
    cats, ns_names = set(), set()
    for p, c in load_cases(root):
        if c.get("category"):
            cats.add(str(c["category"]))
        ns_names.add(ns_of(p.relative_to(root / "knowledge")))
    return cats | ns_names


def covered_cases(root: Path) -> set:
    """已被 reference 收录的 case id（sources[].cases + content.*.source_cases）。"""
    cov = set()
    for p in (root / "references").rglob("*.yaml"):
        if p.name.startswith("_"):
            continue
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(d, dict):
            continue
        for s in d.get("sources") or []:
            if isinstance(s, dict):
                for cid in s.get("cases") or []:
                    cov.add(cid)
        content = d.get("content") or {}
        if isinstance(content, dict):
            for v in content.values():
                if isinstance(v, list):
                    for it in v:
                        if isinstance(it, dict):
                            for cid in it.get("source_cases") or []:
                                cov.add(cid)
    return cov


# ---- 归一 ----

def make_norm(vocab: dict, drop: set):
    syn = {str(k): str(v) for k, v in vocab["synonyms"].items()}

    def norm_tag(t: str):
        t = str(t)
        if t in drop:
            return None
        return syn.get(t, t)

    def norm_list(tags):
        seen, out = set(), []
        for t in tags or []:
            n = norm_tag(t)
            if n and n not in seen:
                seen.add(n)
                out.append(n)
        return out

    return norm_tag, norm_list


TAG_INLINE_RE = re.compile(r"^(\s*(?:- )?tags:\s*)\[(.*)\]\s*$")
TAG_BLOCK_RE = re.compile(r"^(\s*(?:- )?tags:\s*)$")
TAG_ITEM_RE = re.compile(r"^(\s*- )(.*)$")


def emit_item(t: str) -> str:
    """需要引号时加单引号（纯数字、含特殊字符）。"""
    if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.\-]*", t) and not re.fullmatch(r"\d+", t):
        return t
    return f"'{t}'"


def parse_items(raw: str):
    items = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "'\"":
            part = part[1:-1]
        items.append(part)
    return items


def normalize_file(path: Path, norm_list, apply: bool):
    """行级归一；apply=False 时只报告不改。→ [(old, new), ...]"""
    lines = path.read_text(encoding="utf-8").split("\n")
    changes = []
    i = 0
    while i < len(lines):
        m_inline = TAG_INLINE_RE.match(lines[i])
        if m_inline:
            old = parse_items(m_inline.group(2))
            new = norm_list(old)
            if new != old:
                changes.append((old, new))
                if apply:
                    lines[i] = m_inline.group(1) + "[" + ", ".join(emit_item(t) for t in new) + "]"
            i += 1
            continue
        m_block = TAG_BLOCK_RE.match(lines[i])
        if m_block:
            indent = len(m_block.group(1)) - len(m_block.group(1).lstrip())
            j = i + 1
            items = []
            while j < len(lines):
                mi = TAG_ITEM_RE.match(lines[j])
                if not mi or (len(mi.group(1)) - len(mi.group(1).lstrip())) <= indent - 1:
                    break
                raw = mi.group(2).strip()
                if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
                    raw = raw[1:-1]
                items.append(raw)
                j += 1
            new = norm_list(items)
            if new != items:
                changes.append((items, new))
                if apply:
                    item_indent = " " * (indent + 2)
                    lines[i:j] = [m_block.group(1)] + [f"{item_indent}- {emit_item(t)}" for t in new]
                    i = i + 1 + len(new)
                    continue
            i = j
            continue
        i += 1
    if changes and apply:
        write_text_lf(path, "\n".join(lines))
    return changes


# ---- 聚类 ----

def kind_of(tag: str, kinds: dict) -> str:
    for k, tags in kinds.items():
        if tag in (tags or []):
            return k
    return "mechanism"


def main():
    ap = argparse.ArgumentParser(description="case tag 归一 + R8 共性提炼候选聚类")
    ap.add_argument("--root", default=".", help="仓库根目录（含 knowledge/ 与 references/）")
    ap.add_argument("--vocab", default=DEFAULT_VOCAB, help=f"tag 词表路径（默认 {DEFAULT_VOCAB}）")
    ap.add_argument("--min", type=int, default=3, help="R8 组的最小条数（默认 3）")
    ap.add_argument("--normalize", action="store_true", help="归一 tags（默认干跑）")
    ap.add_argument("--apply", action="store_true", help="配合 --normalize 实际改写文件")
    ap.add_argument("--check", action="store_true", help="校验 tag 是否已全部归一")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    vocab = load_vocab(root / args.vocab)
    drop = auto_drop(root) | vocab["drop"]
    _, norm_list = make_norm(vocab, drop)

    if args.check:
        bad = []
        for p, c in load_cases(root):
            tags = [str(t) for t in (c.get("tags") or [])]
            if norm_list(tags) != tags:
                bad.append((str(p.relative_to(root)), c.get("id"), tags, norm_list(tags)))
            for t in tags:
                if re.search(r"[^\x00-\x7F]", t):
                    bad.append((str(p.relative_to(root)), c.get("id"), tags, ["非 ASCII tag"]))
        if bad:
            print(f"tag 未归一（{len(bad)} 处）：")
            for rel, cid, old, new in bad:
                print(f"  {rel} [{cid}]: {old} → {new}")
            return 1
        print(f"tag 归一完备（词表 {args.vocab}；自动删除项 {sorted(drop)}）")
        return 0

    if args.normalize:
        n_files = n_changes = 0
        for p in iter_case_files(root):
            ch = normalize_file(p, norm_list, args.apply)
            if ch:
                n_files += 1
                n_changes += len(ch)
                for old, new in ch:
                    print(f"  {p.relative_to(root)}: {old} → {new}")
        mode = "已改写" if args.apply else "干跑（加 --apply 生效）"
        print(f"\ntag 归一 {mode}：{n_files} 个文件 / {n_changes} 处")
        return 0

    cases = load_cases(root)
    covered = covered_cases(root)
    tag2ids = defaultdict(set)
    for _, c in cases:
        for t in norm_list(c.get("tags") or []):
            tag2ids[t].add(c.get("id"))
    groups = []
    for t, ids in tag2ids.items():
        fresh = sorted(i for i in ids if i not in covered)
        if len(ids) >= args.min and len(fresh) >= args.min:
            groups.append((t, sorted(ids), fresh))
    groups.sort(key=lambda x: (-len(x[1]), x[0]))

    print(f"case {len(cases)} 条 / tag {len(tag2ids)} 个 / 已被 reference 收录 {len(covered)} 条")
    print(f"自动删除项（与字段重复）：{sorted(drop)}")
    print(f"R8 候选组（同 tag ≥{args.min} 条且 ≥{args.min} 条未覆盖）：{len(groups)} 组\n")
    for t, ids, fresh in groups:
        print(f"[{kind_of(t, vocab['kinds']):10s}] {t:20s} 共{len(ids):2d} 未覆盖{len(fresh):2d}  {fresh[:8]}")
    if not groups:
        print("  无（无达标组）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
