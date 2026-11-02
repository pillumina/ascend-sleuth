"""gates 条目 id 的唯一性检查（metrics 与演进两个体检器共用）。

为什么需要：两个体检器都按 id 找判据，`next((g for g in gates if g.get("id") == gid))`
只取第一条。复制粘贴一条判据会让同一个健康项被判两遍、面板出现两行，而阈值静默只认
第一条——`--check` 不会红。id 是判据的身份，重复就是结构性错误，应在评估前报出来。
"""

from __future__ import annotations


def duplicate_ids(gates) -> list[str]:
    """返回重复出现的 gate id（按首次重复的顺序，去重）。缺 id 的条目不在这里判。"""
    seen: set[str] = set()
    dup: list[str] = []
    for gate in gates or []:
        if not isinstance(gate, dict):
            continue
        gid = str(gate.get("id") or "").strip()
        if not gid:
            continue
        if gid in seen and gid not in dup:
            dup.append(gid)
        seen.add(gid)
    return dup
