"""只追加的 JSONL 记录：结论与执行。

没有数据库。每条记录一行 JSON；写入取追加锁（POSIX 下 ``fcntl``，不可用时
退化为单次 ``os.write`` 的 O_APPEND），不做更新与删除——结论历史可复核。
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List

try:  # Windows 没有 fcntl；单次 O_APPEND 写仍能避免行内交错。
    import fcntl
except ImportError:  # pragma: no cover - 平台分支
    fcntl = None  # type: ignore

EVOLVE_DIR = Path(".s2-replay") / "evolve"


class RecordError(RuntimeError):
    """记录文件不可读或内容不是合法 JSON。"""


class JsonlStore:
    """一个 JSONL 文件 = 一类只追加记录。"""

    def __init__(self, path: Path, lock: bool = True) -> None:
        self.path = Path(path)
        self.lock = lock

    def append(self, record: Dict[str, Any]) -> None:
        if not isinstance(record, dict):
            raise TypeError("record must be an object")
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        payload = (line + "\n").encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        fd = os.open(str(self.path), flags, 0o644)
        try:
            if self.lock and fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            if self.lock and fcntl is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(fd)

    def read(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        records: List[Dict[str, Any]] = []
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                for lineno, line in enumerate(handle, start=1):
                    text = line.strip()
                    if not text:
                        continue
                    try:
                        record = json.loads(text)
                    except json.JSONDecodeError as exc:
                        raise RecordError(
                            f"invalid JSON in {self.path} line {lineno}: {exc}"
                        ) from exc
                    if not isinstance(record, dict):
                        raise RecordError(
                            f"record in {self.path} line {lineno} is not an object"
                        )
                    records.append(record)
        except (OSError, UnicodeDecodeError) as exc:
            raise RecordError(f"cannot read {self.path}: {exc}") from exc
        return records

    def last(self, limit: int = 1) -> List[Dict[str, Any]]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        records = self.read()
        return records[-limit:] if limit else []


class ConclusionStore(JsonlStore):
    """结论记录：``<root>/.s2-replay/evolve/conclusions.jsonl``。"""

    def __init__(self, path: Path = None, lock: bool = True, base: Path = None) -> None:
        if base is not None:
            path = Path(base) / "conclusions.jsonl"
        if path is None:
            raise TypeError("ConclusionStore requires path or base")
        super().__init__(path, lock=lock)

    @classmethod
    def for_root(cls, root: Path, lock: bool = True) -> "ConclusionStore":
        return cls(Path(root) / EVOLVE_DIR / "conclusions.jsonl", lock=lock)

    @classmethod
    def for_base(cls, base: Path, lock: bool = True) -> "ConclusionStore":
        """``base`` 是 ``.s2-replay/evolve`` 本身（CLI 主检出锚点）。"""
        return cls(base=base, lock=lock)


class ExperimentStore(JsonlStore):
    """算法提案记录：``<root>/.s2-replay/evolve/experiments.jsonl``。"""

    def __init__(self, path: Path = None, lock: bool = True, base: Path = None) -> None:
        if base is not None:
            path = Path(base) / "experiments.jsonl"
        if path is None:
            raise TypeError("ExperimentStore requires path or base")
        super().__init__(path, lock=lock)

    @classmethod
    def for_base(cls, base: Path, lock: bool = True) -> "ExperimentStore":
        return cls(base=base, lock=lock)


class RunStore(JsonlStore):
    """执行记录：``<root>/.s2-replay/evolve/runs.jsonl``。"""

    def __init__(self, path: Path = None, lock: bool = True, base: Path = None) -> None:
        if base is not None:
            path = Path(base) / "runs.jsonl"
        if path is None:
            raise TypeError("RunStore requires path or base")
        super().__init__(path, lock=lock)

    @classmethod
    def for_root(cls, root: Path, lock: bool = True) -> "RunStore":
        return cls(Path(root) / EVOLVE_DIR / "runs.jsonl", lock=lock)

    @classmethod
    def for_base(cls, base: Path, lock: bool = True) -> "RunStore":
        return cls(base=base, lock=lock)


def append(path: Path, record: Dict[str, Any], lock: bool = True) -> None:
    JsonlStore(path, lock=lock).append(record)


def read(path: Path) -> List[Dict[str, Any]]:
    return JsonlStore(path).read()


def last_conclusions(root: Path, limit: int = 5) -> List[Dict[str, Any]]:
    return ConclusionStore.for_root(root).last(limit)


def conclusion_path(root: Path) -> Path:
    return Path(root) / EVOLVE_DIR / "conclusions.jsonl"


def run_path(root: Path) -> Path:
    return Path(root) / EVOLVE_DIR / "runs.jsonl"
