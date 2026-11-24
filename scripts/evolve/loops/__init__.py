# -*- coding: utf-8 -*-
"""循环层：契约、内置实现与注册表。

六点 stage 描述「一步做什么」；搜索循环层描述「一次搜索怎么走」。两者正交：
循环可以引用 stage，但 stage 组合本身不是循环，预设也不描述循环。
"""

from .budget import BUDGET_KINDS, Budget
from .contract import (ACTORS, LOOP_KINDS, SAMPLE_ROLES, ActionSpec, LoopError,
                       LoopSpec, SearchLoop, Snapshot, action_actor,
                       decision_record, param_errors, validate_action)
from .decisions import DecisionLog, optional_log
from .proposal import ProposalLoop
from .registry import (BASELINE_LOOP, GEPA_LOOP, LOOPS, LOO_LOOP, SKILLOPT_LOOP,
                       get_loop, list_loops, loop_ids, loop_table, restore_loop)

__all__ = [
    "ACTORS", "LOOP_KINDS", "SAMPLE_ROLES", "ActionSpec", "Budget",
    "BUDGET_KINDS", "DecisionLog", "LoopError", "LoopSpec", "SearchLoop",
    "Snapshot", "ProposalLoop", "action_actor", "decision_record", "param_errors", "validate_action",
    "optional_log", "LOOPS", "GEPA_LOOP", "LOO_LOOP", "BASELINE_LOOP",
    "SKILLOPT_LOOP",
    "get_loop", "list_loops", "loop_ids", "loop_table", "restore_loop",
]
