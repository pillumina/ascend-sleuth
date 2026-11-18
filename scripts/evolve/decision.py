"""判定语义：把统计结果与策略翻译成接受 / 证据不足 / 拒绝 / 无法判定。

只做判定，不读文件、不调用模型。主指标是质量且为二元时用配对检验；
连续主指标用配对差值置信区间；成本主指标要求质量非劣且成本明显下降。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from .statistics import exact_mcnemar_ge, paired_diff_ci


class Decision(str, Enum):
    ACCEPT = "accept"
    INSUFFICIENT = "insufficient"
    REJECT = "reject"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DecisionResult:
    """一次判定的完整读数和理由；可原样写进结论记录。"""

    decision: Decision
    reason: str
    method: str = "paired_binary"
    b: Optional[int] = None
    c: Optional[int] = None
    n: Optional[int] = None
    p_value: Optional[float] = None
    alpha_eff: Optional[float] = None
    delta_q: Optional[float] = None
    cost_ratio: Optional[float] = None
    cost_ok: Optional[bool] = None
    cost_path: bool = False
    quality_non_inferior: Optional[bool] = None
    ci: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "decision": self.decision.value,
            "reason": self.reason,
            "method": self.method,
            "b": self.b,
            "c": self.c,
            "n": self.n,
            "p_value": self.p_value,
            "alpha_eff": self.alpha_eff,
            "delta_q": self.delta_q,
            "cost_ratio": self.cost_ratio,
            "cost_ok": self.cost_ok,
            "cost_path": self.cost_path,
            "quality_non_inferior": self.quality_non_inferior,
            "ci": dict(self.ci or {}),
        }
        return {key: value for key, value in data.items() if value is not None}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionResult":
        if not isinstance(data, dict):
            raise ValueError("decision result must be an object")
        return cls(
            decision=Decision(data.get("decision", "unknown")),
            reason=data.get("reason", ""),
            method=data.get("method", "paired_binary"),
            b=data.get("b"),
            c=data.get("c"),
            n=data.get("n"),
            p_value=data.get("p_value"),
            alpha_eff=data.get("alpha_eff"),
            delta_q=data.get("delta_q"),
            cost_ratio=data.get("cost_ratio"),
            cost_ok=data.get("cost_ok"),
            cost_path=bool(data.get("cost_path", False)),
            quality_non_inferior=data.get("quality_non_inferior"),
            ci=dict(data.get("ci") or {}),
        )


def _check_rate_inputs(b: int, c: int, n: int, alpha: float, k: int) -> int:
    for name, value in (("b", b), ("c", c), ("k", k)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if not (0 < alpha < 1):
        raise ValueError("alpha must be between 0 and 1")
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise ValueError("n must be a non-negative integer and is required")
    if n < b + c:
        raise ValueError("n must be >= b + c")
    return n


def _cost_ratio(cost_b: Optional[float], cost_c: Optional[float]) -> Optional[float]:
    if cost_b is None or cost_c is None:
        return None
    for name, value in (("cost_b", cost_b), ("cost_c", cost_c)):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{name} must be a non-negative number or null")
    if cost_b <= 0:
        return None
    return float(cost_c) / float(cost_b)


def decide_binary(
    b: int,
    c: int,
    n: int,
    alpha: float = 0.10,
    k: int = 0,
    cost_b: Optional[float] = None,
    cost_c: Optional[float] = None,
    budget: float = 0.10,
    epsilon: float = 0.10,
    delta: float = 0.0,
    constraints_ok: bool = True,
) -> DecisionResult:
    """二元主指标的配对判定。

    ``n``：配对样本总数（必填，不由 b+c 猜）；``b``：候选独家命中数；
    ``c``：基线独家命中数；``k``：同一评估池已复用次数，阈值按
    ``alpha / (k + 1)`` 收紧。``b+c=0`` 没有质量提升证据；没有成本下降时
    返回 insufficient，有成本下降且质量非劣时按成本路径接受。成本为 None
    时质量路径跳过成本条件（不补 0）。
    """
    n = _check_rate_inputs(b, c, n, alpha, k)
    if budget < 0 or epsilon < 0 or delta < 0:
        raise ValueError("budget, epsilon and delta must be non-negative")
    ratio = _cost_ratio(cost_b, cost_c)
    alpha_eff = alpha / (k + 1)
    p_value = exact_mcnemar_ge(b, c)
    delta_q = ((b - c) / n) if n else None
    cost_missing = ratio is None
    cost_ok = cost_missing or ratio <= 1 + budget
    cost_path = (not cost_missing) and delta_q is not None \
        and delta_q >= -delta and ratio <= 1 - epsilon

    base: Dict[str, Any] = dict(
        method="paired_binary",
        b=b,
        c=c,
        n=n,
        p_value=p_value,
        alpha_eff=alpha_eff,
        delta_q=delta_q,
        cost_ratio=ratio,
        cost_ok=cost_ok if not cost_missing else None,
        cost_path=cost_path,
    )

    if not constraints_ok:
        return DecisionResult(
            decision=Decision.REJECT,
            reason="硬约束或回归检查不通过",
            **base,
        )
    if cost_path:
        return DecisionResult(
            decision=Decision.ACCEPT,
            reason=f"主指标非劣，成本比 {ratio:.3f} 下降至少 epsilon={epsilon:.2f}",
            **base,
        )
    if b + c == 0:
        return DecisionResult(
            decision=Decision.INSUFFICIENT,
            reason="没有方向不一致的对子，证据不足",
            **base,
        )
    if b < c:
        return DecisionResult(
            decision=Decision.REJECT,
            reason=f"主指标变差：b={b} < c={c}",
            **base,
        )
    improved = b > c
    evidence = improved and p_value <= alpha_eff
    if improved and evidence and cost_ok:
        return DecisionResult(
            decision=Decision.ACCEPT,
            reason=(
                f"b={b}, c={c}, p={p_value:.4f} <= alpha_eff={alpha_eff:.4f}"
                + ("；成本缺失，质量路径跳过成本条件" if cost_missing
                   else f"；成本比 {ratio:.3f} 在预算内")
            ),
            **base,
        )
    if improved and evidence and not cost_ok:
        return DecisionResult(
            decision=Decision.INSUFFICIENT,
            reason=f"主指标提升但成本比 {ratio:.3f} 超出预算 B={budget:.2f}",
            **base,
        )
    if improved:
        return DecisionResult(
            decision=Decision.INSUFFICIENT,
            reason=(
                f"有提升但证据不足：b={b}, c={c}, "
                f"p={p_value:.4f} > alpha_eff={alpha_eff:.4f}"
            ),
            **base,
        )
    return DecisionResult(
        decision=Decision.INSUFFICIENT,
        reason=f"无方向性变化：b=c={b}",
        **base,
    )


def decide_cost_primary(
    b: int,
    c: int,
    n: int,
    alpha: float = 0.10,
    k: int = 0,
    cost_b: Optional[float] = None,
    cost_c: Optional[float] = None,
    budget: float = 0.10,
    epsilon: float = 0.10,
    delta: float = 0.0,
    constraints_ok: bool = True,
) -> DecisionResult:
    """效率变更：主指标是成本，质量作非劣约束；n 必填。

    ``b+c=0`` 时没有方向证据，返回 insufficient，不进入成本格式化分支。
    """
    n = _check_rate_inputs(b, c, n, alpha, k)
    if budget < 0 or epsilon < 0 or delta < 0:
        raise ValueError("budget, epsilon and delta must be non-negative")
    ratio = _cost_ratio(cost_b, cost_c)
    alpha_eff = alpha / (k + 1)
    p_value = exact_mcnemar_ge(b, c)
    delta_q = ((b - c) / n) if n else None
    non_inferior = delta_q is not None and delta_q >= -delta
    base: Dict[str, Any] = dict(
        method="cost_primary",
        b=b,
        c=c,
        n=n,
        p_value=p_value,
        alpha_eff=alpha_eff,
        delta_q=delta_q,
        cost_ratio=ratio,
        cost_ok=(ratio is not None and ratio <= 1 - epsilon),
        cost_path=(ratio is not None and non_inferior and ratio <= 1 - epsilon),
        quality_non_inferior=non_inferior,
    )
    if not constraints_ok:
        return DecisionResult(decision=Decision.REJECT, reason="硬约束或回归检查不通过", **base)
    if ratio is None:
        return DecisionResult(
            decision=Decision.UNKNOWN,
            reason="成本缺失或基线成本为 0，只看成本的路径不可用",
            **base,
        )
    if not non_inferior:
        delta_text = "unknown" if delta_q is None else f"{delta_q:.4f}"
        return DecisionResult(
            decision=Decision.REJECT,
            reason=f"质量超出非劣容差：delta_q={delta_text} < -delta={-delta:.4f}",
            **base,
        )
    if ratio <= 1 - epsilon:
        return DecisionResult(
            decision=Decision.ACCEPT,
            reason=f"成本比 {ratio:.3f} <= 1-epsilon={1 - epsilon:.2f}，质量非劣",
            **base,
        )
    if ratio > 1:
        return DecisionResult(
            decision=Decision.REJECT,
            reason=f"成本上升：成本比 {ratio:.3f} > 1",
            **base,
        )
    return DecisionResult(
        decision=Decision.INSUFFICIENT,
        reason=f"成本比 {ratio:.3f} 未达到最小下降幅度 epsilon={epsilon:.2f}",
        **base,
    )


def decide_paired_score(
    diffs: List[Optional[float]],
    delta: float = 0.0,
    confidence: float = 0.95,
    constraints_ok: bool = True,
    **_: Any,
) -> DecisionResult:
    """连续主指标（rubric 分/计数）：配对差值置信区间。"""
    if delta < 0:
        raise ValueError("delta must be non-negative")
    ci = paired_diff_ci(diffs, confidence=confidence)
    base: Dict[str, Any] = dict(
        method="paired_score",
        ci=ci,
        delta_q=ci.get("mean"),
        quality_non_inferior=(ci["low"] is not None and ci["low"] >= -delta),
    )
    if not constraints_ok:
        return DecisionResult(decision=Decision.REJECT, reason="硬约束或回归检查不通过", **base)
    if ci["mean"] is None:
        return DecisionResult(decision=Decision.UNKNOWN, reason="没有配对差值", **base)
    if ci["low"] is None:
        return DecisionResult(
            decision=Decision.INSUFFICIENT,
            reason="配对样本少于 2 条，无法形成置信区间",
            **base,
        )
    if ci["low"] > 0:
        return DecisionResult(
            decision=Decision.ACCEPT,
            reason=(
                f"配对差值均值 {ci['mean']:.4f}，"
                f"{confidence:.0%} 置信区间下界 {ci['low']:.4f} > 0"
            ),
            **base,
        )
    if ci["mean"] < -delta:
        return DecisionResult(
            decision=Decision.REJECT,
            reason=f"配对差值均值 {ci['mean']:.4f} < -delta={-delta:.4f}",
            **base,
        )
    return DecisionResult(
        decision=Decision.INSUFFICIENT,
        reason="置信区间跨过 0，证据不足",
        **base,
    )


DECISION_METHODS: Dict[str, Callable[..., DecisionResult]] = {
    "paired_binary": decide_binary,
    "cost_primary": decide_cost_primary,
    "paired_score": decide_paired_score,
}


def decide(method: str, **kwargs: Any) -> DecisionResult:
    """按方法名分派；未知方法直接报错，不静默退回默认值。"""
    try:
        fn = DECISION_METHODS[method]
    except KeyError as exc:
        raise ValueError(
            f"unknown decision method {method!r}; "
            f"expected one of {list(DECISION_METHODS)}"
        ) from exc
    return fn(**kwargs)


def required_exclusive_wins(alpha_eff: float) -> int:
    """c=0 时达到 p<=alpha_eff 所需的最少独家命中数。"""
    if not isinstance(alpha_eff, (int, float)) or isinstance(alpha_eff, bool):
        raise ValueError("alpha_eff must be a number")
    if not 0 < alpha_eff < 1:
        raise ValueError("alpha_eff must be between 0 and 1")
    wins = 1
    while 2 ** (-wins) > alpha_eff:
        wins += 1
    return wins
