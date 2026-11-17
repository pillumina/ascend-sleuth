"""``evolution_health.py`` / ``metrics_health.py`` 的薄包装。

两条体检器的判据、口径与退出码都在旧脚本；这里只把 ``root`` 显式化，并把可复用的
读数函数暴露出来。完整 CLI 报告仍走旧脚本（它们有各自的三态退出码）。
"""

from pathlib import Path
from typing import Any, Dict

from . import load_legacy


def evolution(root: Any) -> Dict[str, Any]:
    """演进闭环体检的数据契约（旧脚本 ``evaluate`` 的返回值）。"""
    return load_legacy("evolution_health").evaluate(Path(root).resolve())


def render_evolution(payload: Dict[str, Any]) -> str:
    """把演进体检读数渲染成人读报告（旧脚本 ``render``）。"""
    return load_legacy("evolution_health").render(payload)


def metrics_structure(root: Any):
    """指标体检里的结构侧读数（旧脚本 ``collect_structural_safe``）。

    返回旧脚本的原样元组 ``(structural, notes)``；容量判据与越界规则不在包装层。
    """
    return load_legacy("metrics_health").collect_structural_safe(Path(root).resolve())
