#!/usr/bin/env python3
"""EV 卡文本判据：合入指针的唯一实现。

`ev_proposal`（水位与回写）与 `ev_board_data`（面板读数）共用这里的判定；放在独立模块
是为了断开两者互相 import 的循环（`ev_proposal` 在 `--impact` 里复用 `ev_board_data`
的归因口径，`ev_board_data` 又需要合入指针判定）。
"""

import re

_MERGE_POINTER_RE = re.compile(r"(?:PR|#)\s?#?\d{2,6}")


def has_merge_pointer(text: str) -> bool:
    """卡文本里有没有任何 PR/issue 号——判据「待合入积压」分子的**唯一实现**。

    为什么松匹配（任意 PR/issue 号即算有指针）：指针的历史写法不止一种——正式的一条
    （`合入指针回写：本卡随 PR #278 进入 main`）、结论里的散文（`改动随 PR #97 供人审`）、
    以及正文提到的 issue 号。收紧到"只认正式形态"会把 32 张早已合入的老卡重新计进积压
    （实测），把闸门引向"停产新候选"这个错动作；松匹配的代价是"提过 issue 号的卡被当成
    已回写"，那个方向只让读数偏乐观，不触发错误动作。
    """
    return bool(_MERGE_POINTER_RE.search(str(text or "")))


# 旧名保留：面板与既有脚本沿用它，行为与 has_merge_pointer 完全一致。
_has_any_ref = has_merge_pointer
