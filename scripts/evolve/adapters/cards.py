"""``ev_proposal.py`` 的薄包装：卡号、候选水位与同组件先例。

产卡骨架、状态推进提示与聚合口径都在旧脚本；这里只提供显式 ``root`` 的入口，
不复制规则、不改状态语义。
"""

from pathlib import Path
from typing import Any

from . import load_legacy


def next_id(root: Any) -> str:
    """下一个候选卡号（``EV-YYYY-NNN``）。"""
    return load_legacy("ev_proposal").next_id(Path(root))


def make_new(root: Any, force: bool = False) -> Path:
    """生成一张候选卡骨架；部署声明不允许时旧脚本抛 ``DeploymentGate``。"""
    return load_legacy("ev_proposal").make_new(Path(root), force=force)


def waterline(root: Any, limit: int = 20, as_json: bool = False) -> int:
    """候选水位读数；返回旧脚本的退出码（超限为 1）。"""
    return load_legacy("ev_proposal").waterline(Path(root), limit, as_json=as_json)


def impact(root: Any, component: str = "", min_attempts: int = 2) -> int:
    """同组件先例视图；返回旧脚本的退出码。"""
    return load_legacy("ev_proposal").impact(
        Path(root), component=component, min_attempts=min_attempts
    )
