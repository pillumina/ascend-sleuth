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

# ADR-0004 容量治理：soft_cap 触发拆分评估，hard_cap 强制拆分。
# 均为初始估计，服从 roadmap「参数治理」——metrics 实测后按理论 §4.4 复核。
SOFT_CAP = 30
HARD_CAP = 60


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
    """扫 knowledge/**/*.yaml → {namespace: {category: [索引条目, ...]}}
    ADR-0004：目录按 (framework × category) 分层；索引按格子分组，
    格子是阶段一实际被扫的单元，cap 语义精确到格子。"""
    namespaces = {}
    kdir = root / "knowledge"
    for path in sorted(kdir.rglob("*.yaml")):
        rel = path.relative_to(kdir)
        if rel.parts[0] == "_archive" or path.name == "_index.yaml":
            continue
        ns = str(Path(*rel.parts[:-1]))
        # ADR-0004：目录按 (framework × category) 分层，但 ns 停在工作负载层
        # （triage 路由到框架，category 是正交轴的格子维度，从 case 字段取）
        # inference 与 training 对称折叠（2026-08-31 修复：此前只折叠 inference，
        # training 保留三级导致面板渲染出重复 category 标签）
        parts = rel.parts
        if len(parts) >= 3 and parts[0] in ("inference", "training") and parts[2] != "platforms":
            ns = str(Path(parts[0], parts[1]))
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for case in doc.get("cases", []):
            category = case.get("category", "")
            # 三分类强制（废弃 other）：非法 category 直接红——路由层依赖 category 分发，
            # other 会变成不可达格子（2026-08 重分类 5 条 other 的教训）
            if category not in ("interrupt", "precision", "performance"):
                raise ValueError(
                    f"{path}: case {case.get('id', '?')} category {category!r} 非法"
                    "（三分类强制：interrupt / precision / performance，无 other）"
                )
            namespaces.setdefault(ns, {}).setdefault(category, []).append({
                "id": case.get("id", ""),
                "title": case.get("title", ""),
                "category": category,
                "tags": case.get("tags", []),
                "platforms": case.get("platforms", []),
                "compat": compat_summary(case.get("compat")),
                "confidence": {
                    # ADR-0004 修正：索引只保留排序所需的 score；
                    # hits/misdiagnoses 是学习环动态字段（Beta 后验），留在 case 本体，
                    # 由 groom 置信度重算读取，不进入检索视图（避免学习环每次更新全量重建索引）。
                    "score": (case.get("confidence") or {}).get("score"),
                },
                "symptoms": case.get("symptoms", []),
                "quickly_check": quickly_check_summary(case.get("quickly_check")),
                "file": str(Path("knowledge") / rel),
                "hash": case_hash(path),
            })
    return namespaces


def render(namespaces) -> str:
    n = sum(len(c) for cells in namespaces.values() for c in cells.values())
    cell_counts = {
        ns: {cat: len(c) for cat, c in cells.items()}
        for ns, cells in sorted(namespaces.items())
    }
    # 容量行按"工作负载层"折叠展示（与 collect() 的 inference 折叠对称，2026-08-31 修复）：
    #   - inference/vllm-ascend/interrupt → 容量(inference/vllm-ascend): interrupt=N/30, ...
    #   - training/mindspeed-llm/interrupt → 容量(training/mindspeed-llm): interrupt=N/30, precision=M/30
    # 原因：头注是给人/面板看的展示层，namespace 里重复 category（.../interrupt: interrupt=11/30）
    # 会让面板渲染出重复标签；索引 body 的 ns 保持三级（diagnose 路由需要），只折叠头注。
    workload_counts = {}
    for ns, cells in cell_counts.items():
        parts = ns.split("/")
        wl = "/".join(parts[:2]) if (parts[0] == "training" and len(parts) >= 3) else ns
        merged = workload_counts.setdefault(wl, {})
        for cat, cnt in cells.items():
            merged[cat] = merged.get(cat, 0) + cnt
    cap_lines = "\n".join(
        f"#   容量({ns}): {', '.join(f'{cat}={cnt}/{SOFT_CAP}' for cat, cnt in cells.items())}"
        for ns, cells in sorted(workload_counts.items())
    )
    header = "\n".join([
        "# GENERATED FILE —— 由 scripts/build_index.py 生成，不要手改。",
        "# case 变更后重新生成并提交；`build_index.py --check` 校验新鲜度（groom/CI）。",
        "# 阶段一加载协议：diagnose 只读本文件过滤候选 ≤5，按 file 字段定位后做阶段二全量加载。",
        "# 容量治理（ADR-0004）：cap 按 (framework × category) 格子计；soft_cap 触发拆分评估，",
        "# 健康指标（候选溢出率/重复率/维护时长）恶化或超 hard_cap 强制拆分。",
        f"# 生成日期：{date.today().isoformat()}    case 总数：{n}",
        cap_lines,
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
    for cells in (idx.get("namespaces") or {}).values():
        for cases in cells.values():
            for c in cases:
                recorded[c.get("id")] = c.get("hash")
    stale = []
    for ns, cells in namespaces.items():
        for cases in cells.values():
            for c in cases:
                if recorded.get(c["id"]) != c["hash"]:
                    stale.append((ns, c["id"], c["file"]))
    for cid in set(recorded) - {c["id"] for cells in namespaces.values() for cases in cells.values() for c in cases}:
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
        n_cases = sum(len(cases) for cells in ns.values() for cases in cells.values())
        print(f"索引新鲜，与 knowledge/ 一致（{n_cases} 条 case）。")
        return

    out = root / "knowledge" / "_index.yaml"
    out.write_text(render(ns), encoding="utf-8")
    n_cases = sum(len(cases) for cells in ns.values() for cases in cells.values())
    print(f"已生成 {out}（{len(ns)} 个 namespace / {n_cases} 条 case）")


if __name__ == "__main__":
    main()
