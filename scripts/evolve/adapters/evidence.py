"""``verify_evidence.py`` 的薄包装：引文回验。

逐字比对规则、路径解析与 verdict 仍由旧脚本实现；这里只把 trace 路径、原件根和
截断长度显式化，并把逐条记录收成一个可读字典。
"""

from pathlib import Path
from typing import Any, Dict, List

from . import AdapterError, load_legacy


def compare(actual: Any, quote: Any):
    """原文与引文的判定（``PASS`` / ``MISMATCH`` 等），直接转发旧脚本。"""
    return load_legacy("verify_evidence").compare(actual, quote)


def read_line(path: Any, number: Any):
    """读第 ``number`` 行；返回 ``(文本, 错误码, 说明)``，直接转发旧脚本。"""
    return load_legacy("verify_evidence").read_line(Path(path), number)


def verify_trace(trace_path: Any, root: Any, max_chars: int = 160) -> Dict[str, Any]:
    """核一份 trace 的引文，返回计数与逐条判定。

    与旧 CLI 同一组成熟函数（``collect_items`` / ``verify_item``），不在这里
    重新实现比对规则。trace 里没有引文时返回空 items，而不是报错。
    """
    module = load_legacy("verify_evidence")
    path = Path(trace_path)
    items, error = module.collect_items(path)
    if error:
        raise AdapterError(str(error))
    records: List[Dict[str, Any]] = [
        module.verify_item(item, Path(root), max_chars) for item in items
    ]
    failed_verdicts = set(getattr(module, "VERDICTS_FAIL", set()))
    counts: Dict[str, int] = {}
    for record in records:
        verdict = str(record.get("verdict") or "unknown")
        counts[verdict] = counts.get(verdict, 0) + 1
    return {
        "trace": str(path),
        "counts": counts,
        "items": records,
        "failed": [r for r in records if r.get("verdict") in failed_verdicts],
    }
