"""Agent-native GEPA 状态机。

GEPA 的核心不是某个 Python 模型的调用，而是：候选池、reflective mutation、
Pareto 选择、按 metric calls 停。本模块只做状态机，不调用模型、不派 agent；
harness 拿到 ``next_action`` 后用 task/judge/reflection subagent 执行，再把结果
写回。这样任何有 subagent/team 编排能力的 agent 都能跑同一套算法。

sleuth 适配：候选是 skill 的可变异文本，不是整份 SKILL.md；task 只看样本输入，
judge 看 rubric/expected；reflect 只看失败反馈。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class GepaError(ValueError):
    """状态机输入或动作顺序不合法。"""


@dataclass
class Candidate:
    id: str
    skill: str
    parent: Optional[str] = None
    scores: Dict[str, float] = field(default_factory=dict)
    feedback: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "skill": self.skill, "parent": self.parent,
            "scores": dict(self.scores), "feedback": dict(self.feedback),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Candidate":
        return cls(
            id=str(data["id"]), skill=str(data["skill"]), parent=data.get("parent"),
            scores={str(k): float(v) for k, v in (data.get("scores") or {}).items()},
            feedback={str(k): str(v) for k, v in (data.get("feedback") or {}).items()},
        )


class GepaSession:
    """可序列化的 GEPA 搜索状态。"""

    def __init__(self, seed_skill: str, samples: List[str],
                 max_metric_calls: int = 12, population: int = 4,
                 seed: int = 0, min_score: float = 0.0):
        if not isinstance(seed_skill, str) or not seed_skill.strip():
            raise GepaError("seed_skill is required")
        if not samples or not all(isinstance(s, str) and s.strip() for s in samples):
            raise GepaError("samples must be non-empty strings")
        if len(set(samples)) != len(samples):
            raise GepaError("samples must not contain duplicates")
        if not isinstance(max_metric_calls, int) or max_metric_calls <= 0:
            raise GepaError("max_metric_calls must be a positive integer")
        if not isinstance(population, int) or population <= 0:
            raise GepaError("population must be a positive integer")
        self.samples = list(samples)
        self.max_metric_calls = max_metric_calls
        self.population = population
        self.seed = seed
        self.min_score = min_score
        self.candidates: List[Candidate] = [Candidate(id="seed", skill=seed_skill)]
        self.reflected: List[str] = []
        self.pending_reflect: Optional[str] = None
        self.calls = 0

    # -- actions ---------------------------------------------------------
    def next_action(self) -> Dict[str, Any]:
        incomplete = [c for c in self.candidates if len(c.scores) < len(self.samples)]
        if incomplete:
            candidate = incomplete[0]
            missing = [s for s in self.samples if s not in candidate.scores]
            return {
                "kind": "evaluate", "candidate_id": candidate.id,
                "skill": candidate.skill, "sample_id": missing[0],
            }
        if self.calls >= self.max_metric_calls:
            return {"kind": "stop", "reason": "budget"}
        best = self.best()
        if best is not None and all(score >= 1.0 for score in best.scores.values()):
            return {"kind": "stop", "reason": "perfect_score"}
        if len(self.candidates) >= self.population:
            return {"kind": "stop", "reason": "population"}
        parent = self._select_parent()
        if parent is None:
            return {"kind": "stop", "reason": "no_unreflected_pareto"}
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
        if self.calls >= self.max_metric_calls:
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
        self.calls += 1

    def record_candidate(self, skill: str) -> Candidate:
        if self.pending_reflect is None:
            raise GepaError("no reflect action pending")
        if not isinstance(skill, str) or not skill.strip():
            raise GepaError("candidate skill is required")
        parent = self.pending_reflect
        self.reflected.append(parent)
        self.pending_reflect = None
        candidate = Candidate(id=f"c{len(self.candidates)}", skill=skill, parent=parent)
        self.candidates.append(candidate)
        return candidate

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

    def _select_parent(self) -> Optional[Candidate]:
        front = set(self.pareto_ids())
        eligible = [c for c in self.candidates if c.id in front and c.id not in self.reflected]
        if not eligible:
            return None
        return sorted(
            eligible,
            key=lambda c: (-(sum(c.scores.values()) / len(self.samples)), len(c.skill), c.id),
        )[0]

    def best(self) -> Optional[Candidate]:
        complete = [c for c in self.candidates if len(c.scores) == len(self.samples)]
        if not complete:
            return None
        return sorted(
            complete,
            key=lambda c: (-(sum(c.scores.values()) / len(self.samples)), len(c.skill), c.id),
        )[0]

    def result(self) -> Dict[str, Any]:
        best = self.best()
        return {
            "best_id": best.id if best else None,
            "best_skill": best.skill if best else None,
            "best_score": (sum(best.scores.values()) / len(self.samples)) if best else None,
            "calls": self.calls,
            "max_metric_calls": self.max_metric_calls,
            "population": len(self.candidates),
            "pareto": self.pareto_ids(),
            "candidates": [c.to_dict() for c in self.candidates],
        }

    # -- persistence -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "samples": list(self.samples),
            "max_metric_calls": self.max_metric_calls,
            "population": self.population,
            "seed": self.seed,
            "min_score": self.min_score,
            "candidates": [c.to_dict() for c in self.candidates],
            "reflected": list(self.reflected),
            "pending_reflect": self.pending_reflect,
            "calls": self.calls,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GepaSession":
        candidates = [Candidate.from_dict(c) for c in data.get("candidates") or []]
        if not candidates:
            raise GepaError("state has no candidates")
        session = cls(
            seed_skill=candidates[0].skill, samples=list(data["samples"]),
            max_metric_calls=int(data["max_metric_calls"]),
            population=int(data["population"]), seed=int(data.get("seed", 0)),
            min_score=float(data.get("min_score", 0.0)),
        )
        session.candidates = candidates
        session.reflected = list(data.get("reflected") or [])
        session.pending_reflect = data.get("pending_reflect")
        session.calls = int(data.get("calls", 0))
        return session

    def _candidate(self, candidate_id: str) -> Candidate:
        for candidate in self.candidates:
            if candidate.id == candidate_id:
                return candidate
        raise GepaError(f"unknown candidate {candidate_id!r}")
