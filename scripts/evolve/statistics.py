"""统计纯函数：精确配对检验、配对差值置信区间、非劣判断。

不依赖 scipy。配对检验只数方向不一致的对子（b + c），一致对子不含
判别信息。缺失值一律返回 ``None`` 或显式 unknown，不补 0。
"""

import math
import statistics as _statistics
from typing import Dict, Iterable, List, Optional


def exact_mcnemar_ge(b: int, c: int) -> float:
    """精确单侧 p 值：``P[Bin(b + c, 0.5) >= b]``。

    b 是候选独家命中的样本数，c 是基线独家命中的样本数。b + c = 0 时
    没有判别信息，返回 1.0（调用方按 unknown 处理）。
    """
    if not isinstance(b, int) or not isinstance(c, int):
        raise TypeError("b and c must be integers")
    if b < 0 or c < 0:
        raise ValueError("b and c must be non-negative")
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(b, n + 1))
    return tail / (2 ** n)


def paired_diff_ci(
    diffs: Iterable[Optional[float]],
    confidence: float = 0.95,
) -> Dict[str, Optional[float]]:
    """配对差值的均值与正态近似置信区间。

    返回 ``{"mean", "low", "high", "n", "confidence"}``；n=0 时三项均为
    None，n=1 时 low/high 为 None（样本不足，不伪造区间）。
    """
    if not (0 < confidence < 1):
        raise ValueError("confidence must be between 0 and 1")
    values: List[float] = []
    for value in diffs:
        if value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError("diffs must be numbers or None")
        values.append(float(value))
    n = len(values)
    if n == 0:
        return {"mean": None, "low": None, "high": None, "n": 0, "confidence": confidence}
    mean = sum(values) / n
    if n == 1:
        return {"mean": mean, "low": None, "high": None, "n": 1, "confidence": confidence}
    stdev = _statistics.stdev(values)
    z = _statistics.NormalDist().inv_cdf(0.5 + confidence / 2)
    half = z * stdev / math.sqrt(n)
    return {
        "mean": mean,
        "low": mean - half,
        "high": mean + half,
        "n": n,
        "confidence": confidence,
    }


def non_inferior(
    diffs: Iterable[Optional[float]],
    delta: float = 0.0,
    confidence: float = 0.95,
) -> Optional[bool]:
    """候选相对基线是否非劣：差值置信区间下界不低于 ``-delta``。

    样本不足或没有差值时返回 None（unknown），不当作通过。
    """
    if delta < 0:
        raise ValueError("delta must be non-negative")
    ci = paired_diff_ci(diffs, confidence=confidence)
    if ci["low"] is None:
        return None
    return ci["low"] >= -delta


def rate(ok: int, n: int) -> Optional[float]:
    """比率；分母为 0 时返回 None。"""
    if not isinstance(ok, int) or not isinstance(n, int):
        raise TypeError("ok and n must be integers")
    if ok < 0 or n < 0 or ok > n:
        raise ValueError("require 0 <= ok <= n")
    if n == 0:
        return None
    return ok / n
