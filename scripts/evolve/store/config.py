# -*- coding: utf-8 -*-
"""存储配置：默认 local；可用 store.yaml 或环境变量切换后端。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping

import yaml


@dataclass(frozen=True)
class StoreConfig:
    backend: str = "local"
    options: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, base: Path) -> "StoreConfig":
        base = Path(base)
        data: Dict[str, Any] = {}
        path = base / "store.yaml"
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"{path} must contain an object")
            data = raw
        backend = os.environ.get("SLEUTH_RSI_STORE_BACKEND") or str(data.get("backend") or "local")
        options = data.get("options") if isinstance(data.get("options"), dict) else {}
        if os.environ.get("SLEUTH_RSI_STORE_PATH"):
            options = {**options, "path": os.environ["SLEUTH_RSI_STORE_PATH"]}
        return cls(backend=backend, options=dict(options))
