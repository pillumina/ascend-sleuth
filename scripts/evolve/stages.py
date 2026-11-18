"""RSI 各节点的算法注册表：归因、选择、提案、judge、gate。

算法不直接改文件；每个 stage 记录 id/version/execution，实验时固定组合。
GEPA 不是整条循环，而是 select=pareto + propose=reflection 的一个组合。
"""

from dataclasses import dataclass
from typing import Dict, List

POINTS = ("attribute", "select", "propose", "judge", "gate")


@dataclass(frozen=True)
class StageSpec:
    id: str
    point: str
    version: str
    execution: str
    description: str

    def validate(self) -> "StageSpec":
        if self.point not in POINTS:
            raise ValueError(f"unknown stage point {self.point!r}")
        if self.execution not in ("library", "subagent", "manual"):
            raise ValueError(f"unknown execution {self.execution!r}")
        return self


STAGES: Dict[str, StageSpec] = {
    "attribute.trace_rule": StageSpec(
        "attribute.trace_rule", "attribute", "v1", "manual",
        "从 trace attribution 事件抽组件证据；不判定修复",
    ),
    "select.region_hardcount": StageSpec(
        "select.region_hardcount", "select", "v1", "manual",
        "按硬归因数把组件映射到可变异区",
    ),
    "select.pareto": StageSpec(
        "select.pareto", "select", "v1", "manual",
        "候选分数 Pareto 支配 + 未反射选择；GEPA 的选择层",
    ),
    "propose.reflection": StageSpec(
        "propose.reflection", "propose", "v1", "subagent",
        "reflection subagent 看失败反馈产候选区文本",
    ),
    "judge.subagent": StageSpec(
        "judge.subagent", "judge", "v1", "subagent",
        "独立 judge subagent 按 rubric/expected 打分",
    ),
    "gate.paired": StageSpec(
        "gate.paired", "gate", "v1", "manual",
        "baseline/candidate 配对比较与人工 gate",
    ),
}


def get_stage(name: str) -> StageSpec:
    try:
        return STAGES[name].validate()
    except KeyError as exc:
        raise ValueError(f"unknown stage {name!r}; known: {sorted(STAGES)}") from exc


def stage_ids(point: str = None) -> List[str]:
    return sorted(
        name for name, spec in STAGES.items()
        if point is None or spec.point == point
    )
