# -*- coding: utf-8 -*-
"""循环决策记录：只追加的 JSONL，一行一条、自包含。

它不是 ``Conclusion``：结论是配对检验后的合入判断；决策记录是循环内的
接受/拒绝/停止读数（例如 dev 严格提升是否采纳）。两者分开，避免把点估计
冒充统计结论。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..records import JsonlStore
from .contract import LoopError, decision_record


class DecisionLog:
    def __init__(self, path: Any):
        self.path = Path(path)
        self._store = JsonlStore(self.path)

    def append(self, record: Dict[str, Any]) -> None:
        if not isinstance(record, dict):
            raise LoopError("decision record must be an object")
        missing = [key for key in ("loop", "kind") if not record.get(key)]
        if missing:
            raise LoopError("decision record missing: " + ", ".join(missing))
        self._store.append(record)

    def record(self, loop_id: str, kind: str, **kwargs: Any) -> Dict[str, Any]:
        record = decision_record(loop_id, kind, **kwargs)
        self.append(record)
        return record

    def read(self) -> List[Dict[str, Any]]:
        return self._store.read()

    def last(self, limit: int = 1) -> List[Dict[str, Any]]:
        return self._store.last(limit)


def optional_log(path: Optional[Any]) -> Optional[DecisionLog]:
    return DecisionLog(path) if path else None
