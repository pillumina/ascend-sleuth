#!/usr/bin/env python3
# groom_candidates.py —— 从**快照**里取候选，生成给子 agent 的工作单
#
# 它只做"缩小阅读面"，不做语义判断：
#   - 输入 = 快照的 `knowledge/_index.yaml` 行（一行一条 case，不含全文）+ 本地草稿；
#   - 打分 = 报错字面量命中 / token 交集 / 标签与标题重叠（确定性、可复现）；
#   - 输出 = 每份草稿一张 work order：草稿本体 + 有界候选（默认 6，硬上限 8）的摘录。
#
# 为什么不直接把全库给 agent：一次 groom 十几份草稿 × 160 条 case，全量正文是十几万 token，
# 而且大部分与草稿无关。候选检索是**注意力预算**，语义判断才是 agent 的活。
#
# 为什么检索也要看 root_cause/fix（索引行里没有）：索引行只有标题/症状/token，而改写过的
# 重复根因常常症状词不同、根因词相同。本脚本用索引行做**召回**（宽松），再把候选全文的
# root_cause/fix 摘录给 agent 复核；不在这里做"像不像"的结论。
#
# 用法：
#   python3 scripts/groom_candidates.py --snapshot <meta.json> --all
#   python3 scripts/groom_candidates.py --snapshot <meta.json> --draft <draft.case.yaml> --out work.json
#   python3 scripts/groom_candidates.py --snapshot <meta.json> --all --offline   # 允许非权威快照
#
# 退出码：0 = 生成了工作单（可含 0 份草稿）；2 = 快照/索引不可用或参数不满足。

import argparse
import math
import re
import sys
from pathlib import Path

from _lexical import tokens_of
from _stdio import pin_utf8_stdio
from groom_common import (
    SCHEMA_WORK_ORDER, Draft, canonical_content_sha, case_fingerprint, draft_cases,
    draft_text_of, dump_json, find_drafts, load_json, load_yaml, now_iso, sanitize_key,
    shared_inbox, short_sha, work_order_id,
)

DEFAULT_TOP = 6
HARD_TOP = 8
DEFAULT_MIN = 3

# 中文按二元字组、英文按词；只用于"标题/症状"的弱重叠，不用于判重。
_CJK = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[a-z0-9][a-z0-9_.+-]{2,}")
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{2,7}\b")

# 高频通用字组：在标题/症状里几乎每篇都有，带不来区分度。IDF 已会降权，这里再明确剔除，
# 避免"训练/启动/失败"三个词把真正稀有的"链路/allreduce"压下去。
GENERIC_UNITS = {
    "训练", "启动", "失败", "问题", "导致", "异常", "报错", "出现", "进行", "无法",
    "没有", "一个", "以及", "可以", "需要", "使用", "通过", "由于", "同时", "仍然",
    "gradle", "error", "failed", "failure", "issue", "with", "from", "this", "that",
}


def text_units(text: str) -> set:
    out = set()
    for chunk in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        out.update(chunk[i:i + 2] for i in range(max(0, len(chunk) - 1)))
    for word in _WORD.findall((text or "").lower()):
        out.add(word)
    return out


def acronyms_of(text: str) -> set:
    return {m.group(0) for m in _ACRONYM.finditer(text or "")}


def overlap(a: set, b: set) -> int:
    return len(a & b)


def row_units(row) -> set:
    text = str(row.get("title") or "") + " " + " ".join(str(s) for s in (row.get("symptoms") or []))
    units = text_units(text)
    units |= {a.lower() for a in acronyms_of(text)}
    return units


def unit_weights(rows) -> dict:
    """罕见的字组/词权重更高：`训练` 这类高频词不该把 `链路`/`allreduce` 压下去。

    IDF 口径是确定性的、只依赖当前快照索引，不引入模型分数。
    """
    df = {}
    for row in rows:
        for unit in row_units(row):
            df[unit] = df.get(unit, 0) + 1
    n = max(1, len(rows))
    return {u: (0.0 if (u in GENERIC_UNITS or c > 0.2 * n) else math.log((1 + n) / (1 + c)) + 1.0)
            for u, c in df.items()}


def weighted_overlap(units: set, weights: dict) -> float:
    return round(sum(weights.get(u, 1.0) for u in units), 3)


