#!/usr/bin/env python3
# groom_status.py —— 本地草稿的 Groom 状态与新鲜度（人读一屏 + 机器可读）
#
# 回答三个问题：
#   1. 这份草稿评估过没有？评的是什么（covered / variant / new_pattern / ambiguous）？
#   2. 评估之后知识库有没有前进？草稿有没有被改过？（→ stale，需要重跑）
#   3. 下一步该谁做什么？（复核 / 升格 / 等证据 / 重跑）
#
# 新鲜度判据是**确定性的**，且按每份评估自己的目标 ref 比较：
#   - 目标优先级：显式 target_ref（--target / --snapshot）> 评估记录的 provenance.target_ref
#     > 主检出 settings 的提 PR 目标 ref > 传入的兜底 commit；
#   - 评估 commit 是目标祖先时，`git diff <assessed>..<target> -- knowledge/` 非空才 stale；
#   - 目标是评估祖先时说明「目标落后」；两边不互为祖先说明「无法比较」；ref 不可用或与当前
#     配置目标不一致时分别报出，不把不同历史线的比较折叠成「知识库前进了」；
#   - 草稿 case 的内容指纹与评估记录不一致 → 草稿变了 → stale。
# target_warnings 是不阻塞升格的提示（目标未配置、旧 sidecar 没有 target_ref 等），不进
# stale_reasons。它不判断"新知识是否真的与草稿相关"——那要重跑语义比对；这里只保证不会拿
# 旧结论当新结论。
#
# 用法：
#   python3 scripts/groom_status.py                    # 用 settings 的提 PR 目标；未配置时说明兜底
#   python3 scripts/groom_status.py --target <ref>     # 显式指定比较基准（优先于评估记录）
#   python3 scripts/groom_status.py --fetch            # 先 fetch 目标远端分支再判
#   python3 scripts/groom_status.py --snapshot <meta>  # 用快照 meta 的 ref 当目标（没有 ref 时用 commit）
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


# 目标本身有问题时的下一步：先确认基准，而不是一律重跑 groom。
# 只有「目标落后」与「无法比较」可能靠重跑解决；ref 不可用 / 与配置不一致要先修目标。
_TARGET_ACTIONS = {
    "ref_missing": "确认目标 ref：先 fetch，或改用 --target <ref> 指定可用基准",
    "ref_changed": "确认目标：评估基准与当前目标不是同一条 ref，定下提 PR 目标后再比较",
    "target_behind": "目标落后于评估基准：先更新目标 ref（fetch），或改用 --target <评估所用 ref>",
    "not_comparable": "确认基准：评估 commit 与目标不在同一历史线，改用 --target 或对目标重跑",
}


def _action(a, human, stale, human_valid=True, target_state=None):
    if not a:
        return "未评估：先跑 groom_snapshot + groom_candidates + 子 agent 比对 + groom_record"
    if stale and target_state in _TARGET_ACTIONS:
        # 目标本身不可信时，重做批准也解不开；先确认基准。
        return _TARGET_ACTIONS[target_state]
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


def _target_for_row(root: Path, assessed_ref, target_commit, *, target_ref, explicit_commit,
                    configured_target_ref, configured_commit):
    """这一行按哪个基准比较：显式 ref > 评估记录的 ref > 配置目标 > 兜底 commit。

    返回 (commit, ref, source, state, warnings, error)。state 只覆盖 ref 自身的问题
    （ref_missing / ref_changed）；评估与目标的历史关系由调用方判断。error 要进
    stale_reasons（阻塞升格）；warnings 只是提示，不改变新鲜度。
    """
    warnings = []
    if target_ref:
        if explicit_commit:
            return explicit_commit, target_ref, "explicit", None, warnings, None
        return (None, target_ref, "explicit", "ref_missing", warnings,
                f"显式目标 ref {target_ref} 解析不到（先 fetch 或确认远端）")
    if assessed_ref:
        assessed_target = normalize_commit(root, assessed_ref)
        if not assessed_target:
            return (None, assessed_ref, "assessment", "ref_missing", warnings,
                    f"评估记录的 target_ref {assessed_ref} 解析不到（先 fetch 或确认远端）")
        if configured_target_ref:
            if configured_commit is None:
                warnings.append(f"当前配置目标 {configured_target_ref} 解析不到（先 fetch 或确认远端）")
            elif configured_commit != assessed_target:
                return (assessed_target, assessed_ref, "assessment", "ref_changed", warnings,
                        f"评估基准 ref {assessed_ref} 与当前目标 ref {configured_target_ref} 不一致")
        return assessed_target, assessed_ref, "assessment", None, warnings, None
    if configured_target_ref and configured_commit:
        warnings.append("评估记录没有目标 ref，按当前目标比较")
        return configured_commit, configured_target_ref, "configured", None, warnings, None
    label = short_sha(target_commit) or "HEAD"
    if configured_target_ref:
        warnings.append(f"当前配置目标 {configured_target_ref} 解析不到（先 fetch 或确认远端）")
        warnings.append(f"按 {label} 比较")
    else:
        warnings.append(f"目标未配置，按 {label} 比较")
    return target_commit, None, "fallback", None, warnings, None


