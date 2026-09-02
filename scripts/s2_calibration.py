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
#         confidence: high | medium | pending   # high=fix commit/PR 信号；medium=结论性
#                                               # 评论；pending=待人工补（诚实标注）
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
# 评论中的非结论模式（指派/待查/流程语——不是 resolution）
NON_RESOLUTION_PATTERNS = (
    "/wait", "@", "please take a look", "pls check", "please check", "take a look at",
    "assign", "cc ", "reproduce", "can you", "could you", "need more info", "need your",
    "moving to", "dup of", "duplicate of", "this is a known issue",
)
# fix-commit 关键字（referenced commit message 含这些才算 fix 信号）
FIX_KEYWORDS = ("fix", "fixes", "fixed", "resolve", "resolves", "resolved", "bugfix")
# 评论中的"明确 fix 引用"模式（最可靠的 resolution 信号：维护者评论直接指认修复）
FIX_REF_PATTERNS = (
    "fixed by", "fixed in", "fix by", "fix in", "resolved by", "resolved in",
    "fixes #", "fixed #", "has been fixed", "was fixed", "fix https://", "fixed https://",
)


def is_bug_candidate(issue: dict) -> bool:
    title = (issue.get("title") or "").strip()
    if any(title.startswith(p) for p in NON_BUG_PREFIXES):
        return False
    # 有 bug 标签优先；无标签时靠 title 排除非 bug
    labels = [l.get("name", "") for l in (issue.get("labels") or [])]
    if labels and not any("bug" in l.lower() or "triaged" in l.lower() for l in labels):
        return False
    return True


def looks_like_resolution(text: str) -> bool:
    """评论/文本是否像 resolution（排除指派/待查/流程语）。"""
    t = (text or "").strip()
    if len(t) < 15:
        return False
    low = t.lower()
    if any(p in low for p in NON_RESOLUTION_PATTERNS):
        return False
    # 结尾像流程语（"我会看""let me"等）也排除
    if any(t.rstrip().endswith(s) for s in ("?", "。", "！", "?")):
        return False
    return True


def is_fix_commit_message(msg: str) -> bool:
    low = (msg or "").lower()
    return any(k in low for k in FIX_KEYWORDS)


def extract_resolution_via_events(repo: str, num: int) -> tuple:
    """从 timeline 提取 resolution：
    1. fix-commit（referenced commit，message 含 fix/closes 关键字 + PR 标题）→ confidence high
    2. linked PR（cross-referenced 的 PR，标题含 fix 关键字）→ confidence high
    3. 关联 PR（cross-referenced 的 PR，无 fix 关键字）→ confidence medium（仅 fix_commit 引用）
    返回 (resolution, fix_commit, confidence)。
    """
    resolution = ""
    fix_commit = ""
    confidence = "pending"
    try:
        events = gh_api(f"repos/{repo}/issues/{num}/timeline?per_page=50")
    except Exception:
        return resolution, fix_commit, confidence
    for e in events:
        ev = e.get("event")
        # fix commit：referenced 事件带 commit_id，取 commit message 判断
        if ev == "referenced" and e.get("commit_id"):
            cid = e["commit_id"]
            try:
                c = gh_api(f"repos/{repo}/commits/{cid}")
                msg = (c.get("commit", {}).get("message") or "")
                if is_fix_commit_message(msg):
                    resolution = clip_text(msg.split("\n")[0], 200)
                    fix_commit = cid[:12]
                    confidence = "high"
                    return resolution, fix_commit, confidence
            except Exception:
                continue
        # linked/fix PR：cross-referenced 的 PR
        if ev == "cross-referenced":
            src = e.get("source", {}).get("issue", {})
            if src and src.get("pull_request"):
                pr_title = src.get("title") or ""
                if is_fix_commit_message(pr_title) and confidence == "pending":
                    resolution = clip_text(pr_title, 200)
                    fix_commit = f"PR #{src.get('number')}"
                    confidence = "high"
                    return resolution, fix_commit, confidence
    return resolution, fix_commit, confidence


