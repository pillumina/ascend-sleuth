"""数据源注册表：小字典，不引入插件框架。"""

from typing import Any

from ..adapters import AdapterError
from .github import GitHubSource
from .local import LocalSource

SOURCES = {
    "github": GitHubSource,
    "local": LocalSource,
}


def get_source(name: str, repo: str = None, cache: Any = None):
    """按 CLI 名构造源；未知源直接报错，不静默退回 GitHub。"""
    if name == "github":
        if not repo:
            raise AdapterError("source 'github' requires a repo")
        return GitHubSource(repo)
    if name == "local":
        if cache is None:
            raise AdapterError("source 'local' requires a cache path")
        return LocalSource(cache, repo=repo)
    raise AdapterError(
        f"unknown issue source {name!r}; expected one of {sorted(SOURCES)}"
    )