def status_rows(root: Path, target_commit: str, inbox: Path, *,
                target_ref=None, configured_target_ref=None):
    """每份草稿的状态；`target_ref` 是显式基准，`configured_target_ref` 只用于发现目标不一致。

    每份有评估的 row 带 target_commit / target_short / target_ref / target_state /
    target_source / target_warnings。target_state 枚举：ok / ref_missing /
    not_comparable / target_behind / ref_changed；无评估（或评估缺
    compared_against_commit，无法判定关系）时为 None。
    """
    explicit_commit = normalize_commit(root, target_ref) if target_ref else None
    configured_commit = normalize_commit(root, configured_target_ref) if configured_target_ref else None
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
        # 没有评估时这些字段留空：调用方看 target_state / target_source 为 None。
        target = {"commit": target_commit,
                  "short": short_sha(target_commit) if target_commit else None,
                  "ref": None, "state": None, "source": None, "warnings": []}
        target_error = None
        if doc:
            # 目标解析只看评估记录，与草稿能不能解析无关；草稿坏了也应带出目标字段。
            assessed_ref = str(prov.get("target_ref") or "").strip() or None
            (target["commit"], target["ref"], target["source"], target["state"],
             target["warnings"], target_error) = _target_for_row(
                root, assessed_ref, target_commit, target_ref=target_ref,
                explicit_commit=explicit_commit,
                configured_target_ref=configured_target_ref,
                configured_commit=configured_commit)
            target["short"] = short_sha(target["commit"]) if target["commit"] else None
        if draft_error:
            stale_reasons.append(draft_error)
        elif load_error:
            stale_reasons.append(load_error)
        elif not doc:
            stale_reasons.append("未评估")
        else:
            if target_error:
                stale_reasons.append(target_error)
            if not assessed:
                stale_reasons.append("评估记录缺 compared_against_commit")
            elif target["state"] is not None:
                # ref 本身的问题（不可用 / 与配置目标不一致）已经写明原因，不再跨 ref 判关系。
                pass
            elif not target["commit"]:
                target["state"] = "ref_missing"
                stale_reasons.append("没有可用的比较基准 commit")
            elif is_ancestor(root, assessed, target["commit"]):
                target["state"] = "ok"
                changed = knowledge_changes(root, assessed, target["commit"])
                if changed:
                    stale_reasons.append(f"知识库在评估后前进了 {len(changed)} 个文件")
            elif is_ancestor(root, target["commit"], assessed):
                # 方向是目标落后：文案不能沿用「前进了 N 个文件」。
                target["state"] = "target_behind"
                behind = knowledge_changes(root, target["commit"], assessed)
                stale_reasons.append(
                    f"目标 {short_sha(target['commit'])} 落后于评估基准 "
                    f"{short_sha(assessed)} 的 {len(behind)} 个知识文件")
            else:
                target["state"] = "not_comparable"
                stale_reasons.append("评估基准与目标不在同一历史线或被改写，无法比较")
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
            "target_commit": target["commit"],
            "target_short": target["short"],
            "target_ref": target["ref"],
            "target_state": target["state"],
            "target_source": target["source"],
            "target_warnings": target["warnings"],
            "stale": stale,
            "stale_reasons": stale_reasons,
            "gate": doc.get("promotion_gate") or {},
            "next_action": _action(a, human, stale, doc.get("human_decision_valid", True),
                                   target["state"] if not (draft_error or load_error) else None),
            "assessment_file": str((inbox / ".groom" / "assessments")) if doc else None,
        })
    assess_dir = inbox / ".groom" / "assessments"
    if assess_dir.is_dir():
        known_files = {sanitize_key(k) for k in known}
        for path in sorted(assess_dir.glob("*.yaml")):
            if path.stem not in known_files:
                rows.append({
                    "draft": path.stem, "orphan": True, "assessed": True,
                    "target_commit": target_commit,
                    "target_short": short_sha(target_commit) if target_commit else None,
                    "target_ref": None, "target_state": None, "target_source": None,
                    "target_warnings": [],
                    "stale": True, "stale_reasons": ["评估状态存在但 inbox 里找不到对应草稿"],
                    "next_action": "确认草稿是否已升格/删除；不要复用旧评估",
                })
    return rows