def extract_resolution_via_comments(repo: str, num: int, author: str) -> tuple:
    """从评论提取 resolution：优先找含"fixed by/in #PR"明确引用的评论（最高置信，
    维护者直接指认修复）；无则找结论性评论（非作者、排除指派/待查语）。
    返回 (resolution, confidence, fix_ref)。
    """
    try:
        comments = gh_api(f"repos/{repo}/issues/{num}/comments?per_page=20")
    except Exception:
        return "", "pending", ""
    # 第一遍：找明确 fix 引用——**含作者本人的 fix 确认**（作者报 bug 后评论
    # "fixed by #PR" = 他自己验证过修复，是最可靠 resolution；不跳过作者）
    for c in comments:
        body = c.get("body") or ""
        low = body.lower()
        for pat in FIX_REF_PATTERNS:
            if pat in low:
                # 提取 fix 引用：优先 pull/<n> 或 "PR #<n>"；排除引用 issue 自身
                import re as _re
                fix_ref = ""
                m_pr = _re.search(r"(?:pull/|pr\s*#|pull request #)(\d+)", body, _re.I)
                if m_pr:
                    fix_ref = f"PR #{m_pr.group(1)}"
                else:
                    m_iss = _re.search(r"issues?/(\d+)", body)
                    if m_iss and int(m_iss.group(1)) != num:
                        fix_ref = f"PR #{m_iss.group(1)}"
                # 无有效 fix 引用（如"fixed in issue 自己"的笼统话术）→ 跳过此评论继续
                if not fix_ref:
                    continue
                return clip_text(body, 300), "high", fix_ref
    # 第二遍：一般结论性评论
    for c in reversed(comments):
        if c.get("user", {}).get("login") == author:
            continue
        body = c.get("body") or ""
        if looks_like_resolution(body):
            return clip_text(body, 300), "medium", ""
    return "", "pending", ""


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
    ap.add_argument("--incremental", action="store_true", help="增量模式：跳过 output 中已收录的 issue")
    args = ap.parse_args()

    processed = load_processed(args.state_file)
    # 增量：读已有校准集，收集已收录 issue 号
    already_in = set()
    if args.incremental and args.output.exists():
        try:
            old = yaml.safe_load(args.output.read_text())
            already_in = {e.get("issue") for e in old.get("calibration", []) if isinstance(e, dict)}
        except Exception:
            already_in = set()
    # 1. 拉候选 issue 元数据（单页，按最近 closed 排序）
    query = f"repos/{args.repo}/issues?state={args.state}&labels={args.labels}&per_page={max(args.limit*3, 10)}"
    issues = gh_api(query)
    # 2. 排除已沉淀（processed）+ 非 bug 类
    candidates = [
        i for i in issues
        if i["number"] not in processed
        and i["number"] not in already_in          # 增量：跳过已收录
        and i.get("state_reason") == "completed"    # 排除 not_planned（维护者不修）
        and is_bug_candidate(i)
    ]
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
        # 4. 取 resolution（分层提取 + 置信度标注）：
        #    a. 评论中的明确 fix 引用（"fixed by PR #N"）→ high（最可靠，维护者直接指认）
        #    b. events 的 fix-commit / fix-PR 信号 → high
        #    c. 无 fix 信号时，结论性评论 → medium
        #    d. 都没有 → pending（待人工补，诚实标注）
        author = (detail.get("user") or {}).get("login", "")
        resolution, confidence, fix_ref = extract_resolution_via_comments(args.repo, num, author)
        fix_commit = fix_ref
        if not resolution:
            # events 提取（fix-commit/PR）
            res_ev, fix_ev, conf_ev = extract_resolution_via_events(args.repo, num)
            if res_ev:
                resolution, fix_commit, confidence = res_ev, fix_ev, conf_ev
        if not resolution:
            resolution = "（待补：维护者结论）"
            confidence = "pending"
        entries.append({
            "issue": num,
            "split": "selection",  # 默认 selection；test 半由人工/后续划分
            "title": i.get("title", ""),
            "input": {"symptoms": body},
            "expected": {
                "resolution": resolution or "（待补：维护者结论）",
                "fix_commit": fix_commit,
                "confidence": confidence,  # high(fix commit/PR) | medium(结论性评论) | pending(待人工补)
            },
            "status": "active",
        })
        print(f"  #{num} [{entries[-1]['split']}] {i.get('title', '')[:50]} fix={fix_commit or 'N/A'}")
        time.sleep(0.3)  # 礼貌限速

    if args.dry_run:
        print(f"（dry-run：{len(entries)} 条将写入 {args.output}）")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # 增量：合并已有校准集（旧条目保留 + 新条目追加）
    merged = list(entries)
    if args.incremental and args.output.exists():
        try:
            old = yaml.safe_load(args.output.read_text())
            merged = (old.get("calibration") or []) + entries
        except Exception:
            pass
    doc = {
        "_comment": f"GENERATED by scripts/s2_calibration.py（{args.repo}，S2 issue-replay 校准集，见 evolution-run.md §3）。split=test 的条目仅用于 validated 终判，不参与 gate 决策；expected.resolution 是 issue 实际 resolution（外部 ground truth）。",
        "calibration": merged,
    }
    args.output.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"s2_calibration: 已写 {args.output}（{len(merged)} 条，新增 {len(entries)}）")


if __name__ == "__main__":
    main()
