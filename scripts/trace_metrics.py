#!/usr/bin/env python3
# trace_metrics.py —— 从 traces/*.yaml 的 trace 计算指标（metrics/timeline.yaml 数据 + docs/guide/metrics.md 机制）
#
# 目的（ADR-0002）：过滤率/退休率/命中率/路由准确率从"假设"变"实测"。
# 数据源：traces/ 目录（gitignored，活跃 + 历史都归此）。
# 输出：markdown 指标表（stdout），人复核后追加进 docs/guide/metrics.md。
#
# 依赖的 trace action（词表见 skills/diagnose/SKILL.md「每步必写 trace」）：
#   triage / load_index / quickly_check / load_full / run_check / hit / miss
#   / tier3（Tier 3 兜底检索）/ feedback（结果反馈：resolved|not_resolved|partial）
# 字段缺失时降级计算，不硬崩。小样本时比例波动大——解读前先看分母。

import re
import sys
from pathlib import Path

import yaml
from exec_log_path import resolve_traces

# trace action 固定词表（与 skills/diagnose/SKILL.md「每步必写 trace」一致）
# 词表外 action = 诊断纪律违规，写入时靠 SKILL.md 约束，此处确定性检出
# reference_lookup（ADR-0008）：diagnose 查询先验知识层的四个触发点（数据缺口 / 键触发 /
# 判断缺口 / 方法缺口，见 skills/diagnose/references/diagnosis-trace.md）——reference 命中统计
# （hits/last_hit）与引用后 resolve 率的数据源；resolve 从该 session 最终 status 派生，
# 不新增单独事件。事件自带的两组取值各管一件事：`outcome`（hit/miss/skipped）是本行三态，
# `purpose` 是消费点分布。
# triage_semantic（triage 演进 PR #53）：triage 未命中时 agent 语义路由兜底——路由准确率
#   统计与 E2（router 从 trace 错例演进）的数据源。
# source_analysis（源码分析路径 PR #53）：深度排查走源码定位——沉淀/多层级评估的观测。
# attribution（误诊归因）：反馈 not_resolved 后读 trace 判定 case 错 / 执行错——归因比指标
#   的数据源（metrics.md「执行-误诊归因比」），无此落点则该指标无法统计。
#   注意：attribution 事件的 component 字段（执行错归因下沉，diagnose SKILL 写入）的
#   聚合统计由 scripts/component_tally.py 按需聚合承担（归因事件入 trace——无常驻台账表，
#   docs/mechanism/pipeline §2）——本脚本只计 verdict 分布（case_error/execution_error 汇总指标），
#   不重复统计 component，避免双源口径漂移。component 字段不会被词表检查拦截（非 action）。
KNOWN_ACTIONS = {
    "triage", "load_index", "quickly_check", "load_full",
    "run_check", "hit", "miss", "tier3", "feedback", "reference_lookup",
    "triage_semantic", "source_analysis", "attribution", "resume",
    "procedure_follow",   # 按流程执行（方法缺口消费点，EV-2026-038）：记 ref_id/steps_executed/branch_taken
    "report",             # 人读定位报告产出（diagnose 步骤 6）：记 report_file/sediment_candidates
}

# reference_lookup 的 purpose 固定词表（与 skills/diagnose/references/diagnosis-trace.md 一致）：
#   collect    数据缺口的采集面（步骤 1，候选加载前，精度 / 性能单必留一条）
#   signature  键触发：证据里的错误码 / 故障签名 / 环境变量名 / 版本组合（步骤 2 收尾，**先于候选加载**）
#   fix        修复依据（command-side-effect / 工具解读，步骤 3 阶段 2.5）
#   background 平台 / 软件背景 summary（步骤 3 阶段 2.5）
#   procedure  方法缺口的流程加载（步骤 5，EV-2026-038）——**只读全文**，摘要行不算加载
# 词表外的 purpose → 消费点分布指标（docs/guide/metrics.md）不可算，此处确定性检出。
KNOWN_PURPOSES = {"collect", "signature", "fix", "background", "procedure"}

# reference_lookup 的 outcome 三态（词表与 skills/diagnose/references/diagnosis-trace.md 一致）：
#   hit      查到并用于本次推理
#   miss     查了，但没有相关词条（记的是知识库覆盖缺口）
#   skipped  **没有查**，reason 必写为什么（触发点不在本轮路径上 / 证据里没有可检索键）
# 为什么要有 skipped（EV-2026-093）：不查不留痕时，"查了没命中"与"根本没查"在数据上同形——
# 消费率无法归因（分不清该改知识库还是改流程）。skipped 不计入引用次数（那是"查过"的口径）。
# 旧 trace 无 outcome 字段 → 照旧计入引用次数（不追溯改写历史记录）。
KNOWN_OUTCOMES = {"hit", "miss", "skipped"}


# triage miss 归类用的 token 判据见 scripts/_lexical.py（单一事实源：rank_candidates.py 共用同一组模式）
from _lexical import has_lexical_signal  # noqa: E402


