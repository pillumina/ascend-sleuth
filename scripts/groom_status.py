#!/usr/bin/env python3
# groom_status.py —— 本地草稿的 Groom 状态与新鲜度（人读一屏 + 机器可读）
#
# 回答三个问题：
#   1. 这份草稿评估过没有？评的是什么（covered / variant / new_pattern / ambiguous）？
#   2. 评估之后知识库有没有前进？草稿有没有被改过？（→ stale，需要重跑）
#   3. 下一步该谁做什么？（复核 / 升格 / 等证据 / 重跑）
#
# 新鲜度判据是**确定性的**：
#   - 评估记录里的 compared_against_commit 必须存在，且是当前目标 commit 的祖先；
#   - `git diff <assessed>..<target> -- knowledge/` 非空 → 知识变了 → stale；
#   - 草稿 case 的内容指纹与评估记录不一致 → 草稿变了 → stale。
# 它不判断"新知识是否真的与草稿相关"——那要重跑语义比对；这里只保证不会拿旧结论当新结论。
#
# 用法：
#   python3 scripts/groom_status.py                    # 用本地 origin/main（不 fetch）
#   python3 scripts/groom_status.py --fetch            # 先 fetch 再判
#   python3 scripts/groom_status.py --json
#   python3 scripts/groom_status.py --check-stale      # 有 stale / 未评估 → 退出 2
#
# 退出码：0 = 正常；2 = --check-stale 发现 stale 或未评估；3 = 仓库/git 不可用。

import argparse
import sys
from pathlib import Path

from _stdio import pin_utf8_stdio
from groom_common import (
    case_fingerprint, draft_cases, dump_json, find_drafts, is_ancestor, knowledge_changes,
    load_assessment, load_json, normalize_commit, now_iso, repo_root, run_git,
    sanitize_key, shared_inbox, short_sha,
)


def _action(a, human, stale, human_valid=True):
    if not a:
        return "未评估：先跑 groom_snapshot + groom_candidates + 子 agent 比对 + groom_record"
    if human and not human_valid:
        return "重新确认批准：旧批准没有绑定当前评估/内容"
    if stale:
        return "重跑 groom（知识或草稿已变），不要用旧评估升格"
    if human and human.get("decision") == "reject":
        return "已否决：关闭草稿（postmortem 仍可转正 Tier 3）"
    if human and human.get("decision") == "defer":
        return "已延后：等新证据后重跑"
    if human:
        decision = human.get("decision")
        if decision in ("new_pattern", "variant", "covered"):
            return ("收尾：落盘后跑 groom_close_draft（回写 trace 沉淀状态 + 草稿出队）"
                    + f"（{decision}"
                    + (f"，{human.get('candidate_case')}" if human.get("candidate_case") else "")
                    + "）")
        return f"按人决定处理：{decision}"
    if a.get("review_required"):
        return "人工复核：读候选 case 后 groom_decide"
    if a.get("proposed_novelty") == "new_pattern":
        return "可进入既有升格闸门（仍需人审）"
    return "人工复核"