def key_ok_match(path: Path, row) -> bool:
    return path.stem == sanitize_key(str(row.get("draft") or ""))


def print_rows(rows, known_warnings=None):
    """一屏表格；「基准」列显示这一行实际比较的目标 commit（每行可能不同）。"""
    if not rows:
        print("inbox 中没有草稿。")
        return
    print(f"{'Draft':<38} {'评估':<14} {'候选':<22} {'人决定':<10} {'基准':<14} {'新鲜度':<6} 下一步")
    print("-" * 150)
    shown = set(known_warnings or ())
    for r in rows:
        if r.get("orphan"):
            print(f"{r['draft']:<38} {'（孤儿状态）':<14} {'':<22} {'':<10} {'—':<14} "
                  f"{'STALE':<6} {r['next_action']}")
            continue
        print(f"{str(r['draft'])[:37]:<38} {str(r.get('proposed_novelty') or '—'):<14} "
              f"{str(r.get('candidate_case') or '—')[:21]:<22} "
              f"{str(r.get('human_decision') or '—'):<10} "
              f"{str(r.get('target_short') or '—')[:12]:<14} "
              f"{'STALE' if r.get('stale') else 'fresh':<6} "
              f"{r.get('next_action')}")
        for reason in r.get("stale_reasons") or []:
            print(f"{'':<38} └ {reason}")
        for warning in r.get("target_warnings") or []:
            if warning in shown:
                continue
            shown.add(warning)
            print(f"{'':<38} ⚠ {warning}")


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


def _configured_target(root: Path):
    """读主检出 settings 的提 PR 目标 → {"remote", "base", "ref"}；没配置返回 None。

    lazy import pr_status：状态命令不该在没配目标时也加载平台适配器。读不出配置时按
    「未配置」处理，让下面的兜底与提示照常给出，而不是让整条状态命令失败。
    """
    try:
        from pr_status import load_target
        target = load_target(root)
    except Exception:
        return None
    if not isinstance(target, dict):
        return None
    remote = str(target.get("remote") or "").strip()
    base = str(target.get("base") or "").strip()
    if not remote or not base:
        return None
    return {"remote": remote, "base": base, "ref": f"refs/remotes/{remote}/{base}"}


def _fallback_target(root: Path):
    """没有可用目标 ref 时的兜底：origin/main → HEAD。返回 (commit, ref)。"""
    for ref in ("refs/remotes/origin/main", "HEAD"):
        commit = normalize_commit(root, ref)
        if commit:
            return commit, ref
    return None, None


