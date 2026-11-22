"""指标定义、角色与最小聚合。

角色只有四种：主指标、约束指标、硬约束、读数/次要指标。方向表达
“越高越好 / 越低越好 / 通过或不通过”。这里不读文件，也不决定接受与否。
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

ROLE_PRIMARY = "primary"
ROLE_CONSTRAINT = "constraint"
ROLE_HARD = "hard"
ROLE_READOUT = "readout"
ROLES = (ROLE_PRIMARY, ROLE_CONSTRAINT, ROLE_HARD, ROLE_READOUT)

DIRECTION_HIGH = "high"
DIRECTION_LOW = "low"
DIRECTION_PASS = "pass"
DIRECTIONS = (DIRECTION_HIGH, DIRECTION_LOW, DIRECTION_PASS)


@dataclass(frozen=True)
class MetricSpec:
    id: str
    role: str
    direction: str
    description: str = ""
    missing: str = "unknown"

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"{self.id}: role must be one of {list(ROLES)}")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"{self.id}: direction must be one of {list(DIRECTIONS)}")


# 第一版至少包含附录 §A 的指标表；新增指标先登记角色/方向/缺失处理。
DEFAULT_METRICS: Dict[str, MetricSpec] = {
    "routing": MetricSpec("routing", ROLE_CONSTRAINT, DIRECTION_HIGH, "命名空间/类别是否命中"),
    "case_hit": MetricSpec("case_hit", ROLE_PRIMARY, DIRECTION_HIGH, "期望知识条目是否在 top-k"),
    "root_cause": MetricSpec("root_cause", ROLE_CONSTRAINT, DIRECTION_HIGH, "与 issue 结论是否一致"),
    "fix": MetricSpec("fix", ROLE_HARD, DIRECTION_HIGH, "修法与 severity 是否正确"),
    "safety": MetricSpec("safety", ROLE_HARD, DIRECTION_PASS, "是否给出高危修复"),
    "follow_ups": MetricSpec("follow_ups", ROLE_READOUT, DIRECTION_LOW, "追问次数或轮次"),
    "cost.tokens": MetricSpec("cost.tokens", ROLE_READOUT, DIRECTION_LOW, "token 成本（向量）"),
    "cost.calls": MetricSpec("cost.calls", ROLE_READOUT, DIRECTION_LOW, "工具调用数（向量）"),
    "cost.ms": MetricSpec("cost.ms", ROLE_READOUT, DIRECTION_LOW, "工具耗时（向量）"),
}


def get_metric(metric_id: str, specs: Optional[Dict[str, MetricSpec]] = None) -> MetricSpec:
    table = specs if specs is not None else DEFAULT_METRICS
    try:
        return table[metric_id]
    except KeyError as exc:
        raise ValueError(
            f"unknown metric {metric_id!r}; expected one of {list(table)}"
        ) from exc


def _numeric(value: Any) -> Optional[float]:
    if value is None or value == "unknown":
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return None


def aggregate(values: Iterable[Any]) -> Optional[float]:
    """忽略 null / unknown，返回算术均值；没有可评值时返回 None（不补 0）。"""
    numbers: List[float] = [n for n in (_numeric(v) for v in values) if n is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def aggregate_metric(runs: Iterable[Any], metric_id: str) -> Optional[float]:
    """从 run 对象或 ``{"metrics": {...}}`` 字典里取某个指标并聚合。"""
    values: List[Any] = []
    for run in runs:
        metrics = run.get("metrics", {}) if isinstance(run, dict) else getattr(run, "metrics", {})
        if isinstance(metrics, dict) and metric_id in metrics:
            values.append(metrics[metric_id])
    return aggregate(values)


def pass_rate(values: Iterable[Any]) -> Optional[float]:
    """布尔/通过项的比率；非布尔值按 unknown 跳过。"""
    flags = [v for v in values if isinstance(v, bool)]
    if not flags:
        return None
    return sum(1 for v in flags if v) / len(flags)
