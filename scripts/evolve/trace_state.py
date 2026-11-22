"""诊断 trace 归因的幂等状态与快照版本。

状态键是 ``(source_id, trace_id, content_sha256, attribution_schema)``：
同一内容、同一 schema 不重复归因；trace 内容变了、或 schema/归因规则升级，
才重算。快照 id 由当前活跃 trace 列表与 schema 再做一次哈希，用于判断
"这份 evolve 状态是否还对应当前 trace 集"。
"""

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .trace_source import TraceDoc

ATTRIBUTION_SCHEMA = "trace-attribution-v1"
STATE_SCHEMA = "evolve-trace-state-v1"


class TraceStateError(RuntimeError):
    """状态文件不可读/不合法。"""


def snapshot_id(source_id: str, refs: List[Any], schema: str = ATTRIBUTION_SCHEMA) -> str:
    rows = [f"{ref.id}:{ref.sha256}" for ref in sorted(refs, key=lambda item: item.id)]
    payload = "\n".join([source_id, schema, *rows])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def attribute_trace(doc: TraceDoc) -> Dict[str, Any]:
    """从一条 trace 抽 attribution 事件；不判定修复，只给归因证据。"""
    events = []
    for event in doc.events:
        if not isinstance(event, dict) or event.get("action") != "attribution":
            continue
        kind = event.get("attribution_kind") or event.get("verdict")
        hard = kind == "execution" or event.get("verdict") == "execution_error"
        component = event.get("component")
        if not isinstance(component, str) or not component.strip():
            component = "(未归因)"
        events.append({
            "component": component,
            "kind": kind,
            "hard": bool(hard),
            "evidence": str(event.get("evidence") or "")[:200],
        })
    return {"trace_id": doc.id, "sha256": doc.sha256, "events": events}


class TraceState:
    def __init__(self, path: Path, source_id: str):
        self.path = Path(path)
        self.source_id = source_id
        self.data: Dict[str, Any] = {
            "state_schema": STATE_SCHEMA,
            "attribution_schema": ATTRIBUTION_SCHEMA,
            "source_id": source_id,
            "processed": {},
            "snapshot_id": None,
        }

    @classmethod
    def load(cls, path: Path, source_id: str) -> "TraceState":
        state = cls(path, source_id)
        if not path.exists():
            return state
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TraceStateError(f"cannot read trace state: {exc}") from exc
        if not isinstance(data, dict) or data.get("state_schema") != STATE_SCHEMA:
            raise TraceStateError("trace state schema mismatch")
        if data.get("attribution_schema") != ATTRIBUTION_SCHEMA:
            # schema 升级时旧归因不可复用，但保留文件可见；本次从头算。
            state.data = {
                "state_schema": STATE_SCHEMA,
                "attribution_schema": ATTRIBUTION_SCHEMA,
                "source_id": source_id,
                "processed": {},
                "snapshot_id": None,
            }
            return state
        if data.get("source_id") != source_id:
            raise TraceStateError("trace state source_id mismatch")
        processed = data.get("processed")
        if not isinstance(processed, dict):
            raise TraceStateError("trace state processed must be an object")
        state.data = data
        return state

    def cached(self, trace_id: str, sha256: str) -> Optional[Dict[str, Any]]:
        item = self.data["processed"].get(trace_id)
        if not isinstance(item, dict):
            return None
        if item.get("sha256") != sha256:
            return None
        return item.get("attribution")

    def put(self, attribution: Dict[str, Any]) -> None:
        self.data["processed"][attribution["trace_id"]] = {
            "sha256": attribution["sha256"],
            "attribution": attribution,
        }

    def prune(self, active_ids: List[str]) -> None:
        active = set(active_ids)
        for trace_id in list(self.data["processed"]):
            if trace_id not in active:
                del self.data["processed"][trace_id]

    def set_snapshot(self, refs: List[Any]) -> str:
        value = snapshot_id(self.source_id, refs)
        self.data["snapshot_id"] = value
        return value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self.path.name, dir=str(self.path.parent))
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            Path(tmp).replace(self.path)
        finally:
            try:
                Path(tmp).unlink()
            except OSError:
                pass
