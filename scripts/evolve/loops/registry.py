# -*- coding: utf-8 -*-
"""搜索循环注册表：名字 → LoopSpec。静态登记，不做动态插件加载。

新增算法只加一条 ``LoopSpec``：声明它改哪些 target、需要哪些样本角色、产出哪些
动作、工厂怎么构造。实验层与驱动只读这张表，不为算法写特例。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .baseline import BaselineLoop
from .budget import Budget
from .contract import ActionSpec, LoopError, LoopSpec
from .decisions import DecisionLog
from .gepa import GepaSession
from .loo import AuditUnit, LooAudit
from .skillopt import SkillOptLoop
from ..targets.registry import TARGETS


def _data(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    data = cfg.get("data")
    if not isinstance(data, dict):
        return {}
    return {str(key): [str(item) for item in value]
            for key, value in data.items() if isinstance(value, (list, tuple))}


def _budget(cfg: Dict[str, Any], default: int) -> Budget:
    return Budget(target_runs=_target_runs(cfg, default),
                  worker_calls=cfg.get("worker_calls"),
                  tokens=cfg.get("tokens"))


def _target_runs(cfg: Dict[str, Any], default: int) -> int:
    value = cfg.get("target_runs")
    if value is None:
        value = cfg.get("max_metric_calls")
    if value is None:
        value = default
    return int(value)


def _gepa_factory(cfg: Dict[str, Any]) -> GepaSession:
    data = _data(cfg)
    log = DecisionLog(cfg["decision_log"]) if cfg.get("decision_log") else None
    samples = data.get("eval") or data.get("train") or []
    seed = cfg.get("seed_text") or cfg.get("seed_skill") or ""
    return GepaSession(
        seed, samples,
        max_metric_calls=_target_runs(cfg, 12),
        population=int(cfg.get("population") or 4),
        seed=int(cfg.get("seed") or 0),
        min_score=float(cfg.get("min_score") or 0.0),
        target_skill=str(cfg.get("target") or ""),
        mutable_region=str(cfg.get("component") or ""),
        select_stage=str(cfg.get("select_stage") or "select.pareto"),
        propose_stage=str(cfg.get("propose_stage") or "propose.agent"),
        decision_log=log, run_id=str(cfg.get("run_id") or ""),
        budget=_budget(cfg, 12),
    )


def _loo_factory(cfg: Dict[str, Any]) -> LooAudit:
    data = _data(cfg)
    log = DecisionLog(cfg["decision_log"]) if cfg.get("decision_log") else None
    units = []
    for item in cfg.get("units") or []:
        if isinstance(item, AuditUnit):
            units.append(item)
        elif isinstance(item, dict) and item.get("id"):
            units.append(AuditUnit(id=str(item["id"]), label=str(item.get("label") or "")))
        else:
            raise LoopError("units entries must be objects with id")
    samples = data.get("audit") or data.get("eval") or []
    return LooAudit(
        units=units, samples=samples,
        max_audit_calls=_target_runs(cfg, 12),
        shrink_threshold=float(cfg.get("shrink_threshold") or 0.0),
        target_kind=str(cfg.get("target") or ""),
        audit_set=str(cfg.get("audit_set") or ""),
        decision_log=log, run_id=str(cfg.get("run_id") or ""),
        budget=_budget(cfg, 12),
    )


def _skillopt_factory(cfg: Dict[str, Any]) -> SkillOptLoop:
    data = _data(cfg)
    log = DecisionLog(cfg["decision_log"]) if cfg.get("decision_log") else None
    return SkillOptLoop(
        seed_skill=cfg.get("seed_text") or cfg.get("seed_skill") or "",
        train_samples=data.get("train") or [],
        dev_samples=data.get("dev") or [],
        epochs=int(cfg.get("epochs") or 3),
        batch_size=int(cfg.get("batch_size") or 4),
        reflection_minibatch=int(cfg.get("reflection_minibatch") or 2),
        success_threshold=float(cfg.get("success_threshold") or 0.0),
        rejected_memory=int(cfg.get("rejected_memory") or 5),
        max_steps=cfg.get("max_steps"),
        seed=int(cfg.get("seed") or 0),
        target=str(cfg.get("target") or ""),
        component=str(cfg.get("component") or ""),
        budget=_budget(cfg, 12),
        decision_log=log, run_id=str(cfg.get("run_id") or ""),
    )


def _baseline_factory(cfg: Dict[str, Any]) -> BaselineLoop:
    data = _data(cfg)
    samples = data.get("eval") or data.get("train") or []
    return BaselineLoop(
        seed_skill=cfg.get("seed_text") or cfg.get("seed_skill") or "",
        samples=samples,
        target=str(cfg.get("target") or ""),
        component=str(cfg.get("component") or ""),
        max_target_runs=_target_runs(cfg, 12) if cfg.get("target_runs") else None,
        budget=Budget(target_runs=_target_runs(cfg, 12)) if cfg.get("target_runs") else None,
    )


GEPA_LOOP = LoopSpec(
    id="gepa",
    version="v2",
    kind="search",
    targets=tuple(sorted(TARGETS)),
    required_roles=("eval",),
    actions=(
        ActionSpec("evaluate", "target", ("candidate_id", "sample_id"),
                   "在样本上运行指定候选，返回 score 与 feedback"),
        ActionSpec("reflect", "worker", ("candidate_id",),
                   "对失败样例做反思，返回变异后的候选文本"),
    ),
    factory=_gepa_factory,
    params={"population": 4, "seed": 0, "min_score": 0.0,
            "select_stage": "select.pareto", "propose_stage": "propose.agent"},
    description="候选池 + 反思变异 + Pareto 选择；按目标执行预算停。",
    state_schema="agent-gepa-v1",
    restore=GepaSession.from_dict,
)

LOO_LOOP = LoopSpec(
    id="loo",
    version="v2",
    kind="audit",
    targets=("skill", "knowledge", "tooling"),
    required_roles=("audit",),
    actions=(
        ActionSpec("evaluate", "target", ("unit_id", "variant", "sample_id"),
                   "运行 full 或 without:<unit> 变体，返回 score"),
    ),
    factory=_loo_factory,
    params={"units": [], "shrink_threshold": 0.0, "audit_set": ""},
    description="逐单元消融，负效用进收缩队列；不产出新候选。",
    state_schema="loo-audit-v1",
    restore=LooAudit.from_dict,
)

SKILLOPT_LOOP = LoopSpec(
    id="skillopt",
    version="v1",
    kind="search",
    targets=tuple(sorted(TARGETS)),
    required_roles=("train", "dev"),
    actions=(
        ActionSpec("evaluate", "target", ("candidate_id", "sample_id", "phase", "skill"),
                   "在训练批或 dev 上运行候选，返回 score；phase 取 train / dev"),
        ActionSpec("reflect", "worker", ("candidate_id", "group", "items"),
                   "对成功或失败组做定向编辑，返回文本提案"),
        ActionSpec("merge", "worker", ("candidate_id", "proposals"),
                   "合并多组提案，返回合并后的文本"),
    ),
    factory=_skillopt_factory,
    params={"epochs": 3, "batch_size": 4, "reflection_minibatch": 2,
            "success_threshold": 0.0, "rejected_memory": 5,
            "max_steps": None, "seed": 0},
    description="批次分组反思 + 全量 dev 严格采纳；当前只含快更新。",
    state_schema="skillopt-fast-v1",
    restore=SkillOptLoop.from_dict,
)

BASELINE_LOOP = LoopSpec(
    id="baseline",
    version="v1",
    kind="control",
    targets=tuple(sorted(TARGETS)),
    required_roles=("eval",),
    actions=(
        ActionSpec("evaluate", "target", ("sample_id",),
                   "把 seed 在样本上评一遍，返回 score"),
    ),
    factory=_baseline_factory,
    params={},
    description="对照臂：只评 seed，不提案、不选新候选。",
    state_schema="baseline-control-v1",
    restore=BaselineLoop.from_dict,
)

LOOPS: Dict[str, LoopSpec] = {
    spec.id: spec.validate()
    for spec in (GEPA_LOOP, LOO_LOOP, BASELINE_LOOP, SKILLOPT_LOOP)
}


def get_loop(name: str) -> LoopSpec:
    try:
        return LOOPS[name]
    except KeyError as exc:
        raise LoopError(
            f"unknown loop {name!r}; expected one of {sorted(LOOPS)}"
        ) from exc


def loop_ids() -> List[str]:
    return sorted(LOOPS)


def loop_table() -> List[Dict[str, Any]]:
    return [
        {"id": spec.id, "version": spec.version, "kind": spec.kind,
         "targets": list(spec.targets), "roles": list(spec.required_roles),
         "actions": [action.to_dict() for action in spec.actions],
         "description": spec.description}
        for spec in (LOOPS[key] for key in sorted(LOOPS))
    ]


def list_loops(kind: Optional[str] = None) -> List[LoopSpec]:
    return [spec for spec in LOOPS.values() if kind is None or spec.kind == kind]


def restore_loop(loop_id: str, state: Dict[str, Any]):
    spec = get_loop(loop_id)
    if spec.restore is None:
        raise LoopError(f"loop {loop_id!r} has no state restore")
    return spec.restore(state)
