#!/usr/bin/env python3
# s2_calibration.py —— 构建 S2 issue-replay 校准集（eval/s2/）
#
# S2 = Issue-replay 校准（evolution-pipeline.md §2.1 / evolution-run.md §3）：
#   取已闭环 issue 的"现象"（用户首帖）→ 对照其"实际 resolution"（维护者结论/关联
#   fix commit）自动评分诊断系统"从现象能否定位到根因"。这是不依赖工程师回报的
#   自动评分源（S1 断供时的验证门数据）。
#
# 解耦规则（run §3）：先评测后沉淀——校准集只收**未被本系统沉淀过的 issue**
# （不在 ingest-state processed 中）；已沉淀 issue 是"用自己写的题考自己"。
# selection/test 分离：split 字段标记，test 半永不参与 gate 决策。
#
# 输出：eval/s2/<repo-slug>.yaml
#   calibration:
#     - issue: 12989
#       split: selection | test        # test 半仅用于 validated 终判
#       title: ...
#       input: <用户首帖裁剪（现象/日志）>   # diagnose 的输入
#       expected:                       # issue 实际 resolution（外部 ground truth）
#         resolution: <维护者结论/修复要点摘要>
#         fix_commit: <关联 fix commit/PR，若有>
#       status: active                  # 校准集条目状态
#
# 用法：
#   python3 scripts/s2_calibration.py --repo vllm-project/vllm-ascend --state closed \
#     --labels triaged --limit 5 --output eval/s2/vllm-ascend.yaml --state-file ingest-state.json
#   --dry-run 只列候选不写文件
#
# 网络：gh api 逐个取 issue body（元数据已由 fetch_issues 拉过，body 需按需取）。
# 注意：issue 是公开数据可入库；若某 issue 含不可公开信息（极少），移出或标注。

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import yaml

BODY_CLIP = 3500
# 非诊断类 title 前缀（S2 校准集只收 bug/可诊断问题——Doc/Feature/Usage 类无诊断价值）
NON_BUG_PREFIXES = ("[Doc]", "[Feature]", "[Usage]", "[Question]", "docs:", "feat:")


def is_bug_candidate(issue: dict) -> bool:
    title = (issue.get("title") or "").strip()
    if any(title.startswith(p) for p in NON_BUG_PREFIXES):
        return False
    # 有 bug 标签优先；无标签时靠 title 排除非 bug
    labels = [l.get("name", "") for l in (issue.get("labels") or [])]
    if labels and not any("bug" in l.lower() or "triaged" in l.lower() for l in labels):
        return False
    return True


def gh_api(path: str, timeout: int = 40):
    """单次 gh api 调用（不带 --paginate，避免超时）。"""
    out = subprocess.run(
        ["gh", "api", path],
        capture_output=True, text=True, timeout=timeout, check=True,
    )
    return json.loads(out.stdout)


def clip_text(body: str, limit: int = BODY_CLIP) -> str:
    if not body:
        return ""
    if len(body) <= limit:
        return body
    return body[: limit * 2 // 3] + "\n\n……（中段裁剪）……\n\n" + body[-limit // 3:]


def load_processed(state_file: Path):
    """ingest-state.json 的 processed（已沉淀 issue 集合）。"""
    try:
        doc = json.loads(state_file.read_text())
    except Exception:
        return set()
    out = set()
    for v in doc.get("sources", {}).values():
        out.update(v.get("processed", []))
    return out


def main():
    ap = argparse.ArgumentParser(description="构建 S2 issue-replay 校准集")
    ap.add_argument("--repo", required=True, help="owner/repo")
    ap.add_argument("--state", default="closed", help="issue state")
    ap.add_argument("--labels", default="triaged")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--output", type=Path, required=True, help="输出 eval/s2/<slug>.yaml")
    ap.add_argument("--state-file", type=Path, default=Path("ingest-state.json"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    processed = load_processed(args.state_file)
    # 1. 拉候选 issue 元数据（单页，按最近 closed 排序）
    query = f"repos/{args.repo}/issues?state={args.state}&labels={args.labels}&per_page={max(args.limit*3, 10)}"
    issues = gh_api(query)
    # 2. 排除已沉淀（processed）+ 非 bug 类
    candidates = [i for i in issues if i["number"] not in processed and i.get("state_reason") == "completed" and is_bug_candidate(i)]
    candidates = candidates[: args.limit]
    print(f"s2_calibration: 未沉淀 bug 候选 {len([i for i in issues if i['number'] not in processed and is_bug_candidate(i)])} 条 / 取 {len(candidates)} 条")

    entries = []
    for i in candidates:
        num = i["number"]
        # 3. 取 body（用户首帖 = diagnose 输入）
        detail = gh_api(f"repos/{args.repo}/issues/{num}")
        body = clip_text(detail.get("body") or "")
        if not body:
            print(f"  #{num}: 无 body，跳过")
            continue
        # 4. 取 resolution（尽力提取，缺失如实标"待补"）：
        #    a. 跨引用 PR（events cross-referenced 的 PR）
        #    b. 维护者评论尾部（closed 结论常写在评论）
        resolution = ""
        fix_commit = ""
        try:
            events = gh_api(f"repos/{args.repo}/issues/{num}/events?per_page=30")
            for e in events:
                if e.get("event") == "cross-referenced":
                    src = e.get("source", {}).get("issue", {})
                    if src.get("pull_request"):
                        fix_commit = f"PR #{src.get('number')}"
                        resolution = clip_text((src.get("title") or ""), 200)
                        break
        except Exception:
            pass
        if not resolution:
            try:
                # 维护者评论（非作者）尾部——closed 结论常见于此
                comments = gh_api(f"repos/{args.repo}/issues/{num}/comments?per_page=10")
                author = detail.get("user", {}).get("login", "")
                for c in reversed(comments):
                    if c.get("user", {}).get("login") != author:
                        txt = clip_text(c.get("body") or "", 300)
                        if txt:
                            resolution = txt
                            break
            except Exception:
                pass
        if not resolution:
            resolution = "（待补：维护者结论）"
        entries.append({
            "issue": num,
            "split": "selection",  # 默认 selection；test 半由人工/后续划分
            "title": i.get("title", ""),
            "input": {"symptoms": body},
            "expected": {"resolution": resolution or "（待补：维护者结论）", "fix_commit": fix_commit},
            "status": "active",
        })
        print(f"  #{num} [{entries[-1]['split']}] {i.get('title', '')[:50]} fix={fix_commit or 'N/A'}")
        time.sleep(0.3)  # 礼貌限速

    if args.dry_run:
        print(f"（dry-run：{len(entries)} 条将写入 {args.output}）")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "_comment": f"GENERATED by scripts/s2_calibration.py（{args.repo}，S2 issue-replay 校准集，见 evolution-run.md §3）。split=test 的条目仅用于 validated 终判，不参与 gate 决策；expected.resolution 是 issue 实际 resolution（外部 ground truth）。",
        "calibration": entries,
    }
    args.output.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"s2_calibration: 已写 {args.output}（{len(entries)} 条）")


if __name__ == "__main__":
    main()
