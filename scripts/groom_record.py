#!/usr/bin/env python3
# groom_record.py —— 校验子 agent 结果、保守聚合、写本地评估状态
#
# 职责边界（这是整套 Agent Groom 的安全阀）：
#   - **校验**：子 agent 的 JSON 必须是工作单里列出的候选、枚举合法、每条候选都有结论；
#     缺一条、乱填一个 id、或分类不在词表里 → 整份草稿降级为 ambiguous + 人工复核。
#   - **保守聚合**：duplicate/covered 只有 high confidence 才可能成为建议；中/低置信度一律
#     降为 ambiguous。一个候选说重复、另一个说独立 → ambiguous。复核 agent 说 challenge /
#     false_merge_risk → ambiguous。
#   - **人机分家**：`human_decision` 只由 groom_decide.py 写；本脚本重跑时原样保留，
#     绝不覆盖，也不把 agent 建议写成决定。
#   - **provenance**：记录 compared_against_commit、候选清单、agent id、索引状态、是否权威。
#
# 子 agent 不写任何 Case 文件、不升格、不合并——它们只返回 JSON，本脚本只写本地 sidecar。
#
# 用法：
#   python3 scripts/groom_record.py --snapshot snapshot.json --work-orders work.json --results-dir results/
#   python3 scripts/groom_record.py ... --json
#   python3 scripts/groom_record.py --pr-marker --draft-key <key>
#
# 退出码：0 = 记录完成（可以含 review_required）；2 = 工作单/快照不可用；3 = 无有效结果。

import argparse
import hashlib
import json
import sys
from pathlib import Path

from _stdio import pin_utf8_stdio
from groom_common import (
    SCHEMA_ASSESSMENT, VALID_AXIS_VERDICTS, VALID_AXES, VALID_CLASSIFICATIONS,
    VALID_CONFIDENCE, CANONICAL_CONTENT_FIELDS, assessment_path, canonical_content_sha,
    case_fingerprint, compute_assessment_id, dump_json, load_assessment,
    load_json, load_yaml, now_iso, shared_inbox, work_order_id, write_assessment,
)

MERGE_CLASSES = ("duplicate", "covered")
MAX_RATIONALE = 4000


def apply_evidence_guard(comparisons):
    """用 agent 自己给出的证据轴，拦住与分类自相矛盾的结论。

    这不是第二个语义比较器：它只读 `evidence` 里已经写下的 same/different/unknown。
    规则（保守方向）：
      - 判 duplicate/covered，但 root_cause 或 mechanism 不是 same → 降为 ambiguous；
      - 根因/机制相同、但 fix 明确不同 → 降为 variant（是修复补充/变体，不是同一条）；
      - 判 variant，但 root_cause 与 mechanism 都明确不同 → 降为 ambiguous
        （不同根因不是 variant；但也不自动判成 new_pattern，交人）。
    没有 evidence 轴（None/缺字段）不视为 same——合并结论必须有证据。
    """
    reasons = []
    for c in comparisons:
        cls = c.get("_classification")
        ev = c.get("evidence") if isinstance(c.get("evidence"), dict) else {}
        root = str(ev.get("root_cause") or "unknown")
        mech = str(ev.get("mechanism") or "unknown")
        fix = str(ev.get("fix") or "unknown")
        before = cls
        if cls in MERGE_CLASSES:
            if root != "same" or mech != "same":
                cls, why = "ambiguous", f"根因/机制证据不支持合并（root={root}, mechanism={mech}）"
            elif fix == "different":
                cls, why = "variant", "根因与机制相同但修复不同——是修复补充/变体，不是同一条"
            else:
                why = None
        elif cls == "variant" and root == "different" and mech == "different":
            cls, why = "ambiguous", "variant 但根因与机制都明确不同——不自动判为同一主题的变体"
        else:
            why = None
        if cls != before:
            c["_guard"] = why
            reasons.append(f"证据一致性校验：{c.get('candidate_case')} 由 {before} 降为 {cls}（{why}）")
        c["_classification"] = cls
    return reasons


