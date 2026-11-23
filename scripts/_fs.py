#!/usr/bin/env python3
"""文件原语：原子写、YAML 读写、固定 LF。

为什么单独一个模块：同目录临时文件 + fsync + os.replace 在 groom_common、issue_filter、
kb_sync、gc_docs、evolve/samples 各写了一遍，保证并不同（有的 fsync、有的不）。这里把
"写一半崩溃"的处理收成一份；trace_transition 保留自己的 BOM 与读回校验，不用本模块的
通用路径。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8",
                      verify: bool = False) -> None:
    """同目录临时文件 + fsync + os.replace；崩溃点最多留下 `.tmp`，读者不会看到半份。

    ``verify=True`` 时写后读回比对，不一致就删临时件并抛 OSError（调用方决定是否回滚）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                    dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="\n") as handle:
            handle.write(str(text))
            handle.flush()
            os.fsync(handle.fileno())
        if verify and tmp.read_text(encoding=encoding) != str(text):
            raise OSError(f"atomic_write_text: 写盘内容与内存不一致：{path}")
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def load_yaml(path: Path):
    """YAML 读：与全仓同一个解析后端（_yaml.load_file）。"""
    from _yaml import load_file
    return load_file(path)


def dump_yaml(obj: Any, *, width: int = 10 ** 6) -> str:
    """YAML 写：UTF-8、保留键序、按调用方给的宽度折行（默认不折）。"""
    import yaml
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False,
                          default_flow_style=False, width=width)


def write_yaml(path: Path, obj: Any, *, verify: bool = False) -> None:
    atomic_write_text(path, dump_yaml(obj), verify=verify)
