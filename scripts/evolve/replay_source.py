"""S2 replay 结果作为归因信号：逐样本失败，不是评估集文件本身。"""

import hashlib
from pathlib import Path
from typing import Any, Dict, List

import yaml


class ReplaySourceError(RuntimeError):
    pass


def scan_failures(root: Path, results_dir: Path = None,
                  holdout_numbers: set = None) -> Dict[str, Any]:
    directory = Path(results_dir) if results_dir else Path(root) / ".s2-replay"
    if not directory.exists():
        return {"available": False, "components": {}, "snapshot_id": None}
    failures: List[Dict[str, Any]] = []
    hashes = []
    for path in sorted(directory.glob("*.result.yaml")):
        try:
            raw = path.read_bytes()
            doc = yaml.safe_load(raw.decode("utf-8")) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ReplaySourceError(f"cannot read {path}: {exc}") from exc
        if not isinstance(doc, dict):
            continue
        hashes.append(hashlib.sha256(raw).hexdigest())
        issue = path.name[:-len(".result.yaml")]
        if holdout_numbers and str(issue) in holdout_numbers:
            continue
        component = None
        if doc.get("routing_ok") is False:
            component = "routing"
        elif doc.get("tier2_hit") is False:
            component = "case_hit"
        elif doc.get("root_cause_ok") is False:
            component = "diagnosis"
        if component:
            failures.append({
                "sample_id": issue, "component": component,
                "reason": str(doc.get("evidence_gap_class") or doc.get("note") or ""),
                "hard": False,
            })
    components: Dict[str, Dict[str, int]] = {}
    for failure in failures:
        bucket = components.setdefault(failure["component"], {"events": 0, "hard": 0})
        bucket["events"] += 1
    snapshot = hashlib.sha256("\n".join(hashes).encode("utf-8")).hexdigest()[:12] if hashes else None
    return {
        "available": bool(hashes), "components": components,
        "snapshot_id": snapshot, "sample_count": len(hashes), "failures": failures,
    }
