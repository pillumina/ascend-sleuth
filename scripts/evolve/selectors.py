"""选择策略：从已完成候选里选父候选。"""

from typing import Any, List, Optional


class NoneSelector:
    id = "select.none"

    def choose(self, candidates, samples, reflected):
        return None


class BestSelector:
    id = "select.best"

    def choose(self, candidates, samples, reflected):
        complete = [c for c in candidates if len(c.scores) == len(samples)]
        eligible = [c for c in complete if c.id not in reflected]
        if not eligible:
            return None
        return sorted(
            eligible,
            key=lambda c: (-(sum(c.scores.values()) / len(samples)), len(c.skill), c.id),
        )[0]


class ParetoSelector:
    id = "select.pareto"

    def choose(self, candidates: List[Any], samples: List[str],
               reflected: List[str]) -> Optional[Any]:
        complete = [c for c in candidates if len(c.scores) == len(samples)]
        front: List[Any] = []
        for candidate in complete:
            dominated = False
            for other in complete:
                if other.id == candidate.id:
                    continue
                if all(other.scores[s] >= candidate.scores[s] for s in samples) and any(
                    other.scores[s] > candidate.scores[s] for s in samples
                ):
                    dominated = True
                    break
            if not dominated:
                front.append(candidate)
        eligible = [c for c in front if c.id not in reflected]
        if not eligible:
            return None
        return sorted(
            eligible,
            key=lambda c: (-(sum(c.scores.values()) / len(samples)), len(c.skill), c.id),
        )[0]
