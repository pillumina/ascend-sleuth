#!/usr/bin/env python3
# build_index.py —— 生成 knowledge/_index.yaml（Tier 2 阶段一的结构化索引）
#
# 设计决策见 docs/adr/0002-retrieval-no-rag-lightweight-index.md：
#   - 索引是生成物，提交进 git，随 case 变更一起 diff / 评审
#   - 把"阶段一只加载索引字段"从 prompt 纪律变成结构保证：阶段一 = 读这一个文件
#   - 每条 case 记 content hash，--check 校验新鲜度（groom 每次跑，可挂 CI）
#
# 用法：
#   python3 scripts/build_index.py           # 重新生成 knowledge/_index.yaml
#   python3 scripts/build_index.py --check   # 只校验新鲜度，过期则 exit 1
#
# 依赖：PyYAML（pip install pyyaml）。_archive/ 下的退休 case 不进活跃索引
# （复活检查由 groom 直接读目录完成）。

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：pip install pyyaml")


def case_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def compat_summary(compat) -> str:
    """compat 列表压成一行可 grep 的概要："fw A >=1.0,<2.0; fw B >=3.0 (cann:>=8.0)" """
    if not compat:
        return ""
    parts = []
    for c in compat:
        fw = c.get("framework", "?")
        rng = ",".join(c.get("ranges", []) or [])
        extra = []
        if c.get("cann"):
            extra.append("cann:" + ",".join(c["cann"]))
        if c.get("hdk"):
            extra.append("hdk:" + ",".join(c["hdk"]))
        s = f"{fw} {rng}".strip()
        if extra:
            s += " (" + "; ".join(extra) + ")"
        parts.append(s)
    return "; ".join(parts)


def quickly_check_summary(qc) -> dict:
    """只保留阶段一过滤所需字段：command_template + expected（rank_selector 等细节留在全量 body）"""
    out = {}
    for key in ("primary", "fallback"):
        block = (qc or {}).get(key)
        if not block:
            continue
        out[key] = {
            "command": block.get("command_template", ""),
            "expected": block.get("expected", ""),
        }
    return out


def collect(root: Path):
    """扫 knowledge/**/*.yaml → {namespace: [索引条目, ...]}"""
    namespaces = {}
    kdir = root / "knowledge"
    for path in sorted(kdir.rglob("*.yaml")):
        rel = path.relative_to(kdir)
        if rel.parts[0] == "_archive" or path.name == "_index.yaml":
            continue
        ns = str(Path(*rel.parts[:-1]))
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for case in doc.get("cases", []):
            namespaces.setdefault(ns, []).append({
                "id": case.get("id", ""),
                "title": case.get("title", ""),
                "category": case.get("category", ""),
                "tags": case.get("tags", []),
                "platforms": case.get("platforms", []),
                "compat": compat_summary(case.get("compat")),
                "confidence": {
                    k: (case.get("confidence") or {}).get(k)
                    for k in ("score", "hits", "misdiagnoses")
                },
                "symptoms": case.get("symptoms", []),
                "quickly_check": quickly_check_summary(case.get("quickly_check")),
                "file": str(Path("knowledge") / rel),
                "hash": case_hash(path),
            })
    return namespaces


def render(namespaces) -> str:
    n = sum(len(v) for v in namespaces.values())
    header = "\n".join([
        "# GENERATED FILE —— 由 scripts/build_index.py 生成，不要手改。",
        "# case 变更后重新生成并提交；`build_index.py --check` 校验新鲜度（groom/CI）。",
        "# 阶段一加载协议：diagnose 只读本文件过滤候选 ≤5，按 file 字段定位后做阶段二全量加载。",
        f"# 生成日期：{date.today().isoformat()}    case 总数：{n}",
        "",
    ])
    body = yaml.safe_dump(
        {"namespaces": {k: namespaces[k] for k in sorted(namespaces)}},
        allow_unicode=True, sort_keys=False, default_flow_style=False, width=100,
    )
    return header + body


def stale_entries(root: Path, namespaces):
    """当前文件 hash ≠ 索引记录 → 过期。返回过期列表；索引不存在返回 None。"""
    idx_path = root / "knowledge" / "_index.yaml"
    if not idx_path.exists():
        return None
    idx = yaml.safe_load(idx_path.read_text(encoding="utf-8")) or {}
    recorded = {}
    for cases in (idx.get("namespaces") or {}).values():
        for c in cases:
            recorded[c.get("id")] = c.get("hash")
    stale = []
    for ns, cases in namespaces.items():
        for c in cases:
            if recorded.get(c["id"]) != c["hash"]:
                stale.append((ns, c["id"], c["file"]))
    for cid in set(recorded) - {c["id"] for cases in namespaces.values() for c in cases}:
        stale.append(("-", cid, "(索引里有、库里没有)"))
    return stale


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验新鲜度，不写文件")
    ap.add_argument("--root", default=None, help="仓库根目录（默认：脚本上两级）")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]

    ns = collect(root)
    if args.check:
        stale = stale_entries(root, ns)
        if stale is None:
            print("索引不存在 —— 先运行 scripts/build_index.py 生成")
            sys.exit(1)
        if stale:
            for s in stale:
                print(f"STALE: {s[0]} / {s[1]} ({s[2]})")
            print(f"\n{len(stale)} 条过期。运行 `python3 scripts/build_index.py` 重新生成后提交。")
            sys.exit(1)
        print(f"索引新鲜，与 knowledge/ 一致（{sum(len(v) for v in ns.values())} 条 case）。")
        return

    out = root / "knowledge" / "_index.yaml"
    out.write_text(render(ns), encoding="utf-8")
    print(f"已生成 {out}（{len(ns)} 个 namespace / {sum(len(v) for v in ns.values())} 条 case）")


if __name__ == "__main__":
    main()
