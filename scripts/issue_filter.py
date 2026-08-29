#!/usr/bin/env python3
# issue_filter.py —— 从 issue 拉取缓存中做硬过滤（纯本地，不碰网络/认证）
#
# 设计（docs/issue-ingest-pipeline.md）：
#   - 拉取由 scripts/fetch_issues.py（GitHub 专用，精简字段）或 agent 现成工具
#     （GitCode 等）完成；拉取是无状态动作，结果即缓存
#   - 硬过滤脚本化：已处理编号排除、label 池、评论数门槛、标题规则——
#     可复现、可审计、跨框架/平台复用（换源只换缓存输入）
#   - 启发式排序（label 优先级 / state_reason / 评论数）零 token——价值评估
#     （读 body 判断可否沉淀）仍留给 subagent，本脚本不判断语义
#   - --mark-imported：沉淀完成后把编号追加 processed（幂等，防重复导入）
#
# 用法：
#   python3 scripts/issue_filter.py --cached <缓存.json> \
#     --state ingest-state.json --source "github/vllm-project/vllm-ascend" \
#     [--labels triaged] [--min-comments 3] [--limit 50] [--report <候选.json>]
#   python3 scripts/issue_filter.py --cached <缓存> --state ingest-state.json \
#     --source ... --mark-imported 12345,12346

import argparse
import json
import sys
from pathlib import Path

# 标题硬排除规则（框架无关的低价值形态）
SKIP_TITLE_PATTERNS = [
    "[feature", "[doc", "[question", "[usage", "[install",
    "how to", "howto", "support request", "help needed",
]

# label 优先级（启发式排序用）：triaged=维护者确认过，最高
LABEL_PRIORITY = {"triaged": 3, "bug": 2}


def is_issue(item: dict) -> bool:
    """排除 pull_request（REST 返回里带 pull_request 字段的是 PR）"""
    return "pull_request" not in item


def title_skippable(title: str) -> bool:
    t = (title or "").lower()
    return any(p in t for p in SKIP_TITLE_PATTERNS)


def has_label(item: dict, labels: list) -> bool:
    item_labels = {l.get("name", l) if isinstance(l, dict) else l for l in item.get("labels", [])}
    return any(l in item_labels for l in labels)


def heuristic_key(it: dict):
    """启发式排序键（零 token）：label 优先级 > state_reason=completed > 评论数"""
    labels = {l.get("name", l) if isinstance(l, dict) else l for l in it.get("labels", [])}
    label_score = max((LABEL_PRIORITY.get(l, 0) for l in labels), default=0)
    resolved = 1 if it.get("state_reason") == "completed" else 0
    return (label_score, resolved, it.get("comments") or 0)


def load_state(path: Path) -> dict:
    return json.load(open(path, encoding="utf-8")) if path.exists() else {"sources": {}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cached", help="拉取缓存 JSON（列表或页列表）")
    ap.add_argument("--state", required=True, help="ingest-state.json 路径")
    ap.add_argument("--source", required=True, help="source 键，如 github/vllm-project/vllm-ascend")
    ap.add_argument("--labels", help="逗号分隔，候选必须含任一 label（如 bug,triaged）")
    ap.add_argument("--min-comments", type=int, default=3, help="最少评论数（有排查过程的信号）")
    ap.add_argument("--limit", type=int, default=50, help="候选数量上限")
    ap.add_argument("--report", help="候选列表写 JSON（管道产物，供评估阶段消费）")
    ap.add_argument("--mark-imported", help="逗号分隔的 issue 编号：沉淀完成后追加 processed（幂等）")
    args = ap.parse_args()

    state_path = Path(args.state)
    state = load_state(state_path)
    src = state.setdefault("sources", {}).setdefault(args.source, {})
    processed = set(src.get("processed", []))

    # 纯标记模式：不读缓存，只追加已导入编号
    if args.mark_imported:
        nums = [int(n) for n in args.mark_imported.split(",") if n.strip()]
        before = len(processed)
        processed.update(nums)
        src["processed"] = sorted(processed)
        json.dump(state, open(state_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"标记 {len(nums)} 条已导入（{before} → {len(processed)}）→ {state_path}")
        return

    if not args.cached:
        ap.error("--cached 或 --mark-imported 至少提供一个")

    raw = json.load(open(args.cached, encoding="utf-8"))
    if raw and isinstance(raw[0], list):
        items = [it for page in raw for it in page]
    else:
        items = raw

    issues = [it for it in items if is_issue(it)]
    print(f"缓存共 {len(issues)} 条 issue（已排除 PR）")

    want_labels = [l.strip() for l in (args.labels or "").split(",") if l.strip()]

    # 硬过滤（保持缓存顺序，候选按启发式排序）
    candidates = []
    excluded = {"processed": [], "no_label": [], "low_comments": [], "title": []}
    for it in issues:
        n = it["number"]
        if n in processed:
            excluded["processed"].append(n)
            continue
        if want_labels and not has_label(it, want_labels):
            excluded["no_label"].append(n)
            continue
        if (it.get("comments") or 0) < args.min_comments:
            excluded["low_comments"].append(n)
            continue
        if title_skippable(it.get("title", "")):
            excluded["title"].append(n)
            continue
        candidates.append(it)

    candidates.sort(key=heuristic_key, reverse=True)
    candidates = candidates[: args.limit]

    print(f"候选 {len(candidates)} 条（上限 {args.limit}，按 label 优先级/已解决/评论数排序）")
    print(
        f"已排除：已处理 {len(excluded['processed'])} / label 不匹配 {len(excluded['no_label'])}"
        f" / 评论少 {len(excluded['low_comments'])} / 标题规则 {len(excluded['title'])}"
    )
    for it in candidates:
        labels = ",".join(l.get("name", l) if isinstance(l, dict) else l for l in it.get("labels", []))
        print(f"  #{it['number']} [{it.get('comments', 0)}评论][{labels}] {it['title'][:60]}")

    if args.report:
        json.dump(candidates, open(args.report, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"候选已写 → {args.report}")

    # 更新游标（拉取见过的最新/最旧 closed 时间，供增量参考；不自动改 processed）
    closes = sorted(it.get("closed_at") for it in issues if it.get("closed_at"))
    if closes:
        src["last_fetch_latest_closed"] = closes[-1]
        src["last_fetch_oldest_closed"] = closes[0]
        json.dump(state, open(state_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"游标已更新 → {state_path}")


if __name__ == "__main__":
    main()