def status_rows(root: Path, target_commit: str, inbox: Path):
    rows = []
    drafts = find_drafts(inbox)
    known = {d.key for d in drafts}
    for d in drafts:
        try:
            cases = draft_cases(d)
            current = case_fingerprint(cases[0]) if cases else None
            case_id = cases[0].get("id") if cases else None
        except Exception as exc:
            cases, current, case_id = [], None, None
            draft_error = f"草稿解析失败：{exc}"
        else:
            draft_error = None
        try:
            doc = load_assessment(inbox, d.key)
            load_error = None
        except Exception as exc:
            doc = {}
            load_error = f"评估状态解析失败：{exc}"
        a = doc.get("assessment") or {}
        human = doc.get("human_decision") or {}
        prov = doc.get("provenance") or {}
        assessed = prov.get("compared_against_commit")
        stale_reasons = []
        if draft_error:
            stale = True
            stale_reasons.append(draft_error)
        elif load_error:
            stale = True
            stale_reasons.append(load_error)
        elif not doc:
            stale = True
            stale_reasons.append("未评估")
        else:
            if not assessed:
                stale_reasons.append("评估记录缺 compared_against_commit")
            elif not is_ancestor(root, assessed, target_commit):
                stale_reasons.append(f"评估 commit {short_sha(assessed)} 不是当前目标的祖先")
            changed = knowledge_changes(root, assessed, target_commit) if assessed else []
            if changed:
                stale_reasons.append(f"知识库在评估后前进了 {len(changed)} 个文件")
            if current and doc.get("draft_sha256") and current != doc.get("draft_sha256"):
                stale_reasons.append("草稿内容在评估后被改过")
            if prov.get("snapshot_authoritative") is False:
                stale_reasons.append("评估用的是非权威快照")
            if not doc.get("assessment_id"):
                stale_reasons.append("评估没有 assessment_id（旧格式或绑定失败）")
            if human and not doc.get("human_decision_valid", False):
                stale_reasons.append("人的批准没有绑定到当前评估/内容，需要重新确认")
        stale = bool(stale_reasons)
        human_valid = bool(doc.get("human_decision_valid", False))
        needs_reapproval = bool(human) and not human_valid and bool(stale_reasons) and all(
            "人的批准" in reason for reason in stale_reasons)
        rows.append({
            "draft": d.key,
            "case_id": case_id,
            "layout": d.layout,
            "assessed": bool(doc),
            "proposed_novelty": a.get("proposed_novelty"),
            "candidate_case": a.get("candidate_case"),
            "confidence": a.get("confidence"),
            "rationale": a.get("rationale") or "",
            "review_reasons": a.get("review_reasons") or [],
            "review_required": a.get("review_required"),
            "human_decision": human.get("decision"),
            "human_decision_valid": human_valid,
            "needs_reapproval": needs_reapproval,
            "review_state": doc.get("review_state"),
            "assessed_commit": assessed,
            "assessed_short": prov.get("compared_against_short") or short_sha(assessed),
            "target_commit": target_commit,
            "stale": stale,
            "stale_reasons": stale_reasons,
            "gate": doc.get("promotion_gate") or {},
            "next_action": _action(a, human, stale, doc.get("human_decision_valid", True)),
            "assessment_file": str((inbox / ".groom" / "assessments")) if doc else None,
        })
    assess_dir = inbox / ".groom" / "assessments"
    if assess_dir.is_dir():
        known_files = {sanitize_key(k) for k in known}
        for path in sorted(assess_dir.glob("*.yaml")):
            if path.stem not in known_files:
                rows.append({
                    "draft": path.stem, "orphan": True, "assessed": True,
                    "stale": True, "stale_reasons": ["评估状态存在但 inbox 里找不到对应草稿"],
                    "next_action": "确认草稿是否已升格/删除；不要复用旧评估",
                })
    return rows


def key_ok_match(path: Path, row) -> bool:
    return path.stem == sanitize_key(str(row.get("draft") or ""))


def print_rows(rows):
    if not rows:
        print("inbox 中没有草稿。")
        return
    print(f"{'Draft':<38} {'评估':<14} {'候选':<24} {'人决定':<10} {'新鲜度':<6} 下一步")
    print("-" * 130)
    for r in rows:
        if r.get("orphan"):
            print(f"{r['draft']:<38} {'（孤儿状态）':<14} {'':<24} {'':<10} {'STALE':<6} {r['next_action']}")
            continue
        print(f"{str(r['draft'])[:37]:<38} {str(r.get('proposed_novelty') or '—'):<14} "
              f"{str(r.get('candidate_case') or '—')[:23]:<24} "
              f"{str(r.get('human_decision') or '—'):<10} "
              f"{'STALE' if r.get('stale') else 'fresh':<6} "
              f"{r.get('next_action')}")
        for reason in r.get("stale_reasons") or []:
            print(f"{'':<38} └ {reason}")