# ---------------------------------------------------------------- 读取与规范化

def _norm_classification(value):
    v = str(value or "").strip().lower()
    alias = {
        "duplicate": "duplicate", "exact_duplicate": "duplicate", "exact": "duplicate",
        "covered": "covered", "covered_by": "covered", "existing_coverage": "covered",
        "variant": "variant", "variant_of": "variant",
        "new": "new_pattern", "new_pattern": "new_pattern", "novel": "new_pattern",
        "ambiguous": "ambiguous", "uncertain": "ambiguous",
        "insufficient_evidence": "ambiguous", "insufficient": "ambiguous",
    }
    return alias.get(v, v)


def _norm_confidence(value):
    v = str(value or "").strip().lower()
    return {"high": "high", "medium": "medium", "mid": "medium", "low": "low"}.get(v, v)


def _result_paths(results_dir: Path):
    if not results_dir.is_dir():
        return [], []
    primary = sorted(p for p in results_dir.glob("*.result.json"))
    reviews = sorted(p for p in results_dir.glob("*.review*.json"))
    return primary, reviews


def load_results(results_dir: Path):
    """返回 (primary_by_key, reviews_by_key, load_errors)。"""
    primary, reviews = _result_paths(results_dir)
    prim, revs, errors = {}, {}, []
    for path in primary:
        try:
            doc = load_json(path)
        except Exception as exc:
            errors.append(f"{path.name}: JSON 解析失败（{exc}）")
            continue
        key = str(doc.get("draft_key") or doc.get("draft") or "").strip()
        if not key:
            errors.append(f"{path.name}: 缺 draft_key")
            continue
        doc["_file"] = path.name
        doc["_sha256"] = _file_sha(path)
        if key in prim:
            errors.append(f"{path.name}: 同一草稿有第二份 primary 结果（已保留第一份）")
            continue
        prim[key] = doc
    for path in reviews:
        try:
            doc = load_json(path)
        except Exception as exc:
            errors.append(f"{path.name}: JSON 解析失败（{exc}）")
            continue
        key = str(doc.get("draft_key") or doc.get("draft") or "").strip()
        if not key:
            errors.append(f"{path.name}: 缺 draft_key")
            continue
        doc["_file"] = path.name
        doc["_sha256"] = _file_sha(path)
        revs.setdefault(key, []).append(doc)
    return prim, revs, errors


# ---------------------------------------------------------------- 校验

def validate_primary(order, doc):
    errors = []
    if not isinstance(doc.get("comparisons"), list) or not doc["comparisons"]:
        errors.append("comparisons 必须是非空列表")
        return errors
    allowed = {str(c.get("id")) for c in order.get("candidates") or []}
    seen = {}
    for i, cmp in enumerate(doc["comparisons"], 1):
        if not isinstance(cmp, dict):
            errors.append(f"comparisons[{i}] 不是对象")
            continue
        cid = str(cmp.get("candidate_case") or cmp.get("candidate") or "").strip()
        if cid not in allowed:
            errors.append(f"comparisons[{i}] 的候选 `{cid}` 不在工作单里（允许：{sorted(allowed)}）")
            continue
        if cid in seen:
            errors.append(f"候选 `{cid}` 出现了两次")
            continue
        seen[cid] = cmp
        classification = _norm_classification(cmp.get("classification"))
        if classification not in VALID_CLASSIFICATIONS:
            errors.append(f"候选 `{cid}` 的 classification 非法：`{cmp.get('classification')}`")
        cmp["_classification"] = classification
        confidence = _norm_confidence(cmp.get("confidence"))
        if confidence not in VALID_CONFIDENCE:
            errors.append(f"候选 `{cid}` 的 confidence 非法：`{cmp.get('confidence')}`")
        cmp["_confidence"] = confidence
        if not str(cmp.get("rationale") or "").strip():
            errors.append(f"候选 `{cid}` 缺 rationale")
        evidence = cmp.get("evidence")
        if evidence is not None and not isinstance(evidence, dict):
            errors.append(f"候选 `{cid}` 的 evidence 不是对象")
        elif isinstance(evidence, dict):
            for axis, verdict in evidence.items():
                if axis not in VALID_AXES:
                    errors.append(f"候选 `{cid}` 的 evidence 轴非法：`{axis}`")
                elif str(verdict) not in VALID_AXIS_VERDICTS:
                    errors.append(f"候选 `{cid}` 的 evidence.{axis} 取值非法：`{verdict}`")
    missing = sorted(allowed - set(seen))
    if missing:
        errors.append(f"未覆盖工作单里的候选：{missing}（必须逐条给结论，不能只评价看起来像的）")
    doc["_by_candidate"] = seen
    return errors