def main():
    pin_utf8_stdio()
    ap = argparse.ArgumentParser(description="Groom 本地草稿状态与新鲜度")
    ap.add_argument("--repo", default=None)
    ap.add_argument("--target", default=None,
                    help="显式比较基准 ref/commit（优先于评估记录里的目标 ref）")
    ap.add_argument("--snapshot", default=None,
                    help="用快照 meta 的 ref 当显式目标（没有 ref 时用 commit；不 fetch）")
    ap.add_argument("--fetch", action="store_true",
                    help="先 fetch 配置目标的远端分支；未配置时 fetch origin main")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--decision-prompt", action="store_true",
                    help="表格后输出待决定草稿的问答块；不写状态")
    ap.add_argument("--check-stale", action="store_true", help="有 stale/未评估则退出 2")
    args = ap.parse_args()

    root = repo_root(Path(args.repo).resolve() if args.repo else Path.cwd())
    if args.target and not normalize_commit(root, args.target):
        print(f"显式目标 {args.target} 解析不到（先 fetch 或确认 ref/commit）", file=sys.stderr)
        return 3
    explicit_ref = args.target
    configured = None
    configured_commit = None
    fallback_ref = None
    meta_ref = None
    snapshot_warning = None
    target = None
    if args.snapshot:
        meta = load_json(Path(args.snapshot))
        target = meta.get("commit")
        inbox = shared_inbox(Path(meta["repo"]))
        meta_ref = str(meta.get("ref") or "").strip() or None
        if explicit_ref:
            # 显式 --target 覆盖 --snapshot 的基准。
            target = normalize_commit(root, explicit_ref) or target
        else:
            # 快照默认钉住 meta 的 commit；meta 的 ref 只在仍指向同一 commit 时使用。
            resolved = normalize_commit(root, meta_ref) if meta_ref else None
            if resolved and resolved == target:
                explicit_ref = meta_ref
            else:
                explicit_ref = target
                if not meta_ref:
                    snapshot_warning = (f"快照 meta 没有目标 ref，"
                                        f"按快照 commit {short_sha(target)} 比较")
                elif not resolved:
                    snapshot_warning = (f"快照记录的目标 ref {meta_ref} 解析不到，"
                                        f"按快照 commit {short_sha(target)} 比较")
                else:
                    snapshot_warning = (f"快照记录的目标 ref {meta_ref} 已前进到 "
                                        f"{short_sha(resolved)}，按快照 commit {short_sha(target)} 比较")
    else:
        configured = _configured_target(root)
        if args.fetch:
            if configured:
                run_git(["fetch", "--no-tags", configured["remote"], configured["base"]],
                        cwd=root, check=False)
            else:
                run_git(["fetch", "--no-tags", "origin", "main"], cwd=root, check=False)
        if configured:
            configured_commit = normalize_commit(root, configured["ref"])
        if explicit_ref:
            target = (normalize_commit(root, explicit_ref) or configured_commit
                      or _fallback_target(root)[0])
        elif configured_commit:
            target = configured_commit
        else:
            target, fallback_ref = _fallback_target(root)
        inbox = shared_inbox(root)
    if not target:
        print("取不到目标 commit（git 仓库或目标 ref 不可用）", file=sys.stderr)
        return 3

    configured_ref = configured["ref"] if configured else None
    if explicit_ref:
        target_source = "explicit"
        target_ref = explicit_ref
    elif configured_ref and configured_commit:
        target_source = "configured"
        target_ref = configured_ref
    else:
        target_source = "fallback"
        target_ref = fallback_ref

    warnings = []
    if snapshot_warning:
        warnings.append(snapshot_warning)
    if explicit_ref and not normalize_commit(root, explicit_ref):
        warnings.append(f"显式目标 ref {explicit_ref} 解析不到（先 fetch 或确认远端）")
    if configured_ref and not configured_commit:
        warnings.append(f"当前配置目标 {configured_ref} 解析不到（先 fetch 或确认远端）")
    if not explicit_ref and not configured_ref:
        warnings.append(f"目标未配置，按 {short_sha(target)} 比较")

    if explicit_ref:
        basis = f"比较基准 {explicit_ref}（显式）"
    elif configured_ref and configured_commit:
        basis = f"比较基准 {configured_ref}（配置目标）"
    elif configured_ref:
        basis = f"兜底基准 {fallback_ref or short_sha(target)}（配置目标解析不到）"
    elif args.snapshot:
        basis = f"快照基准 {short_sha(target)}"
    else:
        basis = f"兜底基准 {fallback_ref or short_sha(target)}（每行按评估记录比较）"

    rows = status_rows(root, target, inbox, target_ref=explicit_ref,
                       configured_target_ref=configured_ref)
    if args.json:
        print(dump_json({"schema": "groom-status/v1", "generated_at": now_iso(),
                         "target_commit": target, "target_short": short_sha(target),
                         "target_ref": target_ref, "target_source": target_source,
                         "configured_target_ref": configured_ref,
                         "target_warnings": warnings,
                         "inbox": str(inbox), "drafts": rows}))
    else:
        print(f"目标知识版本 {short_sha(target)} · {basis} · inbox {inbox}")
        for warning in warnings:
            print(f"⚠ {warning}")
        print_rows(rows, known_warnings=set(warnings))
        if args.decision_prompt:
            print_decision_prompts(rows)
    if args.check_stale:
        bad = [r for r in rows if r.get("stale")]
        if bad:
            print(f"\n{len(bad)} 份草稿是 stale（见上），按每行的下一步处理。", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
