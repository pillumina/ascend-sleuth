"""Candidate Patch：有界文本改动、隔离 worktree、apply/diff/rollback。

支持两类工件：
- ``skill``：skill 文本 region，只改 ``skills/<skill>/**/*.md``；
- ``tooling``：工具实现/路由数据，只改 region 登记的 ``paths``（如
  ``scripts/src_fetch.py``、``source-catalog.d``）。

tooling 补丁可以带 ``checks``（最多 5 条命令），在 worktree 内执行；任一
失败即回滚，不把坏改动留在工作区。路径校验在解析后的真实路径上做，
``..``、绝对路径、symlink 逃逸与同前缀目录都会被拒。
"""

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from .regions import REGIONS


TARGET_KINDS = ("skill", "tooling")
FORBIDDEN_PREFIXES = (
    ".git/", ".github/", "knowledge/", "references/", "postmortems/",
    "eval/", "tests/", "docs/", "skills/", ".s2-replay/", ".worktrees/",
)
MAX_CHECKS = 5
CHECK_TIMEOUT = 120
MAX_TEXT = {"skill": 8000, "tooling": 20000}
TOOLING_SUFFIXES = (".py", ".yaml", ".yml", ".json")

REGION_MARKERS = {
    "diagnose.routing_hints": ("triage", "路由", "追问", "routing"),
    "diagnose.verification_checklist": ("quickly_check", "验证", "候选", "排除"),
    "diagnose.trace_evidence": ("trace", "evidence", "证据"),
    "diagnose.knowledge_usage": ("知识", "reference", "索引", "全文", "候选数"),
    "diagnose.source_usage": ("源码分析", "src_fetch", "grep 定位", "source_analysis"),
    "knowledge.case_content": ("症状", "symptoms", "quickly_check", "判别"),
    "knowledge.reference_content": ("词条", "适用范围", "来源", "scope"),
    "tooling.source_fetch": ("src_fetch", "cache", "缓存", "retry", "重试", "ref"),
    "tooling.source_catalog": ("catalog", "repo", "仓", "签名", "signature"),
}


class CandidateError(ValueError):
    pass


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CandidateError(f"{name} must be a non-empty string")
    return value


def _relative_path(value: Any) -> str:
    path = _text(value, "file").replace("\\", "/")
    if path.startswith("/") or path.startswith("../") or "/../" in path or path == "..":
        raise CandidateError("file must be a relative path without traversal")
    return path


