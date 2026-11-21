# -*- coding: utf-8 -*-
"""存储配置：从 sleuth.config.yaml 的 evolution.store 读取。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping


@dataclass(frozen=True)
class StoreConfig:
    backend: str = "local"
    options: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, base: Path) -> "StoreConfig":
        base = Path(base)
        import sleuth_config as SC
        try:
            config = SC.load_config(base.parent.parent)
        except SC.ConfigError:
            return cls()
        if str(config.get("_source") or "").startswith("built-in defaults"):
            data = {}
        else:
            data = SC.store_for(config)
        backend = os.environ.get("SLEUTH_RSI_STORE_BACKEND") or str(data.get("backend") or "local")
        options = data.get("options") if isinstance(data.get("options"), dict) else {}
        if data.get("path"):
            options = {**options, "path": str(Path(config["_root"]) / data["path"])}
        if os.environ.get("SLEUTH_RSI_STORE_PATH"):
            options = {**options, "path": os.environ["SLEUTH_RSI_STORE_PATH"]}
        return cls(backend=backend, options=dict(options))
