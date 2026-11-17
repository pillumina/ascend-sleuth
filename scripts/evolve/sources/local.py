"""本地 issue 导出源：JSON/YAML 列表或 ``{issues: [...]}``，含 body。"""

import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

from ..adapters import AdapterError


class LocalSource:
    """从本地导出读 issue；导出是离线夹具或团队收集器的产物。"""

    def __init__(self, cache: Any, repo: str = None, source_id: str = None) -> None:
        self.cache = Path(cache)
        self.repo = str(repo) if repo else ""
        self._source_id = source_id or f"local/{self.repo or self.cache.stem}"

    @property
    def source_id(self) -> str:
        return self._source_id

    def _load(self) -> List[Dict[str, Any]]:
        try:
            text = self.cache.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise AdapterError(f"cannot read local issue cache {self.cache}: {exc}") from exc
        try:
            if self.cache.suffix.lower() == ".json":
                document = json.loads(text)
            else:
                document = yaml.safe_load(text)
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            raise AdapterError(f"invalid local issue cache {self.cache}: {exc}") from exc
        if isinstance(document, dict):
            document = document.get("issues")
        if not isinstance(document, list):
            raise AdapterError(
                f"local issue cache must be a list or {{issues: [...]}}: {self.cache}"
            )
        return [item for item in document if isinstance(item, dict)]

    def list_issues(self, repo: str, labels=None, since=None,
                    state: str = "closed") -> List[Dict[str, Any]]:
        # 本地导出已经是一份离线数据；label/评论数/标题硬过滤仍由上层管线统一做，
        # 这里只做来源（repo）与显式 state/since 的粗过滤，避免把别仓数据混进来。
        target_repo = str(repo or self.repo or "")
        items = []
        for item in self._load():
            item_repo = item.get("repo")
            if item_repo and target_repo and str(item_repo) != target_repo:
                continue
            if state and item.get("state") and str(item["state"]) != state:
                continue
            stamp = str(item.get("closed_at") or item.get("updated_at") or "")
            if since and stamp and stamp < str(since):
                continue
            items.append(item)
        return items

    def fetch_issue(self, repo: str, number: Any) -> Dict[str, Any]:
        if number is None or str(number).strip() == "":
            raise AdapterError("cannot fetch issue body without a number")
        for item in self._load():
            item_repo = item.get("repo")
            if item_repo and self.repo and str(item_repo) != self.repo:
                continue
            if str(item.get("number")) != str(number):
                continue
            return {
                "title": item.get("title") or "",
                "body": item.get("body") or "",
                "closed_at": item.get("closed_at"),
            }
        raise AdapterError(f"issue #{number} not found in local cache {self.cache}")
