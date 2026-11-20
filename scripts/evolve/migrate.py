# -*- coding: utf-8 -*-
"""旧 JSONL 记录 -> RSIStore 的幂等迁移。

迁移只追加事件，不改写三份投影。稳定 id 由源文件、源行和内容哈希推导；
legacy.key 用于兼容早期随机 event_id 的迁移结果。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .records import JsonlStore
from .rsi_store import RSIStore

ARTIFACT_KIND = {
    "skill": "text", "knowledge": "yaml", "tooling": "code", "harness": "config",
}


def _digest(*parts: Any) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _legacy_key(source: str, line: int) -> str:
    return f"{source}:{line}"


def _stable_event_id(kind: str, source: str, line: int, record: Dict[str, Any]) -> str:
    return "E-mig" + _digest(kind, source, line, json.dumps(
        record, ensure_ascii=False, sort_keys=True))[:12]


def _proposal(record: Dict[str, Any], source: str, line: int) -> Dict[str, Any]:
    target = str(record.get("target_kind") or "skill")
    component = str(record.get("target_component") or "")
    at = str(record.get("at") or "")
    pid = "P-LEGACY-" + _digest(target, component, record.get("algorithm_version"),
                                record.get("summary"), at)[:12]
    return {
        "id": pid, "target": target, "component": component,
        "summary": str(record.get("summary") or ""),
        "artifact_kind": ARTIFACT_KIND.get(target, "unknown"),
        "artifact": {}, "draft": {}, "parent": None,
        "expected": "", "risk": "", "rollback": "", "evidence": [],
        "candidate": None, "status": str(record.get("decision") or "unknown"),
        "decision": str(record.get("decision") or "unknown"),
        "conclusion_ref": None, "workspace": None, "rolled_back": False,
        "scores": {}, "feedback": {}, "errors": [], "at": at,
    }


def _experiment_id(record: Dict[str, Any], proposal: Dict[str, Any]) -> str:
    return "EX-LEGACY-" + _digest(proposal["id"], record.get("at"),
                                  record.get("algorithm_version"))[:12]


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
    existing_ids = store.event_ids()
    counts = {"proposals": 0, "experiments": 0, "decisions": 0,
              "rollouts": 0, "skipped": 0, "duplicates": 0}
    seen_experiments: Dict[str, str] = {}
    proposal_ids = {str(row.get("proposal_id")) for row in store.read("proposal")}
    for row in store.read("experiment"):
        proposal = (row.get("data") or {}).get("proposal") or {}
        pid = str(proposal.get("id") or row.get("proposal_id") or "")
        if pid and pid not in proposal_ids and not dry_run:
            store.append("proposal", {"proposal": proposal, "legacy": proposal.get("legacy") or {}},
                         proposal_id=pid,
                         event_id="E-mig" + _digest("proposal", pid)[:12],
                         at=row.get("at"))
            proposal_ids.add(pid)
            counts["proposals"] += 1

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
            event_id = _stable_event_id(kind, source, line, record)
            if kind == "experiment":
                proposal = _proposal(record, source, line)
                if proposal["id"] in seen_experiments:
                    counts["duplicates"] += 1
                    continue
                seen_experiments[proposal["id"]] = key
                experiment_id = _experiment_id(record, proposal)
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
                    store.append("proposal", {"proposal": proposal, "legacy": legacy},
                                 proposal_id=proposal["id"],
                                 event_id="E-mig" + _digest("proposal", proposal["id"])[:12],
                                 at=record.get("at"))
                    store.append("experiment", data, experiment_id=experiment_id,
                                 proposal_id=proposal["id"], event_id=event_id,
                                 at=record.get("at"))
                counts["proposals"] += 1
                counts["experiments"] += 1
            elif kind == "decision":
                data = {"conclusion": record, "legacy": legacy}
                if not dry_run:
                    store.append("decision", data, event_id=event_id,
                                 at=record.get("at"))
                counts["decisions"] += 1
            else:
                data = {"run": record, "legacy": legacy}
                if not dry_run:
                    store.append("rollout", data, event_id=event_id, at=record.get("at"))
                counts["rollouts"] += 1
    return {"base": str(base), "dry_run": dry_run, "counts": counts,
            "store_path": str(store.path) if store.path else None}
