#!/usr/bin/env python3
# capacity_health.py —— 容量健康指标度量（ADR-0004 / roadmap A2）
#
# 候选溢出率：阶段一后候选 >5 的诊断/回放占比（ADR-0004：>20% = 恶化 → 触发拆分）
#
# 口径（精确）：模拟 diagnose 阶段一真实行为——对每个测试输入（golden fixture 症状 +
# S2 校准集症状），用**每条 case 自己的判别式**（quickly_check.primary/fallback 的
# command_template + expected 里的 regex）匹配输入文本，命中数即候选数。
# 候选 >5 的输入占比 = 候选溢出率。
#
# 为什么重写取数路径（原实现恒为 0，是假绿）：
#   ① 原实现从 `knowledge/_index.yaml` 的**索引条目**里取 quickly_check——索引行瘦身后
#      已不含该字段（索引只留 id/title/symptoms 首条摘要/category/score/file/hash）；
#      取不到 → 每个输入、每个格子都算出 0 候选，脚本却打印「0% 溢出 ✅ 健康」。
#   ② 即使拿到 case 本体，原实现找的字段是 `command`，schema 实际是 `command_template`
#      （判定式另写在 `expected: "regex:..."`）。
#   ③ case 文件是 `cases:` 容器（一个文件可含多条），按 dict 直接取字段同样取不到。
#   三处叠加的后果：ADR-0004 的健康指标、再拆闸门与既往"暂不拆"的结论，建立在一个
#   恒为 0 的数上。本版改为**从 case 本体按 id 取数**，并对"整格全 0"报**不可解读**
#   而不是健康——分母可疑时不得给出"正常"（同 metrics_health.py 的假绿教训）。
#
# 确定性度量（原则二）：regex 匹配机械可判，脚本化不靠 agent 自觉。与"关键词并集"
# 近似的区别：这里是"每条 case 的判别式精确匹配"（diagnose 真实语义），非宽松并集。
#
# 用法：python3 scripts/capacity_health.py [--ns inference/vllm-ascend] [--root <repo>] [--json]

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

OVERFLOW_THRESHOLD = 5   # 阶段二硬约束：候选 ≤5
DEGRADE_RATE = 0.20      # ADR-0004：候选溢出率 >20% = 恶化

GREP_PATTERN_RE = re.compile(r"grep\s+-[a-zA-Z]*[eE]?\s*['\"]([^'\"]+)['\"]")
GREP_FIXED_RE = re.compile(r"grep\s+-[a-zA-Z]*F\s*['\"]([^'\"]+)['\"]")
EXPECTED_REGEX_PREFIX = "regex:"


def load_yaml(path):
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def cases_of(path):
    """case 文件 → case 列表。**文件是 `cases:` 容器**（一个文件可含多条）。

    兼容单条扁平形态（顶层直接是 case）——避免将来改回扁平写法时静默取空。
    """
    doc = load_yaml(path)
    if not isinstance(doc, dict):
        return []
    inner = doc.get("cases")
    if isinstance(inner, list):
        return [c for c in inner if isinstance(c, dict)]
    return [doc] if "id" in doc else []


def case_by_id(path, case_id):
    for c in cases_of(path):
        if c.get("id") == case_id:
            return c
    return None


def patterns_of_case(case):
    """从 case 的 quickly_check 提取实际判定模式（primary + fallback）。

    两个来源都要取：命令模板里的 grep 模式，以及 `expected` 的 `regex:` 断言——
    后者是"这条 case 认什么症状"的规范表述，命令模板可能只是取日志的手段。
    """
    qc = case.get("quickly_check")
    if not isinstance(qc, dict):
        return []
    out = []
    for key in ("primary", "fallback"):
        entry = qc.get(key)
        if not isinstance(entry, dict):
            continue
        cmd = entry.get("command_template") or entry.get("command") or ""
        if isinstance(cmd, str) and cmd:
            for m in GREP_FIXED_RE.findall(cmd):
                out.append(re.escape(m))
            for m in GREP_PATTERN_RE.findall(cmd):
                out.append(m)
        expected = entry.get("expected") or ""
        if isinstance(expected, str) and expected.startswith(EXPECTED_REGEX_PREFIX):
            out.append(expected[len(EXPECTED_REGEX_PREFIX):].strip())
    return [p for p in out if p]


def always_true(pattern):
    """判别式是否恒真（含空分支，如 `foo|` 或 `(a|b|)`）——恒真的判别式对候选集没有区分力。

    这是知识库侧的数据缺陷（不是脚本口径问题）：它让这条 case 对**任何**输入都成为候选，
    直接推高溢出率。脚本只如实报出，改不改由 groom/owner 定。
    """
    try:
        return re.search(pattern, "", re.IGNORECASE) is not None
    except re.error:
        return False


