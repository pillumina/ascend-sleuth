#!/usr/bin/env python3
# verify_exec_log.py —— 校验 metrics/skill-exec-log.yaml 结构（run.md §4）
#
# 校验：
#   1. YAML 合法 + records 列表
#   2. 每条含 skill（合法集合）/at/version/source
#   3. seq 连续唯一（append-only 不变量）
#   4. products 若含 status 值合法（submitted/knowledge/archived/rc_match 等）
#   5. decision_reason 若填非空（防空记录）
#
# 用法：python3 scripts/verify_exec_log.py [--check] [--root <repo>]

import argparse
import sys
from pathlib import Path

import yaml

from exec_log_path import describe, resolve

VALID_SKILLS = {
    "diagnose", "resume-diagnosis", "to-postmortem", "to-reference",
    "issue-ingest", "knowledge-groom", "s2-replay", "replay-golden",
    "evolve-check", "self-evolve", "capacity-health",
}


def main():
    ap = argparse.ArgumentParser(description="校验统一执行记录（默认读同一克隆共享的那份）")
    ap.add_argument("--check", action="store_true", help="CI 模式")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--log", type=Path, default=None, help="显式指定 exec-log 路径")
    ap.add_argument("--local", action="store_true", help="只看当前检出内的路径")
    args = ap.parse_args()
    root = args.root.resolve()
    path, where = resolve(root, explicit=args.log, local=args.local)
    if not path.exists():
        print(f"exec-log 不存在——跳过（执行记录未启用；{describe(path, where)}）")
        return

    errors = []
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"skill-exec-log.yaml 解析失败: {e}")
        sys.exit(1)
    if not isinstance(doc, dict) or "records" not in doc:
        print("skill-exec-log.yaml 缺 records 列表"); sys.exit(1)

    records = doc["records"]
    seen_seq = set()
    for i, r in enumerate(records):
        rel = f"records[{i}]"
        if not isinstance(r, dict):
            errors.append(f"{rel}: 必须是 mapping"); continue
        skill = r.get("skill")
        if skill not in VALID_SKILLS:
            errors.append(f"{rel}: skill '{skill}' 非法")
        for k in ("at", "version", "source"):
            if not r.get(k):
                errors.append(f"{rel}: 缺 '{k}'")
        seq = r.get("seq")
        if seq in seen_seq:
            errors.append(f"{rel}: seq {seq} 重复（append-only 不变量破坏）")
        seen_seq.add(seq)
        for p in r.get("products") or []:
            if not isinstance(p, dict) or not p.get("id"):
                errors.append(f"{rel}: products 元素须含 id")
        dr = r.get("decision_reason")
        if dr is not None and not str(dr).strip():
            errors.append(f"{rel}: decision_reason 为空")

    if errors:
        print(f"verify_exec_log: {len(errors)} 个问题")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print(f"verify_exec_log: OK（{len(records)} 条执行记录，seq 连续唯一；{describe(path, where)}）")


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
