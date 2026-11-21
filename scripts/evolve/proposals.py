# -*- coding: utf-8 -*-
"""Target-specific agent proposal contract.

Agent 提案不是某个算法；它是 ``propose.agent`` stage 的产出。本模块提供
request（给 agent 的提示与边界）、draft schema 校验、以及转成 Patch 的入口。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional

from .candidate import validate_candidate
from .contracts import Patch
from .evaluations.registry import get_eval_profile
from .targets.registry import get_target


class ProposalError(ValueError):
    pass


@dataclass(frozen=True)
class ProposalSpec:
    target_kind: str
    change_surface: str
    allowed_paths: tuple
    forbidden_paths: tuple
    prompt_rules: tuple
    required_checks: tuple


SPECS: Dict[str, ProposalSpec] = {
    "skill": ProposalSpec(
        target_kind="skill",
        change_surface="skill 文本 / 步骤 / 流程 / 提示",
        allowed_paths=("skills/",),
        forbidden_paths=("knowledge/", "scripts/", "eval/"),
        prompt_rules=("只能改已登记的 skill 可变异区，不替换整份 SKILL.md",
                      "不改 phase、工具、trace schema、severity、halt 条件",
                      "输出文本 diff，并写预期、风险、回滚"),
        required_checks=("区域在 REGIONS 内", "diff 可应用"),
    ),
    "knowledge": ProposalSpec(
        target_kind="knowledge",
        change_surface="case / reference 内容",
        allowed_paths=("knowledge/", "references/"),
        forbidden_paths=("scripts/", "skills/", "eval/"),
        prompt_rules=("只改 case/reference 内容，不改代码或流程",
                      "保留原结构，补证据与来源；不编造维护者结论",
                      "输出 YAML 变更片段，并写预期、风险、回滚"),
        required_checks=("YAML 可解析", "来源/预期可核对"),
    ),
    "tooling": ProposalSpec(
        target_kind="tooling",
        change_surface="工具路由 / 重试 / 缓存 / 目录",
        allowed_paths=("scripts/", "source-catalog.d/"),
        forbidden_paths=("knowledge/", "skills/"),
        prompt_rules=("只改允许的工具代码或目录数据",
                      "输出 code diff；说明编译、测试或 benchmark",
                      "必须写回滚路径；不能改诊断结论"),
        required_checks=("py_compile", "定向 benchmark 或测试"),
    ),
    "harness": ProposalSpec(
        target_kind="harness",
        change_surface="调度 / 控制流 / 预算与停止条件",
        allowed_paths=("scripts/", "eval/"),
        forbidden_paths=("knowledge/", "scripts/evolve/", "eval/core/",
                         "eval/holdout.yaml", "sleuth.config.yaml", "config/rsi/", "tests/"),
        prompt_rules=("只改调度/控制流；不改知识内容与评分规则",
                      "高风险 A1：必须写回归范围、回滚和人工审原因",
                      "输出 code/config diff，并写预期、风险、回滚"),
        required_checks=("evaluator 已就绪", "end-to-end 回归"),
    ),
}


def _spec(target: str) -> ProposalSpec:
    try:
        return SPECS[target]
    except KeyError as exc:
        raise ProposalError(f"unknown target_kind {target!r}") from exc


def _safe_path(path: str) -> PurePosixPath:
    if not isinstance(path, str) or not path.strip():
        raise ProposalError("change.files entries must be non-empty strings")
    pure = PurePosixPath(path.strip().replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ProposalError(f"unsafe proposal path: {path!r}")
    return pure


def _check_paths(spec: ProposalSpec, files: List[str]) -> None:
    for raw in files:
        path = _safe_path(raw)
        text = path.as_posix()
        if any(text == prefix.rstrip("/") or text.startswith(prefix) for prefix in spec.allowed_paths) is False:
            raise ProposalError(f"path outside {spec.target_kind} surface: {text}")
        if any(text == prefix.rstrip("/") or text.startswith(prefix) for prefix in spec.forbidden_paths):
            raise ProposalError(f"path is forbidden for {spec.target_kind}: {text}")


def request(target: str, component: str, evidence: Optional[Any] = None,
            constraints: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(component, str) or not component.strip():
        raise ProposalError("target_component is required")
    target_spec = get_target(target)
    spec = _spec(target)
    profile = get_eval_profile(target_spec.eval_profile_id)
    prompt = (
        f"你是 ascend-sleuth 的提案 agent。目标 target={target}，"
        f"可改变面={spec.change_surface}，区域={component}。\n"
        f"允许改动：{', '.join(spec.allowed_paths)}；禁止：{', '.join(spec.forbidden_paths)}。\n"
        + "\n".join(f"- {rule}" for rule in spec.prompt_rules)
        + "\n只输出一个 JSON 对象，字段：target_kind、target_component、summary、"
          "change{files,diff}、expected、risk、rollback、evidence。"
          "不要读取 test 答案；不要声称已经合入。"
    )
    return {
        "target_kind": target,
        "target_component": component,
        "change_surface": spec.change_surface,
        "allowed_paths": list(spec.allowed_paths),
        "forbidden_paths": list(spec.forbidden_paths),
        "required_checks": list(spec.required_checks),
        "authority": target_spec.authority,
        "eval_profile_id": target_spec.eval_profile_id,
        "eval_ready": profile.implemented,
        "output_schema": {
            "target_kind": "str",
            "target_component": "str",
            "summary": "str",
            "change": {"files": "list[str]", "diff": "str"},
            "expected": "str",
            "risk": "str",
            "rollback": "str",
            "evidence": "list[str] (optional)",
        },
        "constraints": dict(constraints or {}),
        "evidence": evidence if evidence is not None else [],
        "prompt": prompt,
    }


def validate_draft(data: Any, target_override: Optional[str] = None) -> Patch:
    if not isinstance(data, dict):
        raise ProposalError("draft must be an object")
    target = str(data.get("target_kind") or "")
    if target_override:
        if target and target != target_override:
            raise ProposalError("draft target_kind does not match requested target")
        target = target_override
    spec = _spec(target)
    candidate = data.get("candidate")
    if candidate is not None:
        if not isinstance(candidate, dict):
            raise ProposalError("draft.candidate must be an object")
        candidate = validate_candidate(candidate)
        if candidate["target_kind"] != target:
            raise ProposalError("draft.candidate target_kind does not match draft")
        return Patch(
            target_kind=target, target_component=candidate["region"],
            summary=str(data.get("summary") or "agent candidate"),
            algorithm="agent_draft", algorithm_version="v1",
            payload={
                "source": "agent",
                "candidate": candidate,
                "change": {"files": [candidate["file"]], "diff": candidate["new_text"]},
                "expected": str(data.get("expected") or ""),
                "risk": str(data.get("risk") or ""),
                "rollback": str(data.get("rollback") or ""),
                "evidence": list(data.get("evidence") or []),
            },
        )
    component = str(data.get("target_component") or "")
    summary = str(data.get("summary") or "")
    expected = str(data.get("expected") or "")
    risk = str(data.get("risk") or "")
    rollback = str(data.get("rollback") or "")
    for name, value in (("target_component", component), ("summary", summary),
                        ("expected", expected), ("risk", risk), ("rollback", rollback)):
        if not value.strip():
            raise ProposalError(f"draft.{name} is required")
    change = data.get("change")
    if not isinstance(change, dict):
        raise ProposalError("draft.change must be an object")
    files = change.get("files")
    diff = change.get("diff")
    if not isinstance(files, list) or not files:
        raise ProposalError("draft.change.files must be a non-empty list")
    if not isinstance(diff, str) or not diff.strip():
        raise ProposalError("draft.change.diff is required")
    _check_paths(spec, files)
    evidence = data.get("evidence") or []
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        raise ProposalError("draft.evidence must be a list of strings")
    return Patch(
        target_kind=target, target_component=component, summary=summary,
        algorithm="agent_draft", algorithm_version="v1",
        payload={
            "source": "agent",
            "change": {"files": list(files), "diff": diff},
            "expected": expected,
            "risk": risk,
            "rollback": rollback,
            "evidence": list(evidence),
            "hypothesis": data.get("hypothesis") or "",
        },
    )
