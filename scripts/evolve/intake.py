"""把已闭环的诊断变成候选样本：抽取、完整性、查重。

只做候选，不进评测池；答案由人确认。``provenance`` 记录这条从哪来，
``completeness`` 回答「还差什么」，查重同时看本地队列、S2 校准集、
封存对照集与知识库吸收状态。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .contracts import Sample, now_iso, source_needs_provenance

TRACE_LIMIT = 2400
SYMPTOM_LIMIT = 1200
RESOLUTION_LIMIT = 4000

STATE_ORDER = (
    "missing_source", "absorbed", "missing_answer", "non_diagnostic",
    "not_sanitized", "duplicate_sample", "missing_trace",
)
MARKER_RE = re.compile(r"(现象|根因|处置|排除链|结论|修复|已沉淀)[：:]")


class IntakeError(ValueError):
    pass


def _one_line(text: Any, limit: int = 400) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: max(limit - 1, 1)] + "…"


def _text_block(text: Any, limit: int = TRACE_LIMIT) -> str:
    value = str(text or "").strip()
    return value if len(value) <= limit else value[: max(limit - 1, 1)] + "…"


def _segments(text: str) -> Dict[str, str]:
    """按中文标签切段，不要求空行；真实 summary 常是连续叙述。"""
    matches = list(MARKER_RE.finditer(text or ""))
    out: Dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text or "")
        value = (text or "")[match.end():end].strip()
        if value and match.group(1) not in out:
            out[match.group(1)] = value
    return out


def _phenomenon(summary: str, user_content: str = "") -> str:
    parts = _segments(summary)
    if parts.get("现象"):
        return parts["现象"]
    # 没有「现象」段时不拿 summary 的任何前缀当现象：summary 是 agent 的结论。
    return _one_line(user_content)


def _proposed_resolution(summary: str) -> str:
    parts = _segments(summary)
    values = [parts[key] for key in ("根因", "处置", "修复") if parts.get(key)]
    return "\n\n".join(values)


def sample_id_for(prefix: str, stem: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-")
    return f"{prefix}-{safe}"[:100].rstrip("-") or prefix


def _issue_number(source: str) -> Optional[int]:
    text = str(source or "")
    match = re.search(r"issues?/(\d{3,6})(?:\D|$)", text)
    if match:
        return int(match.group(1))
    match = re.search(r"#(\d{3,6})(?:\D|$)", text)
    if match:
        return int(match.group(1))
    if "/pull/" in text:
        return None
    for item in reversed(re.findall(r"-(\d{3,6})(?=[-._/]|$)", text)):
        if re.fullmatch(r"(?:19|20)\d{2}", item):
            continue
        return int(item)
    return None


def _confidence_from_case(case: Dict[str, Any]) -> str:
    source = str((case.get("verification") or {}).get("source") or "").lower()
    if "issue" in source and ("closed" in source or "verified" in source):
        return "issue-verified"
    if "maintainer" in source or "upstream" in source:
        return "maintainer-reviewed"
    return "agent-reviewed"


def extract_trace(trace_path: Path, root: Path) -> Dict[str, Any]:
    """从一条 diagnose trace 生成候选样本参数；不写本地队列。"""
    trace_path = Path(trace_path)
    try:
        doc = yaml.safe_load(trace_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise IntakeError(f"cannot read trace {trace_path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise IntakeError("trace must be an object")
    session = str(doc.get("session_id") or trace_path.stem)
    summary = str(doc.get("summary") or "").strip()
    user = next((e for e in doc.get("trace") or []
                 if isinstance(e, dict) and e.get("role") == "user"), {})
    user_content = str((user or {}).get("content") or "")
    evidence = user.get("evidence") if isinstance(user, dict) else None
    try:
        rel = trace_path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        rel = f"traces/{trace_path.name}"
    phenomenon = _phenomenon(summary, user_content)
    provenance = {
        "trigger": "diagnosis_end",
        "trace_ref": rel,
        "report_ref": str(doc.get("report_file") or "") or None,
        "captured_at": now_iso(),
        "kb_rev": str(doc.get("kb_rev") or "unknown"),
        "sanitized": False,
        "redactions": [],
        "confidence": "agent-reviewed",
        "extraction": "auto",
    }
    return {
        "id": sample_id_for("S", session),
        "object_type": "diagnosis",
        "source": rel,
        "purpose": "feedback",
        "input": {
            "phenomenon": _text_block(phenomenon),
            "environment": _one_line(doc.get("incident_env")),
            "evidence": evidence if isinstance(evidence, dict) else {},
        },
        "proposed": {"resolution": _text_block(_proposed_resolution(summary)),
                     "confidence": "agent-reviewed"},
        "expected_kind": "resolution",
        "non_diagnostic": not bool(phenomenon),
        "provenance": provenance,
        "notes": f"extracted from {rel}",
    }


def extract_case(case_path: Path, root: Path) -> Dict[str, Any]:
    """从 to-postmortem 产出的 case YAML 生成候选样本参数。"""
    case_path = Path(case_path)
    try:
        doc = yaml.safe_load(case_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise IntakeError(f"cannot read case {case_path}: {exc}") from exc
    cases = doc.get("cases") if isinstance(doc, dict) else None
    if not isinstance(cases, list) or not cases or not isinstance(cases[0], dict):
        raise IntakeError("case file must contain a non-empty cases list")
    case = cases[0]
    case_id = str(case.get("id") or case_path.stem)
    upstream = case.get("upstream") or []
    source = ""
    if isinstance(upstream, list) and upstream and isinstance(upstream[0], dict):
        source = str(upstream[0].get("url") or "")
    if not source:
        refs = case.get("references") or []
        source = str(refs[0]) if refs else f"knowledge/{case_path.name}"
    symptoms = case.get("symptoms") or []
    phenomenon = _one_line("；".join(str(item) for item in symptoms), SYMPTOM_LIMIT)
    resolution = "\n\n".join(
        part for part in (str(case.get("root_cause") or "").strip(),
                          str(case.get("fix") or "").strip()) if part
    ).strip()
    try:
        rel = case_path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        rel = case_path.name
    return {
        "id": sample_id_for("S", case_id),
        "object_type": "diagnosis",
        "source": source,
        "purpose": "evaluation",
        "input": {
            "phenomenon": phenomenon,
            "environment": _one_line(", ".join(str(p) for p in case.get("platforms") or [])),
            "evidence": {"case": case_id, "references": list(case.get("references") or [])},
        },
        "expected": ({
            "resolution": _text_block(resolution, RESOLUTION_LIMIT),
            "case": case_id,
            "confidence": _confidence_from_case(case),
        } if resolution else None),
        "expected_kind": "resolution",
        "non_diagnostic": not bool(phenomenon),
        "provenance": {
            "trigger": "postmortem",
            "report_ref": rel,
            "captured_at": now_iso(),
            "kb_rev": "unknown",
            "sanitized": False,
            "redactions": [],
            "confidence": _confidence_from_case(case),
            "extraction": "auto",
        },
        "notes": f"extracted from {rel}; confirm sanitization before core",
    }


def _repo_index(root: Path) -> Dict[str, Any]:
    root = Path(root)
    s2_issues = set()
    holdout_issues = set()
    knowledge_issues = set()
    cases = set()
    s2 = root / "eval" / "s2"
    for path in sorted(s2.glob("*.yaml")) if s2.exists() else []:
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        for row in (doc or {}).get("calibration") or []:
            if isinstance(row, dict) and isinstance(row.get("issue"), int):
                s2_issues.add(row["issue"])
    holdout = root / "eval" / "holdout.yaml"
    if holdout.exists():
        try:
            doc = yaml.safe_load(holdout.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            doc = {}
        for row in (doc or {}).get("entries") or []:
            fixture = str((row or {}).get("fixture") or "")
            number = _issue_number(fixture)
            if number is not None:
                holdout_issues.add(number)
    knowledge = root / "knowledge"
    if knowledge.exists():
        for path in knowledge.rglob("*.yaml"):
            if path.name.startswith("_"):
                continue
            stem = path.stem
            if not re.search(r"-\d{3,6}$", stem):
                continue
            cases.add(stem)
            number = _issue_number(stem)
            if number is not None:
                knowledge_issues.add(number)
    return {"s2": s2_issues, "holdout": holdout_issues,
            "knowledge": knowledge_issues, "cases": cases}


def completeness(sample: Sample, *, store=None, root: Optional[Path] = None) -> Dict[str, Any]:
    """返回 primary 状态、全部原因与查重命中；只读。"""
    reasons: List[str] = []
    duplicates: List[str] = []
    source = str(sample.source or "")
    issue = _issue_number(source)
    if not source.strip():
        reasons.append("missing_source")
    answer_missing = not (sample.expected or sample.rubric)
    if not answer_missing and isinstance(sample.expected, dict) and not sample.rubric:
        if not str(sample.expected.get("resolution") or "").strip():
            answer_missing = True
    if answer_missing:
        reasons.append("missing_answer")
    if sample.non_diagnostic:
        reasons.append("non_diagnostic")
    provenance = sample.provenance or {}
    sanitized = provenance.get("sanitized")
    if sanitized is False or (
            sample.object_type == "diagnosis"
            and sample.purpose in ("evaluation", "test")
            and sanitized is not True
            and source_needs_provenance(source)):
        reasons.append("not_sanitized")
    trace_ref = provenance.get("trace_ref")
    if trace_ref and root is not None:
        path = Path(root) / str(trace_ref)
        if not path.exists():
            reasons.append("missing_trace")
    if store is not None and source:
        existing = store.find_by_source(source, exclude_id=sample.id)
        if existing:
            duplicates.append(f"local:{existing[0].id}")
    if root is not None:
        index = _repo_index(Path(root))
        if issue is not None and issue in index["s2"]:
            duplicates.append(f"eval:{issue}")
        if issue is not None and issue in index["holdout"]:
            duplicates.append(f"holdout:{issue}")
        expected_case = str((sample.expected or {}).get("case") or "")
        if expected_case and expected_case in index["cases"]:
            duplicates.append(f"knowledge:{expected_case}")
        if issue is not None and issue in index["knowledge"]:
            reasons.append("absorbed")
    if duplicates:
        reasons.append("duplicate_sample")
    reason_set = set(reasons)
    if "missing_source" in reason_set:
        state = "needs_source"
    elif "absorbed" in reason_set:
        state = "absorbed"
    elif "missing_answer" in reason_set:
        state = "needs_answer"
    elif "non_diagnostic" in reason_set:
        state = "non_diagnostic"
    elif "not_sanitized" in reason_set:
        state = "needs_sanitize"
    elif "duplicate_sample" in reason_set:
        state = "duplicate"
    elif "missing_trace" in reason_set:
        state = "stale"
    else:
        state = "ready"
    return {
        "state": state,
        "reasons": [reason for reason in STATE_ORDER if reason in reason_set],
        "duplicates": duplicates,
        "sanitized": sanitized,
    }


def make_sample(payload: Dict[str, Any]) -> Sample:
    """把抽取结果变成一条还没写盘的候选样本。"""
    return Sample(**payload)
