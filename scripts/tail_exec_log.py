#!/usr/bin/env python3
# tail_exec_log.py —— 读「本轮执行现场」（统一执行记录尾部）的确定性入口
#
# 为什么必须是脚本（原则二：不变量写进结构）：
#   evolve-check 第 1 步原先在 SKILL.md 内联一段 `python3 -c "..."`，实测两种环境都跑不通——
#     ① 有记录时：`log_skill_exec.py` 写的是 ISO 时间戳，PyYAML 把 `at` 解析成 datetime
#        对象，`r.get('at','')[:16]` 抛 TypeError（不是 str，不可下标）；
#     ② 无记录时：文件不存在，`open()` 抛 FileNotFoundError。
#   协议第一步的取数入口靠 agent 现场改命令 = 每次收尾都是一次非确定性重写（原则九）。
#
# 路径语义（2026-09-10 起，见 scripts/exec_log_path.py 的完整理由）：
#   **同一克隆共享**——所有 worktree 共写共读主检出的 `metrics/skill-exec-log.yaml`。
#   修的是这样一个结构缺陷：本仓库强制每个 agent 在独立 worktree 工作，而记录原先写在
#   worktree 内、又是 .gitignore 件 → 代理落的记录**主检出（= 用户会话 cwd + 面板读处）
#   读不到**，且 worktree 一清记录随之消失。无 git 环境（沙箱/CI）退化为检出内路径。
#   边界（不假装）：**跨克隆/跨机不聚合**——那需要让聚合值（不是流水）进 git，见 --summary。
#
# 语义边界（诚实退化，原则十）：
#   文件不存在 / records 为空 = **正常退化路径**，不是错误：打印一行「无执行记录」并 exit 0，
#   evolve-check 据此走 SKILL.md 明示的「如实标注，基于现场判断」分支。
#
# 用法：
#   python3 scripts/tail_exec_log.py                 # 尾部 3 条（人读；evolve-check 第 1 步）
#   python3 scripts/tail_exec_log.py --n 5           # 尾部 5 条
#   python3 scripts/tail_exec_log.py --skill evolve-check   # 只看某 skill（如收尾自落记录）
#   python3 scripts/tail_exec_log.py --summary       # 聚合视图（按 skill 计数 + 无信号次数）
#                                                    # 供 groom/周更把**聚合值**写进 metrics/timeline.yaml
#   python3 scripts/tail_exec_log.py --json          # 机器读（面板 / 实验断言）
#   python3 scripts/tail_exec_log.py [--local | --log <path>] [--root <repo>]

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

from exec_log_path import describe, resolve


def load_records(root: Path, explicit: Path = None, local: bool = False):
    """返回 (records, state, path, where)。state ∈ {ok, missing, broken, empty}——绝不抛异常。"""
    path, where = resolve(root, explicit=explicit, local=local)
    if not path.exists():
        return [], "missing", path, where
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return [], "broken", path, where
    records = doc.get("records") if isinstance(doc, dict) else None
    if not isinstance(records, list):
        return [], "broken", path, where
    if not records:
        return [], "empty", path, where
    return records, "ok", path, where


def summarize(r: dict) -> dict:
    """抽 evolve-check 需要的叶子字段；`at` 一律 str 化（YAML 可能给 datetime/date）。"""
    products = r.get("products") or []
    ids = []
    for p in products:
        if isinstance(p, dict):
            pid = str(p.get("id", ""))
            st = p.get("status")
            ids.append(f"{pid}({st})" if st else pid)
    return {
        "seq": r.get("seq"),
        "skill": r.get("skill"),
        "at": str(r.get("at", "")),          # ← 关键：datetime → str，不再是不可下标对象
        "source": r.get("source"),
        "ref": r.get("ref"),
        "products": ids,
        "decision_reason": str(r.get("decision_reason", "")),
    }


