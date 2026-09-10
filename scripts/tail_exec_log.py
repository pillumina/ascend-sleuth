#!/usr/bin/env python3
# tail_exec_log.py —— 读「本轮执行现场」（统一执行记录尾部）的确定性入口
#
# 为什么必须是脚本（原则二：不变量写进结构）：
#   evolve-check 第 1 步原先在 SKILL.md 内联一段 `python3 -c "..."`，2026-09-10 实测两种
#   环境都跑不通——
#     ① 有记录时：`log_skill_exec.py` 写的是 ISO 时间戳，PyYAML 把 `at` 解析成
#        datetime 对象，`r.get('at','')[:16]` 抛 TypeError（不是 str，不可下标）；
#     ② 无记录时：`metrics/skill-exec-log.yaml` 是 .gitignore 运行时件，worktree / 新克隆
#        里不存在，`open()` 抛 FileNotFoundError。
#   协议第一步的取数入口靠 agent 现场改命令 = 每次收尾都是一次非确定性重写（原则九）。
#
# 语义边界（诚实退化，原则十）：
#   - 文件不存在 / records 为空 = **正常退化路径**，不是错误：打印一行「无执行记录」并
#     exit 0，evolve-check 据此走 SKILL.md 明示的「如实标注，基于现场判断」分支；
#   - 这是**本地件**：exec-log 是逐次 append 流水、不入 git（见 CLAUDE.md「exec-log 归属」
#     与 .gitignore），跨 worktree / 跨克隆不聚合——输出里显式标注，防把空表误读成
#     「本轮没做事」，也防把本地 4 条误读成「全系统只跑了 4 次」。
#
# 用法：
#   python3 scripts/tail_exec_log.py                 # 尾部 3 条（人读；evolve-check 第 1 步）
#   python3 scripts/tail_exec_log.py --n 5           # 尾部 5 条
#   python3 scripts/tail_exec_log.py --skill evolve-check   # 只看某 skill（如收尾自落记录）
#   python3 scripts/tail_exec_log.py --json          # 机器读（面板 / 实验断言）
#   python3 scripts/tail_exec_log.py --root <repo>

import argparse
import json
import sys
from pathlib import Path

import yaml

LOG_PATH = "metrics/skill-exec-log.yaml"
LOCAL_NOTE = "本地件：跨 worktree/克隆不聚合（.gitignore 运行时件）"


def load_records(root: Path):
    """返回 (records, state)。state ∈ {ok, missing, broken, empty}——绝不抛异常。"""
    path = root / LOG_PATH
    if not path.exists():
        return [], "missing"
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return [], "broken"
    records = doc.get("records") if isinstance(doc, dict) else None
    if not isinstance(records, list):
        return [], "broken"
    if not records:
        return [], "empty"
    return records, "ok"


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


def main():
    ap = argparse.ArgumentParser(description="读统一执行记录尾部（evolve-check 第 1 步入口）")
    ap.add_argument("--n", type=int, default=3, help="取尾部几条（默认 3）")
    ap.add_argument("--skill", default="", help="只保留该 skill 的记录（如 evolve-check）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（面板/实验断言用）")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.root.resolve()

    records, state = load_records(root)
    picked = [summarize(r) for r in records if isinstance(r, dict)]
    if args.skill:
        picked = [r for r in picked if r["skill"] == args.skill]
    total_matched = len(picked)
    tail = picked[-max(args.n, 0):] if args.n else picked

    if args.json:
        print(json.dumps({
            "present": state == "ok",
            "state": state,
            "path": LOG_PATH,
            "note": LOCAL_NOTE,
            "total": len(records),
            "matched": total_matched,
            "records": tail,
        }, ensure_ascii=False))
        return 0

    if state != "ok":
        why = {"missing": "文件不存在", "empty": "records 为空", "broken": "解析失败/缺 records"}[state]
        print(f"exec-log: 无执行记录（{LOG_PATH}：{why}；{LOCAL_NOTE}）")
        print("→ 按 evolve-check 第 1 步退化分支：如实标注「无执行记录，基于现场判断」，不假装有数据。")
        return 0
    if not tail:
        print(f"exec-log: 无匹配记录（skill={args.skill}；共 {len(records)} 条；{LOCAL_NOTE}）")
        return 0

    print(f"exec-log 尾部 {len(tail)}/{total_matched} 条匹配（{LOG_PATH}；{LOCAL_NOTE}）：")
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