def print_decision_prompts(rows):
    """把待决定的草稿整理成可回答的问答块；不替人做决定。"""
    pending = [r for r in rows
               if not r.get("orphan")
               and (r.get("needs_reapproval")
                    or (not r.get("stale")
                        and r.get("human_decision") in (None, "", "pending")))]
    if not pending:
        print("\n没有待人决定的草稿。")
        return
    print("\n需要人决定的草稿：")
    for r in pending:
        novelty = r.get("proposed_novelty") or "ambiguous"
        candidate = r.get("candidate_case") or "—"
        print(f"\n### {r['draft']}")
        print(f"评估：{novelty}（{r.get('confidence') or '—'}）")
        print(f"候选：{candidate}")
        if r.get("needs_reapproval"):
            print(f"状态：评估已更新，旧批准失效（原决定 {r.get('human_decision') or '—'}），请重新确认。")
        if r.get("rationale"):
            print(f"理由：{r['rationale']}")
        for reason in r.get("review_reasons") or []:
            print(f"待核：{reason}")
        # agent 判 duplicate（精确重复）时，人决定层的等价动作是 covered：human_decision 枚举里
        # 没有 duplicate（groom_common.VALID_HUMAN_DECISIONS），两者对 Case 的授权相同（都不许
        # 新增或修改）。不在这里换一个词，人会被提示"先重跑/补证据"，被迫多做一次改判。
        if novelty == "duplicate":
            print("备注：agent 判 duplicate（精确重复）；人决定落成 covered（授权相同）。")
        agree = "covered" if novelty == "duplicate" else novelty
        merge = agree in ("variant", "covered")
        can_agree = agree in ("new_pattern", "variant", "covered", "defer", "reject") \
            and (not merge or candidate != "—")
        options = []
        if can_agree:
            options.append(f"同意建议：{agree}" + (f"（{candidate}）" if candidate != "—" else ""))
        else:
            options.append(f"先重跑/补证据（当前建议 {novelty} 不是可直接执行的决定）")
        options += [
            "改判 new_pattern",
            "改判 variant（请给候选 Case ID）",
            "改判 covered（请给候选 Case ID）",
            "defer（先不处理）",
            "reject（拒绝这条草稿）",
        ]
        print("请选择：")
        for i, option in enumerate(options, 1):
            print(f"  {i}. {option}")
        print("回复编号 + 候选 ID + 一句 note；agent 再执行 groom_decide，不自动决定。")


def main():
    pin_utf8_stdio()
    ap = argparse.ArgumentParser(description="Groom 本地草稿状态与新鲜度")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--snapshot", default=None, help="用快照 meta 的 commit 当目标（不 fetch）")
    ap.add_argument("--fetch", action="store_true", help="先 git fetch origin main")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--decision-prompt", action="store_true",
                    help="表格后输出待决定草稿的问答块；不写状态")
    ap.add_argument("--check-stale", action="store_true", help="有 stale/未评估则退出 2")
    args = ap.parse_args()

    root = repo_root(Path(args.repo).resolve() if args.repo else Path.cwd())
    if args.snapshot:
        meta = load_json(Path(args.snapshot))
        target = meta.get("commit")
        inbox = shared_inbox(Path(meta["repo"]))
    else:
        if args.fetch:
            run_git(["fetch", "--no-tags", "origin", "main"], cwd=root, check=False)
        target = normalize_commit(root, "refs/remotes/origin/main") or normalize_commit(root, "HEAD")
        inbox = shared_inbox(root)
    if not target:
        print("取不到目标 commit（git 仓库或 origin/main 不可用）", file=sys.stderr)
        return 3

    rows = status_rows(root, target, inbox)
    if args.json:
        print(dump_json({"schema": "groom-status/v1", "generated_at": now_iso(),
                         "target_commit": target, "target_short": short_sha(target),
                         "inbox": str(inbox), "drafts": rows}))
    else:
        print(f"目标知识版本 {short_sha(target)} · inbox {inbox}")
        print_rows(rows)
        if args.decision_prompt:
            print_decision_prompts(rows)
    if args.check_stale:
        bad = [r for r in rows if r.get("stale")]
        if bad:
            print(f"\n{len(bad)} 份草稿需要重跑或尚未评估（见上）。", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
