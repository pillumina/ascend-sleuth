"""目标与算法的静态分发。

``TARGETS`` 是一个目标的唯一事实源：评测面、授权、允许的算法、工件规则与提案边界
都在 ``TargetSpec`` 里。candidate / proposals / proposal_engine / migrate 从这里取值，
不再各存一份 target 枚举。
"""

from typing import Dict, Optional

from ..algorithms.registry import get_algorithm
from ..evaluations.registry import get_eval_profile
from .artifacts import (HARNESS_ARTIFACT, KNOWLEDGE_ARTIFACT, SKILL_ARTIFACT,
                        TOOLING_ARTIFACT)
from .base import TargetSpec

TARGETS: Dict[str, TargetSpec] = {
    "skill": TargetSpec(
        id="skill", change_surface="skill 文本 / 步骤 / 流程 / 提示",
        eval_profile="arena 配对门禁（golden/S2 旁路）", eval_profile_id="arena", authority="A2",
        allowed_algorithms=("baseline",), default_algorithm="baseline",
        artifact=SKILL_ARTIFACT,
        allowed_paths=("skills/",),
        forbidden_paths=("knowledge/", "scripts/", "eval/"),
        prompt_rules=("只能改已登记的 skill 可变异区，不替换整份 SKILL.md",
                      "不改 phase、工具、trace schema、severity、halt 条件",
                      "输出文本 diff，并写预期、风险、回滚"),
        required_checks=("区域在 REGIONS 内", "diff 可应用"),
        description="改 skill 的文本、步骤与流程；评测走 golden/S2/rubric",
    ),
    "knowledge": TargetSpec(
        id="knowledge", change_surface="case / reference 内容",
        eval_profile="rubric + utility audit", eval_profile_id="rubric", authority="A2",
        allowed_algorithms=("baseline", "skillprox", "loo"), default_algorithm="baseline",
        artifact=KNOWLEDGE_ARTIFACT,
        allowed_paths=("knowledge/", "references/"),
        forbidden_paths=("scripts/", "skills/", "eval/"),
        prompt_rules=("只改 case/reference 内容，不改代码或流程",
                      "保留原结构，补证据与来源；不编造维护者结论",
                      "输出 YAML 变更片段，并写预期、风险、回滚"),
        required_checks=("YAML 可解析", "来源/预期可核对"),
        description="改知识条目内容；评测走 rubric，效用审计可后置",
    ),
    "tooling": TargetSpec(
        id="tooling", change_surface="工具路由 / 重试 / 缓存 / 目录",
        eval_profile="replay + trace tool usage", eval_profile_id="replay_trace", authority="A1",
        allowed_algorithms=("baseline", "ael"), default_algorithm="baseline",
        artifact=TOOLING_ARTIFACT,
        allowed_paths=("scripts/", "source-catalog.d/"),
        forbidden_paths=("knowledge/", "skills/"),
        prompt_rules=("只改允许的工具代码或目录数据",
                      "输出 code diff；说明编译、测试或 benchmark",
                      "必须写回滚路径；不能改诊断结论"),
        required_checks=("py_compile", "定向 benchmark 或测试"),
        description="改工具选择、分支、重试；评测看 replay/trace",
    ),
    "harness": TargetSpec(
        id="harness", change_surface="调度 / 控制流 / 预算与停止条件",
        eval_profile="end-to-end replay + regression", eval_profile_id="end_to_end", authority="A1",
        allowed_algorithms=("baseline", "harness-evolve"), default_algorithm="baseline",
        artifact=HARNESS_ARTIFACT,
        allowed_paths=("scripts/", "eval/"),
        forbidden_paths=("knowledge/", "scripts/evolve/", "eval/core/",
                         "eval/holdout.yaml", "sleuth.config.yaml", "config/rsi/", "tests/"),
        prompt_rules=("只改调度/控制流；不改知识内容与评分规则",
                      "高风险 A1：必须写回归范围、回滚和人工审原因",
                      "输出 code/config diff，并写预期、风险、回滚"),
        required_checks=("evaluator 已就绪", "end-to-end 回归"),
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


def artifact_kind(target: str) -> str:
    """工件的显示类别；旧记录里的未知目标记 ``unknown``，不抛异常。"""
    spec: Optional[TargetSpec] = TARGETS.get(str(target))
    return spec.artifact.kind if spec else "unknown"


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
