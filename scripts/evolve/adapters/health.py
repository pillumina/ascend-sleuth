"""``evolution_health.py`` / ``metrics_health.py`` 的薄包装。

两条体检器的判据、口径与退出码都在旧脚本；这里只把 ``root`` 显式化，并把可复用的
读数函数暴露出来。完整 CLI 报告仍走旧脚本（它们有各自的三态退出码）。
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from . import AdapterError, load_legacy


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


def metrics(root: Any) -> Dict[str, Any]:
    """``metrics_health.py --json`` 的只读摘要；判据仍由旧脚本负责。"""
    script = Path(__file__).resolve().parents[2] / "metrics_health.py"
    if not script.exists():
        return {"available": False, "error": f"missing {script.name}"}
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--json", "--root", str(Path(root).resolve())],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": str(exc)}
    if not proc.stdout.strip():
        return {"available": False, "error": proc.stderr.strip() or "empty health output"}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"available": False, "error": f"invalid health JSON: {exc}"}
    if not isinstance(payload, dict):
        return {"available": False, "error": "health output must be an object"}
    payload["available"] = True
    return payload
