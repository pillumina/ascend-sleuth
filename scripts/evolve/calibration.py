"""judge 双标校准：两份 0/1 标签的一致率与 Cohen's kappa。

标签文件支持三种形状：``{"scores": [{"id", "score"}]}``、``{"id": 0|1}``、
``[{"id", "score"}]``。两份文件的 item 集合必须相同；缺项、重复、非 0/1
都报错，不静默跳过。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


class CalibrationError(ValueError):
    pass


def _pairs(data: Any) -> Dict[str, int]:
    if isinstance(data, dict):
        if isinstance(data.get("scores"), list):
            items = data["scores"]
        else:
            items = [{"id": key, "score": value} for key, value in data.items()]
    elif isinstance(data, list):
        items = data
    else:
        raise CalibrationError("labels must be an object or a list")
    out: Dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            raise CalibrationError("each label must be an object")
        item_id = item.get("id")
        score = item.get("score")
        if not isinstance(item_id, str) or not item_id.strip():
            raise CalibrationError("each label needs a non-empty id")
        if score not in (0, 1) or isinstance(score, bool):
            raise CalibrationError(f"label {item_id!r} must be 0 or 1")
        if item_id in out:
            raise CalibrationError(f"duplicate label id: {item_id}")
        out[item_id] = int(score)
    if not out:
        raise CalibrationError("labels are empty")
    return out


def load_labels(path: Path) -> Dict[str, int]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"cannot read labels {path}: {exc}") from exc
    return _pairs(data)


def cohen_kappa(a: Dict[str, int], b: Dict[str, int]) -> Dict[str, Any]:
    if set(a) != set(b):
        missing_a = sorted(set(b) - set(a))
        missing_b = sorted(set(a) - set(b))
        raise CalibrationError(
            f"label id sets differ; missing in A={missing_a}, missing in B={missing_b}"
        )
    ids = sorted(a)
    n = len(ids)
    agree = sum(1 for item in ids if a[item] == b[item])
    observed = agree / n
    p_a = sum(a.values()) / n
    p_b = sum(b.values()) / n
    expected = p_a * p_b + (1 - p_a) * (1 - p_b)
    kappa = 1.0 if expected >= 1 else (observed - expected) / (1 - expected)
    matrix = {
        "both_0": sum(1 for item in ids if a[item] == 0 and b[item] == 0),
        "a0_b1": sum(1 for item in ids if a[item] == 0 and b[item] == 1),
        "a1_b0": sum(1 for item in ids if a[item] == 1 and b[item] == 0),
        "both_1": sum(1 for item in ids if a[item] == 1 and b[item] == 1),
    }
    return {"n": n, "agree": agree, "raw": observed, "kappa": kappa,
            "matrix": matrix, "items": ids}


def calibrate(a_path: Path, b_path: Path, *, min_raw: float = 0.8,
              min_kappa: float = 0.6) -> Dict[str, Any]:
    if not 0 <= min_raw <= 1:
        raise CalibrationError("min_raw must be 0..1")
    if not -1 <= min_kappa <= 1:
        raise CalibrationError("min_kappa must be -1..1")
    result = cohen_kappa(load_labels(a_path), load_labels(b_path))
    result["min_raw"] = min_raw
    result["min_kappa"] = min_kappa
    result["passed"] = result["raw"] >= min_raw and result["kappa"] >= min_kappa
    return result
