#!/usr/bin/env python3
# evolution_health.py —— 演进闭环的体检器（判据在 proposals/gates.yaml）
#
# 为什么需要它：指标侧早有 metrics_health.py（判据落成数据、三态退出码、只报要动作的），
# 演进侧一直缺同构的一层——于是面板只能把 EV 卡平铺出来，实测退化成一堵"只增不减的墙"
# （56/57 validated、0 rejected、采纳率 100%，任何聚合读数都是常数）。人的注意力是硬预算
# （原则九），一批几十张卡按面板自己实测的决策链长度约 4.8 万字，远超人审带宽——所以正确
# 的做法不是把卡显示得更好看，而是**先判决、只在需要动作时上屏**（本脚本 + gates.yaml），
# 卡降为按需展开的 diff 日志。
#
# 三态退出码（与 metrics_health.py / ev_measure.py 同形）：
#   0 = 判据全部被评估过且无越界（本期确实没有阻塞项）
#   1 = 有判据被违反（按报告的 action 处置）
#   2 = 有判据**没被评估**（结构性：声明了没实现 / 数据源坏了）→ **结论不可用**
# 2 与 0 分开的理由照抄 metrics_health 的两个实测教训：判据没触发 ≠ 判据被检查过。
# 本脚本**不进 CI**：安静的一周（无新卡、无新收尾）是正常状态，硬门会假红；服务周批与季度自评。
#
# 用法：
#   python3 scripts/evolution_health.py            # 人读报告
#   python3 scripts/evolution_health.py --check    # 三态退出码
#   python3 scripts/evolution_health.py --json     # 面板的数据契约（dsh-plugins/ev-panel）

import argparse
import json
import operator
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ev_board_data as EBD                      # noqa: E402
from ev_measure import classify as classify_measure, load_cards  # noqa: E402
from verify_proposals import measure_enforced    # noqa: E402

GATES_REL = Path("proposals") / "gates.yaml"

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le,
       "==": operator.eq, "!=": operator.ne}

# 判据实现面（实现事实在代码，阈值在 gates.yaml——与 metrics_health 的 IMPLEMENTED_* 同一分工）。
# gates.yaml 里声明了但这里没有的 dimension → 覆盖面对比时点名 → exit 2，防"声明了没实现"假绿。
IMPLEMENTED_GATE_DIMENSIONS = {
    "negative_terminal", "backlog_count", "runnable_never_measured",
    "external_ground_truth_ratio", "top_signal_share", "dead_ref_count",
    "unfalsifiable_enforced",
}
IMPLEMENTED_READABILITY_RULES = {"source_nonzero", "any_gt_0"}

# 判据的**标题**在 proposals/gates.yaml（文案属数据，人可改不必动代码）；这里只留
# **带数值的读数模板**（格式化贴着维度定义，且要能引上下文值如信号名/失效路径）。
# 找不到 title 时退回 id，不静默。
GATE_READINGS = {
    "no_negative_feedback": "终态 {terminal_cards} 张全部采纳，否决 0 张",
    "backlog_over": "{backlog_count} 张已验证卡无合入指针（批上限 {value}）",
    "measure_never_run": "{runnable_never_measured} 张已声明可复现判据，从未执行",
    "evidence_weak": "外部验证占比 {external_ratio_pct}（下限 {value_pct}）",
    "signal_dominant": "最高信号「{top_signal_name}」占 {top_signal_share_pct}（阈值 {value_pct}）",
    "pointer_rot": "{dead_ref_count} 个点名文件已不存在：{dead_ref_sample}",
    "unfalsifiable": "强制范围内缺可复现判据 {unfalsifiable_enforced} 张",
}
# 比例型维度：读数与阈值都按百分比渲染（"0.246（下限 0.333）"不如"24.6%（下限 33.3%）"可读）。
# 值是占位符名 → 模板里用短名，避免 `{external_ground_truth_ratio_pct}` 这种长占位符。
RATIO_DIMS = {
    "external_ground_truth_ratio": "external_ratio_pct",
    "top_signal_share": "top_signal_share_pct",
}


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def collect_capture(root: Path):
    """现场反馈捕获（最新 live 快照）——能力轴唯一的标签来源。缺席如实标注，不写 0 冒充。"""
    path = root / "metrics" / "timeline.yaml"
    if not path.exists():
        return {"present": False, "total": None, "why": "没有 metrics/timeline.yaml"}
    try:
        d = load_yaml(path)
    except Exception as e:
        return {"present": False, "total": None, "why": f"timeline 解析失败: {e}"}
    if not isinstance(d, dict):
        return {"present": False, "total": None, "why": "timeline 结构不是 mapping"}
    lives = [p for p in (d.get("periods") or [])
             if isinstance(p, dict) and p.get("kind") == "live"]
    if not lives:
        return {"present": False, "total": None, "why": "timeline 里没有 live 期快照"}
    last = lives[-1]
    fc = (last.get("metrics") or {}).get("feedback_capture")
    if not isinstance(fc, dict):
        return {"present": False, "total": None, "period": last.get("period"),
                "why": f"最新 live 期（{last.get('period')}）没有 feedback_capture 字段"}
    total = sum(v for v in fc.values() if isinstance(v, (int, float)))
    return {"present": True, "total": total, "period": last.get("period"), "raw": fc}


