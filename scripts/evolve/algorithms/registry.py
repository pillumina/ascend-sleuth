"""算法注册表：名称 → 工厂；未知算法报错。"""

from typing import Any, Dict

from .baseline import BaselineOptimizer

ALGORITHMS = {
    "baseline": BaselineOptimizer,
}


def get_algorithm(name: str):
    if name not in ALGORITHMS:
        raise ValueError(
            f"unknown algorithm {name!r}; expected one of {sorted(ALGORITHMS)}"
        )
    return ALGORITHMS[name]()


def algorithm_ids():
    return sorted(ALGORITHMS)
