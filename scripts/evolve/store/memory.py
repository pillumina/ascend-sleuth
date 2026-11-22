# -*- coding: utf-8 -*-
"""测试/嵌入用内存后端。"""

from __future__ import annotations

from typing import Any, Dict, List


class MemoryBackend:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def append(self, event: Dict[str, Any]) -> None:
        self.rows.append(event)

    def read(self) -> List[Dict[str, Any]]:
        return list(self.rows)
