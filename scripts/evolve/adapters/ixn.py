"""ixn-arena gold 样本导入：开源 issue 的 curated 首报 + resolution。"""

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from . import AdapterError
from ..samples import SampleStore, StoreError


def _sample_id(repo: str, issue: str) -> str:
    repo_name = repo.split("/")[-1].upper().replace("-", "-")
    return f"IXN-{repo_name}-{issue}"


def import_ixn(store: SampleStore, root: Path, source: Path,
               limit: Optional[int] = None,
               holdout_numbers: Optional[set] = None) -> Dict[str, Any]:
    source = Path(source)
    stats = {"source": str(source), "created": 0, "skipped_held_out": 0,
             "skipped_duplicate": 0, "skipped_missing": 0, "created_ids": []}
    for directory in sorted(p for p in source.iterdir() if p.is_dir()):
        gold = directory / "gold.yaml"
        stage = directory / "stage-0.md"
        if not gold.exists() or not stage.exists():
            stats["skipped_missing"] += 1
            continue
        try:
            doc = yaml.safe_load(gold.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise AdapterError(f"cannot read {gold}: {exc}") from exc
        if doc.get("held_out"):
            stats["skipped_held_out"] += 1
            continue
        if holdout_numbers and str(issue) in holdout_numbers:
            stats["skipped_held_out"] += 1
            continue
        issue = str(doc.get("issue") or directory.name)
        repo = str(doc.get("repo") or "vllm-project/vllm-ascend")
        expected = str(doc.get("resolution_summary") or "").strip()
        symptoms = stage.read_text(encoding="utf-8").strip()
        if not expected or not symptoms:
            stats["skipped_missing"] += 1
            continue
        sample_id = _sample_id(repo, issue)
        source_label = f"{source}#{issue}"
        try:
            store.new(
                id=sample_id, object_type="diagnosis", origin="field",
                purpose="evaluation", source=source_label,
                input={"symptoms": symptoms, "title": f"ixn {issue}"},
                expected={"resolution": expected, "namespace": "unknown", "category": "unknown"},
                expected_kind="resolution",
                provenance={"trigger": "issue_import", "sanitized": True,
                            "redactions": [], "confidence": "issue-verified",
                            "extraction": "auto"},
                proposed={"repo": repo, "issue": issue, "source": "ixn-arena"},
            )
        except StoreError as exc:
            if "duplicate" in str(exc):
                stats["skipped_duplicate"] += 1
                continue
            raise
        stats["created"] += 1
        stats["created_ids"].append(sample_id)
        if limit is not None and stats["created"] >= limit:
            break
    return stats
