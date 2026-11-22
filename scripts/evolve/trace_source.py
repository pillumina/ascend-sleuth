"""诊断 trace 源：本地 ``traces/`` 与未来 collector 的共同形状。

归因层只消费 ``TraceDoc.events``；存储、脱敏、保留期、采集在源实现里。
当前只有本地源；外部 collector 实现同一个 Protocol，不改归因与状态机。
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Protocol

import yaml


class TraceSourceError(RuntimeError):
    """trace 源不可读或格式不合法。"""


@dataclass(frozen=True)
class TraceRef:
    id: str
    path: Path
    sha256: str


@dataclass(frozen=True)
class TraceDoc:
    id: str
    path: Path
    sha256: str
    events: List[Dict[str, Any]]


class TraceSource(Protocol):
    source_id: str

    def list_traces(self) -> List[TraceRef]: ...
    def fetch_trace(self, ref: TraceRef) -> TraceDoc: ...


class LocalTraceSource:
    """读当前检出的 ``traces/*.yaml``；不读 git，不删除原文件。"""

    def __init__(self, root: Path, source_id: str = "local", prefer_main: bool = False):
        self.root = Path(root)
        self.source_id = source_id
        self.prefer_main = prefer_main

    def list_traces(self) -> List[TraceRef]:
        directory = self.root / "traces"
        if self.prefer_main:
            try:
                from exec_log_path import resolve_traces
                directory = resolve_traces(self.root)
            except (ImportError, OSError):
                pass
        if not directory.exists():
            return []
        refs = []
        for path in sorted(directory.glob("*.yaml")):
            try:
                raw = path.read_bytes()
            except OSError as exc:
                raise TraceSourceError(f"cannot read {path}: {exc}") from exc
            refs.append(TraceRef(
                id=path.stem, path=path, sha256=hashlib.sha256(raw).hexdigest(),
            ))
        return refs

    def fetch_trace(self, ref: TraceRef) -> TraceDoc:
        try:
            raw = ref.path.read_bytes()
            document = yaml.safe_load(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise TraceSourceError(f"cannot parse {ref.path}: {exc}") from exc
        if not isinstance(document, dict):
            raise TraceSourceError(f"{ref.path} must be an object")
        events = document.get("trace")
        if not isinstance(events, list):
            raise TraceSourceError(f"{ref.path} has no trace list")
        return TraceDoc(id=ref.id, path=ref.path, sha256=ref.sha256, events=events)
