#!/usr/bin/env python3
# groom_decide.py —— 记录**人**的决定（与 agent 建议分家）
#
# Agent 的评估只是建议。升格 / 合并 / 覆盖 / 延后由人决定，本脚本是那个决定的唯一写入口。
# 它做三件事：
#   1. 只改 sidecar 的 `human_decision`，不动草稿、不动 case、不动 agent 的 assessment；
#   2. 把决定绑到**它当时看到的知识 commit**（applies_to_commit）——知识前进后能判过期；
#   3. 原子写 + 幂等（同一决定重复执行不产生新历史行）。
#
# 用法：
#   python3 scripts/groom_decide.py --draft-key <key> --decision covered --candidate CASE-001 --by <name> --note "同一根因"
#   python3 scripts/groom_decide.py --draft-key <key> --decision new_pattern --by <name>
#   python3 scripts/groom_decide.py --draft-key <key> --decision defer --by <name> --note "等现场补证据"
#
# 退出码：0 = 已记录（或未变）；2 = 参数/状态不允许；3 = 找不到评估。

import argparse
import sys
from pathlib import Path

from _stdio import pin_utf8_stdio
from groom_common import (
    VALID_HUMAN_DECISIONS, case_fingerprint, draft_cases, find_drafts, load_assessment,
    load_json, now_iso, shared_inbox, write_assessment,
)

MERGE_DECISIONS = ("covered", "variant")


def apply_decision(doc, decision, candidate, by, note):
    a = doc.get("assessment") or {}
    existing = doc.get("human_decision") or {}
    now = now_iso()
    assessment_id = doc.get("assessment_id")
    content_sha = (doc.get("content_binding") or {}).get("sha256")
    if (existing.get("decision") == decision
            and str(existing.get("candidate_case") or "") == str(candidate or "")
            and existing.get("assessment_id") == assessment_id):
        return doc, False

    proposed = a.get("proposed_novelty")
    overrides = bool(proposed) and not (
        proposed == decision and str(a.get("candidate_case") or "") == str(candidate or "")
    )
    history = list(doc.get("human_decision_history") or [])
    if existing:
        history.append(existing)
    doc["human_decision_history"] = history[-20:]
    doc["human_decision"] = {
        "decision": decision,
        "candidate_case": candidate,
        "by": by,
        "decided_at": now,
        "note": note or "",
        "applies_to_commit": (doc.get("provenance") or {}).get("compared_against_commit"),
        "assessment_id": assessment_id,
        "content_sha256": content_sha,
        "agent_proposal": {
            "proposed_novelty": proposed,
            "candidate_case": a.get("candidate_case"),
            "confidence": a.get("confidence"),
            "review_required": a.get("review_required"),
        },
        "overrides_agent": overrides,
    }
    doc["human_decision_valid"] = bool(assessment_id and content_sha)
    doc["review_state"] = "decided"
    gate = {"allowed": True, "blocked_reason": None}
    if not (doc.get("provenance") or {}).get("snapshot_authoritative"):
        gate = {"allowed": False, "blocked_reason": "stale-snapshot"}
    elif not doc["human_decision_valid"]:
        gate = {"allowed": False, "blocked_reason": "unbound-assessment"}
    elif decision == "reject":
        gate = {"allowed": False, "blocked_reason": "human-rejected"}
    elif decision == "defer":
        gate = {"allowed": False, "blocked_reason": "deferred"}
    doc["promotion_gate"] = gate
    history = list(doc.get("history") or [])
    history.append({
        "at": now,
        "event": "human_decision",
        "decision": decision,
        "candidate_case": candidate,
        "by": by,
        "overrides_agent": overrides,
        "applies_to_commit": doc["human_decision"]["applies_to_commit"],
        "assessment_id": assessment_id,
        "content_sha256": content_sha,
    })
    doc["history"] = history[-50:]
    return doc, True


