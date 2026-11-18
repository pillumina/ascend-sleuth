"""Candidate Patch：有界文本改动、隔离 worktree、apply/diff/rollback。

只支持 skill 文本 region；tooling/harness 的配置 Patch 还没有 state schema，
不在这里伪装支持。
"""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from .regions import REGIONS


class CandidateError(ValueError):
    pass


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateError(f"{name} must be a non-empty string")
    return value


def validate_candidate(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise CandidateError("candidate must be an object")
    cid = _text(data.get("candidate_id"), "candidate_id")
    target = data.get("target_kind")
    if target != "skill":
        raise CandidateError("candidate apply currently supports skill only")
    component = _text(data.get("target_component"), "target_component")
    region = _text(data.get("region"), "region")
    spec = REGIONS.get(region)
    if spec is None:
        raise CandidateError(f"unknown region {region!r}")
    if component != region:
        raise CandidateError("target_component must equal region for skill candidates")
    skill = data.get("skill") or spec.skill
    if skill != spec.skill:
        raise CandidateError(f"region {region!r} belongs to skill {spec.skill!r}")
    file = _text(data.get("file"), "file")
    if not (file.startswith(f"skills/{skill}/") and file.endswith(".md")):
        raise CandidateError(f"file must be under skills/{skill}/")
    old = _text(data.get("old_text"), "old_text")
    new = _text(data.get("new_text"), "new_text")
    if old == new:
        raise CandidateError("old_text and new_text must differ")
    if len(new) > 8000:
        raise CandidateError("new_text is too large")
    base = _text(data.get("base_rev"), "base_rev")
    return {
        "candidate_id": cid, "target_kind": target,
        "target_component": component, "region": region,
        "skill": skill, "file": file, "old_text": old,
        "new_text": new, "base_rev": base,
        "evidence": list(data.get("evidence") or []),
        "expected_effect": str(data.get("expected_effect") or ""),
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_to_root(root: Path, candidate: Dict[str, Any], *,
                  allow_existing_workspace: bool = False) -> Dict[str, Any]:
    root = Path(root)
    path = root / candidate["file"]
    if not path.exists():
        raise CandidateError(f"target file does not exist: {path}")
    before = path.read_text(encoding="utf-8")
    count = before.count(candidate["old_text"])
    if count != 1:
        raise CandidateError(f"old_text must occur exactly once, found {count}")
    after = before.replace(candidate["old_text"], candidate["new_text"], 1)
    if after == before:
        raise CandidateError("patch produced no change")
    old_sha, new_sha = _sha(path), hashlib.sha256(after.encode("utf-8")).hexdigest()
    path.write_text(after, encoding="utf-8")
    return {"candidate_id": candidate["candidate_id"], "file": candidate["file"],
            "before_sha256": old_sha, "after_sha256": new_sha,
            "workspace": str(root)}


def create_workspace(root: Path, candidate: Dict[str, Any], workspace: Path) -> Dict[str, Any]:
    root, workspace = Path(root), Path(workspace)
    if workspace.exists():
        raise CandidateError(f"workspace already exists: {workspace}")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "--detach", str(workspace), candidate["base_rev"]],
        check=True, capture_output=True, text=True,
    )
    try:
        info = apply_to_root(workspace, candidate)
    except Exception:
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(workspace)],
                       check=False, capture_output=True, text=True)
        raise
    meta = workspace / ".evolve-candidate.json"
    meta.write_text(json.dumps({"candidate": candidate, "apply": info}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return {**info, "workspace": str(workspace), "meta": str(meta)}


def rollback_workspace(root: Path, workspace: Path) -> None:
    root, workspace = Path(root), Path(workspace)
    if not workspace.exists():
        return
    subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(workspace)],
                   check=True, capture_output=True, text=True)


def diff_workspace(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(Path(workspace)), "diff", "--", "."],
        check=True, capture_output=True, text=True,
    )
    return result.stdout