def load_rows(snapshot: Path):
    index = snapshot / "knowledge" / "_index.yaml"
    if not index.exists():
        print(f"快照里没有索引：{index}（先跑 groom_snapshot.py）", file=sys.stderr)
        raise SystemExit(2)
    doc = load_yaml(index) or {}
    rows = []
    for ns, cells in (doc.get("namespaces") or {}).items():
        for cat, entries in (cells or {}).items():
            for e in entries or []:
                if isinstance(e, dict) and e.get("id"):
                    rows.append({"ns": ns, "category": cat, **e})
    return rows


def rank(row, draft_units, draft_tokens, draft_tags, draft_sig_text, draft_acronyms, weights):
    title_units = text_units(str(row.get("title") or ""))
    symptom_text = " ".join(str(s) for s in (row.get("symptoms") or []))
    symptom_units = text_units(symptom_text)
    row_text = str(row.get("title") or "") + " " + symptom_text
    row_acronyms = {a.lower() for a in acronyms_of(row_text)}
    row_tags = {str(t).lower() for t in (row.get("tags") or [])}
    sig_hits = sum(1 for s in (row.get("sig") or []) if str(s).lower() in draft_sig_text)
    tok_overlap = len(draft_tokens & {str(t) for t in (row.get("tok") or [])})
    acronym_hits = len(draft_acronyms & row_acronyms)
    tag_overlap = len(draft_tags & row_tags)
    title_overlap = overlap(title_units, draft_units)
    symptom_overlap = overlap(symptom_units, draft_units)
    w_title = weighted_overlap(title_units & draft_units, weights)
    w_symptom = weighted_overlap(symptom_units & draft_units, weights)
    score = (sig_hits * 6.0 + tok_overlap * 2.0 + acronym_hits * 3.0 + tag_overlap * 1.0
             + w_title * 2.0 + w_symptom * 1.0)
    reasons = []
    if sig_hits:
        reasons.append(f"报错字面量命中 {sig_hits}")
    if tok_overlap:
        reasons.append(f"token 交集 {tok_overlap}")
    if acronym_hits:
        reasons.append(f"缩写/术语交集 {acronym_hits}")
    if tag_overlap:
        reasons.append(f"标签交集 {tag_overlap}")
    if title_overlap:
        reasons.append(f"标题字组交集 {title_overlap}")
    if symptom_overlap:
        reasons.append(f"症状字组交集 {symptom_overlap}")
    return {
        "score": round(score, 3),
        "sig_hits": sig_hits,
        "token_overlap": tok_overlap,
        "acronym_hits": acronym_hits,
        "tag_overlap": tag_overlap,
        "title_overlap": title_overlap,
        "symptom_overlap": symptom_overlap,
        "reasons": reasons or ["同分类/同命名空间补位（无词法证据）"],
    }


def _trunc(value, n):
    if value is None:
        return None
    text = str(value).strip()
    return text if len(text) <= n else text[:n].rstrip() + "…"


def case_excerpt(path: Path, row, rel_file: str):
    """候选的**有界**摘录：只取判重需要的字段，不把整库正文送出去。"""
    case = {}
    try:
        data = load_yaml(path) or {}
        cases = data.get("cases") if isinstance(data, dict) else None
        if isinstance(cases, list) and cases:
            case = cases[0] if isinstance(cases[0], dict) else {}
    except Exception:
        case = {}
    symptoms = case.get("symptoms") or row.get("symptoms") or []
    if isinstance(symptoms, str):
        symptoms = [symptoms]
    diagnosis = []
    for step in (case.get("diagnosis") or [])[:3]:
        if isinstance(step, dict):
            diagnosis.append({
                "check": _trunc(step.get("check"), 200),
                "command_template": _trunc(step.get("command_template"), 200),
                "expected": _trunc(step.get("expected"), 160),
                "fix_on_mismatch": _trunc(step.get("fix_on_mismatch"), 200),
            })
    qc = case.get("quickly_check") or {}
    primary = (qc.get("primary") or {}) if isinstance(qc, dict) else {}
    return {
        "id": row.get("id"),
        "title": _trunc(case.get("title") or row.get("title"), 240),
        "category": row.get("category"),
        "namespace": row.get("ns"),
        "tags": (case.get("tags") or row.get("tags") or [])[:12],
        "symptoms": [_trunc(s, 240) for s in symptoms[:5]],
        "root_cause": _trunc(case.get("root_cause"), 500),
        "fix": _trunc(case.get("fix"), 500),
        "compat": _trunc(case.get("compat") or row.get("compat"), 240),
        "platforms": case.get("platforms") or [],
        "verification": case.get("verification") or {},
        "quickly_check": {
            "command_template": _trunc(primary.get("command_template"), 240),
            "expected": _trunc(primary.get("expected"), 200),
        },
        "diagnosis_head": diagnosis,
        "file": rel_file,
        "content_sha256": canonical_content_sha(case) if case else None,
        "retrieval": None,  # 由调用方填
    }


