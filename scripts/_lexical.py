#!/usr/bin/env python3
# _lexical.py —— token 类信号的单一事实源（错误码 / 环境变量名 / 算子名 / 文件名 / 版本）
#
# 为什么单独放一个模块：这组模式被两处消费，且两处判的是**不同的东西**——
#   - `trace_metrics.py`：triage 未命中里"token 在场而词法层没接住"（真缺陷）vs"本来无 token"（语义路径）；
#   - `rank_candidates.py`：候选排序里的 token 交集数。
# 两处各写一份模式清单就会漂移（改一处忘另一处，且漂移不报错）。故口径只在这里定义一次。
#
# 判据的语义：token = **不会因语言与措辞而变的字面量**。自由语言的症状描述（中文/英文/换词）
# 不属于这一类——含义的模糊归 agent 语义层（设计原则三），形态的模糊归正则。
#
# 强度如实标注（原则十）：假阳性（自由语言里恰好出现的 5-6 位数字）与假阴性（只用领域名词、
# 不引任何字面量的输入）都存在。它是筛选口径与排序信号，不是判词。

import re

LEXICAL_SIGNAL_PATTERNS = [
    r"\b\d{5,6}\b",                       # 错误码 / 端口 / 编号（65536、507014）
    r"error code[ :]*\d+",                  # "error code 507014"
    r"ErrCode=\d+|\bErrCode\b",
    r"0x[0-9a-fA-F]{4,}",                    # 十六进制错误位（0x3000012e）
    r"\b[A-Z][A-Z0-9_]{4,}\b",              # 环境变量 / 常量名（VLLM_ASCEND_ENABLE_FUSED_MC2）
    r"\baclnn[A-Za-z0-9_]+\b",              # ACLNN 算子名
    r"kernel_name=\w+",
    r"\b[\w.]+\.(?:py|cpp|cc|h)\b",         # 源码位置
    r"\b\w+\(\)",                          # 函数调用（repeat_interleave()）
    r"\bv?\d+\.\d+(?:\.\d+)?(?:rc\d+)?\b",  # 版本号（v0.22.1rc1）
]


def tokens_of(text: str) -> set:
    """文本里的 token 集合（空文本 → 空集）。"""
    if not text:
        return set()
    return {m.group(0) for p in LEXICAL_SIGNAL_PATTERNS for m in re.finditer(p, text)}


def has_lexical_signal(text: str) -> bool:
    """文本里有没有 token 类信号（空文本视为没有）。"""
    return bool(tokens_of(text))
