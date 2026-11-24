# -*- coding: utf-8 -*-
"""GEPA：候选池 + 反思变异 + Pareto 选择 + 按目标执行预算停。

这是循环层的第一个实现，用来验证契约能承载「单候选爬山 / 候选池」这一类。
它不调用模型：``next_action`` 产出 evaluate/reflect，驱动执行后经 ``apply``
回写。状态 schema 保持 ``agent-gepa-v1``，旧状态文件可以继续读。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .budget import Budget
from .contract import LoopError, Snapshot
from .decisions import DecisionLog
from ..errors import EvolveError
from ..selectors import BestSelector, NoneSelector, ParetoSelector
from ..stages import get_stage

GEPA_STATE_SCHEMA = "agent-gepa-v1"

Candidate = Snapshot


class GepaError(LoopError, EvolveError):
    """GEPA 状态机输入或动作顺序不合法。"""


class AgentRsiSession:
    """实验状态机：propose/select stage 可替换；GEPA 是默认组合。"""

    id = "gepa"
    version = "v2"

    def __init__(self, seed_skill: str, samples: List[str],
                 max_metric_calls: int = 12, population: int = 4,
                 seed: int = 0, min_score: float = 0.0,
                 target_skill: str = "", mutable_region: str = "",
                 select_stage: str = "select.best",
                 propose_stage: str = "propose.agent",
                 selector: Any = None,
                 budget: Optional[Budget] = None,
                 decision_log: Optional[DecisionLog] = None,
                 run_id: str = ""):
        if not isinstance(seed_skill, str) or not seed_skill.strip():
            raise GepaError("seed_skill is required")
        if not samples or not all(isinstance(s, str) and s.strip() for s in samples):
            raise GepaError("samples must be non-empty strings")
        if len(set(samples)) != len(samples):
            raise GepaError("samples must not contain duplicates")
        if not isinstance(max_metric_calls, int) or isinstance(max_metric_calls, bool) \
                or max_metric_calls <= 0:
            raise GepaError("max_metric_calls must be a positive integer")
        if not isinstance(population, int) or population <= 0:
            raise GepaError("population must be a positive integer")
        self.samples = list(samples)
        self.max_metric_calls = max_metric_calls
        self.population = population
        self.seed = seed
        self.min_score = min_score
        self.target_skill = str(target_skill or "")
        self.mutable_region = str(mutable_region or "")
        self.budget = budget or Budget(target_runs=max_metric_calls)
        if self.budget.target_runs is None:
            self.budget.target_runs = max_metric_calls
        self.decision_log = decision_log
        self.run_id = str(run_id or "")
        self.select_stage = get_stage(select_stage)
        self.propose_stage = get_stage(propose_stage)
        if self.select_stage.point != "select_candidate":
            raise GepaError("select_stage must be a select_candidate stage")
        if self.propose_stage.point not in ("propose",):
            raise GepaError("propose_stage must be a propose stage")
        if selector is None:
            if select_stage == "select.none":
                selector = NoneSelector()
            elif select_stage == "select.pareto":
                selector = ParetoSelector()
            else:
                selector = BestSelector()
        self.selector = selector
        self.candidates: List[Snapshot] = [
            Snapshot.from_text("seed", seed_skill, target=self.target_skill,
                               component=self.mutable_region),
        ]
        self.reflected: List[str] = []
        self.pending_reflect: Optional[str] = None

    # -- 兼容：旧代码读 calls / max_metric_calls ---------------------------
    @property
    def calls(self) -> int:
        return self.budget.spent("target_runs")

    @calls.setter
    def calls(self, value: int) -> None:
        self.budget.used["target_runs"] = int(value)

    # -- actions ---------------------------------------------------------
    def next_action(self) -> Dict[str, Any]:
        if not self.budget.can_spend("target_runs"):
            return {"kind": "stop", "reason": "budget"}
        incomplete = [c for c in self.candidates if len(c.scores) < len(self.samples)]
        if incomplete:
            candidate = incomplete[0]
            missing = [s for s in self.samples if s not in candidate.scores]
            return {
                "kind": "evaluate", "candidate_id": candidate.id,
                "skill": candidate.skill, "sample_id": missing[0],
            }
        if self.select_stage.id == "select.none" or self.propose_stage.id == "propose.none":
            return {"kind": "stop", "reason": "baseline_control"}
        best = self.best()
        if best is not None and all(score >= 1.0 for score in best.scores.values()):
            return {"kind": "stop", "reason": "perfect_score"}
        if len(self.candidates) >= self.population:
            return {"kind": "stop", "reason": "population"}
        parent = self._select_parent()
        if parent is None:
            return {"kind": "stop", "reason": "no_unreflected_pareto"}
        if not self.budget.can_spend("worker_calls"):
            return {"kind": "stop", "reason": "worker_calls_budget"}
        self.pending_reflect = parent.id
        failures = [
            {"sample_id": sid, "score": parent.scores[sid],
             "feedback": parent.feedback.get(sid, "")}
            for sid in self.samples if parent.scores[sid] <= self.min_score
        ]
        return {
            "kind": "reflect", "candidate_id": parent.id,
            "skill": parent.skill, "failures": failures,
        }

    def record_evaluation(self, candidate_id: str, sample_id: str,
                          score: float, feedback: str = "") -> None:
        if not self.budget.can_spend("target_runs"):
            raise GepaError("max_metric_calls reached")
        if sample_id not in self.samples:
            raise GepaError(f"unknown sample {sample_id!r}")
        candidate = self._candidate(candidate_id)
        if sample_id in candidate.scores:
            raise GepaError(f"sample {sample_id!r} already evaluated for {candidate_id!r}")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise GepaError("score must be a number")
        if not 0 <= float(score) <= 1:
            raise GepaError("score must be between 0 and 1")
        candidate.scores[sample_id] = float(score)
        candidate.feedback[sample_id] = str(feedback or "")
        self.budget.spend("target_runs")

    def record_candidate(self, skill: str) -> Snapshot:
        if self.pending_reflect is None:
            raise GepaError("no reflect action pending")
        if not isinstance(skill, str) or not skill.strip():
            raise GepaError("candidate skill is required")
        parent = self.pending_reflect
        self.reflected.append(parent)
        self.pending_reflect = None
        candidate = Snapshot.from_text(
            f"c{len(self.candidates)}", skill, target=self.target_skill,
            component=self.mutable_region, parent=parent,
        )
        self.candidates.append(candidate)
        self.budget.spend("worker_calls")
        if self.decision_log is not None:
            self.decision_log.record(
                self.id, "candidate", run=self.run_id, step=len(self.candidates),
                candidate=candidate.id, parent=parent, reason="reflection",
            )
        return candidate

    def apply(self, action: Dict[str, Any], result: Dict[str, Any]) -> None:
        """统一回写入口；旧方法仍可用。"""
        if not isinstance(action, dict) or not isinstance(result, dict):
            raise GepaError("action and result must be objects")
        kind = action.get("kind")
        if kind == "evaluate":
            if "score" not in result:
                raise GepaError("evaluate result requires score")
            self.record_evaluation(
                str(action.get("candidate_id") or ""), str(action.get("sample_id") or ""),
                result["score"], str(result.get("feedback") or ""),
            )
        elif kind == "reflect":
            text = result.get("text")
            if text is None:
                text = result.get("skill")
            if text is None and isinstance(result.get("snapshot"), dict):
                text = result["snapshot"].get("text")
            if not isinstance(text, str) or not text.strip():
                raise GepaError("reflect result requires candidate text")
            self.record_candidate(text)
        elif kind == "stop":
            return
        else:
            raise GepaError(f"unsupported action kind {kind!r}")

    # -- selection / result ---------------------------------------------
    def pareto_ids(self) -> List[str]:
        complete = [c for c in self.candidates if len(c.scores) == len(self.samples)]
        front: List[str] = []
        for candidate in complete:
            dominated = False
            for other in complete:
                if other.id == candidate.id:
                    continue
                if all(other.scores[s] >= candidate.scores[s] for s in self.samples) and any(
                    other.scores[s] > candidate.scores[s] for s in self.samples
                ):
                    dominated = True
                    break
            if not dominated:
                front.append(candidate.id)
        return front

    def _select_parent(self) -> Optional[Snapshot]:
        return self.selector.choose(self.candidates, self.samples, self.reflected)

    def best(self) -> Optional[Snapshot]:
        complete = [c for c in self.candidates if len(c.scores) == len(self.samples)]
        if not complete:
            return None
        return sorted(
            complete,
            key=lambda c: (-(sum(c.scores.values()) / len(self.samples)), len(c.skill), c.id),
        )[0]

    def best_snapshot(self) -> Optional[Snapshot]:
        return self.best()

    def result(self) -> Dict[str, Any]:
        best = self.best()
        return {
            "loop": self.id,
            "target_skill": self.target_skill,
            "mutable_region": self.mutable_region,
            "select_stage": self.select_stage.id,
            "propose_stage": self.propose_stage.id,
            "stages": {"select_candidate": self.select_stage.id,
                       "propose": self.propose_stage.id},
            "best_id": best.id if best else None,
            "best_skill": best.skill if best else None,
            "best_score": (sum(best.scores.values()) / len(self.samples)) if best else None,
            "calls": self.calls,
            "max_metric_calls": self.max_metric_calls,
            "budget": self.budget.to_dict(),
            "population": len(self.candidates),
            "pareto": self.pareto_ids(),
            "candidates": [c.to_dict() for c in self.candidates],
        }

    # -- persistence -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "state_schema": GEPA_STATE_SCHEMA,
            "loop": self.id,
            "samples": list(self.samples),
            "max_metric_calls": self.max_metric_calls,
            "population": self.population,
            "seed": self.seed,
            "min_score": self.min_score,
            "target_skill": self.target_skill,
            "mutable_region": self.mutable_region,
            "select_stage": self.select_stage.id,
            "propose_stage": self.propose_stage.id,
            "candidates": [
                {"id": c.id, "skill": c.skill, "parent": c.parent,
                 "scores": dict(c.scores), "feedback": dict(c.feedback)}
                for c in self.candidates
            ],
            "reflected": list(self.reflected),
            "pending_reflect": self.pending_reflect,
            "calls": self.calls,
            "budget": self.budget.to_dict(),
            "decision_log": str(self.decision_log.path) if self.decision_log else None,
            "run_id": self.run_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentRsiSession":
        if data.get("state_schema") not in (None, GEPA_STATE_SCHEMA):
            raise GepaError("agent GEPA state schema mismatch")
        missing = [key for key in ("samples", "max_metric_calls", "population")
                   if key not in data]
        if missing:
            raise GepaError("state missing: " + ", ".join(missing))
        if not isinstance(data["samples"], list):
            raise GepaError("state samples must be a list")
        raw_candidates = data.get("candidates")
        if not isinstance(raw_candidates, list):
            raise GepaError("state candidates must be a list")
        try:
            candidates = [Snapshot.from_dict(c) for c in raw_candidates]
        except LoopError as exc:
            raise GepaError(f"invalid candidate snapshot: {exc}") from exc
        if not candidates:
            raise GepaError("state has no candidates")
        if candidates[0].files:
            raise GepaError("GEPA candidates must be single-text snapshots")
        session = cls(
            seed_skill=candidates[0].text, samples=list(data["samples"]),
            max_metric_calls=int(data["max_metric_calls"]),
            population=int(data["population"]), seed=int(data.get("seed", 0)),
            min_score=float(data.get("min_score", 0.0)),
            target_skill=str(data.get("target_skill") or ""),
            mutable_region=str(data.get("mutable_region") or ""),
            select_stage=str(data.get("select_stage") or "select.best"),
            propose_stage=str(data.get("propose_stage") or "propose.agent"),
        )
        session.candidates = candidates
        session.reflected = list(data.get("reflected") or [])
        session.pending_reflect = data.get("pending_reflect")
        session.calls = int(data.get("calls", 0))
        if isinstance(data.get("budget"), dict):
            session.budget = Budget.from_dict(data["budget"])
            if session.budget.target_runs is None:
                session.budget.target_runs = session.max_metric_calls
        if data.get("decision_log"):
            session.decision_log = DecisionLog(str(data["decision_log"]))
        session.run_id = str(data.get("run_id") or "")
        return session

    def _candidate(self, candidate_id: str) -> Snapshot:
        for candidate in self.candidates:
            if candidate.id == candidate_id:
                return candidate
        raise GepaError(f"unknown candidate {candidate_id!r}")


class GepaSession(AgentRsiSession):
    """GEPA = ParetoSelector + ReflectiveProposer 的默认组合。"""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("select_stage", "select.pareto")
        kwargs.setdefault("propose_stage", "propose.agent")
        super().__init__(*args, **kwargs)