def draft_payload(draft: Draft, case: dict):
    symptoms = case.get("symptoms") or []
    if isinstance(symptoms, str):
        symptoms = [symptoms]
    return {
        "draft_key": draft.key,
        "layout": draft.layout,
        "case_file": str(draft.case_path),
        "case_id": case.get("id"),
        "title": case.get("title"),
        "category": case.get("category"),
        "tags": case.get("tags") or [],
        "symptoms": symptoms,
        "root_cause": case.get("root_cause"),
        "fix": case.get("fix"),
        "compat": case.get("compat"),
        "platforms": case.get("platforms") or [],
        "verification": case.get("verification") or {},
        "quickly_check": case.get("quickly_check") or {},
        "diagnosis": case.get("diagnosis") or [],
        "source_session": case.get("source_session"),
        "case_sha256": case_fingerprint(case),
    }


def select_candidates(rows, payload, top, min_candidates):
    draft_text = draft_text_of(payload)
    units = text_units(draft_text)
    toks = tokens_of(draft_text)
    tags = {str(t).lower() for t in (payload.get("tags") or [])}
    acronyms = {a.lower() for a in acronyms_of(draft_text)}
    low_text = draft_text.lower()
    weights = unit_weights(rows)

    scored = [(rank(r, units, toks, tags, low_text, acronyms, weights), r) for r in rows]
    scored.sort(key=lambda t: (-t[0]["score"], -t[0]["sig_hits"], -t[0]["token_overlap"],
                               str(t[1].get("id"))))

    category = payload.get("category")
    same_cat = [(s, r) for s, r in scored if not category or r.get("category") == category]
    # 同一分类里有词法证据的排前面；common/ 是跨框架权威记录，给固定席位；
    # 若不够 min_candidates，再用全库最高分补位（仍然有界）。
    selected, seen = [], set()

    def take(pair):
        s, r = pair
        ident = r.get("id")
        if ident in seen:
            return
        seen.add(ident)
        selected.append((s, r))

    for pair in same_cat:
        if len(selected) >= top:
            break
        if pair[0]["score"] > 0:
            take(pair)
    for pair in same_cat:
        if len(selected) >= top:
            break
        if pair[1].get("ns") == "common":
            take(pair)
    for pair in scored:
        if len(selected) >= max(min_candidates, 1) and len(selected) >= top:
            break
        if len(selected) < min_candidates:
            take(pair)

    selected = selected[:top]
    out = []
    for score, row in selected:
        rel = str(row.get("file") or "")
        path = (snapshot_path_root / rel) if rel else None
        excerpt = case_excerpt(path, row, rel) if path and path.exists() else {
            "id": row.get("id"), "title": _trunc(row.get("title"), 240),
            "category": row.get("category"), "namespace": row.get("ns"),
            "file": rel, "retrieval": None,
        }
        excerpt["retrieval"] = score
        out.append(excerpt)
    return out, len(scored), len(scored) - len(selected)


# 由 main 注入（避免把 snapshot 根一路传参）
snapshot_path_root = Path(".")