def collect_dimensions(root: Path):
    """一次算齐全部判据维度。缺失的维度**不进** dims（覆盖面对比据此点名 → exit 2）。"""
    ideas = EBD.collect_ideas(root)
    stats = EBD.collect_stats(ideas)
    runs = EBD.collect_measure_runs(root)

    # 预测口径：可复现 / 自称不可度量 / 强制卡缺 measure / 存量豁免
    runnable, declared, missing_enforced, legacy = [], [], [], []
    for cid, doc, _p in load_cards(root):
        kind, _m = classify_measure(doc)
        if kind == "runnable":
            runnable.append(cid)
        elif kind == "declared":
            declared.append(cid)
        elif measure_enforced(doc):
            missing_enforced.append(cid)
        else:
            legacy.append(cid)
    measured = [c for c in (runs.get("cards") or [])]

    dims = {
        "negative_terminal": stats["negative_terminal"],
        "terminal_cards": stats["terminal_count"],
        "backlog_count": stats["backlog_count"],
        "runnable_never_measured": len([c for c in runnable if c not in measured]),
        "external_ground_truth_ratio": stats["external_ratio"],
        "top_signal_share": stats["top_signal_share"],
        "dead_ref_count": stats["dead_ref_count"],
        "dead_ref_paths": stats["dead_ref_paths"],
        "unfalsifiable_enforced": len(missing_enforced),
    }

    ages = [d for d in (EBD.days_since(c.get("created_at")) for c in ideas) if isinstance(d, int)]
    dims["newest_card_age_days"] = min(ages) if ages else None
    dims["cards_total"] = stats["total"]

    skill_exec = EBD.collect_skill_exec(root)
    last_check = skill_exec.get("last_evolve_check")
    if last_check and last_check.get("at"):
        try:
            stamp = str(last_check["at"])[:10]
            dims["evolve_check_age_days"] = (date.today() - date.fromisoformat(stamp)).days
        except ValueError:
            dims["evolve_check_age_days"] = None
    else:
        dims["evolve_check_age_days"] = None

    capture = collect_capture(root)
    if capture["present"]:
        dims["s1_feedback_capture"] = capture["total"]

    readouts = {
        "cards_total": stats["total"],
        "terminal_cards": stats["terminal_count"],
        "runnable_cards": len(runnable),
        "declared_unmeasurable": len(declared),
        "legacy_no_measure": len(legacy),
        "measured_cards": len(measured),
        "measure_runs": runs.get("runs", 0),
        "measure_by_verdict": runs.get("by_verdict") or {},
        "measure_ledger": {"state": runs.get("state"), "note": runs.get("note")},
        "by_surface": stats["by_surface"],
        "by_surface_recent": stats["by_surface_recent"],
        "surface_window_days": stats["surface_window_days"],
        "surface_basis_strength": stats["surface_basis_strength"],
        "signal_spread": stats["signal_spread"][:5],
        "top_signal_share": stats["top_signal_share"],
        "cost_median": stats["cost_median"],
        "cost_total": stats["cost_total"],
        "gap_cards": stats["gap_cards"],
        "stale_cards": stats["stale_cards"],
        "evolve_check_runs": skill_exec.get("evolve_check_runs", 0),
        "evolve_check_no_signal": skill_exec.get("evolve_check_no_signal", 0),
        "last_evolve_check": last_check,
        "capture": capture,
        "unattributed_cards": [c.get("id") for c in ideas if c.get("surface") == EBD.UNATTRIBUTED],
    }
    return dims, readouts


