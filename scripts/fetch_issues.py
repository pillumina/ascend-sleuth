#!/usr/bin/env python3
"""fetch_issues.py —— 从 GitHub 拉取 issue 元数据缓存（精简字段，不含 body）

设计（与 issue_filter.py 配套，见 docs/issue-ingest-pipeline.md）：
  - 只拉元数据（number/title/comments/closed_at/labels/state_reason），**不含 body**——
    body 是最大字段，评估候选时才按需单条取（gh api issues/<n>），拉取本身不占 context
  - 拉取是无状态动作，结果即缓存（JSON），后续 issue_filter.py 做硬过滤
  - 仅支持 GitHub（gh 已认证）；其他源（GitCode 等）用 agent 现成工具拉取

用法：
  python3 scripts/fetch_issues.py --repo vllm-project/vllm-ascend --state closed \
    --labels triaged --since 2026-08-27T00:00:00Z --output /tmp/issues.json
"""
import argparse
import json
import subprocess
import sys


def gh_api(url: str) -> list:
    """gh api --paginate：对返回数组的 API 自动合并所有页为一个大数组"""
    out = subprocess.run(
        ["gh", "api", url, "--paginate"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(out.stdout)


def slim(item: dict) -> dict:
    """只保留评估所需的元数据字段（不含 body——body 按需单条取）"""
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "comments": item.get("comments"),
        "closed_at": item.get("closed_at"),
        "state_reason": item.get("state_reason"),
        "labels": [l.get("name") for l in (item.get("labels") or [])],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default="vllm-project/vllm-ascend")
    ap.add_argument("--state", default="closed", choices=["open", "closed", "all"])
    ap.add_argument("--labels", help="逗号分隔，匹配含任一 label 的 issue（如 bug,triaged）")
    ap.add_argument("--since", help="ISO 时间，只拉该时间后更新的 issue（增量游标）")
    ap.add_argument("--output", required=True, help="缓存 JSON 输出路径")
    args = ap.parse_args()

    url = f"repos/{args.repo}/issues?state={args.state}&per_page=100"
    if args.labels:
        url += f"&labels={args.labels}"
    if args.since:
        url += f"&since={args.since}"

    items = gh_api(url)
    issues = [slim(it) for it in items if "pull_request" not in it]

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)
    print(f"拉取 {len(issues)} 条 issue（不含 PR）→ {args.output}")


if __name__ == "__main__":
    main()