def main():
    global snapshot_path_root
    pin_utf8_stdio()
    ap = argparse.ArgumentParser(description="生成 Groom 子 agent 工作单（候选有界）")
    ap.add_argument("--snapshot", required=True, help="groom_snapshot.py --json 的 meta 文件")
    ap.add_argument("--draft", action="append", default=None, help="指定草稿 case 文件（可重复）")
    ap.add_argument("--all", action="store_true", help="处理共享 inbox 里的全部草稿")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP, help=f"每份草稿候选上限（默认 {DEFAULT_TOP}，硬上限 {HARD_TOP}）")
    ap.add_argument("--min-candidates", type=int, default=DEFAULT_MIN,
                    help="候选不足时用同分类/全库最高分补到至少 N 条（默认 3）")
    ap.add_argument("--out", default=None, help="工作单输出路径（默认共享 inbox 的 .groom/runs/）")
    ap.add_argument("--run-id", default=None, help="本次运行 id（默认按 commit + 时间生成）")
    args = ap.parse_args()

    meta = load_json(Path(args.snapshot))
    if not meta.get("ok"):
        print(f"快照不可用：{meta.get('fetch_error') or meta}", file=sys.stderr)
        return 2
    if not meta.get("authoritative"):
        print("注意：快照非权威（离线或索引不可用）——记录阶段会把评估标为不可升格。", file=sys.stderr)
    snapshot = Path(meta["worktree"])
    snapshot_path_root = snapshot
    top = max(1, min(args.top, HARD_TOP))
    min_candidates = max(0, min(args.min_candidates, top))

    inbox = shared_inbox(Path(meta["repo"]))
    if args.draft:
        drafts = []
        for p in args.draft:
            path = Path(p)
            if not path.is_absolute():
                path = (Path.cwd() / path).resolve()
            # 两种命名都要认：<id>.case.yaml 与 <uuid>/case.yaml
            drafts.append(Draft(key=path.parent.name if path.name == "case.yaml" else path.name.replace(".case.yaml", ""),
                                case_path=path, layout="directory" if path.name == "case.yaml" else "flat"))
    else:
        drafts = find_drafts(inbox)
    if not drafts:
        print("inbox 中没有草稿——本轮无需语义比对。")
        return 0

    rows = load_rows(snapshot)
    if not rows:
        print("快照索引为空——无法生成候选。", file=sys.stderr)
        return 2

    run_id = args.run_id or f"{short_sha(meta.get('commit'))}-{now_iso().replace(':', '').replace('-', '')[:15]}"
    out_path = Path(args.out) if args.out else (inbox / ".groom" / "runs" / sanitize_key(run_id) / "work-orders.json")

    orders = []
    for draft in drafts:
        cases = draft_cases(draft)
        if not cases:
            continue
        payload = draft_payload(draft, cases[0])
        candidates, pool_size, omitted = select_candidates(rows, payload, top, min_candidates)
        order = {
            "schema": SCHEMA_WORK_ORDER,
            "run_id": run_id,
            "draft": payload,
            "snapshot": {
                "commit": meta.get("commit"),
                "short": meta.get("short"),
                "ref": meta.get("ref"),
                "fresh": meta.get("fresh"),
                "authoritative": meta.get("authoritative"),
                "index_state": (meta.get("index") or {}).get("state"),
            },
            "candidates": candidates,
            "pool_size": pool_size,
            "omitted_candidates": omitted,
            "instructions": {
                "compare_each_candidate": True,
                "must_cover_all_candidates": True,
                "classifications": ["duplicate", "covered", "variant", "new_pattern", "ambiguous"],
                "conservative_rule": (
                    "只在根因与失效机制都被现有 case 支持时才判 duplicate/covered；"
                    "只是措辞相近、症状相同或主题相同 → variant 或 ambiguous；"
                    "证据不足 → ambiguous，不要猜。"
                ),
            },
        }
        order["work_order_id"] = work_order_id(order)
        orders.append(order)

    doc = {
        "schema": "groom-work-orders/v1",
        "run_id": run_id,
        "created_at": now_iso(),
        "snapshot": {
            "commit": meta.get("commit"), "short": meta.get("short"),
            "fresh": meta.get("fresh"), "authoritative": meta.get("authoritative"),
            "worktree": str(snapshot), "index": meta.get("index"),
        },
        "orders": orders,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(dump_json(doc), encoding="utf-8")
    print(f"工作单：{out_path}")
    print(f"  草稿 {len(orders)} 份 · 快照 {meta.get('short')} · 候选上限 {top}")
    for order in orders:
        cands = ", ".join(c["id"] for c in order["candidates"]) or "（无）"
        print(f"  - {order['draft']['draft_key']}: {len(order['candidates'])} 候选"
              f"（池 {order['pool_size']}，省略 {order['omitted_candidates']}）→ {cands}")
    if not meta.get("authoritative"):
        print("  ⚠ 快照非权威：本轮评估不得用于升格，需联网重跑。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
