# -*- coding: utf-8 -*-
"""旧 JSONL 记录 -> RSIStore 的幂等迁移。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .records import JsonlStore
from .rsi_store import RSIStore

ARTIFACT_KIND = {
    "skill": "text", "knowledge": "yaml", "tooling": "code", "harness": "config",
}


def _legacy_key(source: str, line: int) -> str:
    return f"{source}:{line}"


def _digest(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def _proposal(record: Dict[str, Any], source: str, line: int) -> Dict[str, Any]:
    target = str(record.get("target_kind") or "skill")
    at = str(record.get("at") or "")
    pid = "P-LEGACY-" + _digest(source, line, target, record.get("target_component"), at)
    return {
        "id": pid, "target": target,
        "component": str(record.get("target_component") or ""),
        "summary": str(record.get("summary") or ""),
        "artifact_kind": ARTIFACT_KIND.get(target, "unknown"),
        "artifact": {}, "draft": {}, "parent": None,
        "expected": "", "risk": "", "rollback": "", "evidence": [],
        "candidate": None, "status": str(record.get("decision") or "unknown"),
        "decision": str(record.get("decision") or "unknown"),
        "conclusion_ref": None, "workspace": None, "rolled_back": False,
        "scores": {}, "feedback": {}, "errors": [], "at": at,
    }


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return JsonlStore(path).read() if path.exists() else []


def migrate_legacy(base: Path, *, dry_run: bool = False) -> Dict[str, Any]:
    base = Path(base)
    store = RSIStore(base)
    existing = {
        str((row.get("data") or {}).get("legacy", {}).get("key"))
        for row in store.read()
        if isinstance(row.get("data"), dict)
    }
    counts = {"experiments": 0, "decisions": 0, "rollouts": 0, "skipped": 0}
    for source, kind in (("experiments.jsonl", "experiment"),
                         ("conclusions.jsonl", "decision"),
                         ("runs.jsonl", "rollout")):
        path = base / source
        for line, record in enumerate(_read_jsonl(path), start=1):
            key = _legacy_key(source, line)
            if key in existing:
                counts["skipped"] += 1
                continue
            legacy = {"key": key, "source": source, "line": line}
            if kind == "experiment":
                proposal = _proposal(record, source, line)
                data = {
                    "proposal": proposal, "experiment": record, "conclusion": {},
                    "rollout": {
                        "samples": list(record.get("samples") or []),
                        "arms": {
                            "baseline": len((record.get("baseline") or {}).get("samples") or []),
                            "candidate": len((record.get("candidate") or {}).get("samples") or []),
                        },
                        "decision": record.get("decision"),
                        "paired": record.get("paired"),
                    },
                    "legacy": legacy,
                }
                if not dry_run:
                    store.append("experiment", data,
                                 experiment_id=f"EX-{proposal['id']}",
                                 proposal_id=proposal["id"])
                counts["experiments"] += 1
            elif kind == "decision":
                data = {"conclusion": record, "legacy": legacy}
                if not dry_run:
                    store.append("decision", data)
                counts["decisions"] += 1
            else:
                data = {"run": record, "legacy": legacy}
                if not dry_run:
                    store.append("rollout", data)
                counts["rollouts"] += 1
    return {"base": str(base), "dry_run": dry_run, "counts": counts,
            "store_path": str(store.path) if store.path else None}
