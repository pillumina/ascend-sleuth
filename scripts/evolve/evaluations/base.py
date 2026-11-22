"""评测面描述：哪个 target 用哪套 scorer/gate，是否已端到端可用。"""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class EvalProfile:
    id: str
    label: str
    object_types: Tuple[str, ...]
    gate: str
    implemented: bool = False

    def validate(self) -> "EvalProfile":
        for name in ("id", "label", "gate"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"eval_profile.{name} is required")
        if not self.object_types:
            raise ValueError(f"eval_profile {self.id}: object_types is empty")
        return self
