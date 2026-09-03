#!/usr/bin/env python3
# capacity_health.py —— 容量健康指标度量（ADR-0004 / roadmap A2）
#
# 候选溢出率：阶段一后候选 >5 的诊断/回放占比（ADR-0004：>20% = 恶化 → 触发拆分）
# 口径（精确）：模拟 diagnose 阶段一真实行为——对每个测试输入（golden fixture 症状 +
# S2 校准集症状），用各 index 条目的 quickly_check.primary/fallback 的实际 grep 模式
# 匹配症状文本，命中数即候选数。候选 >5 的输入占比 = 候选溢出率。
#
# 确定性度量（原则二）：regex 匹配机械可判，脚本化不靠 agent 自觉。与"关键词并集"
# 近似的区别：这里是"每个 case 的判别式精确匹配"（diagnose 真实语义），非宽松并集。
#
# 用法：python3 scripts/capacity_health.py [--ns inference/vllm-ascend] [--root <repo>]

import argparse
import re
import sys
from pathlib import Path

import yaml

OVERFLOW_THRESHOLD = 5   # 阶段二硬约束：候选 ≤5
DEGRADE_RATE = 0.20      # ADR-0004：候选溢出率 >20% = 恶化


def load_yaml(path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def extract_match_patterns(case):
    """从 case 的 quickly_check primary/fallback 提取实际 grep 模式。"""
    qc = case.get("quickly_check") or {}
    pats = []
    for key in ("primary", "fallback"):
        entry = qc.get(key)
        if not isinstance(entry, dict):
            continue
        cmd = entry.get("command", "") or ""
        # grep -E/-e/-i 'pattern' 或 "pattern"
        for m in re.findall(r"grep\s+-[a-zA-Z]*[eE]?\s*['\"]([^'\"]+)['\"]", cmd):
            pats.append(m)
        # grep -F 'literal'（字面匹配 → 转义）
        for m in re.findall(r"grep\s+-[a-zA-Z]*F\s*['\"]([^'\"]+)['\"]", cmd):
            pats.append(re.escape(m))
    return pats


def count_candidates_regex(signatures_sym, case_list):
    """精确模拟阶段一：每个 case 的实际 regex 匹配症状 → 候选数。"""
    n = 0
    for c in case_list:
        for p in extract_match_patterns(c):
            try:
                if re.search(p, signatures_sym, re.IGNORECASE):
                    n += 1
                    break
            except re.error:
                continue
    return n


def main():
    ap = argparse.ArgumentParser(description="容量健康指标度量（候选溢出率，精确 regex 口径）")
    ap.add_argument("--ns", default="inference/vllm-ascend", help="目标 namespace")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.root.resolve()

    index = load_yaml(root / "knowledge" / "_index.yaml")
    ns = (index.get("namespaces") or {}).get(args.ns)
    if not ns:
        print(f"namespace {args.ns} 不在索引"); sys.exit(1)

    print(f"=== {args.ns} 容量 ===")
    for cat in ["interrupt", "precision", "performance"]:
        print(f"  {cat}: {len(ns.get(cat, []))} 条")

    # 测试输入
    test_inputs = []
    for f in sorted((root / "eval" / "golden").glob("*.fixture.yaml")):
        d = load_yaml(f)
        sym = (d.get("input") or {}).get("symptoms", "")
        if sym:
            test_inputs.append((f"golden/{f.name}", sym))
    for f in sorted((root / "eval" / "s2").glob("*.yaml")):
        d = load_yaml(f)
        for e in d.get("calibration", []):
            sym = (e.get("input") or {}).get("symptoms", "")
            if sym:
                test_inputs.append((f"s2/#{e.get('issue')}", sym))

    if not test_inputs:
        print("无测试输入"); sys.exit(1)

    print(f"\n=== 候选溢出率（精确 regex，模拟阶段一）===\n测试输入: {len(test_inputs)} 条")
    for cat in ["interrupt", "precision", "performance"]:
        items = ns.get(cat, [])
        if not items:
            continue
        overflow = 0
        dist = []
        for _, sym in test_inputs:
            n = count_candidates_regex(sym, items)
            dist.append(n)
            if n > OVERFLOW_THRESHOLD:
                overflow += 1
        rate = overflow / len(test_inputs)
        med = sorted(dist)[len(dist) // 2]
        flag = "⚠️ 恶化" if rate > DEGRADE_RATE else "✅ 健康"
        print(f"  {cat}: {overflow}/{len(test_inputs)} 溢出 → 率 {rate:.0%} {flag} "
              f"(候选数 min={min(dist)} med={med} max={max(dist)})")

    print(f"\n阈值：溢出率 >{DEGRADE_RATE:.0%} = 恶化（ADR-0004）。精确 regex 口径 = diagnose 阶段一")
    print("真实匹配（非关键词并集）；health 判断供拆分评估，非自动动作。")


if __name__ == "__main__":
    main()