def _reading(text: str, dims) -> str:
    """把实测值塞进一行标题里——判决必须带读数，否则又是一句无法核对的散文。"""
    return text.format(**{k: ("—" if v is None else v) for k, v in dims.items()})


def _rule_any_gt_0(value) -> bool:
    """`any_gt_0`：来源是 mapping 时任一值 > 0；是数值时自身 > 0；其他形态判否。"""
    if isinstance(value, dict):
        return any(v > 0 for v in value.values() if isinstance(v, (int, float)))
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, (list, tuple)):
        return any(v > 0 for v in value if isinstance(v, (int, float)))
    return False


def evaluate(root: Path):
    findings = []
    broken = []
    errors = []

    gates_path = root / GATES_REL
    if not gates_path.exists():
        errors.append(f"判据文件不存在：{GATES_REL}")
        cfg = {}
    else:
        try:
            cfg = load_yaml(gates_path) or {}
            if not isinstance(cfg, dict):
                raise ValueError("顶层不是 mapping")
        except Exception as e:
            errors.append(f"判据文件解析失败：{GATES_REL}: {e}")
            cfg = {}

    try:
        dims, readouts = collect_dimensions(root)
    except Exception as e:
        errors.append(f"维度采集失败：{e}")
        dims, readouts = {}, {}

    # 读数模板可引用的上下文值（阈值本身 + 需要点名的主体：哪个信号、哪些失效路径）。
    # 判据的读数应当**点名主体**：只报数字的判决仍然要人自己去查是哪一处。
    top = (readouts.get("signal_spread") or [{}])[0] if readouts else {}
    dead = dims.get("dead_ref_paths") or []
    fmt_ctx = dict(dims)
    fmt_ctx.update({
        "top_signal_name": top.get("signal") or "—",
        "top_signal_cards": top.get("cards"),
        "dead_ref_sample": "、".join(dead[:3]) + ("…" if len(dead) > 3 else "") if dead else "—",
    })
    for _d, _alias in RATIO_DIMS.items():
        _v = dims.get(_d)
        fmt_ctx[_alias] = f"{_v:.1%}" if isinstance(_v, (int, float)) else "—"

    # ---- 新鲜度：演进还在跑吗 ----
    fresh = cfg.get("freshness") or {}
    lim_ev = fresh.get("evolve_check_max_age_days")
    lim_card = fresh.get("card_max_age_days")
    age_ev = dims.get("evolve_check_age_days")
    age_card = dims.get("newest_card_age_days")
    if readouts.get("evolve_check_runs", 0) == 0:
        findings.append({"level": "fail", "face": "新鲜度", "id": "evolve_check_never",
                         "title": "收尾记录为空：一次 evolve-check 都没跑过",
                         "reading": "共 0 次",
                         "action": "内容流程收尾应落记录（log_skill_exec.py --skill evolve-check）；"
                                   "先让它跑起来，再谈趋势"})
    elif isinstance(age_ev, int) and isinstance(lim_ev, (int, float)) and age_ev > lim_ev:
        findings.append({"level": "fail", "face": "新鲜度", "id": "evolve_check_stale",
                         "title": "演进断档：最近一次收尾距今过久",
                         "reading": f"{age_ev} 天前（上限 {lim_ev} 天）",
                         "action": "跑一轮内容流程或深度轮（/skill:self-evolve）"})
    if isinstance(age_card, int) and isinstance(lim_card, (int, float)) and age_card > lim_card:
        findings.append({"level": "fail", "face": "新鲜度", "id": "no_new_cards",
                         "title": "产卡停滞",
                         "reading": f"最新一张卡 {age_card} 天前（上限 {lim_card} 天）",
                         "action": "复核是「确实无事可做」还是信号被关掉了"})

    # ---- 越界 ----
    gate_rows = []
    for g in (cfg.get("gates") or []):
        if not isinstance(g, dict) or not g.get("id"):
            errors.append("gates 里有缺 id 的条目")
            continue
        gid = g["id"]
        dim_name = g.get("dimension")
        implemented = dim_name in IMPLEMENTED_GATE_DIMENSIONS
        row = {"id": gid, "dimension": dim_name, "op": g.get("op"), "value": g.get("value"),
               "implemented": implemented, "evaluated": False}
        gate_rows.append(row)
        if not implemented:
            broken.append(f"判据 {gid} 声明了 dimension={dim_name}，但实现面里没有它")
            continue
        val = dims.get(dim_name)
        if val is None:
            broken.append(f"判据 {gid}（{dim_name}）的数据源缺失，本期未被评估")
            continue
        row["evaluated"] = True
        sample = g.get("min_sample")
        sample_dim = dims.get("terminal_cards") if dim_name in (
            "negative_terminal", "external_ground_truth_ratio") else dims.get("cards_total")
        if isinstance(sample, (int, float)) and isinstance(sample_dim, (int, float)) \
                and sample_dim < sample:
            findings.append({"level": "note", "face": "越界", "id": gid,
                             "title": (g.get("title") or gid) + "（样本不足，本期不判）",
                             "reading": f"样本 {sample_dim} < 门槛 {sample}",
                             "action": "积累样本后本判据自动生效"})
            continue
        try:
            hit = OPS[g.get("op")](val, g.get("value"))
        except KeyError:
            broken.append(f"判据 {gid} 的 op={g.get('op')!r} 不支持")
            continue
        if hit:
            ctx = dict(fmt_ctx)
            ctx["value"] = g.get("value")
            if dim_name in RATIO_DIMS and isinstance(g.get("value"), (int, float)):
                ctx["value_pct"] = f"{g['value']:.1%}"
            tpl = GATE_READINGS.get(gid)
            if tpl:
                reading = tpl.format(**{k: ("—" if v is None else v) for k, v in ctx.items()})
            else:
                reading = f"{dim_name} = {val}（阈值 {g.get('op')} {g.get('value')}）"
            findings.append({"level": "fail", "face": "越界", "id": gid,
                             "title": g.get("title") or gid,
                             "reading": reading,
                             "meaning": " ".join(str(g.get("meaning") or "").split()),
                             "action": " ".join(str(g.get("action") or "").split())})

    # ---- 可解读性 ----
    read_rows = []
    readability = {}
    for r in (cfg.get("readability") or []):
        if not isinstance(r, dict) or not r.get("metric"):
            errors.append("readability 里有缺 metric 的条目")
            continue
        metric, rule, src = r["metric"], r.get("rule"), r.get("source")
        implemented = rule in IMPLEMENTED_READABILITY_RULES
        row = {"metric": metric, "rule": rule, "source": src, "implemented": implemented,
               "present_in_snapshot": src in dims}
        read_rows.append(row)
        if not implemented:
            broken.append(f"可解读性规则 {metric} 的 rule={rule!r} 没有实现")
            continue
        if src not in dims:
            broken.append(f"可解读性规则 {metric} 的来源 {src} 缺席（无法判断读数能不能信）")
            readability[metric] = {"readable": None, "why": f"来源 {src} 缺席",
                                   "label": r.get("label") or metric, "label_readable": "不可判定"}
            continue
        v = dims[src]
        if rule == "source_nonzero":
            ok = bool(v)
        elif rule == "any_gt_0":
            ok = _rule_any_gt_0(v)
        else:
            ok = False
        readability[metric] = {
            "readable": ok,
            "why": " ".join(str(r.get("why") or "").split()),
            "label": r.get("label") or metric,     # 面板显示用人读名，不把内部 metric id 端给人看
            "label_readable": "可读" if ok else "不可解读",
            "source_value": v,
        }

    fails = [f for f in findings if f["level"] == "fail"]
    exit_code = 2 if (broken or errors) else (1 if fails else 0)
    verdict = "broken" if (broken or errors) else ("violations" if fails else "clean")

    coverage = {
        "gates_total": len(gate_rows),
        "gates_evaluated": sum(1 for r in gate_rows if r["evaluated"]),
        "gates": gate_rows,
        "readability_total": len(read_rows),
        "readability_evaluated": len([r for r in read_rows
                                      if r["implemented"] and r["present_in_snapshot"]]),
        "readability": read_rows,
    }

    commands = []
    for f in fails:
        if f["id"] == "measure_never_run":
            commands.append({"label": "复核一张卡的预测", "why": f["title"],
                             "command": "python3 scripts/ev_measure.py <卡号> --run"})
        elif f["id"] == "backlog_over":
            commands.append({"label": "盘点预测可复现性", "why": f["title"],
                             "command": "python3 scripts/ev_measure.py --audit"})
        elif f["id"] == "pointer_rot":
            commands.append({"label": "跑一遍闭环演练（含 CI parity）", "why": f["title"],
                             "command": "python3 scripts/rehearse_evolve_loop.py"})

    return {
        "findings": findings,
        "fail_count": len(fails),
        "dimensions": dims,
        "readouts": readouts,
        "gates": (cfg.get("gates") or []),
        "readability": readability,
        "coverage": coverage,
        "candidate_commands": commands,
        "broken": broken,
        "errors": errors,
        "exit_code": exit_code,
        "check_verdict": verdict,
        "gates_path": str(GATES_REL),
    }


