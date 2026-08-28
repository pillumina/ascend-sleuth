#!/usr/bin/env python3
# trace_metrics.py —— 从 diagnosis_state-*.yaml 的 trace 计算 docs/metrics.md 的指标
#
# 目的（ADR-0002）：过滤率/退休率/命中率/路由准确率从"假设"变"实测"。
# 数据源：仓库根的活跃 diagnosis_state-*.yaml + postmortems/history/ 里的历史。
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
KNOWN_ACTIONS = {
    "triage", "load_index", "quickly_check", "load_full",
    "run_check", "hit", "miss", "tier3", "feedback", "reference_lookup",
}


def load_states(root: Path):
    files = list(root.glob("diagnosis_state-*.yaml"))
    files += list((root / "postmortems" / "history").rglob("diagnosis_state-*.yaml"))
    states = []
    for f in files:
        try:
            states.append(yaml.safe_load(f.read_text(encoding="utf-8")) or {})
        except Exception as e:  # noqa: BLE001
            print(f"WARN: 解析失败 {f}: {e}", file=sys.stderr)
    return states


def ns_map_from_index(root: Path) -> dict:
    """case id → namespace。优先读生成索引；索引缺失则现扫 knowledge/。"""
    m = {}
    idx = root / "knowledge" / "_index.yaml"
    if idx.exists():
        doc = yaml.safe_load(idx.read_text(encoding="utf-8")) or {}
        for ns, cells in (doc.get("namespaces") or {}).items():
            # ADR-0004 格子结构：ns → category → [entries]
            for cases in cells.values():
                for c in cases:
                    m[c.get("id")] = ns
        return m
    kdir = root / "knowledge"
    for f in kdir.rglob("*.yaml"):
        if f.name.startswith("_") or f.parent.name == "_archive":
            continue
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        ns = str(f.parent.relative_to(kdir))
        for c in doc.get("cases", []):
            m[c.get("id")] = ns
    return m


def main():
    root = Path(__file__).resolve().parents[1]
    by_case = ns_map_from_index(root)
    states = load_states(root)
    if not states:
        print("未找到任何 diagnosis_state-*.yaml（活跃或历史）。先跑 /skill:diagnose 产生 trace。")
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

    for st in states:
        trace = st.get("trace") or []
        actions = [t.get("action") for t in trace]
        resolved = st.get("status") == "resolved"
        for t in trace:
            a = t.get("action")
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
        if "triage" in actions and (
            "quickly_check" in actions or "load_full" in actions or "hit" in actions
        ):
            complete += 1

        hit_case = None
        routed = []
        for t in trace:
            a = t.get("action")
            if a == "triage":
                routed += [str(r).rstrip("/") for r in (t.get("routed") or [])]
            elif a == "hit":
                hit_case = t.get("case") or hit_case
            elif a == "feedback":
                out = t.get("outcome")
                if out in fb:
                    fb[out] += 1

        if hit_case:
            tier2_hit += 1
            ns = by_case.get(hit_case)
            if routed and ns:
                routed_total += 1
                if any(r == ns or r.endswith("/" + ns) or ns.endswith("/" + r) for r in routed):
                    routed_ok += 1
        if "tier3" in actions:
            tier3_used += 1
            if st.get("status") == "resolved" and not hit_case:
                tier3_saved += 1

    rows = [
        "| 指标 | 值 |",
        "|---|---|",
        f"| 诊断 session 数 | {n}（活跃 + 历史） |",
        f"| Tier 2 命中 session | {tier2_hit} |",
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
    print("\n<!-- metrics 由 owner 在 groom 周批时集中汇总 append 进 docs/metrics.md（每期一条，团队共享）；工程师不需要提交 metrics——他们只做诊断（本地 trace）+ 反馈（case confidence 走 PR）。小样本比例波动大，解读先看分母 -->")


if __name__ == "__main__":
    main()