def matches_any(patterns, text):
    for p in patterns:
        try:
            if re.search(p, text, re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def count_candidates(text, cases):
    return sum(1 for c in cases if matches_any(c["patterns"], text))


def collect_cases(root, ns, cat, index):
    """索引条目 → case 本体（按 id 精确取），带 patterns。取不到如实记入 unresolved。"""
    items = ((index.get("namespaces") or {}).get(ns) or {}).get(cat) or []
    cases, unresolved, no_pattern = [], [], []
    for item in items:
        case_id, rel = item.get("id"), item.get("file")
        case = case_by_id(root / rel, case_id) if rel else None
        if case is None:
            unresolved.append(case_id or "<no-id>")
            continue
        pats = patterns_of_case(case)
        if not pats:
            no_pattern.append(case_id)
        cases.append({"id": case_id, "patterns": pats})
    return cases, unresolved, no_pattern


def test_inputs(root):
    inputs = []
    for f in sorted((root / "eval" / "golden").glob("*.fixture.yaml")):
        inp = (load_yaml(f).get("input") or {})
        text = "\n".join(str(inp.get(k) or "") for k in ("symptoms", "log_snippet")).strip()
        if text:
            inputs.append((f"golden/{f.name}", text))
    for f in sorted((root / "eval" / "s2").glob("*.yaml")):
        for e in (load_yaml(f).get("calibration") or []):
            inp = (e.get("input") or {})
            text = "\n".join(str(inp.get(k) or "") for k in ("symptoms", "log_snippet")).strip()
            if text:
                inputs.append((f"s2/#{e.get('issue')}", text))
    return inputs


def main():
    ap = argparse.ArgumentParser(description="容量健康指标度量（候选溢出率，精确 regex 口径）")
    ap.add_argument("--ns", default="inference/vllm-ascend", help="目标 namespace")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--json", action="store_true", help="输出 JSON（面板/断言用）")
    args = ap.parse_args()
    root = args.root.resolve()

    index = load_yaml(root / "knowledge" / "_index.yaml")
    ns = (index.get("namespaces") or {}).get(args.ns)
    if not ns:
        print(f"namespace {args.ns} 不在索引")
        sys.exit(1)

    inputs = test_inputs(root)
    if not inputs:
        print("无测试输入")
        sys.exit(1)

    report = {"ns": args.ns, "inputs": len(inputs), "cells": {}, "unresolved": {}, "no_pattern": {}}
    if not args.json:
        print(f"=== {args.ns} 容量 ===")
        for cat in ["interrupt", "precision", "performance"]:
            print(f"  {cat}: {len(ns.get(cat, []))} 条")
        print(f"\n=== 候选溢出率（精确 regex，模拟阶段一）===\n测试输入: {len(inputs)} 条")

    for cat in ["interrupt", "precision", "performance"]:
        if not ns.get(cat):
            continue
        cases, unresolved, no_pattern = collect_cases(root, args.ns, cat, index)
        report["unresolved"][cat] = unresolved
        report["no_pattern"][cat] = no_pattern
        if not cases:
            report["cells"][cat] = {"readable": False, "why": "取不到任何 case 本体"}
            if not args.json:
                print(f"  {cat}: ⚠️ 不可解读——取不到 case 本体（索引 file/id 与 case 文件不匹配），不得判健康")
            continue
        patterns_total = sum(len(c["patterns"]) for c in cases)
        degenerate = [c["id"] for c in cases if any(always_true(p) for p in c["patterns"])]
        dist = [count_candidates(text, cases) for _, text in inputs]
        overflow = sum(1 for n in dist if n > OVERFLOW_THRESHOLD)
        rate = overflow / len(inputs)
        med = sorted(dist)[len(dist) // 2]
        # 不可解读判据：整格全 0（没有任何输入命中任何判别式）或判别式整体缺失——
        # 这两种情况下的 "0% 溢出" 不是健康，是度量失效。
        readable = max(dist) > 0 and patterns_total > 0
        report["cells"][cat] = {
            "cases": len(cases), "patterns": patterns_total, "readable": readable,
            "overflow": overflow, "rate": round(rate, 4), "min": min(dist), "med": med, "max": max(dist),
            "unresolved_ids": unresolved, "no_pattern_ids": no_pattern, "degenerate_ids": degenerate,
        }
        if args.json:
            continue
        if not readable:
            print(f"  {cat}: ⚠️ 不可解读——{len(cases)} 条 case 全部输入 0 命中（判别式 {patterns_total} 条）"
                  f"；0% 溢出不是健康，是度量失效。先查 casing/字段/输入文本，再据它做拆分决策")
        else:
            flag = "⚠️ 恶化" if rate > DEGRADE_RATE else "✅ 健康"
            print(f"  {cat}: {overflow}/{len(inputs)} 溢出 → 率 {rate:.0%} {flag} "
                  f"(候选数 min={min(dist)} med={med} max={max(dist)}；判别式 {patterns_total} 条)")
        if unresolved:
            print(f"      ⚠️ {len(unresolved)} 条索引条目取不到 case 本体（要求：索引 file/id 与 case 文件一致）: "
                  f"{', '.join(unresolved[:5])}{' …' if len(unresolved) > 5 else ''}")
        if no_pattern:
            print(f"      ⚠️ {len(no_pattern)} 条 case 无任何可提取判别式（quickly_check 缺失或形态不符）: "
                  f"{', '.join(no_pattern[:5])}{' …' if len(no_pattern) > 5 else ''}")
        if degenerate:
            print(f"      ⚠️ {len(degenerate)} 条 case 的判别式恒真（含空分支，如 `foo|`）——对任何输入都成为候选，"
                  f"直接推高溢出率: {', '.join(degenerate[:5])}{' …' if len(degenerate) > 5 else ''}")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return
    print(f"\n阈值：溢出率 >{DEGRADE_RATE:.0%} = 恶化（ADR-0004）。精确 regex 口径 = diagnose 阶段一")
    print("真实匹配（非关键词并集）；health 判断供拆分评估，非自动动作。")


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