# ---------------------------------------------------------------- 聚合

def aggregate(order, doc, review_docs, meta):
    reasons = []
    comparisons = doc.get("_by_candidate") or {}
    reasons.extend(apply_evidence_guard(comparisons.values()))

    strong = [c for c in comparisons.values()
              if c.get("_classification") in MERGE_CLASSES and c.get("_confidence") == "high"]
    medium_merge = [c for c in comparisons.values()
                    if c.get("_classification") in MERGE_CLASSES and c.get("_confidence") == "medium"]
    variants = [c for c in comparisons.values() if c.get("_classification") == "variant"]
    news = [c for c in comparisons.values() if c.get("_classification") == "new_pattern"]
    ambiguous = [c for c in comparisons.values() if c.get("_classification") == "ambiguous"]

    if ambiguous:
        reasons.append(f"{len(ambiguous)} 条候选被 agent 判为 ambiguous")
    low = [c for c in comparisons.values() if c.get("_confidence") == "low"]
    if low:
        reasons.append(f"{len(low)} 条候选置信度为 low")

    proposed, candidate, confidence = "ambiguous", None, "low"

    if strong:
        ids = sorted({str(c.get("candidate_case") or c.get("candidate")) for c in strong})
        if len(ids) > 1:
            reasons.append(f"多个候选被高置信度判为重复/覆盖：{ids}——不自动选一个")
        else:
            candidate = ids[0]
            # duplicate 优先于 covered（更具体）
            cls = "duplicate" if any(c.get("_classification") == "duplicate" for c in strong) else "covered"
            proposed, confidence = cls, "high"
    elif medium_merge:
        reasons.append("只有中置信度的重复/覆盖建议——按保守规则降为 ambiguous")
    elif variants:
        ids = sorted({str(c.get("candidate_case") or c.get("candidate")) for c in variants})
        if len(ids) == 1:
            confidence = "high" if all(c.get("_confidence") == "high" for c in variants) else "medium"
            proposed, candidate = "variant", ids[0]
        else:
            reasons.append(f"variant 指向多个候选：{ids}——不自动选一个")
    elif news and len(news) == len(comparisons):
        confidences = {c.get("_confidence") for c in news}
        if confidences <= {"high"}:
            proposed, confidence = "new_pattern", "high"
        elif confidences <= {"high", "medium"}:
            proposed, confidence = "new_pattern", "medium"
        else:
            reasons.append("new_pattern 结论含 low 置信度")
    else:
        reasons.append("候选结论不一致或不足以支持一个分类")

    # 复核 agent：只能往保守方向拉，不能把 ambiguous 变成 covered
    for review in review_docs:
        verdict = str(review.get("verdict") or "").strip().lower()
        if verdict in ("challenge", "challenged", "reject") or review.get("false_merge_risk") is True:
            proposed, candidate, confidence = "ambiguous", None, "low"
            reasons.append("复核 agent challenge / 标记 false_merge_risk")
        elif verdict in ("insufficient", "insufficient_evidence"):
            proposed, candidate, confidence = "ambiguous", None, "low"
            reasons.append("复核 agent 认为证据不足")
        issues = review.get("issues") or []
        if issues:
            reasons.extend(f"复核：{i}" for i in issues[:5])

    authoritative = bool(meta.get("authoritative"))
    if not authoritative:
        reasons.append("快照非权威（离线或索引不可用）——不能据此升格")

    review_required = (
        proposed != "new_pattern"
        or confidence != "high"
        or bool(ambiguous or low)
        or bool(review_docs)
        or not authoritative
    )

    if proposed == "new_pattern" and confidence == "high" and authoritative and not review_docs:
        review_required = False

    rationale = str(doc.get("rationale") or "").strip()
    if not rationale:
        picked = comparisons.get(candidate) if candidate else None
        rationale = str((picked or {}).get("rationale") or "").strip()
    if not rationale and reasons:
        rationale = "；".join(reasons[:3])
    if not rationale:
        rationale = "agent 未给出可读理由"

    return {
        "proposed_novelty": proposed,
        "candidate_case": candidate,
        "confidence": confidence,
        "review_required": review_required,
        "rationale": rationale[:MAX_RATIONALE],
        "review_reasons": reasons,
        "alternatives": [
            {
                "candidate_case": str(c.get("candidate_case") or c.get("candidate")),
                "classification": c.get("_classification"),
                "confidence": c.get("_confidence"),
                "rationale": str(c.get("rationale") or "")[:800],
            }
            for c in comparisons.values()
            if str(c.get("candidate_case") or c.get("candidate")) != candidate
        ],
    }


