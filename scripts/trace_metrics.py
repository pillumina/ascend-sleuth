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
KNOWN_ACTIONS = {
    "triage", "load_index", "quickly_check", "load_full",
    "run_check", "hit", "miss", "tier3", "feedback",
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
        for ns, cases in (doc.get("namespaces") or {}).items():
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

    for st in states:
        trace = st.get("trace") or []
        actions = [t.get("action") for t in trace]
        for t in trace:
            a = t.get("action")
            vocab_total += 1
            if a not in KNOWN_ACTIONS:
                vocab_bad.append(f"{st.get('session_id', '?')}: {a!r}")
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
    print("\n".join(rows))
    print("\n<!-- 复核后把上表追加进 docs/metrics.md；小样本比例波动大，解读先看分母 -->")


if __name__ == "__main__":
    main()
