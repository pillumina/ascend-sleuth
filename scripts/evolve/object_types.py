"""评估对象描述表。

新增一个评估对象只需要在这里登记描述，评分器按 ``scorer`` 分派，
判定按 ``default_decision_method`` 选。样本、记录与 CLI 不写对象分支。
"""

from dataclasses import dataclass
from typing import Dict, Tuple

from .contracts import OBJECT_TYPE_VALUES, ORIGINS, PURPOSES


@dataclass(frozen=True)
class ObjectTypeSpec:
    name: str
    description: str
    scorer: str
    default_decision_method: str
    allowed_purposes: Tuple[str, ...]
    default_origin: str = "field"
    answer_visibility: str = "hidden_from_drafter"

    def allows_purpose(self, purpose: str) -> bool:
        return purpose in self.allowed_purposes

    @property
    def default_method(self) -> str:
        """兼容字段名：默认判定方法。"""
        return self.default_decision_method

    @property
    def scorer_name(self) -> str:
        """兼容字段名：评分器名。"""
        return self.scorer


OBJECT_TYPES: Dict[str, ObjectTypeSpec] = {
    "diagnosis": ObjectTypeSpec(
        name="diagnosis",
        description="历史 issue 回放：把现象重新跑一遍诊断。",
        scorer="replay",
        default_decision_method="paired_binary",
        allowed_purposes=(
            "evaluation", "feedback", "test", "regression", "cross", "scale",
        ),
        default_origin="field",
        answer_visibility="hidden_from_drafter",
    ),
    "case": ObjectTypeSpec(
        name="case",
        description="一条知识沉淀：按 rubric 评来源、完整、具体、去重与可检索。",
        scorer="rubric",
        default_decision_method="paired_score",
        allowed_purposes=("evaluation", "feedback", "regression"),
        default_origin="field",
        answer_visibility="hidden_from_drafter",
    ),
    "reference": ObjectTypeSpec(
        name="reference",
        description="一条先验词条：按 rubric 评事实、来源、范围与可复用。",
        scorer="rubric",
        default_decision_method="paired_score",
        allowed_purposes=("evaluation", "feedback", "regression"),
        default_origin="field",
        answer_visibility="hidden_from_drafter",
    ),
    "trace": ObjectTypeSpec(
        name="trace",
        description="一条真实工作轨迹：按 rubric 评证据链、步骤与工具使用。",
        scorer="rubric",
        default_decision_method="paired_score",
        allowed_purposes=("evaluation", "feedback", "regression"),
        default_origin="field",
        answer_visibility="hidden_from_drafter",
    ),
}


def get_object_type(name: str) -> ObjectTypeSpec:
    try:
        return OBJECT_TYPES[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown object_type {name!r}; expected one of {list(OBJECT_TYPES)}"
        ) from exc


def validate_registry() -> None:
    """启动/测试时的自检：登记表本身不能写错。"""
    if tuple(OBJECT_TYPES) != OBJECT_TYPE_VALUES:
        raise ValueError("OBJECT_TYPES must cover all object type values")
    for spec in OBJECT_TYPES.values():
        if spec.default_origin not in ORIGINS:
            raise ValueError(f"{spec.name}: bad default_origin {spec.default_origin!r}")
        for purpose in spec.allowed_purposes:
            if purpose not in PURPOSES:
                raise ValueError(f"{spec.name}: bad purpose {purpose!r}")
