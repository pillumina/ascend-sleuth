"""issue 数据源抽象。

管线（过滤、建候选、state）只依赖 ``IssueSource``；GitHub 是默认实现，本地
JSON/YAML 导出是第二个实现。新增源（如 GitCode）只加一个 adapter，不复制管线。
"""

from .base import IssueSource
from .github import GitHubSource
from .local import LocalSource
from .registry import SOURCES, get_source

__all__ = [
    "IssueSource",
    "GitHubSource",
    "LocalSource",
    "SOURCES",
    "get_source",
]
