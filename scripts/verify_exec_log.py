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
import re
import sys
from pathlib import Path

import yaml

from exec_log_path import describe, resolve
from log_skill_exec import git_head

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
    try:
        head_now = git_head(root)          # 能解析到 HEAD 时，"version: unknown" 就是漏填而非环境所限
    except Exception:
        head_now = "unknown"
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
        # at 必须是 ISO 字符串：PyYAML 把未加引号的时间读成 datetime —— 同一字段两种形态，
        # 且下游切片/比较会直接炸。写侧已加引号；这里把"又漂回去"的情况拦住。
        at = r.get("at")
        if at is not None and not isinstance(at, str):
            errors.append(f"{rel}: at 不是字符串（{type(at).__name__}）——写侧漏了引号，时间会被 YAML 读成 datetime")
        elif isinstance(at, str) and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", at):
            errors.append(f"{rel}: at 不是 ISO 形态（'{at}'），应为 YYYY-MM-DDTHH:MM:SS")
        # version: 有 git 信息却记成 unknown = 审计链丢栏（实测踩过：git 不在 PATH）
        if r.get("version") == "unknown" and head_now != "unknown":
            errors.append(f"{rel}: version 记成 unknown，但本检出能解析到 HEAD={head_now}——写侧退化路径没生效")
        seq = r.get("seq")
        if seq in seen_seq:
            errors.append(f"{rel}: seq {seq} 重复（append-only 不变量破坏）")
        seen_seq.add(seq)
        for p in r.get("products") or []:
            if not isinstance(p, dict) or not p.get("id"):
                errors.append(f"{rel}: products 元素须含 id")
                continue
            # id 里出现括号/逗号 = 十有八九被 `--products "id(a,b)"` 的逗号 split 撕裂过
            # （实测：一条产物被写成两条 `id(in_progress` / `no_hit)`）。这正是校验该拦的形态。
            if any(ch in str(p["id"]) for ch in "(),"):
                errors.append(f"{rel}: products id「{p['id']}」含括号或逗号——疑似被 --products 逗号切分撕裂")
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