def load_states(root: Path, traces_dir: Path | None = None):
    # traces/ 是诊断状态目录（gitignored，含客户信息）——活跃 + 历史都归此。
    # traces_dir 显式给了就用它（单元测试的合成 trace / 读另一份检出）；
    # 不给则沿用共享侧语义（resolve_traces 解析到主检出），既有调用面行为不变。
    base = Path(traces_dir) if traces_dir else resolve_traces(root)
    files = list(base.glob("*.yaml"))
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
    ap.add_argument("--emit-yaml-only", action="store_true",
                    help="只输出 YAML（块末的 periods 片段，不带人读 markdown）——供 "
                         "scripts/metrics_snapshot.py 组合快照时取诊断侧那一块")
    ap.add_argument("--root", default=None,
                    help="仓库根（默认：脚本上两级）。**traces/ 是各检出各一份的运行时件**——"
                         "在 worktree 里跑本脚本读不到主检出的 trace，需显式传主检出根；"
                         "metrics_snapshot.py 会自动解析并标注读的是哪一份")
    ap.add_argument("--traces-dir", default=None,
                    help="显式指定 traces/ 目录（默认由 resolve_traces(root) 解析到主检出）。"
                         "用于单元测试的合成 trace 与「读另一份检出」的场景；不传即保持共享侧语义")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    by_case = ns_map_from_index(root)
    states = load_states(root, Path(args.traces_dir) if args.traces_dir else None)
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
    # 消费点分布（docs/guide/metrics.md「reference 引用」口径）：purpose ∈ collect/signature/fix/background
    ref_purposes = {}
    purpose_bad = []
    # 触发三态（EV-2026-093）：hit / miss / skipped——三态缺一，"没查"与"查了没命中"同形
    ref_outcomes = {}
    outcome_bad = []

    # 按类命中（metrics.md 定义）：每个 category 的 Tier2 命中 session / 该 category session
    # category 从 trace 的 triage/triage_semantic 事件取（agent 语义路由兜底也带 category）。
    cat_total = {}
    cat_hit = {}
    # 误诊率（metrics.md 定义）：反馈 not_resolved/partial 的命中 session / Tier2 命中 session
    misdiagnosed = 0
    # 执行-误诊归因比（metrics.md 定义）：attribution 事件 verdict 分布——case 错 vs 执行错。
    # 归因由 diagnose 在反馈 not_resolved 后读 trace 判定（SKILL 硬要求），此处只统计落点。
    attr = {"case_error": 0, "execution_error": 0}
    # triage miss 两类（EV-2026-110）——两类同形就没法判断"该不该补词"，这里把它们分开记
    miss_lex, miss_sem, miss_unrec, miss_notriage = [], [], [], []

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
                out = t.get("outcome")
                if out:
                    ref_outcomes[out] = ref_outcomes.get(out, 0) + 1
                    if out not in KNOWN_OUTCOMES:
                        outcome_bad.append(f"{st.get('session_id', '?')}: {out!r}")
                # skipped = 本触发点没有查 → 不计入引用次数（"没查"不得读成"查了没命中"）。
                # 旧 trace 无 outcome 字段（out is None）→ 照旧计入，不追溯改写历史记录的读法。
                if out != "skipped":
                    ref_hits[rid] = ref_hits.get(rid, 0) + 1
                    if resolved:
                        ref_resolved[rid] = ref_resolved.get(rid, 0) + 1
                plat = t.get("platform")
                if plat:
                    ref_platforms[plat] = ref_platforms.get(plat, 0) + 1
                pur = t.get("purpose")
                if pur:
                    ref_purposes[pur] = ref_purposes.get(pur, 0) + 1
                    if pur not in KNOWN_PURPOSES:
                        purpose_bad.append(f"{st.get('session_id', '?')}: {pur!r}")
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
        sid = str(st.get("session_id") or "?")
        # triage miss 归类（EV-2026-110）。先分清两件被混在一起的事：
        #   ① 真 miss：trace 里有 triage_semantic（语义兜底被触发）或 triage 明确记了空 routed；
        #   ② **记录缺口**：有 triage 事件但 routed 字段没记——E2 的错例池正是靠这个字段取数，
        #      没记就等于"这一单没进池"，与"路由没错"在数据上同形。
        has_semantic = any(t.get("action") == "triage_semantic" for t in trace)
        triage_events = [t for t in trace if t.get("action") == "triage"]
        routed_ok_ = any(t.get("routed") for t in triage_events)
        explicit_miss = any(t.get("action") == "triage" and t.get("routed") == [] for t in trace)
        if not routed_ok_:
            user_text = " ".join(
                str(t.get("content") or "") + " "
                + str((t.get("evidence") or {}).get("inline") or "")
                for t in trace if t.get("role") == "user"
            )
            if has_semantic or explicit_miss:
                (miss_lex if has_lexical_signal(user_text) else miss_sem).append(sid)
            elif triage_events:
                miss_unrec.append(sid)
            else:
                miss_notriage.append(sid)

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
        # triage miss 两类（EV-2026-110）：lexical_gap 进 E2 错例池，semantic_path 是级联正常换挡
        "triage_miss_classes": ({"lexical_gap": len(miss_lex), "semantic_path": len(miss_sem),
                                 "routed_unrecorded": len(miss_unrec),
                                 "no_triage_event": len(miss_notriage)}
                                if (miss_lex or miss_sem or miss_unrec or miss_notriage) else None),
        "triage_miss_sessions": ({"lexical_gap": miss_lex[:5], "semantic_path": miss_sem[:5],
                                  "routed_unrecorded": miss_unrec[:5]}
                                 if (miss_lex or miss_sem or miss_unrec) else None),
        "reference": {"hits": sum(ref_hits.values()), "refs": len(ref_hits)} if ref_hits else None,
        # 触发三态（EV-2026-093）：三态都进快照——消费率要能与"没查"区分才可归因
        "reference_outcomes": ref_outcomes or None,
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
        (f"| triage miss 归类 | lexical_gap {len(miss_lex)}（token 在场却没接住→进 E2 错例池）"
         f"；semantic_path {len(miss_sem)}（本来无 token，级联正常换挡）"
         f"；routed 未记录 {len(miss_unrec)}（E2 取数字段缺口）"
         + (f"；无 triage 事件 {len(miss_notriage)}" if miss_notriage else "")
         if (miss_lex or miss_sem or miss_unrec or miss_notriage)
         else "| triage miss 归类 | 本批无 miss（routed 全记录） |"),
    ]
    # reference 指标（ADR-0008 观测性）——无引用时如实显示为空（reference 刚建立是现状）
    if ref_hits or ref_outcomes:
        if ref_hits:
            rows.append(f"| reference 引用次数（去重 ref） | {sum(ref_hits.values())}（{len(ref_hits)} 个 ref） |")
        # 触发三态（EV-2026-093）：skipped = 没查，单列——它与 miss（查了没命中）指向相反的改进方向
        if ref_outcomes:
            three = "、".join(f"{k} {v}" for k, v in sorted(ref_outcomes.items(), key=lambda x: -x[1]))
            rows.append(
                f"| reference 触发三态（hit/miss/skipped） | {three}（合计 {sum(ref_outcomes.values())}）"
                + (f"；**词表外：{'、'.join(outcome_bad[:5])}**" if outcome_bad else "")
                + " |"
            )
        pur_summary = "、".join(f"{k} {v}" for k, v in sorted(ref_purposes.items(), key=lambda x: -x[1]))
        rows.append(
            f"| reference 消费点分布（collect/signature/fix/background） | "
            + (pur_summary if pur_summary else "无 purpose 字段（旧 trace 未记）")
            + (f"；**词表外：{'、'.join(purpose_bad[:5])}**" if purpose_bad else "")
            + " |"
        )
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
    # `--emit-yaml-only` 是机器读路径（供 metrics_snapshot.py 组合快照）：不出人读 markdown，
    # 否则调用方要在一堆 markdown 里找 YAML 块（实测会直接解析失败）。
    if not args.emit_yaml_only:
        print("\n".join(rows))
        print("\n<!-- metrics 在周批时机汇总（**任何人跑周批时都可做**，不是某个角色的专属动作）：人复核后把这一期写进 metrics/timeline.d/<期号>.yaml，再跑 python3 scripts/build_timeline.py 重建生成物 metrics/timeline.yaml（每期一个源文件，团队共享）。工程师不需要提交 metrics——他们只做诊断（本地 trace）+ 回报 fix 结果（case confidence 走 PR）。小样本比例波动大，解读先看分母。机器可读快照：python3 scripts/trace_metrics.py --emit-yaml -->")

    if args.emit_yaml or args.emit_yaml_only:
        import datetime
        snapshot = {
            "period": "YYYY-WNN",  # TODO: 填本期（如 2026-W36）；W 周期 ISO 8601
            "kind": "live",        # live | replay | example（只有 live 参与趋势对比）
            "title": "本期诊断指标（trace_metrics.py 自动生成，人复核）",
            "recorded_at": datetime.date.today().isoformat(),
            "source": "trace_metrics.py 从 traces/*.yaml 自动生成",
            "metrics": {k: v for k, v in m.items() if v is not None},
        }
        if args.emit_yaml_only:
            # 机器读路径：只吐 metrics mapping（组合快照的调用方要的就是这一块）
            yaml.safe_dump({"metrics": snapshot["metrics"]}, sys.stdout,
                           allow_unicode=True, sort_keys=False, default_flow_style=False)
        else:
            print("\n--- metrics yaml 快照（复核后 append 进 metrics/timeline.yaml）---")
            yaml.safe_dump({"periods": [snapshot]}, sys.stdout, allow_unicode=True,
                           sort_keys=False, default_flow_style=False)


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
