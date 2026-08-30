#!/usr/bin/env python3
# replay_trace.py —— 从真实诊断轨迹（traces/）做回放回归 + fixture 供给
#
# 双角色（roadmap 讨论 2026-08-29，A 定位）：
#   1. 弱断言回归（行为差异哨兵）：对每条 trace 提取输入（user 事件原文），
#      重放后校验"本次路由/命中的 case 是否与历史一致"——只判漂移，不判对错。
#      适用全部 trace（含未 resolve 的）。
#   2. 强断言 fixture 供给：仅 status=resolved 且 feedback.outcome=resolved 的 trace
#      是 fixture 合格来源——期望 = 实际命中（有反馈闭环确认的正确性基准）。
#      输出 fixture 候选（YAML 骨架），人确认后入 eval/golden/。
#
# 输入源：traces/*.yaml（gitignored，含客户现场信息；本脚本只读不写原文）
# 断言口径：LLM 非确定性 → top-3 命中（docs/eval.md），不要求必须第一。
#
# 用法：
#   python3 scripts/replay_trace.py                  # 弱断言回归报告（全部 trace）
#   python3 scripts/replay_trace.py --emit-fixtures  # 强断言：输出 fixture 候选骨架
#   python3 scripts/replay_trace.py --gap-report     # 内容缺口（D）：高频 miss 症状聚合
#   python3 scripts/replay_trace.py --session <id>   # 只处理指定 session
#
# 注意：真正的"重放执行"依赖 /skill:diagnose 的 replay 模式（M2 半自动化目标）。
# 本脚本当前做的是**结构级回放**：用轨迹中的路由/命中记录校验一致性，
# 输出可供 replay 模式消费的输入-期望对。重放执行本身仍由 diagnose replay 完成。

import argparse
import sys
from datetime import date
from pathlib import Path

import yaml


