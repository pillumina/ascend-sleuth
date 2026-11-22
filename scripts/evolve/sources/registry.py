"""数据源注册表：小字典，不引入插件框架。"""

from typing import Any

from ..adapters import AdapterError
from .github import GitHubSource
from .local import LocalSource

SOURCES = {
    "github": lambda repo, cache: GitHubSource(repo),
    "local": lambda repo, cache: LocalSource(cache, repo=repo),
}


def get_source(name: str, repo: str = None, cache: Any = None):
    """按 CLI 名构造源；未知源直接报错，不静默退回 GitHub。"""
    if name not in SOURCES:
        raise AdapterError(
            f"unknown issue source {name!r}; expected one of {sorted(SOURCES)}"
        )
    if name == "github" and not repo:
        raise AdapterError("source 'github' requires a repo")
    if name == "local" and cache is None:
        raise AdapterError("source 'local' requires a cache path")
    return SOURCES[name](repo, cache)
