"""RSI 各节点的算法注册表：归因、选择、提案、judge、gate。

算法不直接改文件；每个 stage 记录 id/version/execution，实验时固定组合。
GEPA 不是整条循环，而是 select_candidate=pareto + propose=agent 的一个组合。
"""

from dataclasses import dataclass
from typing import Dict, List

POINTS = ("attribute", "select_region", "select_candidate", "propose", "judge", "gate")


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
        "select.region_hardcount", "select_region", "v1", "manual",
        "按硬归因数把组件映射到可变异区",
    ),
    "attribute.agent": StageSpec(
        "attribute.agent", "attribute", "v1", "subagent",
        "规则归因不确定/冲突时，由 agent 读 trace/metrics/replay 信号补证据；只能给候选归因",
    ),
    "select.region_agent": StageSpec(
        "select.region_agent", "select_region", "v1", "subagent",
        "多个注册 region 接近时，由 agent 按证据选一个；不能发明 region",
    ),
    "select.none": StageSpec(
        "select.none", "select_candidate", "v1", "manual",
        "baseline 控制臂：不选新父候选，只评估当前 skill",
    ),
    "select.best": StageSpec(
        "select.best", "select_candidate", "v1", "manual",
        "只选平均分最高的未反射候选；单候选/agent heuristic 默认",
    ),
    "select.pareto": StageSpec(
        "select.pareto", "select_candidate", "v1", "manual",
        "候选分数 Pareto 支配 + 未反射选择；GEPA 的选择层",
    ),
    "propose.none": StageSpec(
        "propose.none", "propose", "v1", "manual",
        "baseline 控制臂：不产候选，只评估 seed",
    ),
    "propose.agent": StageSpec(
        "propose.agent", "propose", "v1", "subagent",
        "agent 通过 ProposalPort 的 target-specific prompt 写结构化提案；不依赖 GEPA 库",
    ),
    "propose.reflection": StageSpec(
        "propose.reflection", "propose", "v1", "subagent",
        "propose.agent 的兼容别名，历史实验仍可读",
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
