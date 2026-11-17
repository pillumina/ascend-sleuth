"""GEPA 适配器：把 Pareto prompt 进化包成 Optimizer。

真正的 rollout、task model、reflection model 由实验调用方注入；本适配器不建
模型、不读密钥、不伪造分数。`gepa` 只在调用时导入，未安装时给可照做的错误。
"""

from typing import Any, Dict, List

from ..contracts import Patch


class GepaUnavailable(RuntimeError):
    """gepa 未安装或实验配置不完整。"""


class GepaOptimizer:
    id = "gepa"
    version = "0.1"
    scope = "skill"

    def propose(self, target: str, observations: List[Any], current: Any,
                budget: Dict[str, Any]) -> Patch:
        if target != "skill":
            raise GepaUnavailable("GEPA adapter currently supports target 'skill' only")
        config = (budget or {}).get("gepa")
        if not isinstance(config, dict):
            raise GepaUnavailable("budget.gepa is required")
        required = ("seed_candidate", "trainset", "evaluator",
                    "task_lm", "reflection_lm")
        missing = [key for key in required if key not in config]
        if missing:
            raise GepaUnavailable("budget.gepa missing: " + ", ".join(missing))
        try:
            import gepa  # type: ignore
        except ImportError as exc:
            raise GepaUnavailable(
                "gepa is not installed; use Python >=3.10 and `pip install gepa`"
            ) from exc
        result = gepa.optimize(
            seed_candidate=config["seed_candidate"],
            trainset=config["trainset"],
            valset=config.get("valset"),
            evaluator=config["evaluator"],
            task_lm=config["task_lm"],
            reflection_lm=config["reflection_lm"],
            max_metric_calls=config.get("max_metric_calls", 100),
            reflection_minibatch_size=config.get("reflection_minibatch_size", 3),
            seed=config.get("seed", (budget or {}).get("seed", 0)),
            display_progress_bar=False,
        )
        best = getattr(result, "best_candidate", None)
        if isinstance(best, dict) and "skill" in best:
            best_text = best["skill"]
        else:
            best_text = str(best)
        return Patch(
            target_kind=target,
            target_component=config.get("component", "skill"),
            summary="GEPA Pareto candidate",
            algorithm=self.id,
            algorithm_version=self.version,
            payload={
                "best_candidate": best_text,
                "total_metric_calls": getattr(result, "total_metric_calls", None),
                "candidate_count": len(getattr(result, "candidates", []) or []),
                "observation_count": len(observations or []),
            },
            budget={key: value for key, value in config.items()
                    if key in ("max_metric_calls", "reflection_minibatch_size", "seed")},
            seed=config.get("seed", (budget or {}).get("seed", 0)),
        )
