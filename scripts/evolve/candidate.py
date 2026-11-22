"""Candidate Patch：有界文本改动、隔离 worktree、apply/diff/rollback。

支持三类工件：
- ``skill``：skill 文本 region，只改 ``skills/<skill>/**/*.md``；
- ``knowledge``：case/reference 内容，只改 ``knowledge/`` 或 ``references/`` 下的 YAML；
- ``tooling``：工具实现/路由数据，只改 region 登记的 ``paths``（如
  ``scripts/src_fetch.py``、``source-catalog.d``）。

tooling 补丁可以带 ``checks``：固定枚举 ``py_compile`` / ``diff_check`` /
``src_fetch_self_test``，按 argv 在 worktree 内执行，不走 shell；任一失败即
回滚，不把坏改动留在工作区。路径校验在解析后的真实路径上做，
``..``、绝对路径、symlink 逃逸与同前缀目录都会被拒。
"""

import hashlib
import json
import yaml
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from .regions import REGIONS


TARGET_KINDS = ("skill", "knowledge", "tooling", "harness")
FORBIDDEN_PREFIXES = (
    ".git/", ".github/", "knowledge/", "references/", "postmortems/",
    "eval/", "tests/", "docs/", "skills/", ".s2-replay/", ".worktrees/",
)
CHECK_TIMEOUT = 120
CHECK_KINDS = ("py_compile", "diff_check", "src_fetch_self_test")
MAX_TEXT = {"skill": 8000, "knowledge": 12000, "tooling": 20000, "harness": 20000}
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
    "harness.scheduler": ("scheduler", "调度", "budget", "预算", "stop", "停止"),
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
        raise CandidateError(f"checks must be a list of {list(CHECK_KINDS)}")
    out: List[str] = []
    for item in value:
        if item not in CHECK_KINDS:
            raise CandidateError(f"unknown check {item!r}; expected one of {list(CHECK_KINDS)}")
        if item in out:
            raise CandidateError(f"duplicate check {item!r}")
        out.append(item)
    return out