# ---------------------------------------------------------------- 状态文档

def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _first_case(path: Path):
    data = load_yaml(path)
    if not isinstance(data, dict) or not isinstance(data.get("cases"), list) or not data["cases"]:
        return None
    first = data["cases"][0]
    return first if isinstance(first, dict) else None


def validate_binding(order, meta, result, snapshot_root: Path):
    """校验快照 ↔ 工作单 ↔ 结果 ↔ 草稿内容 ↔ 候选内容是否同一次评估。

    不信任"从预期路径加载"这件事：commit、工作单 id、草稿指纹、候选 id 与候选内容
    都在这里重新计算并对照。
    """
    errors = []
    draft = order.get("draft") or {}
    key = str(draft.get("draft_key") or "")
    order_snapshot = order.get("snapshot") or {}
    if order_snapshot.get("commit") != meta.get("commit"):
        errors.append(
            f"工作单快照 {str(order_snapshot.get('commit'))[:12]} 与 --snapshot 的 "
            f"{str(meta.get('commit'))[:12]} 不一致"
        )
    draft_path = Path(str(draft.get("case_file") or ""))
    if not draft_path.is_absolute():
        draft_path = Path(meta.get("repo") or Path.cwd()) / draft_path
    cases = []
    if draft_path.exists():
        try:
            first = _first_case(draft_path)
            cases = [first] if first else []
        except Exception as exc:
            errors.append(f"草稿读不出来：{exc}")
    else:
        errors.append(f"草稿文件不存在：{draft_path}")
    draft_case = cases[0] if cases else {}
    current_draft_sha = case_fingerprint(draft_case) if draft_case else None
    if current_draft_sha and current_draft_sha != draft.get("case_sha256"):
        errors.append(
            "草稿在生成工作单之后被改过（工作单 "
            f"{str(draft.get('case_sha256'))[:12]} ≠ 现状 {current_draft_sha[:12]}）"
        )

    candidate_bindings = []
    for cand in order.get("candidates") or []:
        rel = str(cand.get("file") or "")
        cpath = snapshot_root / rel
        ccase = _first_case(cpath) if cpath.exists() else None
        if ccase is None:
            errors.append(f"候选 {cand.get('id')} 的内容在快照里读不到：{rel}")
            continue
        csha = canonical_content_sha(ccase)
        if cand.get("content_sha256") and cand["content_sha256"] != csha:
            errors.append(f"候选 {cand.get('id')} 内容与工作单不一致")
        candidate_bindings.append({"id": str(cand.get("id")), "content_sha256": csha})

    work_id = work_order_id(order)
    if result is not None:
        for field, expected in (
            ("work_order_id", work_id),
            ("snapshot_commit", meta.get("commit")),
            ("draft_sha256", draft.get("case_sha256")),
        ):
            if str(result.get(field) or "") != str(expected or ""):
                errors.append(
                    f"结果字段 {field} 与工作单不一致（结果 {str(result.get(field))[:16]}，"
                    f"期望 {str(expected)[:16]}）"
                )
        got_ids = sorted(str(x) for x in (result.get("candidate_ids") or []))
        want_ids = sorted(str(c.get("id")) for c in order.get("candidates") or [])
        if got_ids != want_ids:
            errors.append(f"结果候选集与工作单不一致（结果 {got_ids}，工作单 {want_ids}）")

    return {
        "ok": not errors,
        "errors": errors,
        "draft_case": draft_case,
        "draft_sha256": draft.get("case_sha256"),
        "content_sha256": canonical_content_sha(draft_case) if draft_case else None,
        "candidate_bindings": candidate_bindings,
        "work_order_id": work_id,
    }