def main():
    pin_utf8_stdio()
    ap = argparse.ArgumentParser(description="记录 Groom 的人决定（agent 建议与之分家）")
    ap.add_argument("--draft-key", required=True)
    ap.add_argument("--decision", required=True, choices=VALID_HUMAN_DECISIONS)
    ap.add_argument("--candidate", default=None, help="variant / covered 时必填")
    ap.add_argument("--by", default="owner", help="决定人（写自己名字）")
    ap.add_argument("--note", default="", help="为什么这样定（半年后还看得懂）")
    ap.add_argument("--snapshot", default=None, help="快照 meta（用于定位共享 inbox）")
    ap.add_argument("--allow-unassessed", action="store_true",
                    help="没有 agent 评估也允许记录决定（人工独立判断时）")
    args = ap.parse_args()

    if args.snapshot:
        meta = load_json(Path(args.snapshot))
        inbox = shared_inbox(Path(meta["repo"]))
    else:
        inbox = shared_inbox(Path.cwd())

    if args.decision in MERGE_DECISIONS and not args.candidate:
        print(f"--decision {args.decision} 需要 --candidate（指向哪条现有 case）", file=sys.stderr)
        return 2

    try:
        doc = load_assessment(inbox, args.draft_key)
    except Exception as exc:
        print(f"{args.draft_key} 的评估状态解析失败（{exc}）——先跑 groom_record.py 重建，"
              f"或人工检查 {inbox / '.groom' / 'assessments'} 下的文件", file=sys.stderr)
        return 3
    if not doc:
        if not args.allow_unassessed:
            print(f"没有找到 {args.draft_key} 的评估状态——先跑 groom_record.py；"
                  f"确属人工独立判断再加 --allow-unassessed", file=sys.stderr)
            return 3
        doc = {
            "schema": "groom-assessment/v1",
            "draft": args.draft_key,
            "assessment_id": None,
            "content_binding": {"sha256": None},
            "assessment": {
                "proposed_novelty": None, "candidate_case": None, "confidence": None,
                "review_required": True, "rationale": "未运行 agent 比对",
            },
            "history": [],
        }
    if not args.allow_unassessed and not doc.get("assessment_id"):
        print(f"{args.draft_key} 的评估没有 assessment_id——先重跑 groom_record.py；"
              f"旧格式不能作为 PR 授权", file=sys.stderr)
        return 3

    # 人的决定必须绑在**当前草稿内容**上；评估之后草稿被改过就不允许写批准。
    draft = next((d for d in find_drafts(inbox) if d.key == args.draft_key), None)
    if draft is None:
        if not args.allow_unassessed:
            print(f"inbox 里找不到草稿 {args.draft_key}——不能把批准绑到不存在的草稿", file=sys.stderr)
            return 3
    else:
        try:
            cases = draft_cases(draft)
            current = case_fingerprint(cases[0]) if cases else None
        except Exception as exc:
            print(f"草稿读不出来（{exc}）", file=sys.stderr)
            return 3
        if doc.get("draft_sha256") and current != doc.get("draft_sha256"):
            print(f"{args.draft_key} 的草稿在评估后被改过——先重跑 groom，"
                  f"旧评估不能批准新内容", file=sys.stderr)
            return 3
    new_doc, changed = apply_decision(doc, args.decision, args.candidate, args.by, args.note)
    if not changed:
        print(f"未变：{args.draft_key} 已是 {args.decision}"
              + (f"（{args.candidate}）" if args.candidate else ""))
        return 0
    path = write_assessment(inbox, args.draft_key, new_doc)
    print(f"已记录：{args.draft_key} → {args.decision}"
          + (f"（{args.candidate}）" if args.candidate else ""))
    if new_doc["human_decision"].get("overrides_agent"):
        print(f"  注意：这覆盖了 agent 的建议 {new_doc['human_decision']['agent_proposal']}"
              f"——覆盖已留痕，但仍建议在 note 里写明理由")
    if (new_doc.get("promotion_gate") or {}).get("blocked_reason"):
        print(f"  升格仍被阻塞：{new_doc['promotion_gate']['blocked_reason']}")
    print(f"  状态文件：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
