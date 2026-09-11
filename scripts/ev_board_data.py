#!/usr/bin/env python3
# ev_board_data.py —— 自演进看板数据汇总（EV 卡 + timeline + 容量 + 归因聚合）
#
# 供 DSH 面板（dsh-plugins/ev-panel）host 侧调用：一次性汇总 proposals/ideas/、
# metrics/timeline.yaml、knowledge/_index.yaml 头注、归因事件按需聚合
# （component_tally 逻辑：trace attribution + .s2-replay/attributions.yaml）、
# .s2-replay/attributions.yaml 为 JSON，stdout 输出。确定性逻辑（原则二）：解析与
# 聚合进脚本，agent/面板只读聚合结果。
#
# 用法：python3 scripts/ev_board_data.py [--root <repo>]

import argparse
import datetime
import glob
import json
import re
import sys
from pathlib import Path

import yaml

# 允许 import 同目录脚本（component_tally 按需聚合复用）
sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_yaml(path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"__error__": str(e)}


def parse_index_header(text):
    """knowledge/_index.yaml 头注容量行：'#   容量(inference/vllm-ascend): interrupt=36/30, ...'"""
    caps = {}
    for line in text.splitlines():
        m = re.match(r"#\s*容量\(([^)]+)\):\s*(.*)$", line.strip())
        if not m:
            continue
        ns = m.group(1)
        cells = {}
        for part in m.group(2).split(","):
            cm = re.match(r"\s*(\w+)=(\d+)/(\d+)", part)
            if cm:
                cells[cm.group(1)] = {"count": int(cm.group(2)), "cap": int(cm.group(3))}
        if cells:
            caps[ns] = cells
    return caps


# EV 卡状态词表 v5（schema 校验源：scripts/verify_proposals.py VALID_STATUS）。
# 面板旧版曾按 v1 词表（candidate/proposed/pending_merge/adopted/rolled_back）分组——
# 那些状态在 v5 下永不出现，而 rejected/superseded 从未被渲染。词表以校验器为准，不各自维护。
VALID_STATUS = ("in_experiment", "validated", "rejected", "superseded")
TERMINAL_STATUS = ("validated", "rejected", "superseded")
# 卡龄超过该天数仍未闭合 → 标 stale（面板"待办优先"条据此提示）
STALE_DAYS = 14

PR_RE = re.compile(r"(?:PR|#)\s?#?(\d{2,6})")


def extract_pr_refs(text):
    """从卡文本里抽 PR/issue 号（决策链里常写「随 PR #97 供人审」）。"""
    if not text:
        return []
    out = []
    for m in PR_RE.finditer(str(text)):
        n = m.group(1)
        if n not in out:
            out.append(n)
    return out[:5]


def days_since(value):
    """created_at（date/datetime/str）→ 距今天数；无法解析返回 None。"""
    if value is None:
        return None
    if hasattr(value, "timetuple"):
        d = value
    else:
        s = str(value).strip()[:10]
        try:
            d = datetime.date.fromisoformat(s)
        except ValueError:
            return None
    return (datetime.date.today() - datetime.date(d.year, d.month, d.day)).days


def compact_decisions(decisions):
    """决策链瘦身：完整结论留给 detail RPC，列表页只带前 60 字摘要。"""
    out = []
    for x in decisions or []:
        if not isinstance(x, dict):
            continue
        concl = str(x.get("conclusion") or "")
        out.append({
            "who": x.get("who"),
            "when": x.get("when"),
            "type": x.get("type"),
            "summary": concl[:60],
            "length": len(concl),
        })
    return out


def full_decisions(decisions):
    out = []
    for x in decisions or []:
        if not isinstance(x, dict):
            continue
        out.append({
            "who": x.get("who"),
            "when": x.get("when"),
            "type": x.get("type"),
            "conclusion": x.get("conclusion"),
        })
    return out


