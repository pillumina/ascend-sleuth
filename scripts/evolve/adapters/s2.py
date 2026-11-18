"""S2 校准集 → 候选样本。

读 ``eval/s2/*.yaml`` 的 ``calibration``（兼容旧的 ``issues`` 键），把每一条可诊断
的 issue 转成一条候选样本。只做格式转换，不判答案、不改状态；写库走调用方传入的
``SampleStore``，重复来源跳过而不是覆盖。

来源字段统一写成 ``<校准集相对路径>#<issue>``，这样同一 issue 在池与样本队列里能
互相对上；重复判定也用它（``SampleStore.find_by_source``）。
"""

import re
from pathlib import Path
from typing import Any, Dict, Optional, Set

import yaml

from ..samples import StoreError
from . import AdapterError

DIAGNOSIS_OBJECT_TYPE = "diagnosis"
S2_ORIGIN = "field"
S2_PURPOSE = "evaluation"


def _slug(text: str, fallback: str = "X") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", str(text or "")).strip("-").upper()
    return cleaned or fallback


def sample_id_for(source_path: Path, issue: Any) -> str:
    """样本 id：vllm-ascend 用既有的 ``VLLM-ASC-<issue>``，其余来源带来源前缀。

    旧 case 实名与 arena 的 case 前缀都是 ``VLLM-ASC-<issue>``，同一条 issue 用同一个
    id 才能被吸收判据认出来；其他来源加 ``S2-<来源名>`` 前缀，避免不同仓的 issue 号
    撞 id。
    """
    path = Path(source_path)
    stamp = _slug(issue, "0")
    stem = path.stem
    if stem.lower() == "vllm-ascend":
        return f"VLLM-ASC-{stamp}"
    return f"S2-{_slug(stem, 'SOURCE')}-{stamp}"


def expected_for(row: Dict[str, Any]) -> Dict[str, Any]:
    """把校准集行的 ``expected`` 转成样本答案字段；五个字段都保留。"""
    expected = row.get("expected") if isinstance(row, dict) else None
    if not isinstance(expected, dict):
        expected = {}
    return {
        "namespace": expected.get("namespace") or "",
        "category": expected.get("category") or "",
        "resolution": expected.get("resolution") or "",
        "fix_commit": expected.get("fix_commit") or "",
        "confidence": expected.get("confidence") or "pending",
    }


def input_for(row: Dict[str, Any]) -> Dict[str, Any]:
    """现象与标题；缺症状时返回空串，由导入方按复核清单跳过。"""
    raw = row.get("input") if isinstance(row, dict) else None
    symptoms = raw.get("symptoms") if isinstance(raw, dict) else ""
    title = row.get("title") if isinstance(row, dict) else ""
    return {"title": str(title or ""), "symptoms": str(symptoms or "")}


def candidate_kwargs(
    row: Dict[str, Any],
    source_label: str,
    sample_id: str,
) -> Dict[str, Any]:
    """一条候选的 ``SampleStore.new`` 参数；纯函数，便于单测。"""
    return {
        "id": sample_id,
        "object_type": DIAGNOSIS_OBJECT_TYPE,
        "origin": S2_ORIGIN,
        "purpose": S2_PURPOSE,
        "source": source_label,
        "input": input_for(row),
        "expected": expected_for(row),
        "expected_kind": "resolution",
    }