def _checks(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CandidateError("checks must be a list of commands")
    out: List[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise CandidateError("each check must be a non-empty string")
        if len(item) > 300:
            raise CandidateError("check command is too long")
        out.append(item)
    if len(out) > MAX_CHECKS:
        raise CandidateError(f"checks supports at most {MAX_CHECKS} commands")
    return out


def _file_allowed(file: str, region) -> bool:
    if region.target_kind == "tooling":
        if any(file == prefix or file.startswith(prefix.rstrip("/") + "/")
               for prefix in FORBIDDEN_PREFIXES):
            return False
        if not file.endswith(TOOLING_SUFFIXES):
            return False
        return any(file == path or file.startswith(path.rstrip("/") + "/")
                   for path in region.paths)
    return file.startswith(f"skills/{region.skill}/") and file.endswith(".md")


def validate_candidate(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise CandidateError("candidate must be an object")
    cid = _text(data.get("candidate_id"), "candidate_id")
    target = data.get("target_kind")
    if target not in TARGET_KINDS:
        raise CandidateError(f"target_kind must be one of {list(TARGET_KINDS)}")
    component = _text(data.get("target_component"), "target_component")
    region = _text(data.get("region"), "region")
    spec = REGIONS.get(region)
    if spec is None:
        raise CandidateError(f"unknown region {region!r}")
    if spec.target_kind != target:
        raise CandidateError(
            f"region {region!r} belongs to target_kind {spec.target_kind!r}, not {target!r}"
        )
    if component != region:
        raise CandidateError("target_component must equal region")
    skill = data.get("skill") or spec.skill
    if target == "skill" and skill != spec.skill:
        raise CandidateError(f"region {region!r} belongs to skill {spec.skill!r}")
    file = _relative_path(data.get("file"))
    if not _file_allowed(file, spec):
        raise CandidateError(f"file {file!r} is not allowed for region {region!r}")
    old = _text(data.get("old_text"), "old_text")
    new = _text(data.get("new_text"), "new_text")
    markers = REGION_MARKERS.get(region, ())
    if not any(marker.lower() in old.lower() for marker in markers):
        raise CandidateError(f"old_text does not look like region {region!r}")
    if old == new:
        raise CandidateError("old_text and new_text must differ")
    if len(new) > MAX_TEXT[target]:
        raise CandidateError(f"new_text is too large for {target} patch")
    base = _text(data.get("base_rev"), "base_rev")
    return {
        "candidate_id": cid, "target_kind": target,
        "target_component": component, "region": region,
        "skill": skill, "file": file, "old_text": old,
        "new_text": new, "base_rev": base,
        "checks": _checks(data.get("checks")),
        "evidence": list(data.get("evidence") or []),
        "expected_effect": str(data.get("expected_effect") or ""),
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_checks(root: Path, checks: List[str]) -> None:
    for command in checks:
        try:
            proc = subprocess.run(
                command, shell=True, cwd=str(root), capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=CHECK_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise CandidateError(f"check timed out after {CHECK_TIMEOUT}s: {command}") from exc
        if proc.returncode != 0:
            tail = (proc.stdout + proc.stderr)[-1200:]
            raise CandidateError(
                f"check failed with exit {proc.returncode}: {command}\n{tail}"
            )


def _resolve_target(root: Path, candidate: Dict[str, Any]) -> Path:
    root = Path(root).resolve()
    path = (root / candidate["file"]).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise CandidateError("candidate file escapes the repository") from exc
    spec = REGIONS[candidate["region"]]
    if not _file_allowed(relative, spec):
        raise CandidateError("candidate file escapes its region paths")
    if not path.exists():
        raise CandidateError(f"target file does not exist: {path}")
    if not path.is_file():
        raise CandidateError(f"target is not a regular file: {path}")
    return path


def apply_to_root(root: Path, candidate: Dict[str, Any]) -> Dict[str, Any]:
    root = Path(root).resolve()
    path = _resolve_target(root, candidate)
    before = path.read_text(encoding="utf-8")
    count = before.count(candidate["old_text"])
    if count != 1:
        raise CandidateError(f"old_text must occur exactly once, found {count}")
    after = before.replace(candidate["old_text"], candidate["new_text"], 1)
    if after == before:
        raise CandidateError("patch produced no change")
    before_sha = _sha(path)
    path.write_text(after, encoding="utf-8")
    try:
        _run_checks(root, candidate.get("checks") or [])
    except Exception:
        path.write_text(before, encoding="utf-8")
        raise
    return {
        "candidate_id": candidate["candidate_id"], "file": candidate["file"],
        "before_sha256": before_sha,
        "after_sha256": hashlib.sha256(after.encode("utf-8")).hexdigest(),
        "checks": list(candidate.get("checks") or []),
        "workspace": str(root),
    }


def create_workspace(root: Path, candidate: Dict[str, Any], workspace: Path) -> Dict[str, Any]:
    root, workspace = Path(root), Path(workspace)
    if workspace.exists():
        raise CandidateError(f"workspace already exists: {workspace}")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", "--detach", str(workspace), candidate["base_rev"]],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        info = apply_to_root(workspace, candidate)
    except Exception:
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(workspace)],
                       check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
        raise
    meta = workspace / ".evolve-candidate.json"
    meta.write_text(json.dumps({"candidate": candidate, "apply": info},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {**info, "workspace": str(workspace), "meta": str(meta)}


def rollback_workspace(root: Path, workspace: Path) -> None:
    root, workspace = Path(root), Path(workspace)
    if not workspace.exists():
        return
    subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(workspace)],
                   check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")


def diff_workspace(workspace: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(Path(workspace)), "diff", "--", "."],
        check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.stdout
