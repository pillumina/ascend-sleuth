#!/usr/bin/env python3
"""实测证据的唯一形状（卡内 ``measure_evidence``）。

写侧 ``ev_measure.append_card_evidence`` 用 :func:`card_entry` 生成一条；读侧
``verify_proposals`` 与 ``evolution_health`` 用 :func:`card_passes` 判定。
``metrics/ev-measure-log.yaml`` 是同一事实的本机运行历史，字段由
``ev_measure.append_run`` 维护；它不参与这里的判定。

为什么单独一个模块：卡内证据的写侧与两个读侧原先各拼一份字段列表。加 ``version``
时三处都要记得改，漏一处不报错——这正是「同一事实两份表示」的典型来源。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

PASS = "PASS"


def card_entry(*, command: str, verdict: str, exit_code: int,
               at: Optional[str] = None, version: str = "") -> Dict[str, Any]:
    """一条卡内证据。``version`` 记录跑这次实测时的检出提交，空值表示取不到。"""
    return {
        "at": at or datetime.now().isoformat(timespec="seconds"),
        "command": str(command or "").strip(),
        "verdict": str(verdict or ""),
        "exit_code": int(exit_code),
        "version": str(version or ""),
    }


def log_entry(*, seq: int, card: str, command: str, verdict: str, exit_code: int,
              at: Optional[str] = None, version: str = "") -> Dict[str, Any]:
    """运行日志的一条记录：共同的证据字段 + ``seq`` / ``card``。

    字段顺序沿旧文件（``seq, at, card, verdict, exit_code, command, version``），
    避免一次收口把 append-only 日志的排版整体改掉。
    """
    common = card_entry(command=command, verdict=verdict, exit_code=exit_code,
                        at=at, version=version)
    return {
        "seq": int(seq),
        "at": common["at"],
        "card": str(card),
        "verdict": common["verdict"],
        "exit_code": common["exit_code"],
        "command": common["command"],
        "version": common["version"],
    }


def card_entries(doc: Any) -> List[Dict[str, Any]]:
    """卡里的证据列表（结构不对时返回空列表，不替调用方猜）。"""
    if not isinstance(doc, dict):
        return []
    evidence = doc.get("measure_evidence")
    if not isinstance(evidence, list):
        return []
    return [entry for entry in evidence if isinstance(entry, dict)]


def card_passes(doc: Any, command: Optional[str] = None) -> bool:
    """这张卡有没有一条 PASS 证据；给了 ``command`` 时还要求命令相同。

    命令比较沿用写侧与读侧共用的归一：两端都 ``strip()``。空 ``command`` 表示
    只看 verdict，不看命令。
    """
    wanted = str(command).strip() if command is not None else None
    for entry in card_entries(doc):
        if str(entry.get("verdict") or "") != PASS:
            continue
        if wanted is None or str(entry.get("command") or "").strip() == wanted:
            return True
    return False
