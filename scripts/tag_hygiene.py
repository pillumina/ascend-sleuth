#!/usr/bin/env python3
# tag_hygiene.py —— case tag 归一 + R8 共性提炼候选聚类（机械环节，M5 脚本先行）
#
# 两个职责：
#   1) --normalize：按 SYNONYMS/DROP 归一 knowledge/** 的 case tags（行级改写，保留原格式）
#   2) 默认：输出 R8 候选组（同 tag ≥ N 条且 ≥N 条未被 reference 收录），带 tag 类别标注
#
# 为什么需要归一：R8 是 tag 驱动的机械信号，但 tag 出现三类污染——
#   ① category / namespace 名混进 tag（与字段重复，零信息）；
#   ② 同义分裂（同一现象四种拼法，互相看不见）；
#   ③ 拼写变体（fusedmoe / fused-moe）。
# 归一前 507 个不同 tag、70 个出现 ≥3 次，R8 几乎不筛（2026-09-09 实测）。
#
# 用法：
#   python3 scripts/tag_hygiene.py                      # R8 候选组（默认 --min 3）
#   python3 scripts/tag_hygiene.py --min 4              # 只看更大的组
#   python3 scripts/tag_hygiene.py --normalize          # 干跑：列出将改动的 tag
#   python3 scripts/tag_hygiene.py --normalize --apply  # 实际改写
#
# 依赖：PyYAML（pip install pyyaml）

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：pip install pyyaml")

# ---- 归一映射（决策留痕：见 docs/git-workflow.md PR 或 kb/tag-hygiene PR body）----

# ① 删除：与 case 字段重复（category / namespace），零信息
DROP = {"precision", "performance", "interrupt", "vllm-ascend", "verl", "mindspeed-llm", "sglang"}

# ② 合并：同义 / 拼写变体 → 规范名（取组内最高频者）
SYNONYMS = {
    "startup": "startup-failure",
    "startup-fail": "startup-failure",
    "startup-crash": "startup-failure",
    "pd-disaggregation": "pd-separation",
    "pd-disagg": "pd-separation",
    "speculative-decode": "spec-decode",
    "fusedmoe": "fused-moe",
    "dsv4": "deepseek-v4",
    "upgrade": "version-upgrade",
}

# ③ 明确不合并（非近义，是不同 facet）：kv-transfer / kv-pool / hybrid-kv；
#    module-not-found / import-error；quantization / modelslim / w8a8 / w4a8；
#    mtp / spec-decode；a2 / a5 / 910b

# tag 类别：模型名/产品名族——同模型 ≠ 同根因，不建议提炼（聚类时标注出来）
MODEL_TAGS = {
    "glm5", "glm", "qwen3.5", "qwen3", "minimax", "deepseek-v4", "deepseek", "dsv4",
    "kimi", "llama", "gemma", "mova", "tora", "qwen2.5", "qwen-image-edit",
}


def load_cases(root: Path):
    """扫 knowledge/**/*.yaml → [(path, case_dict), ...]（跳过生成物与 _archive 之外的索引）"""
    out = []
    kdir = root / "knowledge"
    for p in sorted(kdir.rglob("*.yaml")):
        if "_index" in p.parts or p.name.startswith("_"):
            continue
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for c in doc.get("cases") or []:
            if isinstance(c, dict):
                out.append((p, c))
    return out


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


def norm_tag(t: str) -> str | None:
    """归一单个 tag；返回 None 表示删除。"""
    if t in DROP:
        return None
    return SYNONYMS.get(t, t)


def norm_list(tags):
    seen, out = set(), []
    for t in tags or []:
        n = norm_tag(str(t))
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


# ---- 归一（行级改写，保留原 YAML 格式）----

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


def normalize_file(path: Path) -> list:
    """返回 [(old_tags, new_tags), ...] 且已就地改写。"""
    lines = path.read_text(encoding="utf-8").split("\n")
    changes = []
    i = 0
    while i < len(lines):
        m_inline = TAG_INLINE_RE.match(lines[i])
        if m_inline:
            old = parse_items(m_inline.group(2))
            new = norm_list(old)
            if new != old:
                lines[i] = m_inline.group(1) + "[" + ", ".join(emit_item(t) for t in new) + "]"
                changes.append((old, new))
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
                item_indent = " " * (indent + 2)
                lines[i:j] = [m_block.group(1)] + [f"{item_indent}- {emit_item(t)}" for t in new]
                changes.append((items, new))
                i = i + 1 + len(new)
                continue
            i = j
            continue
        i += 1
    if changes:
        path.write_text("\n".join(lines), encoding="utf-8")
    return changes


# ---- R8 聚类 ----

def clusters(root: Path, min_size: int):
    cases = load_cases(root)
    covered = covered_cases(root)
    tag2ids = defaultdict(set)
    id2cat = {}
    for _, c in cases:
        cid = c.get("id")
        id2cat[cid] = c.get("category")
        for t in norm_list(c.get("tags") or []):
            tag2ids[t].add(cid)
    groups = []
    for t, ids in tag2ids.items():
        fresh = sorted(i for i in ids if i not in covered)
        if len(ids) >= min_size and len(fresh) >= min_size:
            groups.append((t, sorted(ids), fresh))
    groups.sort(key=lambda x: (-len(x[1]), x[0]))
    return groups, len(cases), len(covered), len(tag2ids)


def kind_of(tag: str) -> str:
    if tag in MODEL_TAGS:
        return "模型名"
    if tag in ("310p", "w8a8", "w4a8", "cudagraph", "mtp", "spec-decode", "quantization"):
        return "环境/特性"
    return "机制"


def main():
    ap = argparse.ArgumentParser(description="case tag 归一 + R8 共性提炼候选聚类")
    ap.add_argument("--root", default=".", help="仓库根目录（含 knowledge/ 与 references/）")
    ap.add_argument("--min", type=int, default=3, help="R8 组的最小条数（默认 3）")
    ap.add_argument("--normalize", action="store_true", help="归一 tags（默认干跑）")
    ap.add_argument("--apply", action="store_true", help="配合 --normalize 实际改写文件")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    if args.normalize:
        total_files = total_cases = 0
        for p in sorted((root / "knowledge").rglob("*.yaml")):
            if "_index" in p.parts or p.name.startswith("_"):
                continue
            ch = normalize_file(p) if args.apply else []
            if not args.apply:
                # 干跑：解析后比对
                try:
                    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                except yaml.YAMLError:
                    continue
                for c in doc.get("cases") or []:
                    old = [str(t) for t in (c.get("tags") or [])]
                    new = norm_list(old)
                    if new != old:
                        ch.append((old, new))
            if ch:
                total_files += 1
                total_cases += len(ch)
                rel = p.relative_to(root)
                for old, new in ch:
                    print(f"  {rel}: {old} → {new}")
        mode = "已改写" if args.apply else "干跑（加 --apply 生效）"
        print(f"\ntag 归一 {mode}：{total_files} 个文件 / {total_cases} 处")
        return 0

    groups, n_cases, n_cov, n_tags = clusters(root, args.min)
    print(f"case {n_cases} 条 / 归一后 tag {n_tags} 个 / 已被 reference 收录 {n_cov} 条")
    print(f"R8 候选组（同 tag ≥{args.min} 条且 ≥{args.min} 条未覆盖）：{len(groups)} 组\n")
    for t, ids, fresh in groups:
        print(f"[{kind_of(t):6s}] {t:20s} 共{len(ids):2d} 未覆盖{len(fresh):2d}  {fresh[:8]}")
    if not groups:
        print("  无（无达标组）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