def render(p: dict) -> str:
    out = ["演进闭环体检（判据：proposals/gates.yaml）", ""]
    by_face = {}
    for f in p["findings"]:
        by_face.setdefault(f["face"], []).append(f)
    icon = {"fail": "✗", "warn": "!", "note": "·"}
    for face in ("新鲜度", "越界"):
        rows = by_face.get(face) or []
        out.append(f"[{face}]")
        if not rows:
            out.append("  ✓ 无待处理项")
        for f in rows:
            out.append(f"  {icon.get(f['level'], '·')} {f['title']} —— {f['reading']}")
            if f.get("meaning"):
                out.append(f"      判据：{f['meaning'][:160]}")
            if f.get("action"):
                out.append(f"      → {f['action'][:200]}")
        out.append("")
    out.append("[数字可信度]")
    if not p["readability"]:
        out.append("  ✓ 无规则声明")
    for metric, r in p["readability"].items():
        mark = "✓" if r.get("readable") else "!"
        out.append(f"  {mark} {r.get('label') or metric}: {r.get('label_readable')}"
                   f"（来源={r.get('source_value')}）")
        if not r.get("readable"):
            out.append(f"      → {r.get('why', '')[:200]}")
    out.append("")
    ro = p["readouts"]
    if ro:
        out.append("[读数]（判据之外，供人判读）")
        surf = " · ".join(f"{k} {v}" for k, v in (ro.get("by_surface") or {}).items())
        rec = " · ".join(f"{k} {v}" for k, v in (ro.get("by_surface_recent") or {}).items())
        out.append(f"  触及面（累计 {ro.get('cards_total')} 张）：{surf or '—'}")
        out.append(f"  触及面（近 {ro.get('surface_window_days')} 天）：{rec or '—'}")
        out.append(f"  证据强度：{' · '.join(f'{k} {v}' for k, v in (ro.get('surface_basis_strength') or {}).items()) or '—'}")
        out.append(f"  预测口径：可复现 {ro.get('runnable_cards')} · 自称不可度量 "
                   f"{ro.get('declared_unmeasurable')} · 存量无口径 {ro.get('legacy_no_measure')} · "
                   f"实测过 {ro.get('measured_cards')}（记录 {ro.get('measure_runs')} 笔）")
        out.append("")
    cov = p["coverage"]
    out.append(f"[判据覆盖面] 判据 {cov['gates_evaluated']}/{cov['gates_total']} 条已评估 · "
               f"可解读性规则 {cov['readability_evaluated']}/{cov['readability_total']} 条已评估")
    for b in p["broken"]:
        out.append(f"  ✗ {b}")
    for e in p["errors"]:
        out.append(f"  ✗ {e}")
    out.append("")
    for c in p["candidate_commands"]:
        out.append(f"  可跑：{c['command']}   （{c['why']}）")
    out.append(f"结论：{p['check_verdict']}（{p['fail_count']} 项要处理）")
    out.append("  退出码：0 判据全部评过且无越界 · 1 有判据被违反 · 2 有判据未被评估（结论不可用）")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="演进闭环体检器（判据：proposals/gates.yaml）")
    ap.add_argument("--check", action="store_true", help="用三态退出码表示结论")
    ap.add_argument("--usable", action="store_true",
                    help="只问「结论可用吗」：判据全部被评估即退 0（有违反也退 0），未被评估才退 2")
    ap.add_argument("--json", action="store_true", help="输出 JSON（面板的数据契约）")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()

    payload = evaluate(args.root.resolve())
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(render(payload))
    # 两种问法分开（这是本次落地时踩出来的）：`--check` 的三态是给**人**读的——"有违反"与
    # "判不了"必须分开，否则"体检器坏了"会被读成"本期没事"。但**下游消费者**（reviewer 的
    # measure、周批的前置检查）常只需要"这份结论能不能用"：有违反是数据的事实，不是判据层
    # 失效。把两种问法都做成显式开关，比让调用方去 parse 退出码更不容易出错。
    if args.usable:
        return 2 if payload["check_verdict"] == "broken" else 0
    return payload["exit_code"] if args.check else 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
