# -*- coding: utf-8 -*-
"""本地 JSONL 默认后端。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..records import JsonlStore


class LocalJsonlBackend:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._store = JsonlStore(self.path)

    def append(self, event: Dict[str, Any]) -> None:
        self._store.append(event)

    def read(self) -> List[Dict[str, Any]]:
        return self._store.read()