def _history(existing):
    hist = existing.get("history") if isinstance(existing, dict) else None
    return list(hist) if isinstance(hist, list) else []


def build_assessment(order, doc, review_docs, meta, existing, errors, binding):
    draft = order.get("draft") or {}
    key = str(draft.get("draft_key") or "")
    human = dict(existing.get("human_decision")) if isinstance(existing.get("human_decision"), dict) else None
    binding_ok = bool(binding.get("ok"))

    if binding_ok and not errors:
        assessment = aggregate(order, doc, review_docs, meta)
    else:
        assessment = {
            "proposed_novelty": "ambiguous",
            "candidate_case": None,
            "confidence": "low",
            "review_required": True,
            "rationale": ("证据绑定失败：" if not binding_ok else "子 agent 结果未通过校验：")
                         + "；".join((binding.get("errors") or errors)[:5]),
            "review_reasons": (binding.get("errors") or errors)[:10],
            "alternatives": [],
        }

    result_hashes = [doc.get("_sha256")] if doc and doc.get("_sha256") else []
    reviewer_hashes = [r.get("_sha256") for r in review_docs if r.get("_sha256")]
    assessment_id = None
    if binding_ok:
        assessment_id = compute_assessment_id(
            commit=meta.get("commit"), draft_key=key,
            draft_sha=binding.get("draft_sha256") or "",
            content_sha=binding.get("content_sha256") or "",
            candidate_bindings=binding.get("candidate_bindings") or [],
            result_hashes=result_hashes, reviewer_hashes=reviewer_hashes,
        )

    human_ok = bool(
        human and assessment_id
        and human.get("assessment_id") == assessment_id
        and human.get("content_sha256") == (binding.get("content_sha256") or "")
    )
    stale_after_decision = bool(human and not human_ok)

    gate_reason = None
    if not binding_ok:
        gate_reason = "binding-mismatch"
    elif not meta.get("authoritative"):
        gate_reason = "stale-snapshot"
    elif human and not human_ok:
        gate_reason = "approval-stale"
    elif human and human.get("decision") == "reject":
        gate_reason = "human-rejected"
    elif human and human.get("decision") == "defer":
        gate_reason = "deferred"
    elif assessment["proposed_novelty"] in MERGE_CLASSES + ("variant",) and not human:
        gate_reason = "pending-human-review"
    elif assessment["review_required"] and not human:
        gate_reason = "pending-human-review"

    now = now_iso()
    history = _history(existing)
    history.append({
        "at": now,
        "event": "assessed",
        "proposed_novelty": assessment["proposed_novelty"],
        "candidate_case": assessment.get("candidate_case"),
        "confidence": assessment.get("confidence"),
        "review_required": assessment.get("review_required"),
        "knowledge_commit": meta.get("commit"),
        "assessment_id": assessment_id,
        "content_sha256": binding.get("content_sha256"),
        "agent": (doc.get("agent") or {}).get("id") if isinstance(doc.get("agent"), dict) else None,
    })

    return {
        "schema": SCHEMA_ASSESSMENT,
        "draft": key,
        "draft_case_id": draft.get("case_id"),
        "draft_category": draft.get("category"),
        "draft_file": draft.get("case_file"),
        "draft_sha256": draft.get("case_sha256"),
        "assessment_id": assessment_id,
        "content_binding": {
            "sha256": binding.get("content_sha256"),
            "fields": list(CANONICAL_CONTENT_FIELDS),
            "candidate_bindings": binding.get("candidate_bindings") or [],
        },
        "assessed_at": now,
        "assessment": assessment,
        "human_decision": human,
        "human_decision_valid": human_ok,
        "review_state": ("binding-failed" if not binding_ok
                         else ("revalidation-needed" if stale_after_decision
                               else ("decided" if human else "pending-review"))),
        "promotion_gate": {"allowed": gate_reason is None, "blocked_reason": gate_reason},
        "provenance": {
            "compared_against_commit": meta.get("commit"),
            "compared_against_short": meta.get("short"),
            "target_ref": meta.get("ref"),
            "snapshot_fresh": meta.get("fresh"),
            "snapshot_authoritative": meta.get("authoritative"),
            "index_state": (meta.get("index") or {}).get("state"),
            "knowledge_worktree": meta.get("worktree"),
            "work_order_id": binding.get("work_order_id"),
            "binding_ok": binding_ok,
            "binding_errors": list(binding.get("errors") or []),
            "candidates": [str(c.get("id")) for c in order.get("candidates") or []],
            "candidate_files": {
                str(c.get("id")): c.get("file") for c in order.get("candidates") or []
            },
            "candidate_bindings": binding.get("candidate_bindings") or [],
            "result_sha256": result_hashes,
            "reviewer_sha256": reviewer_hashes,
            "pool_size": order.get("pool_size"),
            "omitted_candidates": order.get("omitted_candidates"),
            "agents": [
                {"role": "comparator", **(doc.get("agent") or {})},
            ] + [
                {"role": "reviewer", **(r.get("agent") or {})} for r in review_docs
            ],
            "result_files": [doc.get("_file")] + [r.get("_file") for r in review_docs],
            "recorded_at": now,
            "tool": "groom-record/v2",
        },
        "history": history[-50:],
    }


