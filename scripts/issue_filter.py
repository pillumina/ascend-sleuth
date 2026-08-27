#!/usr/bin/env python3
# issue_filter.py —— 从 issue 拉取缓存中做硬过滤（纯本地，不碰网络/认证）
#
# 设计（docs 讨论结论）：
#   - 拉取靠 agent 现成工具（gh api / curl / GitCode CLI），不脚本化——
#     避免维护多平台认证；拉取是无状态动作，结果即缓存
#   - 硬过滤脚本化：已处理编号排除、评论数门槛、标题规则——
#     可复现、可审计、跨框架/平台复用（换源只换缓存输入）
#   - 价值评估（四门槛+评分）留给 subagent，本脚本不判断语义
#
# 用法：
#   python3 scripts/issue_filter.py --cached <缓存.json> \
#     --state ingest-state.json --source "github/vllm-project/vllm-ascend" \
#     [--min-comments 3] [--limit 50]
#
# 缓存格式：gh api 分页输出的 JSON 列表，或合并后的 issue 列表（含 number/title/comments/closed_at/labels）

import argparse
import json
import sys
from pathlib import Path

# 标题硬排除规则（框架无关的低价值形态）
SKIP_TITLE_PATTERNS = [
    "[feature", "[docs", "[question", "[usage", "[install",
    "how to", "howto", "support request", "help needed",
]


def is_issue(item: dict) -> bool:
    """排除 pull_request（REST 返回里带 pull_request 字段的是 PR）"""
    return "pull_request" not in item


def title_skippable(title: str) -> bool:
    t = (title or "").lower()
    return any(p in t for p in SKIP_TITLE_PATTERNS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cached", required=True, help="拉取缓存 JSON（列表或页列表）")
    ap.add_argument("--state", required=True, help="ingest-state.json 路径")
    ap.add_argument("--source", required=True, help="source 键，如 github/vllm-project/vllm-ascend")
    ap.add_argument("--min-comments", type=int, default=3, help="最少评论数（有排查过程的信号）")
    ap.add_argument("--limit", type=int, default=50, help="候选数量上限")
    ap.add_argument("--write-state", action="store_true", help="将已排除编号写入状态文件")
    args = ap.parse_args()

    # 读缓存：兼容单列表或分页列表（list[list]）
    raw = json.load(open(args.cached, encoding="utf-8"))
    if raw and isinstance(raw[0], list):
        items = [it for page in raw for it in page]
    else:
        items = raw

    # 读状态
    state_path = Path(args.state)
    state = json.load(open(state_path, encoding="utf-8")) if state_path.exists() else {"sources": {}}
    src = state.setdefault("sources", {}).setdefault(args.source, {})
    processed = set(src.get("processed", []))

    issues = [it for it in items if is_issue(it)]
    print(f"缓存共 {len(issues)} 条 issue（已排除 PR）")

    # 按关闭时间倒序（最新的优先）
    issues.sort(key=lambda it: it.get("closed_at") or "", reverse=True)

    # 硬过滤
    candidates = []
    excluded = {"processed": [], "low_comments": [], "title": []}
    for it in issues:
        n = it["number"]
        if n in processed:
            excluded["processed"].append(n)
            continue
        if (it.get("comments") or 0) < args.min_comments:
            excluded["low_comments"].append(n)
            continue
        if title_skippable(it.get("title", "")):
            excluded["title"].append(n)
            continue
        candidates.append(it)
        if len(candidates) >= args.limit:
            break

    print(f"候选 {len(candidates)} 条（上限 {args.limit}）")
    print(f"已排除：已处理 {len(excluded['processed'])} / 评论少 {len(excluded['low_comments'])} / 标题规则 {len(excluded['title'])}")
    for it in candidates:
        print(f"  #{it['number']} [{it.get('comments', 0)}评论] {it['title'][:60]}")

    # 更新状态：把候选里被排除的（非候选）已处理编号以外的……仅记录拉取过的最早 closed_at 作为下次游标参考
    if args.write_state:
        # 记录本次拉取见过的最新/最旧时间（供下次增量参考），不自动改 processed
        closes = [it.get("closed_at") for it in issues if it.get("closed_at")]
        if closes:
            src["last_fetch_latest_closed"] = closes[0]
            src["last_fetch_oldest_closed"] = closes[-1]
        json.dump(state, open(state_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"状态已更新 → {state_path}")


if __name__ == "__main__":
    main()
