"""``s2_replay.py`` 的准备与收集包装。

旧脚本自己决定工作目录与报告位置；这里把两条路径显式化，调用方（CLI/测试）传入
检出根与报告路径。不复制评分规则，也不改变旧脚本输出。
"""

from pathlib import Path
from typing import Any

from . import AdapterError, load_legacy


def _root(path: Any) -> Path:
    root = Path(path)
    if not root.exists():
        raise AdapterError(f"replay root does not exist: {root}")
    if not root.is_dir():
        raise AdapterError(f"replay root is not a directory: {root}")
    return root


def prepare(root: Any) -> None:
    """产 replay 输入清单（``<root>/.s2-replay/<issue>.md``）。"""
    module = load_legacy("s2_replay")
    module.prepare(_root(root))


def collect(root: Any, report_path: Any) -> None:
    """读 replay 结果并写评分报告；报告父目录不存在时先建出来。"""
    module = load_legacy("s2_replay")
    report = Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    module.collect(_root(root), report)