def stable_view(doc):
    """幂等比较：时间戳与 history 不参与。"""
    clone = json.loads(json.dumps(doc, ensure_ascii=False))
    clone.pop("assessed_at", None)
    clone.pop("history", None)
    if isinstance(clone.get("provenance"), dict):
        clone["provenance"].pop("recorded_at", None)
    return clone


# ---------------------------------------------------------------- 报告 / marker

def print_report(doc, path):
    a = doc.get("assessment") or {}
    human = doc.get("human_decision") or {}
    gate = doc.get("promotion_gate") or {}
    print(f"\nDraft: {doc.get('draft')}（建议 id: {doc.get('draft_case_id') or '未填'}）")
    print(f"  知识快照: {doc.get('provenance', {}).get('compared_against_short')}"
          f" · {'fresh' if doc.get('provenance', {}).get('snapshot_fresh') else 'STALE'}")
    print(f"  评估: {str(a.get('proposed_novelty')).upper()}"
          + (f"（候选 {a.get('candidate_case')}）" if a.get("candidate_case") else "")
          + f" · confidence={a.get('confidence')}"
          + (" · REVIEW REQUIRED" if a.get("review_required") else ""))
    print(f"  理由: {a.get('rationale')}")
    if a.get("review_reasons"):
        print(f"  待核: {'；'.join(a['review_reasons'][:5])}")
    print(f"  人决定: {human.get('decision') or '未决定'}"
          + (f"（{human.get('by')}）" if human.get("by") else ""))
    if gate.get("blocked_reason"):
        print(f"  升格: 阻塞（{gate['blocked_reason']}）")
    else:
        print("  升格: 可进入既有升格闸门（仍需人审）")
    print(f"  状态文件: {path}")
    if a.get("proposed_novelty") in MERGE_CLASSES:
        print("  可做: 复核候选 case / 附证据 / 保留为独立 variant / 延后")
    elif a.get("proposed_novelty") == "variant":
        print("  可做: 并入候选（扩 compat / 补症状）/ 保留独立 / 延后")