def audit_gaps(doc, days_open):
    """卡自审：机制要求 vs 实际字段的缺口（诚实退化——面板报出来，不粉饰）。

    依据 docs/mechanism/pipeline.md §7「生命周期完整性规则」与 verify_proposals.py：
      - 终态卡必须有 decision 记录（审计缺口）
      - validated 卡 actual_cost 必填（成本审计缺口）
      - 执行/验证完成而卡停在 in_experiment = 卡不完整（机制推进，不靠 agent 记得改状态）
    """
    gaps = []
    status = doc.get("status")
    decisions = doc.get("decisions") or []
    types = [x.get("type") for x in decisions if isinstance(x, dict)]

    if status in TERMINAL_STATUS and "decision" not in types:
        gaps.append({"kind": "no_decision", "text": "终态卡缺 decision 记录（审计缺口）"})

    if status == "validated":
        ac = doc.get("actual_cost")
        tokens = ac.get("tokens") if isinstance(ac, dict) else None
        if tokens is None:
            gaps.append({"kind": "no_cost", "text": "validated 卡 actual_cost 未写回（成本审计缺口）"})

    if status == "in_experiment" and "decision" in types:
        gaps.append({"kind": "status_lag", "text": "已记 decision 但状态仍 in_experiment（状态未推进）"})

    if status == "in_experiment" and days_open is not None and days_open >= STALE_DAYS:
        gaps.append({"kind": "stale", "text": f"在实验 {days_open} 天未闭合（超 {STALE_DAYS} 天）"})

    return gaps


def collect_ideas(root):
    ideas = []
    for f in sorted((root / "proposals" / "ideas").glob("*.yaml")):
        d = load_yaml(f)
        if not isinstance(d, dict) or "__error__" in d:
            ideas.append({"file": f.name, "error": d.get("__error__", "解析失败")})
            continue
        days_open = days_since(d.get("created_at"))
        decisions = d.get("decisions") or []
        # 决策链全文参与 PR 号提取（「随 PR #97 供人审」这类追溯指针只在结论里）
        blob = " ".join(str(x.get("conclusion") or "") for x in decisions if isinstance(x, dict))
        validation = d.get("validation") or {}
        ideas.append({
            "id": d.get("id"),
            "title": d.get("title"),
            "layer": d.get("layer"),
            "status": d.get("status"),
            "authorization": d.get("authorization"),
            "dimension": d.get("dimension"),
            "risk": d.get("risk"),
            "principle_refs": d.get("principle_refs") or [],
            # 触发信号：signal 名 + 证据一句话（面板列表页够用；完整 trajectory 进 detail）
            "source_signals": [
                {
                    "signal": s.get("signal"),
                    "evidence": s.get("evidence"),
                    "trajectory": s.get("trajectory") or [],
                }
                for s in (d.get("source_signals") or [])[:3] if isinstance(s, dict)
            ],
            "hypothesis": d.get("hypothesis"),
            "predicted_effect": d.get("predicted_effect"),
            "validation": {
                "method": validation.get("method"),
                "success_criteria": validation.get("success_criteria"),
                "baseline": validation.get("baseline"),
            },
            "gate": (d.get("gate") or {}).get("condition") if isinstance(d.get("gate"), dict) else d.get("gate"),
            "actual_cost": d.get("actual_cost"),
            "estimated_cost": d.get("estimated_cost"),
            "decisions": compact_decisions(decisions),
            "decision_count": len(decisions),
            "created_at": d.get("created_at"),
            "days_open": days_open,
            "pr_refs": extract_pr_refs(blob),
            "supersedes": d.get("supersedes") or [],
            "superseded_by": d.get("superseded_by"),
            # 派生：面板"待办优先"与自审用
            "gaps": audit_gaps(d, days_open),
            "file": f.name,
        })
    return ideas


def collect_idea_detail(root, idea_id):
    """单卡全文（点开才拉）：完整决策链 + 验证标准 + 证据轨迹 + 门控。"""
    for f in sorted((root / "proposals" / "ideas").glob("*.yaml")):
        d = load_yaml(f)
        if not isinstance(d, dict) or "__error__" in d or d.get("id") != idea_id:
            continue
        validation = d.get("validation") or {}
        return {
            "id": d.get("id"),
            "title": d.get("title"),
            "status": d.get("status"),
            "layer": d.get("layer"),
            "authorization": d.get("authorization"),
            "dimension": d.get("dimension"),
            "risk": d.get("risk"),
            "created_at": d.get("created_at"),
            "hypothesis": d.get("hypothesis"),
            "predicted_effect": d.get("predicted_effect"),
            "validation": {
                "method": validation.get("method"),
                "baseline": validation.get("baseline"),
                "success_criteria": validation.get("success_criteria"),
                "rollback": validation.get("rollback"),
            },
            "gate": d.get("gate"),
            "actual_cost": d.get("actual_cost"),
            "estimated_cost": d.get("estimated_cost"),
            "principle_refs": d.get("principle_refs") or [],
            "source_signals": d.get("source_signals") or [],
            "decisions": full_decisions(d.get("decisions")),
            "supersedes": d.get("supersedes") or [],
            "superseded_by": d.get("superseded_by"),
            "file": f.name,
        }
    return None