def _file_allowed(file: str, region) -> bool:
    if region.target_kind == "knowledge":
        return file.startswith(("knowledge/", "references/")) and file.endswith((".yaml", ".yml"))
    if region.target_kind == "harness":
        if file.startswith(("scripts/evolve/", "eval/core/", "tests/")):
            return False
        if file in ("eval/holdout.yaml", "sleuth.config.yaml", "config/rsi/pipelines.yaml"):
            return False
        return (file.startswith(("scripts/", "eval/"))
                and file.endswith((".py", ".yaml", ".yml", ".json")))
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
    action = str(data.get("action") or "modify")
    if action not in ("modify", "add", "delete"):
        raise CandidateError("action must be modify, add or delete")
    if action == "delete":
        old = ""
        new = ""
    elif action == "add":
        old = ""
        new = _text(data.get("content"), "content")
    else:
        old = _text(data.get("old_text"), "old_text")
        new = _text(data.get("new_text"), "new_text")
        markers = REGION_MARKERS.get(region, ())
        if not any(marker.lower() in old.lower() for marker in markers):
            raise CandidateError(f"old_text does not look like region {region!r}")
        if old == new:
            raise CandidateError("old_text and new_text must differ")
    checks = _checks(data.get("checks"))
    if "py_compile" in checks and not file.endswith(".py"):
        raise CandidateError("py_compile check requires a .py file")
    if len(new) > MAX_TEXT[target]:
        raise CandidateError(f"new_text is too large for {target} patch")
    base = _text(data.get("base_rev"), "base_rev")
    return {
        "candidate_id": cid, "target_kind": target,
        "target_component": component, "region": region,
        "skill": skill, "file": file, "action": action,
        "old_text": old, "new_text": new, "base_rev": base,
        "checks": checks,
        "evidence": list(data.get("evidence") or []),
        "expected_effect": str(data.get("expected_effect") or ""),
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_content(candidate: Dict[str, Any], text: str) -> None:
    """在写入前做 target-specific 语法/结构检查；不判断语义正确性。"""
    target = candidate["target_kind"]
    file = candidate["file"]
    if target == "knowledge":
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise CandidateError(f"knowledge YAML is invalid: {exc}") from exc
        if not isinstance(doc, dict) or not doc.get("id"):
            raise CandidateError("knowledge YAML must be an object with id")
    elif target == "harness":
        if file.endswith(".py"):
            try:
                compile(text, file, "exec")
            except SyntaxError as exc:
                raise CandidateError(f"harness Python is invalid: {exc}") from exc
        elif file.endswith((".yaml", ".yml")):
            try:
                doc = yaml.safe_load(text)
            except yaml.YAMLError as exc:
                raise CandidateError(f"harness YAML is invalid: {exc}") from exc
            if file.endswith("scheduler.yaml"):
                if not isinstance(doc, dict) or "scheduler" not in doc:
                    raise CandidateError("harness scheduler.yaml requires scheduler key")
        elif file.endswith(".json"):
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                raise CandidateError(f"harness JSON is invalid: {exc}") from exc
    elif target == "tooling":
        if file.endswith(".py"):
            try:
                compile(text, file, "exec")
            except SyntaxError as exc:
                raise CandidateError(f"tooling Python is invalid: {exc}") from exc
        elif file.endswith((".yaml", ".yml")):
            try:
                yaml.safe_load(text)
            except yaml.YAMLError as exc:
                raise CandidateError(f"tooling YAML is invalid: {exc}") from exc
        elif file.endswith(".json"):
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                raise CandidateError(f"tooling JSON is invalid: {exc}") from exc


def _check_commands(root: Path, candidate: Dict[str, Any]) -> List[List[str]]:
    commands: List[List[str]] = []
    for kind in candidate.get("checks") or []:
        if kind == "py_compile":
            if not candidate["file"].endswith(".py"):
                raise CandidateError("py_compile check requires a .py file")
            commands.append([sys.executable, "-m", "py_compile", candidate["file"]])
        elif kind == "diff_check":
            commands.append(["git", "-C", str(root), "diff", "--check"])
        elif kind == "src_fetch_self_test":
            if candidate["region"] not in ("tooling.source_fetch", "tooling.source_catalog"):
                raise CandidateError(
                    "src_fetch_self_test is only valid for source tooling regions")
            commands.append([sys.executable, "scripts/src_fetch.py", "--self-test"])
    return commands


def _run_checks(root: Path, candidate: Dict[str, Any]) -> None:
    for command in _check_commands(root, candidate):
        try:
            proc = subprocess.run(
                command, cwd=str(root), capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=CHECK_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise CandidateError(
                f"check timed out after {CHECK_TIMEOUT}s: {' '.join(command)}"
            ) from exc
        if proc.returncode != 0:
            tail = (proc.stdout + proc.stderr)[-1200:]
            raise CandidateError(
                f"check failed with exit {proc.returncode}: {' '.join(command)}\n{tail}"
            )


def _resolve_target(root: Path, candidate: Dict[str, Any], *, must_exist: bool = True) -> Path:
    root = Path(root).resolve()
    path = (root / candidate["file"]).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise CandidateError("candidate file escapes the repository") from exc
    spec = REGIONS[candidate["region"]]
    if not _file_allowed(relative, spec):
        raise CandidateError("candidate file escapes its region paths")
    if must_exist and not path.exists():
        raise CandidateError(f"target file does not exist: {path}")
    if not must_exist and path.exists():
        raise CandidateError(f"target file already exists: {path}")
    if path.exists() and not path.is_file():
        raise CandidateError(f"target is not a regular file: {path}")
    return path


def apply_to_root(root: Path, candidate: Dict[str, Any]) -> Dict[str, Any]:
    root = Path(root).resolve()
    action = candidate.get("action", "modify")
    after = ""
    path = _resolve_target(root, candidate, must_exist=action != "add")
    if action == "delete":
        before = path.read_text(encoding="utf-8")
        before_sha = _sha(path)
        path.unlink()
        try:
            _run_checks(root, candidate)
        except Exception:
            path.write_text(before, encoding="utf-8")
            raise
    elif action == "add":
        after = candidate["new_text"]
        _validate_content(candidate, after)
        before_sha = None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after, encoding="utf-8")
        try:
            _run_checks(root, candidate)
        except Exception:
            path.unlink(missing_ok=True)
            raise
    else:
        before = path.read_text(encoding="utf-8")
        count = before.count(candidate["old_text"])
        if count != 1:
            raise CandidateError(f"old_text must occur exactly once, found {count}")
        after = before.replace(candidate["old_text"], candidate["new_text"], 1)
        if after == before:
            raise CandidateError("patch produced no change")
        _validate_content(candidate, after)
        before_sha = _sha(path)
        path.write_text(after, encoding="utf-8")
        try:
            _run_checks(root, candidate)
        except Exception:
            path.write_text(before, encoding="utf-8")
            raise
    return {
        "candidate_id": candidate["candidate_id"], "file": candidate["file"],
        "action": action,
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
