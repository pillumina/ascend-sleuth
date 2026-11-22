# -*- coding: utf-8 -*-
"""存储后端端口；实现只负责持久化事件，不解释领域语义。"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol


class Backend(Protocol):
    def append(self, event: Dict[str, Any]) -> None: ...
    def read(self) -> List[Dict[str, Any]]: ...
