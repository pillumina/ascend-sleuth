"""holdout 隔离：开源 issue 不能同时进候选池和封存对照集。

holdout 的判据是 fixture 的 issue 号；这里只做“来源是否在封存集”的硬检查，
不改 holdout 清单，也不重算哈希（哈希门仍由 ``scripts/holdout.py`` 负责）。
"""

import re
from pathlib import Path
from typing import Set

import yaml

HOLDOUT_REL = Path("eval") / "holdout.yaml"
_ISSUE = re.compile(
    r"(?:VLLM-ASC|SGL[-A-Z0-9]*)-(\d+)|#(\d+)|issues/(\d+)", re.IGNORECASE,
)


class HoldoutError(ValueError):
    """holdout 清单不可读。"""


def issue_numbers(root: Path) -> Set[str]:
    path = Path(root) / HOLDOUT_REL
    if not path.exists():
        # 有 eval/ 但没有 holdout 清单 = 部署配置坏了，不能静默放行；
        # 完全没有 eval/ 的临时目录按“未配置 holdout”处理。
        if (Path(root) / ".git").exists() and (Path(root) / "eval").exists():
            raise HoldoutError(f"missing {path}")
        return set()
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise HoldoutError(f"cannot read {path}: {exc}") from exc
    numbers = set()
    for entry in doc.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        fixture = str(entry.get("fixture") or "")
        for match in _ISSUE.finditer(fixture):
            numbers.add(next(group for group in match.groups() if group))
    return numbers


def is_holdout_source(source: str, numbers: Set[str]) -> bool:
    for match in _ISSUE.finditer(str(source)):
        if next(group for group in match.groups() if group) in numbers:
            return True
    return False
