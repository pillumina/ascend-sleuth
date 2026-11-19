"""从 DSH 会话记录读模型与 token 用量。

trace 由 agent 写，模型名和 token 计数不在 trace 里；这两项在 DSH 的会话
存储里（`modelSelection` 与 `tokenUsage`）。本模块只读，不写；没有 DSH
或没有对应会话时返回 None，不补零、不猜模型。非 DSH agent 由
`trace_begin.py --model/--tokens-start` 与 `trace_usage.py --tokens` 写 trace
显式字段，本模块只是 DSH 的自动填充适配器。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

_TOKEN_KEYS = ("uncachedInputTokens", "outputTokens",
               "cacheReadTokens", "cacheWriteTokens")
_SESSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _sessions_root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    home = os.environ.get("DSH_HOME")
    if home:
        base = Path(home)
    else:
        try:
            base = Path.home() / ".dsh"
        except (RuntimeError, OSError):
            # 无 home 的 CI/容器：没有会话库可读，返回一个不存在的路径。
            return Path(".dsh-sessions-unavailable")
    return base / "storages" / "session_projcache" / "sessions"


def _session_file(session_id: str, root: Path) -> Optional[Path]:
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        return None
    if ".." in session_id:
        return None
    for name in (f"{session_id}.json", f"session-{session_id}.json"):
        path = root / name
        if path.is_file():
            return path
    return None


def read_session(session_id: str, root: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """读一条会话的模型与累计 token；取不到返回 None。"""
    path = _session_file(session_id, _sessions_root(root))
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload["record"]["rows"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    model_row = ((rows.get("modelSelection") or {}).get("val") or {})
    last = model_row.get("lastUsed") or {}
    totals = ((rows.get("tokenUsage") or {}).get("val") or {}).get("totals") or {}
    if not isinstance(totals, dict):
        totals = {}
    clean = {key: totals[key] for key in _TOKEN_KEYS
             if isinstance(totals.get(key), int) and not isinstance(totals.get(key), bool)
             and totals[key] >= 0}
    total = sum(clean.values()) if clean else None
    result = {
        "model": last.get("model") if isinstance(last.get("model"), str) else None,
        "provider": last.get("provider") if isinstance(last.get("provider"), str) else None,
        "reasoning_effort": (last.get("reasoningEffort")
                             if isinstance(last.get("reasoningEffort"), str) else None),
        "tokens": total,
        "token_totals": clean or None,
    }
    if not any(result[key] is not None for key in
               ("model", "provider", "reasoning_effort", "tokens")):
        return None
    return result


def model_of(session_id: str, root: Optional[Path] = None) -> Optional[str]:
    usage = read_session(session_id, root)
    return usage["model"] if usage else None


def tokens_of(session_id: str, root: Optional[Path] = None) -> Optional[int]:
    usage = read_session(session_id, root)
    return usage["tokens"] if usage else None
