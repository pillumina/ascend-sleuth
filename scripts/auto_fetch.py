#!/usr/bin/env python3
# auto_fetch.py —— 自动增量拉取全部 issue 源（GAP-1：全自动采集编排）
#
# 目标：agent 不再手动逐个跑 fetch_issues + issue_filter，一条命令自动处理
# ingest-state.json 里配置的全部 source：读游标 → 增量拉新 closed issue →
# 硬过滤 → 产出候选报告（每个源一份）。跑完更新游标（幂等，重复跑不重拉）。
#
# 用法：
#   python3 scripts/auto_fetch.py                     # 全部源增量拉取 + 过滤（dry-run 候选报告）
#   python3 scripts/auto_fetch.py --source vllm-ascend  # 只跑指定源
#   python3 scripts/auto_fetch.py --days 14           # 拉最近 N 天（无游标时兜底）
#
# 产出：
#   .auto-fetch/<source-slug>.candidates.json     # 过滤后候选（供评估/沉淀）
#   控制台打印每源候选数 + 新 issue 数
#
# 注意：GitCode 源（如 MindSpeed-LLM）不走 gh——本脚本检测到非 github 源时
# 打印提示并跳过（由 agent 用平台工具处理），保持脚本只做 gh 可自动的部分。

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml  # noqa: F401  (对齐仓库脚本风格，可能用于 config 扩展)

STATE_FILE = "ingest-state.json"
OUT_DIR = ".auto-fetch"


def load_state(root: Path):
    return json.loads((root / STATE_FILE).read_text())


def save_state(root: Path, state):
    (root / STATE_FILE).write_text(json.dumps(state, indent=2, ensure_ascii=False))


def gh_api(path: str):
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=50)
    if out.returncode != 0:
        raise RuntimeError(f"gh api 失败: {out.stderr[:200]}")
    return json.loads(out.stdout)


def fetch_since(repo: str, since: str, labels: str):
    """增量拉：state=closed + labels + since 游标。GitHub search 不可靠用 issues list API。"""
    # issues list API 不支持 since 直接过滤 closed_at——用 state=closed + per_page 拉到足够再本地滤
    q = f"repos/{repo}/issues?state=closed&labels={labels}&per_page=50"
    issues = []
    page = 1
    cutoff = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None
    while True:
        batch = gh_api(f"{q}&page={page}")
        if not batch:
            break
        issues.extend(batch)
        # 本地按 closed_at 过滤 + 提前停（增量窗口外的页不再翻）
        if cutoff:
            oldest = batch[-1].get("closed_at")
            if oldest and datetime.fromisoformat(oldest.replace("Z", "+00:00")) < cutoff:
                break
        page += 1
        if page > 10:  # 安全上限
            break
    # 过滤：closed_at > since 的才是新
    fresh = []
    if cutoff:
        for i in issues:
            ca = i.get("closed_at")
            if ca and datetime.fromisoformat(ca.replace("Z", "+00:00")) > cutoff:
                fresh.append(i)
    else:
        fresh = issues
    return fresh


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def main():
    ap = argparse.ArgumentParser(description="自动增量拉取全部 issue 源")
    ap.add_argument("--source", default=None, help="只跑指定源（键尾匹配，如 vllm-ascend）")
    ap.add_argument("--days", type=int, default=14, help="无游标时拉最近 N 天")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()
    root = args.root.resolve()
    state = load_state(root)
    out_dir = root / OUT_DIR
    out_dir.mkdir(exist_ok=True)

    fallback_since = (datetime.utcnow() - timedelta(days=args.days)).strftime("%Y-%m-%dT00:00:00Z")

    # 无 --source 时只列可用源，不自动全跑（数据源由用户指定——目标驱动，非死板全拉）
    if not args.source:
        print("可用 issue 源（用 --source <名称片段> 指定，如 --source vllm-ascend）：")
        for key in state.get("sources", {}):
            print(f"  {key}")
        print("（未指定源 = 不拉取——数据源由目标/用户决定）")
        return

    for key, src in state.get("sources", {}).items():
        if args.source and args.source not in key:
            continue
        if not key.startswith("github/"):
            print(f"⏭  {key}: 非 GitHub 源（走 agent 平台工具），跳过")
            continue
        repo = key.split("github/", 1)[1]
        config = src.get("config", {})
        labels = config.get("labels", "")
        since = src.get("last_fetch_latest_closed") or fallback_since

        print(f"\n▶ {key} (repo={repo}, labels={labels})")
        try:
            fresh = fetch_since(repo, since, labels)
        except Exception as e:
            print(f"  ✗ 拉取失败: {e}")
            continue

        # 排除已 processed
        processed = set(src.get("processed", []))
        new = [i for i in fresh if i["number"] not in processed]
        print(f"  新 closed issue（closed_at > {since}）: {len(fresh)}，未处理: {len(new)}")

        if not new:
            print("  无新候选")
            continue

        # 写候选报告
        slug = slugify(repo)
        out = out_dir / f"{slug}.candidates.json"
        out.write_text(json.dumps(new[: config.get("limit", 20)], indent=2, ensure_ascii=False))
        print(f"  候选报告 → {out}")
        for i in new[:5]:
            print(f"    #{i['number']} [{i.get('state_reason','')}] {(i.get('title') or '')[:60]}")

        # 更新游标到最新 closed_at（幂等：下次只拉更新的）
        closed_times = [i.get("closed_at") for i in fresh if i.get("closed_at")]
        if closed_times:
            latest = max(closed_times)
            if latest > since:
                src["last_fetch_latest_closed"] = latest
                save_state(root, state)
                print(f"  游标更新 → {latest}")

    print("\nauto_fetch 完成。候选在 .auto-fetch/，可评估沉淀或入 S2 校准集。")


if __name__ == "__main__":
    main()
