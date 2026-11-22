# -*- coding: utf-8 -*-
"""兼容入口：RSIStore 已拆到 ``evolve.store`` 包。"""

from .store import (KINDS, SCHEMA, MemoryBackend, RSIEvent, RSIStore,
                    RSIStoreError, StoreConfig, open_store)

__all__ = ["RSIStore", "open_store", "StoreConfig", "RSIEvent", "RSIStoreError",
           "MemoryBackend", "KINDS", "SCHEMA"]