def aggregate(rows: list) -> dict:
    """聚合视图：跨 worktree 的**过程侧**度量（内容流程跑了几次、evolve-check 收尾几次、
    其中几次无信号）。这是"聚合值进 timeline"那条设计承诺的取数口——流水留在本地共享件，
    聚合值由 groom/周更写进 metrics/timeline.yaml（数据量不足时不建指标，原则十一）。"""
    by_skill = Counter(r["skill"] for r in rows)
    ev = [r for r in rows if r["skill"] == "evolve-check"]
    no_signal = [r for r in ev if not r["products"] and "无演进信号" in r["decision_reason"]]
    ats = [r["at"] for r in rows if r["at"]]
    return {
        "total": len(rows),
        "by_skill": dict(sorted(by_skill.items(), key=lambda kv: -kv[1])),
        "evolve_check_runs": len(ev),
        "evolve_check_no_signal": len(no_signal),
        "first_at": min(ats) if ats else None,
        "last_at": max(ats) if ats else None,
    }


def main():
    ap = argparse.ArgumentParser(description="读统一执行记录（evolve-check 第 1 步入口）")
    ap.add_argument("--n", type=int, default=3, help="取尾部几条（默认 3）")
    ap.add_argument("--skill", default="", help="只保留该 skill 的记录（如 evolve-check）")
    ap.add_argument("--summary", action="store_true", help="输出聚合视图（按 skill 计数/无信号次数）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（面板/实验断言用）")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--log", type=Path, default=None, help="显式指定 exec-log 路径")
    ap.add_argument("--local", action="store_true", help="强制读写当前检出内的路径（隔离测试/演练）")
    args = ap.parse_args()
    root = args.root.resolve()

    records, state, path, where = load_records(root, explicit=args.log, local=args.local)
    picked = [summarize(r) for r in records if isinstance(r, dict)]
    if args.skill:
        picked = [r for r in picked if r["skill"] == args.skill]
    total_matched = len(picked)
    tail = picked[-max(args.n, 0):] if args.n else picked
    agg = aggregate(picked)

    if args.json:
        print(json.dumps({
            "present": state == "ok",
            "state": state,
            "path": str(path),
            "where": where,
            "sharing": describe(path, where),
            "total": len(records),
            "matched": total_matched,
            "aggregate": agg,
            "records": tail,
        }, ensure_ascii=False))
        return 0

    if args.summary:
        if state != "ok":
            print(f"exec-log: 无记录可聚合（{path}；状态 {state}）")
            return 0
        print(f"exec-log 聚合（{describe(path, where)}）")
        print(f"  记录总数 {agg['total']} · 窗口 {agg['first_at'] or '—'} → {agg['last_at'] or '—'}")
        print("  按 skill：" + "、".join(f"{k}×{v}" for k, v in agg["by_skill"].items()))
        print(f"  evolve-check 收尾 {agg['evolve_check_runs']} 次，其中无信号 {agg['evolve_check_no_signal']} 次")
        print("  → 聚合值由 groom/周更写进 metrics/timeline.yaml（流水本身不进 git）")
        return 0

    if state != "ok":
        why = {"missing": "文件不存在", "empty": "records 为空", "broken": "解析失败/缺 records"}[state]
        print(f"exec-log: 无执行记录（{describe(path, where)}：{why}）")
        print("→ 按 evolve-check 第 1 步退化分支：如实标注「无执行记录，基于现场判断」，不假装有数据。")
        return 0
    if not tail:
        print(f"exec-log: 无匹配记录（skill={args.skill}；共 {len(records)} 条；{describe(path, where)}）")
        return 0

    print(f"exec-log 尾部 {len(tail)}/{total_matched} 条匹配（{describe(path, where)}）：")
    for r in tail:
        when = r["at"][:16].replace("T", " ")
        prod = "、".join(r["products"]) if r["products"] else "—"
        reason = r["decision_reason"][:60]
        print(f"  [{r['seq']}] {r['skill']:<16} {when}  产出 {prod}  ← {reason}")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
