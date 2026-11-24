# -*- coding: utf-8 -*-
"""兼容入口：GEPA 实现已迁到 ``evolve.loops.gepa``。

保留本模块是为了让旧脚本、旧状态文件与旧 import 不改；新代码直接 import
``evolve.loops.gepa`` 或从 ``evolve.loops`` 取。状态 schema 仍是
``agent-gepa-v1``。
"""

from .loops.gepa import (GEPA_STATE_SCHEMA, AgentRsiSession, Candidate,
                         GepaError, GepaSession)

__all__ = ["GEPA_STATE_SCHEMA", "AgentRsiSession", "Candidate", "GepaError",
           "GepaSession"]