def collect_stats(ideas):
    """自演进度量：面板首屏"系统最近做了什么"用（比"一共几张卡"有意义）。"""
    ok = [c for c in ideas if c.get("id")]
    total = len(ok)
    by_status = {}
    for c in ok:
        st = c.get("status") or "unknown"
        by_status[st] = by_status.get(st, 0) + 1

    adopted = by_status.get("validated", 0)
    terminal = sum(by_status.get(s, 0) for s in TERMINAL_STATUS)
    # 采纳率只在终态卡上算（in_experiment 未判决，分母不含）
    adoption_rate = round(adopted / terminal, 3) if terminal else None

    by_method = {}
    for c in ok:
        m = ((c.get("validation") or {}).get("method")) or "未标"
        by_method[m] = by_method.get(m, 0) + 1

    by_signal = {}
    for c in ok:
        for s in c.get("source_signals") or []:
            name = (s or {}).get("signal")
            if name:
                by_signal[name] = by_signal.get(name, 0) + 1

    costs = []
    for c in ok:
        ac = c.get("actual_cost")
        t = ac.get("tokens") if isinstance(ac, dict) else None
        if isinstance(t, (int, float)):
            costs.append(t)

    open_days = [c["days_open"] for c in ok if isinstance(c.get("days_open"), int)]
    gap_cards = [c for c in ok if c.get("gaps")]
    stale = [c for c in ok if c.get("status") == "in_experiment" and isinstance(c.get("days_open"), int)
             and c["days_open"] >= STALE_DAYS]

    return {
        "total": total,
        "by_status": by_status,
        "adoption_rate": adoption_rate,
        "terminal_count": terminal,
        "by_method": by_method,
        "by_signal": by_signal,
        "cost_total": sum(costs) if costs else None,
        "cost_median": sorted(costs)[len(costs) // 2] if costs else None,
        "cost_cards": len(costs),
        "oldest_open_days": max(open_days) if open_days else None,
        "gap_count": len(gap_cards),
        "gap_cards": [c["id"] for c in gap_cards],
        "stale_count": len(stale),
        "stale_cards": [c["id"] for c in stale],
    }


def collect_skill_exec(root):
    """统一执行记录（exec-log）——让面板看得见 evolve-check 是否真的在收尾运行。

    为什么需要这一格（2026-09-10 审计）：exec-log 先前只被 evolve-check 第 1 步读，
    面板与 metrics 都不看它，于是"收尾跑了但无信号"与"根本没跑"在数据上完全不可区分——
    机制是否在运作无法证伪。解析复用 scripts/tail_exec_log.py（单一事实源：datetime
    归一 / 文件缺失退化只在一处实现，防两处漂移）。

    语义边界（2026-09-10 修）：exec-log 从"各 worktree 各持一份的检出内文件"改为
    **同一克隆共享**（主检出 metrics/，见 scripts/exec_log_path.py）——从此代理在任意
    worktree 收尾落的记录，本面板（读用户会话的 cwd）就能看到，且 worktree 清理不再
    丢数据。仍不假装的部分：**跨克隆/跨机不聚合**；共享件是 read-modify-write，
    写侧持锁（并发实测：无锁 16 次写入只剩 3 条）。note/sharing 字段随数据一起递给
    面板，防把本地读数误读成全系统读数。
    """
    try:
        import tail_exec_log
    except Exception as e:  # 不该发生；如实标注而非伪造数据
        return {"present": False, "state": "unavailable", "note": f"tail_exec_log 不可用: {e}",
                "total": 0, "recent": [], "evolve_check_runs": 0, "last_evolve_check": None,
                "by_skill": {}}
    records, state, path, where = tail_exec_log.load_records(root)
    rows = [tail_exec_log.summarize(r) for r in records if isinstance(r, dict)]
    ev = [r for r in rows if r["skill"] == "evolve-check"]
    by_skill = {}
    for r in rows:
        by_skill[r["skill"]] = by_skill.get(r["skill"], 0) + 1
    # 无信号收尾也落记录（products 为空 + reason 含"无演进信号"）——单独计数，
    # 这样"跑了且无信号"是可观测的，而不是消失在沉默里。
    no_signal = [r for r in ev if not r["products"] and "无演进信号" in r["decision_reason"]]
    return {
        "present": state == "ok",
        "state": state,
        "note": tail_exec_log.describe(path, where),
        "path": str(path),
        "where": where,
        "aggregate": tail_exec_log.aggregate(rows),
        "total": len(rows),
        "recent": rows[-5:],
        "by_skill": by_skill,
        "evolve_check_runs": len(ev),
        "evolve_check_no_signal": len(no_signal),
        "last_evolve_check": ev[-1] if ev else None,
    }


def collect_timeline(root):
    """只取每期标题/kind/关键指标（路由准确率/候选召回等），供趋势 sparkline。"""
    path = root / "metrics" / "timeline.yaml"
    if not path.exists():
        return []
    d = load_yaml(path)
    if not isinstance(d, dict):
        return []
    out = []
    for p in d.get("periods") or []:
        m = p.get("metrics") or {}
        row = {
            "period": p.get("period"),
            "kind": p.get("kind"),
            "title": (p.get("title") or "")[:60],
        }
        for k in ("routed_accuracy", "candidate_recall", "golden_suite"):
            if k in m:
                v = m[k]
                row[k] = v if not isinstance(v, dict) else v.get("ok", v)
        out.append(row)
    return out


def collect_tally(root):
    """归因事件按需聚合（2026-09 重构：无常驻 metrics/component-tally.yaml 表——
    从 trace attribution + s2 候选现聚合，语义同 component_tally.py）。"""
    # 复用 component_tally 的聚合逻辑（同仓库脚本，直接导入避免双源漂移）
    import component_tally
    entries = component_tally.scan_traces(root) + component_tally.scan_replay_attributions(root)
    if not entries:
        return []
    agg = component_tally.aggregate(entries)
    return [
        {"id": comp, **v, "traces": sorted(v["traces"])}
        for comp, v in sorted(agg.items(), key=lambda x: -(x[1]["trace_mis"] + x[1]["s2_candidate"]))
    ]


def collect_s2_attrib(root):
    path = root / ".s2-replay" / "attributions.yaml"
    if not path.exists():
        return None
    d = load_yaml(path)
    return d.get("attributions") if isinstance(d, dict) else None


def main():
    ap = argparse.ArgumentParser(description="自演进看板数据汇总")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--detail", metavar="EV-YYYY-NNN",
                    help="只输出该卡的全文（面板点开时按需拉取，避免列表页背全文）")
    args = ap.parse_args()
    root = args.root.resolve()

    # 单卡全文模式：面板 host 的 ev-idea-detail RPC 走这条路
    if args.detail:
        detail = collect_idea_detail(root, args.detail)
        if detail is None:
            print(json.dumps({"ok": False, "error": "未找到卡 " + args.detail}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, "idea": detail}, ensure_ascii=False, default=str))
        return 0

    ideas = collect_ideas(root)
    timeline = collect_timeline(root)
    index_path = root / "knowledge" / "_index.yaml"
    capacity = parse_index_header(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    tally = collect_tally(root)
    s2_attrib = collect_s2_attrib(root)
    skill_exec = collect_skill_exec(root)

    # 卡状态机分布（词表以 verify_proposals 为准；unknown 说明卡有 schema 问题）
    status_count = {}
    for c in ideas:
        st = c.get("status") or "unknown"
        status_count[st] = status_count.get(st, 0) + 1

    payload = {
        "ideas": ideas,
        "idea_count": len(ideas),
        "status_count": status_count,
        "stats": collect_stats(ideas),
        "timeline": timeline,
        "capacity": capacity,
        "tally": tally,
        "s2_attrib": s2_attrib,
        "skill_exec": skill_exec,
        "stale_days": STALE_DAYS,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    print(json.dumps(payload, ensure_ascii=False, default=str))


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main() or 0)
