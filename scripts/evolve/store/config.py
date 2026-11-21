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
        try:
            import sleuth_config as SC
            config = SC.load_config(base.parent.parent)
            if config.get("_source") != "legacy（deployment.yaml / eval/policy*.yaml / store.yaml）":
                data = SC.store_for(config)
                if data.get("path"):
                    data = dict(data)
                    data["path"] = str(Path(config["_root"]) / data["path"])
        except (ImportError, Exception):
            data = {}
        path = base / "store.yaml"
        if not data and path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"{path} must contain an object")
            data = raw
        backend = os.environ.get("SLEUTH_RSI_STORE_BACKEND") or str(data.get("backend") or "local")
        options = data.get("options") if isinstance(data.get("options"), dict) else {}
        if data.get("path"):
            options = {**options, "path": data["path"]}
        if os.environ.get("SLEUTH_RSI_STORE_PATH"):
            options = {**options, "path": os.environ["SLEUTH_RSI_STORE_PATH"]}
        return cls(backend=backend, options=dict(options))