def pr_marker(doc, submitted_case_id=None):
    a = doc.get("assessment") or {}
    human = doc.get("human_decision") or {}
    binding = doc.get("content_binding") or {}
    human_valid = bool(
        doc.get("human_decision_valid")
        and human.get("assessment_id")
        and human.get("assessment_id") == doc.get("assessment_id")
        and human.get("content_sha256") == binding.get("sha256")
    )
    decision = human.get("decision") if human_valid else "pending"
    candidate = human.get("candidate_case") if human_valid else a.get("candidate_case")
    return (
        "<!-- groom-assessment\n"
        "schema: groom-pr/v2\n"
        f"draft: {doc.get('draft')}\n"
        f"case_id: {doc.get('draft_case_id') or ''}\n"
        f"submitted_case_id: {submitted_case_id or doc.get('draft_case_id') or ''}\n"
        f"category: {doc.get('draft_category') or ''}\n"
        f"assessed_commit: {doc.get('provenance', {}).get('compared_against_commit')}\n"
        f"assessment_id: {doc.get('assessment_id') or ''}\n"
        f"assessed_content_sha256: {binding.get('sha256') or ''}\n"
        f"proposed_novelty: {a.get('proposed_novelty')}\n"
        f"candidate_case: {candidate or ''}\n"
        f"human_decision: {decision}\n"
        f"human_decision_assessment_id: {human.get('assessment_id') if human_valid else ''}\n"
        f"human_decision_content_sha256: {human.get('content_sha256') if human_valid else ''}\n"
        f"review_required: {'true' if a.get('review_required') else 'false'}\n"
        f"approval_stale: {'true' if human and not human_valid else 'false'}\n"
        "-->\n"
    )


