"""issue 质量/答案门：agent 产出结构化质量结论，管线只做校验与拒绝。

质量判断本身由 agent/subagent 完成；这里不调用模型，也不从 issue 评论里
自动猜答案。格式：
{ "123": {"score": 0.8, "answer": "...", "namespace": "...",
           "category": "...", "evidence": "..."}, ...}
"""

import json
from pathlib import Path
from typing import Any, Dict

MIN_SCORE = 0.6
PLACEHOLDERS = ("待补", "todo", "tbd", "待定")


class QualityError(ValueError):
    pass


def load_quality(path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualityError(f"cannot read quality file: {exc}") from exc
    if not isinstance(data, dict):
        raise QualityError("quality file must be an object keyed by issue number")
    out = {}
    for key, value in data.items():
        if not isinstance(value, dict):
            raise QualityError(f"quality[{key}] must be an object")
        score = value.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
            raise QualityError(f"quality[{key}].score must be 0..1")
        answer = str(value.get("answer") or "").strip()
        if any(marker in answer.lower() for marker in PLACEHOLDERS):
            raise QualityError(f"quality[{key}].answer is a placeholder")
        if score < MIN_SCORE or not answer:
            out[str(key)] = {**value, "accepted": False}
            continue
        out[str(key)] = {**value, "answer": answer, "accepted": True}
    return out