def load_traces(root: Path):
    traces = []
    for f in sorted((root / "traces").glob("*.yaml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception as e:
            print(f"WARN: 解析失败 {f}: {e}", file=sys.stderr)
            continue
        if doc:
            doc["_path"] = str(f)
            traces.append(doc)
    return traces


def extract_input(doc: dict):
    """提取 fixture 输入：合并**所有** user 事件的 content——真实诊断是问答式，
    首轮症状常模糊，判别信号（错误码/签名）在后续追问的回答里。只取首轮会
    丢失关键信号（曾实测：TP2 崩溃 → 第 4 轮才给出 EL0008），replay 无法命中。
    多轮折叠为完整症状描述（按轮次顺序拼接，标注轮次）。"""
    parts = []
    for t in doc.get("trace") or []:
        if t.get("role") == "user" and t.get("content"):
            parts.append(str(t["content"]).strip())
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return "\n\n".join(f"[第 {i + 1} 轮用户输入]\n{p}" for i, p in enumerate(parts))


def extract_route(doc: dict):
    """提取历史路由决策：triage 事件的 routed + 命中 case。"""
    routed = []
    hit_case = None
    for t in doc.get("trace") or []:
        a = t.get("action")
        if a == "triage":
            routed += [str(r).rstrip("/") for r in (t.get("routed") or [])]
        elif a == "triage_semantic":
            ns = t.get("namespace")
            if ns:
                routed.append(str(ns).rstrip("/"))
        elif a == "hit":
            hit_case = t.get("case") or hit_case
    return routed, hit_case


def ns_of_case(root: Path, case_id: str):
    """case id → namespace（读生成索引）。"""
    idx = root / "knowledge" / "_index.yaml"
    if idx.exists():
        doc = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
        for ns, cells in (doc.get("namespaces") or {}).items():
            for cases in cells.values():
                for c in cases:
                    if c.get("id") == case_id:
                        return ns
    return None


def is_fixture_eligible(doc: dict):
    """强断言资格：status=resolved 且 feedback.outcome=resolved（反馈闭环确认）。"""
    return (doc.get("status") == "resolved"
            and (doc.get("feedback") or {}).get("outcome") == "resolved")


def main():
    ap = argparse.ArgumentParser(description="从真实诊断轨迹做回放回归 + fixture 供给")
    ap.add_argument("--emit-fixtures", action="store_true",
                    help="强断言：输出 fixture 候选骨架（resolved+feedback 确认的 trace）")
    ap.add_argument("--gap-report", action="store_true",
                    help="内容缺口（D）：聚合 miss/tier3 高频症状，报告无 case 覆盖的缺口")
    ap.add_argument("--session", default=None, help="只处理指定 session_id")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    traces = load_traces(root)
    if args.session:
        traces = [t for t in traces if t.get("session_id") == args.session]
    if not traces:
        print("traces/ 无记录。先跑 /skill:diagnose 产生轨迹。")
        return

    # ---- 弱断言：路由一致性（历史 routed 是否覆盖实际命中 case 的 namespace）----
    drift = []
    checked = 0
    for doc in traces:
        routed, hit_case = extract_route(doc)
        sid = doc.get("session_id", "?")
        if not hit_case:
            continue  # 未命中（走 Tier 3 或人工），无路由一致性可校验
        ns = ns_of_case(root, hit_case)
        if not ns:
            continue
        checked += 1
        if not any(r == ns or r.endswith("/" + ns) or ns.endswith("/" + r) for r in routed):
            drift.append(f"{sid}: 命中 {hit_case}（{ns}）不在路由 {routed}")

    print(f"=== 弱断言回归（行为差异哨兵）===")
    print(f"traces: {len(traces)}，可校验路由一致性的命中 session: {checked}")
    if drift:
        print(f"漂移 {len(drift)} 处：")
        for d in drift:
            print(f"  - {d}")
    else:
        print("无路由漂移——历史路由决策与命中 case 一致 ✓")

    # ---- 强断言：fixture 供给候选 ----
    if args.emit_fixtures:
        print(f"\n=== 强断言 fixture 供给（resolved + feedback 确认）===")
        eligible = [t for t in traces if is_fixture_eligible(t)]
        if not eligible:
            print("无合格来源：需要 status=resolved 且 feedback.outcome=resolved 的 trace")
            print("（反馈闭环未确认的 trace 只能做弱断言，不能作 fixture 正确性基准）")
            return
        # 覆盖去重：读已有 golden fixture 的 case_id 集合（饱和策略——覆盖优先，
        # 已覆盖的格子不再重复供给，避免 10 条 interrupt 重复却漏 precision）
        existing = set()
        for f in (root / "eval" / "golden").glob("*.fixture.yaml"):
            try:
                d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
                if d.get("case_id"):
                    existing.add(d["case_id"])
            except Exception:
                pass
        for doc in eligible:
            sid = doc.get("session_id", "?")
            routed, hit_case = extract_route(doc)
            inp = extract_input(doc)
            if not hit_case or not inp:
                print(f"  - {sid}: 缺 hit case 或 user 输入，跳过 fixture 候选")
                continue
            if hit_case in existing:
                print(f"  - {sid}: 命中 {hit_case} 已有 fixture（覆盖已满足）——跳过，防重复")
                continue
            fixture = {
                "case_id": hit_case,
                "input": {"symptoms": inp,
                          "framework": doc.get("detected_framework", ""),
                          "platform": doc.get("detected_platform", "")},
                "expected": {"namespace": ns_of_case(root, hit_case) or "",
                             "case_id": hit_case,
                             "assertion": "top-3"},
                "_candidate": True,   # 候选标记：期望待人工核定（eval.md：期望由人核定）
                "source": f"traces/{sid}.yaml（resolved + feedback 确认）",
            }
            print(f"\n--- {sid} → eval/golden/{hit_case}.fixture.yaml 候选 ---")
            print(yaml.safe_dump(fixture, allow_unicode=True, sort_keys=False,
                                 default_flow_style=False).rstrip())
            print("  # 人确认要点：①期望 case_id 是否正确根因（agent 命中≠ground truth）"
                  " ②输入是否足以支撑路由 ③脱敏——确认后移除 _candidate 标记入库")

    # ---- 内容缺口（D）：miss/tier3 高频症状聚合 ----
    if args.gap_report:
        print(f"\n=== 内容缺口报告（高频症状 × 无 case 覆盖）===")
        # 从 miss 事件的 symptom 字段 / user 输入原文提取关键词（简单词频，不引入 NLP）
        from collections import Counter
        miss_keywords = Counter()
        miss_sessions = 0
        for doc in traces:
            sid = doc.get("session_id", "?")
            miss = False
            for t in doc.get("trace") or []:
                if t.get("action") in ("miss", "tier3"):
                    miss = True
                    kw = t.get("symptom") or t.get("keyword")
                    if kw:
                        miss_keywords[kw.strip()] += 1
            if miss:
                miss_sessions += 1
        if miss_sessions == 0:
            print("无 miss/tier3 记录（全部命中）——当前无内容缺口信号")
        else:
            print(f"miss/tier3 session: {miss_sessions}/{len(traces)}")
            if miss_keywords:
                print("高频未覆盖关键词（重复出现 = 该补 case 的信号）：")
                for kw, cnt in miss_keywords.most_common(10):
                    print(f"  - {kw}（{cnt} 次）")
            else:
                print("miss 事件未带 symptom/keyword 字段——诊断时 miss/tier3 事件应记录"
                      "（见 SKILL：tier3 记 {action: tier3, keyword}）")


if __name__ == "__main__":
    main()
