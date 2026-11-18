"""目标与算法的静态分发。"""

from typing import Dict

from ..algorithms.registry import get_algorithm
from ..evaluations.registry import get_eval_profile
from .base import TargetSpec

TARGETS: Dict[str, TargetSpec] = {
    "skill": TargetSpec(
        id="skill", change_surface="skill text / flow / prompt",
        eval_profile="arena 配对门禁（golden/S2 旁路）", eval_profile_id="arena", authority="A2",
        allowed_algorithms=("baseline",), default_algorithm="baseline",
        description="改 skill 的文本、步骤与流程；评测走 golden/S2/rubric",
    ),
    "knowledge": TargetSpec(
        id="knowledge", change_surface="case / reference content",
        eval_profile="rubric + utility audit", eval_profile_id="rubric", authority="A2",
        allowed_algorithms=("baseline", "skillprox", "loo"), default_algorithm="baseline",
        description="改知识条目内容；评测走 rubric，效用审计可后置",
    ),
    "tooling": TargetSpec(
        id="tooling", change_surface="tool routing / retry / cache / catalog",
        eval_profile="replay + trace tool usage", eval_profile_id="replay_trace", authority="A1",
        allowed_algorithms=("baseline", "ael"), default_algorithm="baseline",
        description="改工具选择、分支、重试；评测看 replay/trace",
    ),
    "harness": TargetSpec(
        id="harness", change_surface="harness scheduling / control flow",
        eval_profile="end-to-end replay + regression", eval_profile_id="end_to_end", authority="A1",
        allowed_algorithms=("baseline", "harness-evolve"), default_algorithm="baseline",
        description="改调度与控制流；高风险，默认人工逐次审",
    ),
}


def get_target(name: str) -> TargetSpec:
    try:
        spec = TARGETS[name].validate()
        get_eval_profile(spec.eval_profile_id)
        return spec
    except KeyError as exc:
        raise ValueError(
            f"unknown optimization target {name!r}; expected one of {sorted(TARGETS)}"
        ) from exc


def resolve_optimizer(target: str, algorithm: str = None):
    spec = get_target(target)
    name = algorithm or spec.default_algorithm
    if name not in spec.allowed_algorithms:
        raise ValueError(
            f"algorithm {name!r} is not allowed for target {target!r}; "
            f"allowed: {list(spec.allowed_algorithms)}"
        )
    optimizer = get_algorithm(name)
    scope = getattr(optimizer, "scope", "all")
    if scope not in ("all", target):
        raise ValueError(
            f"optimizer {name!r} scope {scope!r} does not cover target {target!r}"
        )
    return spec, optimizer


def resolve_evaluator(target: str):
    spec = get_target(target)
    return spec, get_eval_profile(spec.eval_profile_id)


def target_ids():
    return sorted(TARGETS)
