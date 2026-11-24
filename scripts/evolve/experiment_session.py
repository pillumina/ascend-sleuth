# -*- coding: utf-8 -*-
"""组合实验状态机：按 spec 跑多臂或顺序链，产出每臂结果与主臂读数。

它不调用模型：与搜索循环一样产出动作，驱动按 ``action.actor`` 分派。多臂按顺序
执行（v1 不做交错），每臂有独立目标执行预算；每臂跑完后在共同的 dev/eval
样本上再评一遍，得到可横向比较的读数。最终合入仍由配对门判定，本模块不把
臂间均分差当成统计结论。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from typing import Any, Dict, List, Optional

from .experiment_spec import ExperimentSpec
from .errors import EvolveError
from .loops import Budget, LoopError, get_loop, restore_loop
from .loops.baseline import BaselineLoop
from .recipes import RecipeError, get_recipe

EXPERIMENT_STATE_SCHEMA = "rsi-experiment-v1"


class ExperimentError(LoopError, EvolveError):
    """实验状态或动作不合法。"""


class ExperimentSession:
    def __init__(self, spec: ExperimentSpec, decisions_path: Optional[str] = None):
        self.spec = spec.validate()
        self.decisions_path = decisions_path
        self.arm_index = 0
        self.phase = "arm"  # arm | eval | done
        self.loop: Any = None
        self.eval_loop: Any = None
        self.eval_arm: str = ""
        self.arm_results: List[Dict[str, Any]] = []
        self.pending: Optional[Dict[str, Any]] = None
        self.stop_reason: Optional[str] = None

    # -- 状态推进 -------------------------------------------------------
    def next_action(self) -> Dict[str, Any]:
        if self.pending is not None:
            return self.pending
        if self.phase == "done":
            return {"kind": "stop", "reason": self.stop_reason or "complete"}
        if self.phase == "arm" and self.loop is None:
            self._start_arm()
        if self.phase == "arm":
            action = self.loop.next_action()
            if action.get("kind") == "stop":
                self._finish_loop(str(action.get("reason") or "complete"))
            else:
                self.pending = {
                    "arm": self.spec.arms[self.arm_index].name,
                    "loop": self.spec.arms[self.arm_index].loop,
                    "action": action,
                }
                return self.pending
        if self.phase == "eval":
            action = self.eval_loop.next_action()
            if action.get("kind") == "stop":
                self._finish_eval()
            else:
                self.pending = {
                    "arm": self.eval_arm, "loop": "baseline", "eval": True,
                    "action": action,
                }
                return self.pending
        return self.next_action()

    def apply(self, pending: Dict[str, Any], result: Dict[str, Any]) -> None:
        if self.pending is None:
            raise ExperimentError("no pending action")
        if pending != self.pending:
            raise ExperimentError("pending action mismatch; call next first")
        if not isinstance(result, dict):
            raise ExperimentError("result must be an object")
        action = pending["action"]
        if pending.get("eval"):
            self.eval_loop.apply(action, result)
        else:
            self.loop.apply(action, result)
        self.pending = None

    # -- 臂的起止 -------------------------------------------------------
    def _start_arm(self) -> None:
        arm = self.spec.arms[self.arm_index]
        seed_text = self.spec.seed_text
        if self.spec.composition == "sequential" and self.arm_index > 0:
            previous = self.arm_results[-1]
            seed_text = str(previous.get("best_skill") or "")
            if not seed_text:
                raise ExperimentError(
                    f"sequential arm {arm.name!r} has no previous snapshot to seed"
                )
        spec = get_loop(arm.loop)
        cfg: Dict[str, Any] = dict(arm.params)
        cfg.update({
            "seed_text": seed_text,
            "data": self.spec.data_for(arm),
            "target": self.spec.target,
            "component": self.spec.component,
            "seed": self.spec.seed,
            "run_id": f"{self.spec.id}/{arm.name}",
        })
        if self.decisions_path:
            cfg["decision_log"] = self.decisions_path
        cfg["target_runs"] = int(arm.budget.get("target_runs") or 12)
        cfg["worker_calls"] = arm.budget.get("worker_calls")
        cfg["tokens"] = arm.budget.get("tokens")
        self.loop = spec.factory(cfg)
        self.phase = "arm"

    def _finish_loop(self, stop_reason: str = "") -> None:
        result = self.loop.result()
        result["arm"] = self.spec.arms[self.arm_index].name
        result["loop"] = self.spec.arms[self.arm_index].loop
        result["stop_reason"] = stop_reason or str(result.get("stop_reason") or "")
        self.arm_results.append(result)
        if self._wants_eval(result):
            self._start_eval(result)
        else:
            self._advance_arm()

    def _wants_eval(self, result: Dict[str, Any]) -> bool:
        if self.spec.eval_role not in self.spec.samples:
            return False
        return bool(result.get("best_skill")) and bool(self.spec.samples[self.spec.eval_role])

    def _start_eval(self, result: Dict[str, Any]) -> None:
        self.eval_arm = result["arm"]
        samples = list(self.spec.samples[self.spec.eval_role])
        self.eval_loop = BaselineLoop(
            seed_skill=str(result["best_skill"]), samples=samples,
            target=self.spec.target, component=self.spec.component,
            budget=Budget(target_runs=len(samples)),
        )
        self.phase = "eval"

    def _finish_eval(self) -> None:
        evaluated = self.eval_loop.result()
        scores = dict(evaluated.get("scores") or {})
        mean = (round(sum(scores.values()) / len(scores), 9) if scores else None)
        if self.arm_results:
            self.arm_results[-1]["eval_role"] = self.spec.eval_role
            self.arm_results[-1]["eval_scores"] = scores
            self.arm_results[-1]["eval_score"] = mean
            self.arm_results[-1]["eval_calls"] = evaluated.get("calls")
        self.eval_loop = None
        self.eval_arm = ""
        self._advance_arm()

    def _advance_arm(self) -> None:
        self.loop = None
        self.arm_index += 1
        if self.arm_index >= len(self.spec.arms):
            self.phase = "done"
            self.stop_reason = "complete"
        else:
            self.phase = "arm"

    # -- 结果 -----------------------------------------------------------
    def result(self) -> Dict[str, Any]:
        primary = self.spec.primary_arm or None
        primary_result = None
        if primary:
            for item in self.arm_results:
                if item.get("arm") == primary:
                    primary_result = item
                    break
        return {
            "experiment": self.spec.id,
            "target": self.spec.target,
            "component": self.spec.component,
            "composition": self.spec.composition,
            "eval_role": self.spec.eval_role,
            "primary_arm": primary,
            "primary_eval_score": (primary_result or {}).get("eval_score"),
            "arms": list(self.arm_results),
            "done": self.phase == "done",
            "stop_reason": self.stop_reason,
            "remaining": [arm.name for arm in self.spec.arms[self.arm_index:]],
        }

    # -- 持久化 ---------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_schema": EXPERIMENT_STATE_SCHEMA,
            "spec": self.spec.to_dict(),
            "arm_index": self.arm_index,
            "phase": self.phase,
            "loop": ({"id": self.spec.arms[self.arm_index].loop,
                      "state": self.loop.to_dict()}
                     if self.loop is not None and self.arm_index < len(self.spec.arms)
                     else None),
            "eval_loop": (self.eval_loop.to_dict() if self.eval_loop is not None else None),
            "eval_arm": self.eval_arm,
            "arm_results": list(self.arm_results),
            "pending": self.pending,
            "stop_reason": self.stop_reason,
            "decisions_path": self.decisions_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperimentSession":
        if data.get("state_schema") not in (None, EXPERIMENT_STATE_SCHEMA):
            raise ExperimentError("experiment state schema mismatch")
        if not isinstance(data.get("spec"), dict):
            raise ExperimentError("experiment state requires spec")
        session = cls(ExperimentSpec.from_dict(data["spec"]).validate(),
                      decisions_path=data.get("decisions_path"))
        session.arm_index = int(data.get("arm_index") or 0)
        session.phase = str(data.get("phase") or "arm")
        if session.phase not in ("arm", "eval", "done"):
            raise ExperimentError(f"unknown experiment phase {session.phase!r}")
        if not 0 <= session.arm_index <= len(session.spec.arms):
            raise ExperimentError("experiment arm_index is out of range")
        raw_loop = data.get("loop")
        if raw_loop:
            if not isinstance(raw_loop, dict) or not raw_loop.get("state"):
                raise ExperimentError("experiment loop state must be an object")
            session.loop = restore_loop(str(raw_loop.get("id") or ""), raw_loop["state"])
        raw_eval = data.get("eval_loop")
        session.eval_loop = BaselineLoop.from_dict(raw_eval) if raw_eval else None
        session.eval_arm = str(data.get("eval_arm") or "")
        session.arm_results = list(data.get("arm_results") or [])
        session.pending = data.get("pending")
        session.stop_reason = data.get("stop_reason")
        return session


def init_session(spec_path: str, seed_file: Optional[str] = None,
                 decisions_path: Optional[str] = None,
                 policy: Optional[Dict[str, Any]] = None,
                 root: Optional[str] = None) -> ExperimentSession:
    try:
        raw = yaml.safe_load(Path(spec_path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ExperimentError(f"spec YAML is invalid: {exc}") from exc
    if not isinstance(raw, dict):
        raise ExperimentError("experiment spec must be an object")
    spec = ExperimentSpec.from_dict(raw)
    if policy is not None:
        experiment = policy.get("experiment") or {}
        default_recipe = str(experiment.get("recipe") or "")
        default_loop = str(experiment.get("loop") or "")
        configured = experiment.get("loops") or {}
        for arm in spec.arms:
            recipe_name = arm.recipe or ("" if arm.loop else default_recipe)
            if recipe_name:
                recipe = get_recipe(recipe_name, root=root)
                if arm.loop and arm.loop != recipe.loop:
                    raise ExperimentError(
                        f"arm {arm.name!r}: recipe {recipe_name!r} uses loop "
                        f"{recipe.loop!r}, not {arm.loop!r}"
                    )
                arm.loop = recipe.loop
                roles = dict(recipe.roles)
                roles.update(arm.roles)
                arm.roles = roles
                params = dict(recipe.params)
                params.update(arm.params)
                arm.params = params
                budget = dict(recipe.budget)
                budget.update(arm.budget)
                arm.budget = budget
                continue
            if not arm.loop:
                arm.loop = default_loop
            defaults = configured.get(arm.loop) or {}
            params = dict(defaults.get("params") or {})
            params.update(arm.params)
            arm.params = params
            budget = dict(defaults.get("budget") or {})
            budget.update(arm.budget)
            arm.budget = budget
    seed_path = seed_file or raw.get("seed_file")
    if seed_path:
        spec.seed_text = Path(str(seed_path)).read_text(encoding="utf-8")
    return ExperimentSession(spec.validate(), decisions_path=decisions_path)