def _relative_source(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def load_calibration(root: Path, source: Any) -> Dict[str, Any]:
    """读一份校准集，返回 ``{"path", "relative", "rows"}``。"""
    root_path = Path(root)
    source_path = Path(source)
    if not source_path.is_absolute():
        source_path = root_path / source_path
    try:
        text = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AdapterError(f"cannot read S2 calibration {source_path}: {exc}") from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AdapterError(f"invalid S2 calibration YAML {source_path}: {exc}") from exc
    if not isinstance(document, dict):
        raise AdapterError(
            f"S2 calibration must contain an object with a calibration list: {source_path}"
        )
    rows = document.get("calibration")
    if rows is None:
        rows = document.get("issues")
    if not isinstance(rows, list):
        raise AdapterError(
            f"S2 calibration has no calibration/issues list: {source_path}"
        )
    return {
        "path": source_path,
        "relative": _relative_source(root_path, source_path),
        "rows": rows,
    }


def import_s2_samples(
    root: Path,
    source: Any,
    store: Any,
    limit: Optional[int] = None,
    holdout_numbers: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """把一份校准集导入候选队列，返回统计。

    ``limit`` 限制的是**实际创建的候选数**（不是扫描行数）：先跳过非诊断、无症状和
    重复来源，再按上限创建。``limit=0`` 合法，表示只扫描不创建。

    返回字典的键是稳定读数：``total`` / ``created`` / ``created_ids`` 与四个 skip
    计数，外加 ``skipped_invalid`` 与 ``limit_reached``。
    """
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 0
    ):
        raise AdapterError("limit must be a non-negative integer or None")
    calibration = load_calibration(root, source)
    relative = calibration["relative"]
    stats: Dict[str, Any] = {
        "source": relative,
        "total": 0,
        "created": 0,
        "created_ids": [],
        "skipped_non_diagnostic": 0,
        "skipped_no_symptoms": 0,
        "skipped_missing_issue": 0,
        "skipped_invalid": 0,
        "skipped_no_answer": 0,
        "skipped_holdout": 0,
        "skipped_split": 0,
        "skipped_duplicate_source": 0,
        "skipped_duplicate_id": 0,
        "limit_reached": False,
    }
    for row in calibration["rows"]:
        stats["total"] += 1
        if not isinstance(row, dict):
            stats["skipped_invalid"] += 1
            continue
        issue = row.get("issue")
        if issue is None or str(issue).strip() == "":
            stats["skipped_missing_issue"] += 1
            continue
        if holdout_numbers and str(issue) in holdout_numbers:
            stats["skipped_holdout"] += 1
            continue
        if row.get("non_diagnostic"):
            stats["skipped_non_diagnostic"] += 1
            continue
        split = str(row.get("split") or "").strip()
        if split and split != "selection":
            stats["skipped_split"] = stats.get("skipped_split", 0) + 1
            continue
        symptoms = input_for(row)["symptoms"]
        if not symptoms.strip():
            stats["skipped_no_symptoms"] += 1
            continue
        expected = expected_for(row)
        if not any(expected.get(key) for key in ("namespace", "category", "resolution", "fix_commit")):
            stats["skipped_no_answer"] = stats.get("skipped_no_answer", 0) + 1
            continue
        resolution = str(expected.get("resolution") or "").lower()
        if any(marker in resolution for marker in ("待补", "todo", "tbd", "待定")):
            stats["skipped_no_answer"] = stats.get("skipped_no_answer", 0) + 1
            continue
        sample_id = sample_id_for(calibration["path"], issue)
        source_label = f"{relative}#{str(issue).strip()}"
        if store.find_by_source(source_label):
            stats["skipped_duplicate_source"] += 1
            continue
        if store.load(sample_id) is not None:
            stats["skipped_duplicate_id"] += 1
            continue
        if limit is not None and stats["created"] >= limit:
            stats["limit_reached"] = True
            continue
        try:
            kwargs = candidate_kwargs(row, source_label, sample_id)
            kwargs["provenance"] = {
                "trigger": "issue_import", "sanitized": True, "redactions": [],
                "confidence": "issue-verified", "extraction": "auto",
            }
            sample = store.new(**kwargs)
        except StoreError as exc:
            message = str(exc)
            if "duplicate source" in message:
                stats["skipped_duplicate_source"] += 1
                continue
            if "duplicate sample id" in message:
                stats["skipped_duplicate_id"] += 1
                continue
            raise AdapterError(f"cannot create S2 candidate {sample_id}: {message}") from exc
        stats["created"] += 1
        stats["created_ids"].append(sample.id)
    return stats

