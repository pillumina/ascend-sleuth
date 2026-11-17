"""优化目标描述。

`object_type` 是评估对象（diagnosis/case/reference/trace）；`TargetSpec` 是改什么
（skill/knowledge/tooling/harness）。两者正交，不能拿 object_type 直接当 target。
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class TargetSpec:
    id: str
    change_surface: str
    eval_profile: str
    eval_profile_id: str
    authority: str
    allowed_algorithms: Tuple[str, ...]
    default_algorithm: str = "baseline"
    description: str = ""

    def validate(self) -> "TargetSpec":
        for name in ("id", "change_surface", "eval_profile", "authority"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"target.{name} is required")
        if not self.allowed_algorithms:
            raise ValueError(f"target {self.id}: allowed_algorithms is empty")
        if self.default_algorithm not in self.allowed_algorithms:
            raise ValueError(
                f"target {self.id}: default_algorithm must be in allowed_algorithms"
            )
        return self