def main():
    pin_utf8_stdio()
    ap = argparse.ArgumentParser(description="记录 Agent Groom 评估（校验 + 保守聚合 + 本地状态）")
    ap.add_argument("--snapshot", default=None, help="groom_snapshot.py --json 的 meta")
    ap.add_argument("--work-orders", default=None, help="groom_candidates.py 生成的工作单")
    ap.add_argument("--results-dir", default=None, help="子 agent 结果目录（*.result.json / *.review*.json）")
    ap.add_argument("--draft-key", default=None, help="--pr-marker 时指定草稿 key")
    ap.add_argument("--submitted-case-id", default=None,
                    help="--pr-marker 时最终提交的 case id（升格时改了 id 就填这里）")
    ap.add_argument("--pr-marker", action="store_true", help="输出可贴进 PR body 的 provenance marker")
    ap.add_argument("--json", action="store_true", help="输出机器可读摘要")
    ap.add_argument("--report", action="store_true", help="打印逐草稿的人读报告")
    args = ap.parse_args()

    if args.pr_marker:
        if not args.draft_key:
            ap.error("--pr-marker 需要 --draft-key")
        # 找 inbox：有 --snapshot 用它，否则用当前仓库
        if args.snapshot:
            meta = load_json(Path(args.snapshot))
            inbox = shared_inbox(Path(meta["repo"]))
        else:
            meta = {}
            inbox = shared_inbox(Path.cwd())
        doc = load_assessment(inbox, args.draft_key)
        if not doc:
            print(f"没有找到 {args.draft_key} 的评估状态", file=sys.stderr)
            return 3
        print(pr_marker(doc, submitted_case_id=args.submitted_case_id), end="")
        return 0

    if not (args.snapshot and args.work_orders and args.results_dir):
        ap.error("需要 --snapshot / --work-orders / --results-dir（或用 --pr-marker）")

    meta = load_json(Path(args.snapshot))
    orders_doc = load_json(Path(args.work_orders))
    if not meta.get("ok"):
        print(f"快照不可用：{meta.get('fetch_error')}", file=sys.stderr)
        return 2
    orders = orders_doc.get("orders") or []
    if not orders:
        print("工作单里没有草稿（跳过）")
        return 0

    prim, revs, load_errors = load_results(Path(args.results_dir))
    inbox = shared_inbox(Path(meta["repo"]))
    by_key = {str(o["draft"]["draft_key"]): o for o in orders}
    snapshot_root = Path(meta.get("worktree") or "")

    summaries, written, unchanged = [], [], []
    any_binding_failure = False
    for key, order in by_key.items():
        doc = prim.get(key)
        # 只把与本草稿有关的读取错误带进来：结果目录里别的草稿坏了，不应污染这一份。
        errors = [e for e in load_errors if key.lower() in str(e).lower()]
        if doc is None:
            errors = errors or ["没有收到该草稿的比对结果"]
        else:
            errors += validate_primary(order, doc)
        review_docs = revs.get(key, [])
        binding = validate_binding(order, meta, doc, snapshot_root)
        expected_work = work_order_id(order)
        for review in review_docs:
            for field, expected in (
                ("work_order_id", expected_work),
                ("snapshot_commit", meta.get("commit")),
                ("draft_sha256", order.get("draft", {}).get("case_sha256")),
            ):
                if str(review.get(field) or "") != str(expected or ""):
                    binding["errors"].append(
                        f"复核结果 {review.get('_file')} 的 {field} 与工作单不一致"
                    )
                    binding["ok"] = False
        if not binding["ok"]:
            any_binding_failure = True
            errors = list(binding["errors"]) + errors

        existing = {}
        path = assessment_path(inbox, key)
        if path.exists():
            try:
                existing = load_assessment(inbox, key)
            except Exception as exc:
                # 半份/损坏的旧状态：留档再重写，不静默覆盖掉唯一副本
                backup = path.with_suffix(path.suffix + f".corrupt-{now_iso().replace(':', '')}")
                try:
                    path.replace(backup)
                except OSError:
                    pass
                errors.append(f"旧状态解析失败，已备份到 {backup.name}（{exc}）")
                existing = {}

        new_doc = build_assessment(order, doc or {}, review_docs, meta, existing, errors, binding)
        if existing and stable_view(existing) == stable_view(new_doc):
            unchanged.append(key)
            summaries.append({"draft": key, "state": "unchanged",
                              "assessment": new_doc["assessment"],
                              "human_decision": new_doc.get("human_decision"),
                              "gate": new_doc.get("promotion_gate")})
        else:
            write_assessment(inbox, key, new_doc)
            written.append(key)
            summaries.append({"draft": key, "state": "written",
                              "path": str(assessment_path(inbox, key)),
                              "assessment": new_doc["assessment"],
                              "human_decision": new_doc.get("human_decision"),
                              "gate": new_doc.get("promotion_gate")})
        if args.report:
            print_report(new_doc, assessment_path(inbox, key))

    if args.json:
        print(dump_json({"schema": "groom-record-summary/v1", "run_id": orders_doc.get("run_id"),
                         "written": written, "unchanged": unchanged, "drafts": summaries}))
    else:
        print(f"记录完成：写入 {len(written)} 份、未变 {len(unchanged)} 份"
              f"（快照 {meta.get('short')}）")
        for s in summaries:
            a = s["assessment"]
            print(f"  - {s['draft']}: {a.get('proposed_novelty')}"
                  + (f" → {a.get('candidate_case')}" if a.get("candidate_case") else "")
                  + ("（需复核）" if a.get("review_required") else "")
                  + ("" if s["state"] == "written" else "（未变）"))
        if load_errors:
            print("  ⚠ 结果目录有读取问题：" + "；".join(load_errors[:3]))
    return 2 if any_binding_failure else 0


if __name__ == "__main__":
    sys.exit(main())
