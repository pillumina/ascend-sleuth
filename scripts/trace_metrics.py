#!/usr/bin/env python3
# trace_metrics.py —— 从 traces/*.yaml 的 trace 计算指标（metrics/timeline.yaml 数据 + docs/metrics.md 机制）
#
# 目的（ADR-0002）：过滤率/退休率/命中率/路由准确率从"假设"变"实测"。
# 数据源：traces/ 目录（gitignored，活跃 + 历史都归此）。
# 输出：markdown 指标表（stdout），人复核后追加进 docs/metrics.md。
#
# 依赖的 trace action（词表见 skills/diagnose/SKILL.md「每步必写 trace」）：
#   triage / load_index / quickly_check / load_full / run_check / hit / miss
#   / tier3（Tier 3 兜底检索）/ feedback（结果反馈：resolved|not_resolved|partial）
# 字段缺失时降级计算，不硬崩。小样本时比例波动大——解读前先看分母。

import sys
from pathlib import Path

import yaml

# trace action 固定词表（与 skills/diagnose/SKILL.md「每步必写 trace」一致）
# 词表外 action = 诊断纪律违规，写入时靠 SKILL.md 约束，此处确定性检出
# reference_lookup（ADR-0008）：diagnose 阶段 2.5 查询先验知识层——reference 命中统计
# （hits/last_hit）与引用后 resolve 率的数据源；outcome 从该 session 最终 status 派生，
# 不新增单独事件。
# triage_semantic（triage 演进 PR #53）：triage 未命中时 agent 语义路由兜底——路由准确率
#   统计与 E2（router 从 trace 错例演进）的数据源。
# source_analysis（源码分析路径 PR #53）：深度排查走源码定位——沉淀/多层级评估的观测。
# attribution（误诊归因）：反馈 not_resolved 后读 trace 判定 case 错 / 执行错——归因比指标
#   的数据源（metrics.md「执行-误诊归因比」），无此落点则该指标无法统计。
#   注意：attribution 事件的 component 字段（执行错归因下沉，diagnose SKILL 写入）的
#   聚合统计由 scripts/component_tally.py 承担（组件失败台账 metrics/component-tally.yaml，
#   evolution-pipeline §2）——本脚本只计 verdict 分布（case_error/execution_error 汇总指标），
#   不重复统计 component，避免双源口径漂移。component 字段不会被词表检查拦截（非 action）。
KNOWN_ACTIONS = {
    "triage", "load_index", "quickly_check", "load_full",
    "run_check", "hit", "miss", "tier3", "feedback", "reference_lookup",
    "triage_semantic", "source_analysis", "attribution", "resume",
}


def load_states(root: Path):
    # traces/ 是诊断状态目录（gitignored，含客户信息）——活跃 + 历史都归此
    files = list((root / "traces").glob("*.yaml"))
    states = []
    for f in files:
        try:
            states.append(yaml.safe_load(f.read_text(encoding="utf-8")) or {})
        except Exception as e:  # noqa: BLE001
            print(f"WARN: 解析失败 {f}: {e}", file=sys.stderr)
    return states


def ns_map_from_index(root: Path) -> dict:
    """case id → (namespace, category, score)。优先读生成索引；索引缺失则现扫 knowledge/。"""
    m = {}
    idx = root / "knowledge" / "_index.yaml"
    if idx.exists():
        doc = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
        for ns, cells in (doc.get("namespaces") or {}).items():
            # ADR-0004 格子结构：ns → category → [entries]
            for cat, cases in cells.items():
                for c in cases:
                    m[c.get("id")] = (ns, cat, (c.get("confidence") or {}).get("score"))
        return m
    kdir = root / "knowledge"
    for f in kdir.rglob("*.yaml"):
        if f.name.startswith("_") or f.parent.name == "_archive":
            continue
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        ns = str(f.parent.relative_to(kdir))
        for c in doc.get("cases", []):
            m[c.get("id")] = (ns, c.get("category"), (c.get("confidence") or {}).get("score"))
    return m


