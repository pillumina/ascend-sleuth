"""人工 baseline：不自动提议，只提供对照身份和 Patch 包络。"""

from typing import Any, Dict, List

from ..contracts import Patch


class BaselineOptimizer:
    id = "baseline"
    version = "manual"
    scope = "all"
    execution = "manual"

    def propose(self, target: str, observations: List[Any], current: Any,
                budget: Dict[str, Any]) -> Patch:
        return Patch(
            target_kind=str(target),
            target_component="control",
            summary="control arm: no automatic proposal; candidate must be supplied separately",
            algorithm=self.id,
            algorithm_version=self.version,
            payload={"role": "control", "proposal": False,
                     "observations": len(observations or [])},
            budget=dict(budget or {}),
        )
