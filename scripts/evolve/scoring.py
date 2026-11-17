"""rubric 评分：0–2 分/维度，任一维度 0 分即退回，总分按阈值判。

rubric 是样本自带的人工量表，不在这里生成；这里只做确定性算分，避免每个
evaluator 自己写一套阈值。当前只覆盖 case/reference 的人工 rubric。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


class RubricError(ValueError):
    """rubric 结构或评分输入不合法。"""


@dataclass
class RubricResult:
    passed: bool
    score: Optional[float]
    threshold: float
    failed_dimensions: List[str]
    missing: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "score": round(self.score, 4) if self.score is not None else None,
            "threshold": self.threshold,
            "failed_dimensions": list(self.failed_dimensions),
            "missing": list(self.missing),
        }


def _dimensions(rubric: Any) -> List[str]:
    if not isinstance(rubric, dict):
        raise RubricError("rubric must be an object")
    dimensions = rubric.get("dimensions")
    if isinstance(dimensions, dict):
        names = [str(key) for key in dimensions]
    elif isinstance(dimensions, list):
        names = [str(item) for item in dimensions]
    else:
        raise RubricError("rubric.dimensions must be a list or object")
    names = [name for name in names if name.strip()]
    if not names:
        raise RubricError("rubric.dimensions must not be empty")
    if len(set(names)) != len(names):
        raise RubricError("rubric.dimensions contains duplicates")
    return names


def score_rubric(rubric: Any, scores: Any,
                 threshold: Optional[float] = None) -> RubricResult:
    if not isinstance(scores, dict):
        raise RubricError("scores must be an object")
    dimensions = _dimensions(rubric)
    if threshold is None:
        threshold = rubric.get("threshold", 0.7)
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise RubricError("rubric.threshold must be a number")
    if not 0 <= float(threshold) <= 1:
        raise RubricError("rubric.threshold must be between 0 and 1")

    missing = [name for name in dimensions if name not in scores]
    failed_dimensions: List[str] = []
    values: List[float] = []
    for name in dimensions:
        if name not in scores:
            continue
        value = scores[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise RubricError(f"score for {name!r} must be a number")
        if value not in (0, 1, 2):
            raise RubricError(f"score for {name!r} must be 0, 1, or 2")
        values.append(float(value))
        if value == 0:
            failed_dimensions.append(name)

    score = None if missing else (sum(values) / (2 * len(values)) if values else 0.0)
    passed = bool(
        score is not None and not failed_dimensions and score >= float(threshold)
    )
    return RubricResult(
        passed=passed, score=score, threshold=float(threshold),
        failed_dimensions=failed_dimensions, missing=missing,
    )