def main():
    import argparse
    ap = argparse.ArgumentParser(description="从 traces/*.yaml 计算 metrics")
    ap.add_argument("--emit-yaml", action="store_true",
                    help="额外输出 YAML 快照骨架（人复核后 append 进 metrics/timeline.yaml）")
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[1]
    by_case = ns_map_from_index(root)
    states = load_states(root)
    if not states:
        print("未找到任何 traces/*.yaml。先跑 /skill:diagnose 产生 trace。")
        return

    n = len(states)
    routed_ok = routed_total = 0
    tier2_hit = 0
    fb = {"resolved": 0, "not_resolved": 0, "partial": 0}
    tier3_used = tier3_saved = 0
    complete = 0
    vocab_total = 0
    vocab_bad = []

    # reference 指标（ADR-0008 观测性）：hits per ref / 引用后 resolve 率 / 平台分布。
    # 引用后 outcome 从该 session 最终 status 派生（不新增事件）；平台来自 lookup 事件。
    ref_hits = {}
    ref_resolved = {}
    ref_platforms = {}

    # 按类命中（metrics.md 定义）：每个 category 的 Tier2 命中 session / 该 category session
    # category 从 trace 的 triage/triage_semantic 事件取（agent 语义路由兜底也带 category）。
    cat_total = {}
    cat_hit = {}
    # 误诊率（metrics.md 定义）：反馈 not_resolved/partial 的命中 session / Tier2 命中 session
    misdiagnosed = 0
    # 执行-误诊归因比（metrics.md 定义）：attribution 事件 verdict 分布——case 错 vs 执行错。
    # 归因由 diagnose 在反馈 not_resolved 后读 trace 判定（SKILL 硬要求），此处只统计落点。
    attr = {"case_error": 0, "execution_error": 0}

    for st in states:
        trace = st.get("trace") or []
        # trajectory 统一 {role, ...}：agent 事件带 action，user 事件只带 content（无 action）
        # 词表只约束 agent 决策事件；user 输入事件是回放/fixture 的输入源，不参与词表检查
        actions = [t.get("action") for t in trace if t.get("action")]
        resolved = st.get("status") == "resolved"
        # category 归属：首个 triage / triage_semantic 事件的 category（该 session 路由结果）
        cat = next(
            (t.get("category") for t in trace
             if t.get("action") in ("triage", "triage_semantic") and t.get("category")),
            None,
        )
        if cat:
            cat_total[cat] = cat_total.get(cat, 0) + 1
        for t in trace:
            a = t.get("action")
            if not a:                       # user 事件（role=user）：无 action，跳过
                continue
            vocab_total += 1
            if a not in KNOWN_ACTIONS:
                vocab_bad.append(f"{st.get('session_id', '?')}: {a!r}")
            elif a == "reference_lookup":
                rid = t.get("ref_id") or t.get("ref") or "?"
                ref_hits[rid] = ref_hits.get(rid, 0) + 1
                if resolved:
                    ref_resolved[rid] = ref_resolved.get(rid, 0) + 1
                plat = t.get("platform")
                if plat:
                    ref_platforms[plat] = ref_platforms.get(plat, 0) + 1
            elif a == "attribution":
                v = t.get("verdict")
                if v in attr:
                    attr[v] += 1
        if "triage" in actions and (
            "quickly_check" in actions or "load_full" in actions or "hit" in actions
        ):
            complete += 1

        hit_case = None
        routed = []
        fb_outcome = None
        for t in trace:
            a = t.get("action")
            if a == "triage":
                routed += [str(r).rstrip("/") for r in (t.get("routed") or [])]
            elif a == "triage_semantic":
                # 语义路由兜底也是路由决策（E2 学习数据源）——计入路由准确率，
                # 否则语义路由错例不可见（路由准确率只覆盖 triage 会漏掉兜底路径）
                ns = t.get("namespace")
                if ns:
                    routed.append(str(ns).rstrip("/"))
            elif a == "hit":
                hit_case = t.get("case") or hit_case
            elif a == "feedback":
                out = t.get("outcome")
                if out in fb:
                    fb[out] += 1
                    fb_outcome = out

        if hit_case:
            tier2_hit += 1
            if cat:
                cat_hit[cat] = cat_hit.get(cat, 0) + 1
            if fb_outcome in ("not_resolved", "partial"):
                misdiagnosed += 1
            info = by_case.get(hit_case)
            ns = info[0] if isinstance(info, tuple) else info
            if routed and ns:
                routed_total += 1
                if any(r == ns or r.endswith("/" + ns) or ns.endswith("/" + r) for r in routed):
                    routed_ok += 1
        if "tier3" in actions:
            tier3_used += 1
            if st.get("status") == "resolved" and not hit_case:
                tier3_saved += 1

    # 置信度分布（metrics.md 定义）：低置信（score < 0.5）case 占比，从索引统计（无需 trace）
    scores = [v[2] for v in by_case.values() if isinstance(v, tuple) and v[2] is not None]
    n_low = sum(1 for s in scores if s < 0.5)

    # ---- 统一指标 dict（单一数据源：markdown 概览与 YAML 快照同源）----
    m = {
        "sessions_total": n,
        "tier2_hit": tier2_hit,
        "routed_accuracy": {"ok": routed_ok, "total": routed_total} if routed_total else None,
        "misdiagnosis_rate": {"ok": misdiagnosed, "total": tier2_hit} if tier2_hit else None,
        "by_category_hit": {c: {"hit": cat_hit.get(c, 0), "total": cat_total[c]}
                            for c in sorted(cat_total)} or None,
        "attribution_ratio": {"case_error": attr["case_error"],
                              "execution_error": attr["execution_error"]},
        "confidence_distribution": {"low": n_low, "total": len(scores)} if scores else None,
        "feedback_capture": {"resolved": fb["resolved"], "not_resolved": fb["not_resolved"],
                             "partial": fb["partial"]},
        "trace_completeness": {"ok": complete, "total": n},
        "vocab_compliance": {"ok": vocab_total - len(vocab_bad), "total": vocab_total},
        "tier3": {"used": tier3_used, "saved": tier3_saved},
        "reference": {"hits": sum(ref_hits.values()), "refs": len(ref_hits)} if ref_hits else None,
        "reference_detail": {rid: {"hits": h, "resolved": ref_resolved.get(rid, 0)}
                             for rid, h in sorted(ref_hits.items(), key=lambda x: -x[1])} or None,
    }

    rows = [
        "| 指标 | 值 |",
        "|---|---|",
        f"| 诊断 session 数 | {m['sessions_total']}（活跃 + 历史） |",
        f"| Tier 2 命中 session | {m['tier2_hit']} |",
        f"| 误诊率（命中但反馈 not_resolved/partial） | "
        + (f"{misdiagnosed}/{tier2_hit} ({misdiagnosed / tier2_hit:.0%})" if tier2_hit
           else "无可算样本（需 hit + feedback outcome）"),
        f"| 按类命中（hit session / 该 category session） | "
        + ("；".join(f"{c} {cat_hit.get(c, 0)}/{cat_total[c]}" for c in sorted(cat_total))
           if cat_total else "无可算样本（需 trace 含 triage.category）"),
        f"| 执行-误诊归因比（case 错 / 执行错） | "
        + (f"case {attr['case_error']} / execution {attr['execution_error']}"
           if sum(attr.values()) else "无归因落点（反馈 not_resolved 后 diagnose 应记 attribution 事件）"),
        (f"| 置信度分布 | {n_low}/{len(scores)} 低置信（score<0.5）；"
         f"中高置信 {len(scores) - n_low}" if scores else "| 置信度分布 | 索引无 score 数据（未生成或全空） |"),
        f"| 路由准确率 | "
        + (f"{routed_ok}/{routed_total} ({routed_ok / routed_total:.0%})" if routed_total
           else "无可算样本（需 trace 含 triage.routed + hit.case）"),
        f"| 结果反馈捕获 | {sum(fb.values())}/{tier2_hit}"
        f"（resolved {fb['resolved']} / not_resolved {fb['not_resolved']} / partial {fb['partial']}）",
        f"| trace 完整性（proxy：含 triage + 过滤步） | {complete}/{n} ({complete / n:.0%})",
        f"| trace 词表合规（词表外 action） | {vocab_total - len(vocab_bad)}/{vocab_total}"
        + (f"（违规：{'、'.join(vocab_bad[:5])}{'…' if len(vocab_bad) > 5 else ''}）" if vocab_bad else ""),
        f"| Tier 3 兜底使用 / 其中挽救（resolved 且无 Tier 2 命中） | {tier3_used} / {tier3_saved} |",
    ]
    # reference 指标（ADR-0008 观测性）——无引用时如实显示为空（reference 刚建立是现状）
    if ref_hits:
        rows.append(f"| reference 引用次数（去重 ref） | {sum(ref_hits.values())}（{len(ref_hits)} 个 ref） |")
        for rid, hits in sorted(ref_hits.items(), key=lambda x: -x[1]):
            res = ref_resolved.get(rid, 0)
            rate = f"{res}/{hits} ({res / hits:.0%})" if hits else "0"
            rows.append(f"|   {rid} | hits {hits}，引用后 resolved {rate} |")
        if ref_platforms:
            rows.append(
                "| reference 平台分布 | "
                + "、".join(f"{p} {c}" for p, c in sorted(ref_platforms.items(), key=lambda x: -x[1]))
                + " |"
            )
    else:
        rows.append("| reference 引用 | 0——先验知识层刚建立（ADR-0008），trace 尚未积累 reference_lookup 事件 |")
    print("\n".join(rows))
    print("\n<!-- metrics 由 owner 在 groom 周批时集中汇总：人复核后 append 进 metrics/timeline.yaml（每期一条，团队共享）；工程师不需要提交 metrics——他们只做诊断（本地 trace）+ 反馈（case confidence 走 PR）。小样本比例波动大，解读先看分母。机器可读快照：python3 scripts/trace_metrics.py --emit-yaml -->")

    if args.emit_yaml:
        print("\n--- metrics yaml 快照（复核后 append 进 metrics/timeline.yaml）---")
        import datetime
        snapshot = {
            "period": "YYYY-WNN",  # TODO: 填本期（如 2026-W36）；W 周期 ISO 8601
            "kind": "live",        # live | replay | example（只有 live 参与趋势对比）
            "title": "本期诊断指标（trace_metrics.py 自动生成，人复核）",
            "recorded_at": datetime.date.today().isoformat(),
            "source": "trace_metrics.py 从 traces/*.yaml 自动生成",
            "metrics": {k: v for k, v in m.items() if v is not None},
        }
        yaml.safe_dump({"periods": [snapshot]}, sys.stdout, allow_unicode=True,
                       sort_keys=False, default_flow_style=False)


if __name__ == "__main__":
    main()
