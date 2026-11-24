# -*- coding: utf-8 -*-
"""组合实验的描述：声明跑哪些搜索循环、用哪些样本角色、怎么组合。

实验层不碰模型与文件：它只把「多臂比较 / 顺序链」写成可校验的 spec，由
``experiment_session`` 驱动。预设只描述节点，搜索循环由 ``loops.registry`` 登记；
spec 里的 ``arms[].loop`` 指向那张表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .errors import EvolveError
from .loops import LoopError, get_loop, param_errors
from .loops.contract import SAMPLE_ROLES
from .targets.registry import TARGETS

COMPOSITIONS = ("parallel", "sequential")
BUDGET_KEYS = ("target_runs", "worker_calls", "tokens")


class ExperimentSpecError(LoopError, EvolveError):
    """实验描述不合法。"""


@dataclass
class ArmSpec:
    name: str
    loop: str
    recipe: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    budget: Dict[str, int] = field(default_factory=dict)
    roles: Dict[str, str] = field(default_factory=dict)

    def resolved_roles(self, required: List[str]) -> Dict[str, str]:
        resolved = {}
        for role in required:
            mapped = self.roles.get(role, role)
            resolved[role] = mapped
        return resolved

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "loop": self.loop, "recipe": self.recipe,
                "params": dict(self.params), "budget": dict(self.budget),
                "roles": dict(self.roles)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArmSpec":
        if not isinstance(data, dict):
            raise ExperimentSpecError("arm must be an object")
        return cls(
            name=str(data.get("name") or ""),
            loop=str(data.get("loop") or ""),
            recipe=str(data.get("recipe") or ""),
            params=dict(data.get("params") or {}),
            budget=dict(data.get("budget") or {}),
            roles=dict(data.get("roles") or {}),
        )


@dataclass
class ExperimentSpec:
    id: str
    target: str
    component: str
    arms: List[ArmSpec]
    samples: Dict[str, List[str]]
    composition: str = "parallel"
    primary_arm: str = ""
    eval_role: str = "dev"
    seed_text: str = ""
    seed: int = 0

    def validate(self) -> "ExperimentSpec":
        if not self.id.strip():
            raise ExperimentSpecError("experiment id is required")
        if self.target not in TARGETS:
            raise ExperimentSpecError(
                f"unknown target {self.target!r}; expected one of {sorted(TARGETS)}"
            )
        if not self.component.strip():
            raise ExperimentSpecError("component is required")
        if self.composition not in COMPOSITIONS:
            raise ExperimentSpecError(
                f"composition must be one of {list(COMPOSITIONS)}"
            )
        if not self.arms:
            raise ExperimentSpecError("at least one arm is required")
        names = [arm.name for arm in self.arms]
        if any(not name.strip() for name in names):
            raise ExperimentSpecError("arm names are required")
        if len(set(names)) != len(names):
            raise ExperimentSpecError("arm names must be unique")

        allowed_roles = set(SAMPLE_ROLES) - {"test"}
        if not self.samples:
            raise ExperimentSpecError("samples are required")
        seen: Dict[str, str] = {}
        for role, values in self.samples.items():
            if role not in allowed_roles:
                raise ExperimentSpecError(
                    f"unknown sample role {role!r}; expected one of {sorted(allowed_roles)}"
                )
            if not isinstance(values, list) or not all(
                isinstance(item, str) and item.strip() for item in values
            ):
                raise ExperimentSpecError(f"samples.{role} must be non-empty strings")
            if len(set(values)) != len(values):
                raise ExperimentSpecError(f"samples.{role} must not contain duplicates")
            for sample_id in values:
                if sample_id in seen:
                    raise ExperimentSpecError(
                        f"sample {sample_id!r} appears in both "
                        f"{seen[sample_id]!r} and {role!r}"
                    )
                seen[sample_id] = role

        for arm in self.arms:
            self._validate_arm(arm)

        kinds = [get_loop(arm.loop).kind for arm in self.arms]
        audit_only = all(kind == "audit" for kind in kinds)

        if self.composition == "sequential":
            if len(self.arms) == 1:
                pass
            kinds = [get_loop(arm.loop).kind for arm in self.arms]
            if any(kind == "audit" for kind in kinds):
                raise ExperimentSpecError(
                    "sequential composition only accepts search/control loops; "
                    "audit loops run as a single arm"
                )
            if self.primary_arm:
                raise ExperimentSpecError(
                    "sequential composition has one output; primary_arm is not used"
                )
        else:
            if len(self.arms) > 1 and any(kind == "audit" for kind in kinds):
                raise ExperimentSpecError(
                    "parallel composition cannot mix audit loops with search arms; "
                    "run the audit as a single arm"
                )
            if not self.primary_arm and not all(kind == "audit" for kind in kinds):
                search = [arm.name for arm in self.arms
                          if get_loop(arm.loop).kind == "search"]
                if not search:
                    search = [arm.name for arm in self.arms
                              if get_loop(arm.loop).kind == "control"]
                if not search:
                    raise ExperimentSpecError("parallel composition needs a search arm")
                self.primary_arm = search[0]
            if self.primary_arm and self.primary_arm not in names:
                raise ExperimentSpecError(
                    f"primary_arm {self.primary_arm!r} is not an arm"
                )
            if len(self.arms) == 1 and get_loop(self.arms[0].loop).kind == "audit":
                if self.primary_arm:
                    raise ExperimentSpecError("audit arm cannot be primary")

        if audit_only:
            return self
        if self.eval_role not in ("dev", "eval"):
            raise ExperimentSpecError("eval_role must be dev or eval")
        if self.eval_role not in self.samples:
            raise ExperimentSpecError(
                f"eval_role {self.eval_role!r} is not in samples"
            )
        if not self.samples[self.eval_role]:
            raise ExperimentSpecError("eval_role samples must be non-empty")
        return self

    def _validate_arm(self, arm: ArmSpec) -> None:
        try:
            spec = get_loop(arm.loop)
        except LoopError as exc:
            raise ExperimentSpecError(str(exc)) from exc
        if self.target not in spec.targets:
            raise ExperimentSpecError(
                f"loop {arm.loop!r} does not support target {self.target!r}"
            )
        resolved = arm.resolved_roles(list(spec.required_roles))
        for role, mapped in resolved.items():
            if mapped not in self.samples:
                raise ExperimentSpecError(
                    f"arm {arm.name!r}: role {role!r} maps to missing sample role "
                    f"{mapped!r}"
                )
            if not self.samples[mapped]:
                raise ExperimentSpecError(
                    f"arm {arm.name!r}: sample role {mapped!r} is empty"
                )
        errors = param_errors(spec, arm.params)
        if errors:
            raise ExperimentSpecError(
                f"arm {arm.name!r}: {'; '.join(errors)}"
            )
        unknown = set(arm.roles) - set(spec.required_roles)
        if unknown:
            raise ExperimentSpecError(
                f"arm {arm.name!r}: unknown roles {sorted(unknown)}; "
                f"expected {list(spec.required_roles)}"
            )
        for key, value in arm.budget.items():
            if key not in BUDGET_KEYS:
                raise ExperimentSpecError(
                    f"arm {arm.name!r}: unknown budget key {key!r}"
                )
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 1
            ):
                raise ExperimentSpecError(
                    f"arm {arm.name!r}: budget {key} must be a positive integer"
                )
        if arm.budget.get("target_runs") is None:
            arm.budget["target_runs"] = 12

    def arm(self, name: str) -> ArmSpec:
        for arm in self.arms:
            if arm.name == name:
                return arm
        raise ExperimentSpecError(f"unknown arm {name!r}")

    def data_for(self, arm: ArmSpec) -> Dict[str, List[str]]:
        spec = get_loop(arm.loop)
        return {
            role: list(self.samples[mapped])
            for role, mapped in arm.resolved_roles(list(spec.required_roles)).items()
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "target": self.target, "component": self.component,
            "composition": self.composition, "primary_arm": self.primary_arm,
            "eval_role": self.eval_role, "seed_text": self.seed_text,
            "seed": self.seed,
            "samples": {key: list(value) for key, value in self.samples.items()},
            "arms": [arm.to_dict() for arm in self.arms],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperimentSpec":
        if not isinstance(data, dict):
            raise ExperimentSpecError("experiment spec must be an object")
        raw_arms = data.get("arms")
        if not isinstance(raw_arms, list):
            raise ExperimentSpecError("arms must be a list")
        raw_samples = data.get("samples")
        if not isinstance(raw_samples, dict):
            raise ExperimentSpecError("samples must be an object")
        samples = {}
        for key, value in raw_samples.items():
            if not isinstance(value, (list, tuple)):
                raise ExperimentSpecError(f"samples.{key} must be a list")
            samples[str(key)] = [str(item) for item in value]
        return cls(
            id=str(data.get("id") or ""),
            target=str(data.get("target") or ""),
            component=str(data.get("component") or ""),
            arms=[ArmSpec.from_dict(item) for item in raw_arms],
            samples=samples,
            composition=str(data.get("composition") or "parallel"),
            primary_arm=str(data.get("primary_arm") or ""),
            eval_role=str(data.get("eval_role") or "dev"),
            seed_text=str(data.get("seed_text") or ""),
            seed=int(data.get("seed") or 0),
        )


def load_spec(path: str) -> ExperimentSpec:
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ExperimentSpecError(f"spec YAML is invalid: {exc}") from exc
    return ExperimentSpec.from_dict(data).validate()
