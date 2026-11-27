#!/usr/bin/env python3
"""fetch_issues.py —— 从 GitHub 拉取 issue 元数据缓存（精简字段，不含 body）

设计（与 issue_filter.py 配套，见 docs/guide/issue-ingest-pipeline.md）：
  - 只拉元数据（number/title/comments/closed_at/labels/state_reason），**不含 body**——
    body 是最大字段，评估候选时才按需单条取（gh api issues/<n>），拉取本身不占 context
  - 拉取是无状态动作，结果即缓存（JSON），后续 issue_filter.py 做硬过滤
  - 两个源：GitHub 走 `gh api`；GitCode 走 GitCode CLI 的 `api`（`gitcode` 或 `gc`，
    登录态/环境 token 由 CLI 自己解析；未装或未登录时如实报错，不回落到网页）
  - 输出同一份缓存字段，issue_filter.py 不感知来源

用法：
  python3 scripts/fetch_issues.py --repo vllm-project/vllm-ascend --state closed \
    --labels triaged --since 2026-08-27T00:00:00Z --output /tmp/issues.json
  python3 scripts/fetch_issues.py --host gitcode --repo cann/ops-nn --state closed \
    --labels bug-report --output /tmp/ops-nn-issues.json
"""
import argparse
import json
import shutil
import subprocess
from _cli import main_entry


def gh_api(url: str) -> list:
    """gh api --paginate：对返回数组的 API 自动合并所有页为一个大数组"""
    out = subprocess.run(
        ["gh", "api", url, "--paginate"],
        capture_output=True, text=True, check=True,
        encoding="utf-8", errors="replace")
    return json.loads(out.stdout)


def _gitcode_bin() -> str:
    for name in ("gitcode", "gc"):
        if shutil.which(name):
            return name
    raise SystemExit(
        "GitCode 通道未就绪：没找到 gitcode / gc CLI。先装并登录——"
        "npx -y atomgit-cli@latest install，然后 gitcode auth login --web；"
        "已配 GITCODE_TOKEN 但没装 CLI 时，本脚本仍需要 CLI 作为 API 入口。")


def gitcode_api(path: str) -> list:
    """GitCode CLI 的 `api` 子命令：一次取一页，按 per_page 循环合并。

    GitCode 的字段与 GitHub 不同（number 是字符串、labels 是对象数组、没有
    state_reason、关闭时间在 finished_at），归一在 slim_gitcode() 里做。
    """
    bin_name = _gitcode_bin()
    items = []
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        paged = f"{path}{sep}page={page}" if "per_page=" in path else f"{path}{sep}per_page=100&page={page}"
        proc = subprocess.run([bin_name, "api", paged], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            msg = (proc.stderr or proc.stdout or "").strip().splitlines()
            tail = msg[-1] if msg else "无输出"
            code = proc.returncode
            if code == 3:
                hint = "仓库或条目不存在——核对 --repo 与编号，不是登录问题"
            elif code == 4:
                hint = ("未登录或 token 无效——跑 gitcode auth login --web，或更新 "
                        "GC_TOKEN / GITCODE_TOKEN；看 doctor 的 gitcode 项")
            elif code == 2:
                hint = "命令用法错误——核对 --repo / --labels / --since 的取值"
            else:
                hint = "API 或网络错误——看 stderr；不要据此认定「没有 issue」"
            raise SystemExit(f"GitCode CLI 调用失败（exit {code}）：{tail}；{hint}")
        try:
            page_items = json.loads(proc.stdout)
        except Exception:
            raise SystemExit("GitCode CLI 返回的不是 JSON——先跑 gitcode auth status 确认登录")
        if not isinstance(page_items, list):
            raise SystemExit(f"GitCode API 返回的不是数组：{str(page_items)[:120]}")
        items.extend(page_items)
        if len(page_items) < 100:
            break
        page += 1
    return items


def slim_gitcode(item: dict) -> dict:
    """GitCode issue → 与 GitHub 同一份缓存字段（filter 不感知来源）。"""
    labels = [l.get("name") if isinstance(l, dict) else l
              for l in (item.get("labels") or [])]
    number = item.get("number")
    try:
        number = int(number)
    except (TypeError, ValueError):
        pass
    return {
        "number": number,
        "title": item.get("title"),
        "comments": item.get("comments"),
        # GitCode 没有 state_reason；不硬造「completed」，filter 会按未解析处理
        "closed_at": item.get("closed_at") or item.get("finished_at"),
        "state_reason": item.get("state_reason"),
        "labels": [x for x in labels if x],
    }


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
    ap.add_argument("--host", choices=["github", "gitcode"], default="github",
                    help="issue 所在平台；gitcode 走 gitcode/gc CLI 的 api 子命令")
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

    if args.host == "gitcode":
        items = gitcode_api(url)
        issues = [slim_gitcode(it) for it in items if "pull_request" not in it]
    else:
        items = gh_api(url)
        issues = [slim(it) for it in items if "pull_request" not in it]

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)
    print(f"拉取 {len(issues)} 条 issue（不含 PR）→ {args.output}")


if __name__ == "__main__":
    raise SystemExit(main_entry(main))
