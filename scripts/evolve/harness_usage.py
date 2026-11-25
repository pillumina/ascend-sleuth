"""从 DSH 会话记录读模型与 token 用量。

trace 由 agent 写，模型名和 token 计数不在 trace 里；这两项在 DSH 的会话
存储里（`modelSelection` 与 `tokenUsage`）。本模块只读，不写；没有 DSH
或没有对应会话时返回 None，不补零、不猜模型。非 DSH agent 由
`trace_begin.py --model/--tokens-start` 与 `trace_usage.py --tokens` 写 trace
显式字段，本模块只是 DSH 的自动填充适配器。

DSH 会话存储的文件名有两种（`<uuid>.json` 与 `session-<uuid>.json`），
`$DSH_SESSION_ID` 在不同入口也可能带或不带 `session-` 前缀；`normalize_session_id`
统一写成带前缀，`_session_file` 两种文件名都试。
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
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


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


def session_base(session_id: str) -> Optional[str]:
    """去掉至多一个 `session-` 前缀，返回会话记录文件名的基名；形状不合法返回 None。"""
    if not isinstance(session_id, str):
        return None
    raw = session_id.strip()
    if raw.startswith("session-"):
        raw = raw[len("session-"):]
    if not raw or not _SESSION_ID_RE.fullmatch(raw) or ".." in raw:
        return None
    return raw


def normalize_session_id(value: str) -> str:
    """`session-<uuid>` 与裸 uuid 统一成前者；其它形状返回空串（不猜）。

    为什么要归一：DSH 会话记录的文件名有两种（`<uuid>.json` 与
    `session-<uuid>.json`），不同入口的 `$DSH_SESSION_ID` 也可能带或不带前缀。
    写侧只认一种，成本链与面板就会各断一半：trace 头写成裸 uuid 时面板挂不上，
    写成带前缀时裸文件名的会话记录又读不到。
    """
    if not isinstance(value, str):
        return ""
    raw = value.strip()
    if raw.startswith("session-"):
        base = raw[len("session-"):]
        if base and _SESSION_ID_RE.fullmatch(base) and ".." not in base:
            return raw
        return ""
    if _UUID_RE.fullmatch(raw):
        return "session-" + raw
    return ""


def _session_file(session_id: str, root: Path) -> Optional[Path]:
    base = session_base(session_id)
    if base is None:
        return None
    for name in (f"{base}.json", f"session-{base}.json"):
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
