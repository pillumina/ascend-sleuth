# -*- coding: utf-8 -*-
"""搜索循环层契约：候选快照、动作规格、预算、决策记录与循环描述。

这一层回答「一次搜索怎么走」，与六点 stage（一次改动怎么提、怎么选、怎么判）
正交。搜索循环不调用模型、不写知识文件；它只产出动作，由驱动会话分派执行，再把
结果回写。这样同一套协议可以承载单候选爬山、批次/epoch、群体演化、多保真分配
与消融审计，而不需要每接一个算法就复制一份调度与记账。

三个约束决定了实现形状：

- 候选是快照（一组文件），不是一段文本；单文件算法用 ``Snapshot.from_text``。
- 动作的 ``kind`` 开放，但必须登记在 ``LoopSpec.actions`` 里，驱动按 actor 分派。
- 预算与决策是循环共有的对象，不是框架替循环做决定。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Protocol, Tuple

from ..contracts import now_iso
from ..errors import EvolveError

LOOP_KINDS = ("search", "audit", "control")
SAMPLE_ROLES = ("train", "dev", "eval", "audit", "feedback")
ACTORS = ("target", "worker", "judge")


class LoopError(EvolveError, ValueError):
    """循环状态、动作或参数不合法。"""


@dataclass
class Snapshot:
    """一个可被评估、可被比较的候选版本。

    ``text`` 与 ``files`` 二选一：单文件算法（skill 可变异区）用 ``text``；
    多文件资源（harness、模块组合）用 ``files``。两者同时给或都为空都拒绝，
    避免「看着像快照、其实不知道改了什么」的状态。
    """

    id: str
    text: str = ""
    files: Dict[str, str] = field(default_factory=dict)
    target: str = ""
    component: str = ""
    parent: Optional[str] = None
    scores: Dict[str, float] = field(default_factory=dict)
    feedback: Dict[str, str] = field(default_factory=dict)
    status: str = "candidate"
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise LoopError("snapshot id is required")
        if self.text and self.files:
            raise LoopError("snapshot text and files are mutually exclusive")
        if not self.text and not self.files:
            raise LoopError("snapshot content is empty")
        for sample_id, score in self.scores.items():
            if not isinstance(score, (int, float)) or isinstance(score, bool):
                raise LoopError(f"snapshot score for {sample_id!r} must be a number")

    @property
    def skill(self) -> str:
        """旧接口别名：单文件快照的文本。多文件快照返回空串，不猜主文件。"""
        return self.text

    def content(self) -> Dict[str, str]:
        """统一读法；单文件用空路径作键，多文件按原路径。"""
        return dict(self.files) if self.files else {"": self.text}

    def digest(self) -> str:
        payload = json.dumps(
            {"target": self.target, "component": self.component,
             "content": self.content()},
            ensure_ascii=False, sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id, "text": self.text, "files": dict(self.files),
            "target": self.target, "component": self.component,
            "parent": self.parent, "scores": dict(self.scores),
            "feedback": dict(self.feedback), "status": self.status,
            "meta": dict(self.meta),
        }
        return data

    @classmethod
    def from_text(cls, snapshot_id: str, text: str, *, target: str = "",
                  component: str = "", parent: Optional[str] = None,
                  meta: Optional[Dict[str, Any]] = None) -> "Snapshot":
        return cls(id=snapshot_id, text=text, target=target,
                   component=component, parent=parent, meta=dict(meta or {}))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Snapshot":
        if not isinstance(data, dict):
            raise LoopError("snapshot must be an object")
        # 兼容旧状态：候选只有 skill 文本。
        text = data.get("text")
        if text is None:
            text = data.get("skill") or ""
        files = data.get("files") or {}
        if not isinstance(files, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in files.items()
        ):
            raise LoopError("snapshot files must be a path->text object")
        return cls(
            id=str(data.get("id") or ""), text=str(text or ""),
            files={str(k): str(v) for k, v in files.items()},
            target=str(data.get("target") or ""),
            component=str(data.get("component") or ""),
            parent=data.get("parent"), status=str(data.get("status") or "candidate"),
            scores={str(k): float(v) for k, v in (data.get("scores") or {}).items()},
            feedback={str(k): str(v) for k, v in (data.get("feedback") or {}).items()},
            meta=dict(data.get("meta") or {}),
        )


@dataclass(frozen=True)
class ActionSpec:
    """循环会产出的一个动作。驱动按 actor 决定用哪类 subagent 执行。"""

    kind: str
    actor: str
    required: Tuple[str, ...] = ()
    description: str = ""

    def validate(self) -> "ActionSpec":
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise LoopError("action kind is required")
        if self.actor not in ACTORS:
            raise LoopError(f"action actor must be one of {list(ACTORS)}")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "actor": self.actor,
                "required": list(self.required),
                "description": self.description}


@dataclass(frozen=True)
class LoopSpec:
    """一个算法的登记项。预设只描述节点，循环由这里登记。"""

    id: str
    version: str
    kind: str
    targets: Tuple[str, ...]
    required_roles: Tuple[str, ...]
    actions: Tuple[ActionSpec, ...]
    factory: Callable[[Dict[str, Any]], Any]
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""
    state_schema: str = ""
    restore: Optional[Callable[[Dict[str, Any]], Any]] = None

    def validate(self) -> "LoopSpec":
        if not isinstance(self.id, str) or not self.id.strip():
            raise LoopError("loop id is required")
        if self.kind not in LOOP_KINDS:
            raise LoopError(f"loop kind must be one of {list(LOOP_KINDS)}")
        if not self.targets:
            raise LoopError(f"loop {self.id}: targets is empty")
        for role in self.required_roles:
            if role not in SAMPLE_ROLES:
                raise LoopError(f"loop {self.id}: unknown sample role {role!r}")
            if role == "test":
                raise LoopError(f"loop {self.id}: loops must not read the test role")
        if not callable(self.factory):
            raise LoopError(f"loop {self.id}: factory is not callable")
        if not isinstance(self.params, dict):
            raise LoopError(f"loop {self.id}: params must be an object")
        if self.restore is not None and not callable(self.restore):
            raise LoopError(f"loop {self.id}: restore is not callable")
        kinds = [spec.kind for spec in self.actions]
        if len(set(kinds)) != len(kinds):
            raise LoopError(f"loop {self.id}: duplicate action kinds")
        for spec in self.actions:
            spec.validate()
        return self

    def action(self, kind: str) -> Optional[ActionSpec]:
        for spec in self.actions:
            if spec.kind == kind:
                return spec
        return None


class SearchLoop(Protocol):
    """循环状态机协议；实现可以是纯 Python，也可以包一层已有状态机。"""

    id: str

    def next_action(self) -> Dict[str, Any]:
        ...

    def apply(self, action: Dict[str, Any], result: Dict[str, Any]) -> None:
        ...

    def result(self) -> Dict[str, Any]:
        ...

    def to_dict(self) -> Dict[str, Any]:
        ...


def validate_action(action: Any, spec: Optional[LoopSpec] = None) -> Dict[str, Any]:
    """校验动作外壳；``stop`` 不需要登记。循环内字段由循环自己再校验。"""
    if not isinstance(action, dict):
        raise LoopError("action must be an object")
    kind = action.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        raise LoopError("action kind is required")
    if kind == "stop":
        return action
    if spec is not None:
        action_spec = spec.action(kind)
        if action_spec is None:
            raise LoopError(
                f"unknown action {kind!r} for loop {spec.id}; "
                f"registered: {sorted(s.kind for s in spec.actions)}"
            )
        missing = [key for key in action_spec.required if key not in action]
        if missing:
            raise LoopError(f"action {kind!r} missing: {', '.join(missing)}")
    return action


def action_actor(spec: LoopSpec, kind: str) -> Optional[str]:
    action_spec = spec.action(kind)
    return action_spec.actor if action_spec else None


def param_errors(spec: "LoopSpec", params: Dict[str, Any]) -> list:
    """参数名与类型的校验；返回错误消息，不抛异常。"""
    if not isinstance(params, dict):
        return ["params must be an object"]
    errors = []
    unknown = set(params) - set(spec.params)
    if unknown:
        errors.append(f"unknown params: {sorted(unknown)}")
    for name, value in params.items():
        if name not in spec.params:
            continue
        default = spec.params[name]
        if default is None:
            ok = value is None or (isinstance(value, int) and not isinstance(value, bool))
            expected = "an integer or null"
        elif isinstance(default, bool):
            ok = isinstance(value, bool)
            expected = "a boolean"
        elif isinstance(default, int):
            ok = isinstance(value, int) and not isinstance(value, bool)
            expected = "an integer"
        elif isinstance(default, float):
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
            expected = "a number"
        elif isinstance(default, str):
            ok = isinstance(value, str)
            expected = "a string"
        elif isinstance(default, list):
            ok = isinstance(value, list)
            expected = "a list"
        elif isinstance(default, dict):
            ok = isinstance(value, dict)
            expected = "an object"
        else:
            ok = True
            expected = "a supported value"
        if not ok:
            errors.append(f"{name} must be {expected}")
    return errors


def decision_record(loop_id: str, kind: str, *, run: str = "", step: int = 0,
                    candidate: str = "", parent: str = "",
                    score: Optional[float] = None,
                    baseline: Optional[float] = None,
                    accepted: Optional[bool] = None,
                    reason: str = "") -> Dict[str, Any]:
    """决策记录的统一形状；循环只追加，不就地改写。"""
    return {
        "run": str(run), "loop": str(loop_id), "kind": str(kind),
        "step": int(step), "candidate": str(candidate), "parent": str(parent),
        "score": score, "baseline": baseline, "accepted": accepted,
        "reason": str(reason), "at": now_iso(),
    }
