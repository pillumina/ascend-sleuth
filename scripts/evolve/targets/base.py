"""优化目标描述。

`object_type` 是评估对象（diagnosis/case/reference/trace）；`TargetSpec` 是改什么
（skill/knowledge/tooling/harness）。两者正交，不能拿 object_type 直接当 target。

一个目标的全部事实都在这里：评测面、授权级别、允许的算法、工件规则、提案边界。
新增目标只改 `registry.TARGETS` 的一条与（需要时）一条工件规则，不在 candidate、
proposals、proposal_engine、migrate 里各加一份枚举。
"""

from dataclasses import dataclass
from typing import Any, Callable, Tuple

# 未配置目标时用的默认目标；代码里不要另写字面量 "skill"。
DEFAULT_TARGET = "skill"

ARTIFACT_KINDS = ("text", "yaml", "code", "config")


@dataclass(frozen=True)
class ArtifactRule:
    """一个目标的工件规则：路径许可、体积上限与写前检查。

    ``allowed`` 判断某条 region 下能否改这个文件；``check`` 在写盘前做语法/结构
    检查，不判断语义正确性，失败时抛 ValueError（调用方转成自己的错误类型）。
    """

    kind: str
    max_text: int
    allowed: Callable[[str, Any], bool]
    check: Callable[[str, str], None]
    region_owns_skill: bool = False

    def validate(self) -> "ArtifactRule":
        if self.kind not in ARTIFACT_KINDS:
            raise ValueError(
                f"artifact.kind must be one of {list(ARTIFACT_KINDS)}, got {self.kind!r}"
            )
        if not isinstance(self.max_text, int) or isinstance(self.max_text, bool) \
                or self.max_text <= 0:
            raise ValueError("artifact.max_text must be a positive integer")
        if not callable(self.allowed) or not callable(self.check):
            raise ValueError("artifact.allowed and artifact.check must be callable")
        if not isinstance(self.region_owns_skill, bool):
            raise ValueError("artifact.region_owns_skill must be boolean")
        return self


@dataclass(frozen=True)
class TargetSpec:
    id: str
    change_surface: str
    eval_profile: str
    eval_profile_id: str
    authority: str
    allowed_algorithms: Tuple[str, ...]
    artifact: ArtifactRule
    allowed_paths: Tuple[str, ...]
    forbidden_paths: Tuple[str, ...]
    prompt_rules: Tuple[str, ...]
    required_checks: Tuple[str, ...]
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
        if not self.allowed_paths:
            raise ValueError(f"target {self.id}: allowed_paths is empty")
        if not self.prompt_rules:
            raise ValueError(f"target {self.id}: prompt_rules is empty")
        self.artifact.validate()
        return self
