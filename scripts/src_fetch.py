#!/usr/bin/env python3
"""src_fetch.py —— 确定性获取（复用 / 新拉）**对应版本**的分析用源码

背景（两件事叠在一起，2026-09-14 一起修）：

  ① **闸门说假话（"本地没找到这个版本就去 web 搜索"的直接成因）**。旧实现的"复用优先"分支在版本
     不符时**无条件** `print("复用 <路径>")` + `return 0`——fetch/checkout 失败也走这条。而 SKILL 的
     契约是"非零退出 = 未取得源码"，于是 agent 拿到 exit 0 + 一个路径、grep 不到预期符号 → 判"本地
     没有这个版本" → 转 web 搜索。**换成任何目录布局这个失败都会复发**（布局只让"有没有这个版本"
     可判定，不会让"版本不符"变成失败），所以退出码是本脚本的第一契约，不是附带改进。
     加剧因素：`--ref 0.26.0` 与真实 tag `v0.26.0` 只差一个前缀——现在做 v 前缀容错解析，解析不到时
     列出可用 tag（旧实现静默判不匹配）。
  ② **缓存不可共享**。缓存根原为 `__file__` 上两级（= 执行脚本的那个检出），而 `src-code/` 是
     .gitignore 件 → 新 worktree 天然没有它、`git worktree remove` 连它一起删；"平铺版本目录给多
     agent 协作"在共享面根本不成立。现在根解析到**主检出**（同一克隆共享，复用 exec_log_path 的既有
     范式；`--local` 可强制回检出内）。

布局（每个版本目录自包含、互不干扰）：

    src-code/<org>/<repo>/<解析后的 ref>/                     # 例：…/vllm-ascend/v0.26.0/
    src-code/<org>/<repo>/<解析后的 ref>/.git/src-fetch-meta.json   # 版本标记（离线核对用）

  版本目录名 = **解析后的** ref（tag/分支名；commit 用 `sha-<12>`），于是「本地有没有这个版本」是一次
  目录名可判定的检查，且 `source_ref.ref` 与目录名是同一个 token（案例 ↔ 源码互查免费）。
  每个版本是一次独立浅克隆（`--depth 1`）：代价是一份工作树，换来版本间物理隔离——并发诊断下不存在
  "别人 checkout 走了我正在读的版本"这类静默错证据（单目录 + 换版本 checkout 的旧布局正是如此）。

退出码契约（agent 依此决定下一步，别只看输出里的路径）：

    0  已在本地产出该 ref 的树**并通过核对**（stdout 最后一行 = 绝对路径）
    2  用法/参数问题（未知仓库且无 --url、--prune 缺 --ref、--prune 目标不存在…）
    3  ref 解析不了：源可达但找不到该 tag/分支（**附可用 tag 示例**——多半是 tag 名不同或版本说错）
    4  拉取失败：候选源都不可达/克隆失败，或拉到的提交与 ref 不符（网络、私网、凭据）
    5  本地有该版本的目录但**核对不通过**（内容不是该 ref / 被外部改动）→ 确认后 --force 重拉

  stdout 末行只有两种形态：**exit 0 时是版本目录的绝对路径**，非零时是一行显式的失败声明
  （`✗ 未取得该版本源码`）——绝不会把某个版本目录当成结果给出来。旧实现正是在这里让 agent 误以为
  拿到了对应版本源码（版本不符也 exit 0 + 打印路径）。

用法：
  python3 scripts/src_fetch.py vllm-ascend --ref v0.23.0
  python3 scripts/src_fetch.py vllm-ascend --ref 0.26.0        # 自动容错到 v0.26.0
  python3 scripts/src_fetch.py vllm-project/vllm-ascend --ref v0.23.0
  python3 scripts/src_fetch.py Ascend/MindSpeed-LLM --ref v0.23.0        # gitcode
  python3 scripts/src_fetch.py my-org/my-repo --ref <commit> --url https://...   # 自定义/私有
  python3 scripts/src_fetch.py --find "aclnnQuantBatchMatMulV3" --ref 8.1.RC1    # 只知道签名、不知道在哪个仓
  python3 scripts/src_fetch.py --list                    # 已知仓库与 host
  python3 scripts/src_fetch.py --list-versions           # 本地缓存：有哪些仓库、哪些版本（体积/时间/HEAD）
  python3 scripts/src_fetch.py vllm-ascend --ref v0.23.0 --prune        # 手工删版本（无自动 GC）

`--find` 的退出码语义与取源码一致，调用方照旧只看退出码：
  0  候选里**只有一个仓**能解析出该 ref → 已按它取好源码（stdout 末行 = 路径）
  3  候选 ≥2（或一个都解析不到）→ stdout 给了带判据的候选表，**问工程师选哪个**，别猜
  4  拉取失败（与普通路径同义）
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from _stdio import write_text_lf

from exec_log_path import WHERE_LABEL_SRC, describe_src, resolve_src_code  # noqa: E402  （共享缓存根解析的单一事实源）

# 已知仓库 → 有序候选 URL host（按可信度排序；同一仓库不同 host 是常态，自动回退）
HOSTS = {
    "github": "https://github.com/{owner}/{repo}.git",
    "gitcode": "https://gitcode.com/{owner}/{repo}.git",
    "gitee": "https://gitee.com/{owner}/{repo}.git",
}
KNOWN_REPOS = {
    # key: (canonical org/repo, [(host, {owner, repo}), ...] 按序尝试)
    "vllm-ascend": ("vllm-project/vllm-ascend", [("github", {"owner": "vllm-project", "repo": "vllm-ascend"})]),
    "vllm-project/vllm-ascend": ("vllm-project/vllm-ascend", [("github", {"owner": "vllm-project", "repo": "vllm-ascend"})]),
    "mindspeed-llm": ("Ascend/MindSpeed-LLM", [("gitcode", {"owner": "Ascend", "repo": "MindSpeed-LLM"})]),
    "Ascend/MindSpeed-LLM": ("Ascend/MindSpeed-LLM", [("gitcode", {"owner": "Ascend", "repo": "MindSpeed-LLM"})]),
    "mindspeed-mm": ("Ascend/MindSpeed-MM", [("gitcode", {"owner": "Ascend", "repo": "MindSpeed-MM"})]),
    "Ascend/MindSpeed-MM": ("Ascend/MindSpeed-MM", [("gitcode", {"owner": "Ascend", "repo": "MindSpeed-MM"})]),
    "torch-npu": ("Ascend/pytorch", [("gitcode", {"owner": "Ascend", "repo": "pytorch"}), ("github", {"owner": "Ascend", "repo": "pytorch"})]),
    "Ascend/pytorch": ("Ascend/pytorch", [("gitcode", {"owner": "Ascend", "repo": "pytorch"}), ("github", {"owner": "Ascend", "repo": "pytorch"})]),
    "verl": ("volcengine/verl", [("github", {"owner": "volcengine", "repo": "verl"})]),
    "volcengine/verl": ("volcengine/verl", [("github", {"owner": "volcengine", "repo": "verl"})]),
    # CANN 开源面（gitcode 的 cann 组织，2026-09 起 82 仓）：报错签名最常指向的层。
    # 只收「错误签名会直接点到名字」的层，不是把组织全表搬进来——其余层走 `--find <签名>`
    # 现枚举（见 ORG_SIGNATURE_REPOS），免得这张表随上游增减而腐烂。
    "cann/ops-nn": ("cann/ops-nn", [("gitcode", {"owner": "cann", "repo": "ops-nn"})]),
    "cann/ops-transformer": ("cann/ops-transformer", [("gitcode", {"owner": "cann", "repo": "ops-transformer"})]),
    "cann/ops-math": ("cann/ops-math", [("gitcode", {"owner": "cann", "repo": "ops-math"})]),
    "cann/ops-cv": ("cann/ops-cv", [("gitcode", {"owner": "cann", "repo": "ops-cv"})]),
    "cann/hccl": ("cann/hccl", [("gitcode", {"owner": "cann", "repo": "hccl"})]),
    "cann/hcomm": ("cann/hcomm", [("gitcode", {"owner": "cann", "repo": "hcomm"})]),
    "cann/ge": ("cann/ge", [("gitcode", {"owner": "cann", "repo": "ge"})]),
    "cann/metadef": ("cann/metadef", [("gitcode", {"owner": "cann", "repo": "metadef"})]),
    "cann/runtime": ("cann/runtime", [("gitcode", {"owner": "cann", "repo": "runtime"})]),
    "cann/driver": ("cann/driver", [("gitcode", {"owner": "cann", "repo": "driver"})]),
    "cann/asc-devkit": ("cann/asc-devkit", [("gitcode", {"owner": "cann", "repo": "asc-devkit"})]),
}

# 签名 → 候选仓（`--find` 的匹配表）。**只做"给候选"，不做"替人选"**：一条签名常常同时
# 命中多层（aclnn 算子名既可能在上层算子库、也可能在 pyasc/asc-devkit 的接口层），谁对由
# 报错栈与调用方判断。候选 ≤3 个，按「签名里命中的关键词数」排序。
# 覆盖判据：只收**错误签名会直接点到名字**的词——收多了会让候选表变成一张需要维护的全量表。
ORG_SIGNATURE_REPOS = {
    "cann": [
        {"repo": "ops-nn", "why": "aclnn 神经网络类算子（Conv/MatMul/Attention 等）"},
        {"repo": "ops-transformer", "why": "aclnn transformer 类算子"},
        {"repo": "ops-math", "why": "aclnn 数学类算子"},
        {"repo": "ops-cv", "why": "aclnn 图像类算子"},
        {"repo": "hccl", "why": "集合通信（Hccl* 接口、通信域/rank 表）"},
        {"repo": "hcomm", "why": "HCCL 的通信基础库（通信资源/单边通信）"},
        {"repo": "ge", "why": "图编译器与执行器（ge:: 命名空间）"},
        {"repo": "metadef", "why": "算子元数据定义（算子原型/属性注册）"},
        {"repo": "runtime", "why": "运行时与维测组件（aclrt*、plog）"},
        {"repo": "driver", "why": "驱动模块（drv* 接口、设备资源与调度）"},
        {"repo": "asc-devkit", "why": "Ascend C 算子开发语言与类库（AscendC::）"},
        {"repo": "pyasc", "why": "Python 算子编程接口（与 Ascend C 一一对应）"},
        {"repo": "oam-tools", "why": "故障定位工具（aicore error 分析、信息收集）"},
    ],
}
# 签名里出现这些词 → 指向上表。**关键词一律小写，且这条由 --self-test 钉成断言**：
# 大写不会报错，只会让匹配静默失效——实测 `HcclCommInitRootInfo failed` 就因为没有小写归一
# 而零候选（`HcclAllReduce` 侥幸命中，因为驼峰拆分后留了 `hccl` 这一段）。
# 匹配用「词元边界 + 小写 + 驼峰拆分」：`HcclAllReduce` → {hccl, all, reduce, hcclallreduce}，
# 于是 `hccl` 命中，而 `transformer` 不会命中 `ascend-transformer-boost`（候选表不被撑大）。
#   any_of  任一关键词出现即命中（前缀本身就是层名：hccl / ge / pyasc …）
#   all_of  全部出现才命中（通用词要组合证据：aclnn 是四条算子库的公共前缀，靠 any_of 区分层）
#   primary **主候选**关键词，须是完整词元——只有主候选为 1 个时脚本才自动开始取源码；
#           没有主候选命中就只给候选表（`aclnnXxx` 这种公共前缀分不出是哪条算子库，
#           硬猜会取错仓、读错证据）
#   fallback 兜底候选：`aclnn` 是四条算子库的公共前缀，签名只给到这一层时命中它只能说明
#           「是 aclnn 接口层」，**不足以定到 `ops-nn`**——所以它排在有判别词命中的候选之后
#           （同分时最后一名），而不是被判成"唯一候选然后自动取"
#   discriminators 判别词：命中它就不再是兜底（`aclnn` + `matmul` 对 ops-nn 是有效判别，
#           与 ops-math 并列时分高者胜；只命中 `aclnn` 才是兜底）
ORG_SIGNATURE_KEYWORDS = {
    "cann": [
        {"repo": "ops-nn", "all_of": ["aclnn"], "discriminators": ["conv", "matmul", "attention"],
         "fallback": True, "primary": ["aclnnop", "opapi"]},
        {"repo": "ops-transformer", "all_of": ["aclnn"],
         "any_of": ["attention", "flash", "increment", "paged", "rotary"],
         "primary": ["flashattention", "pagedattention"]},
        {"repo": "ops-math", "all_of": ["aclnn"],
         "any_of": ["matmul", "quantbatchmatmul", "add", "mul", "softmax", "norm"],
         "primary": ["quantbatchmatmul", "softmax"]},
        {"repo": "ops-cv", "all_of": ["aclnn"], "any_of": ["conv", "roi", "resize", "crop"]},
        {"repo": "hccl", "any_of": ["hccl", "hccltest", "allreduce", "allgather",
                                    "reducescatter", "alltoall", "broadcast"],
         "primary": ["hccl", "hccltest", "allreduce", "allgather", "reducescatter", "alltoall"]},
        {"repo": "hcomm", "any_of": ["hcomm", "hcommres"], "primary": ["hcomm", "hcommres"]},
        {"repo": "ge", "any_of": ["ge", "geapi", "graphengine", "geir"],
         "primary": ["ge", "geapi", "graphengine", "geir"]},
        {"repo": "metadef", "any_of": ["metadef", "opproto", "implytype"],
         "primary": ["metadef", "opproto", "implytype"]},
        {"repo": "runtime", "any_of": ["aclrt", "aclmdl", "plog", "rts", "acl"],
         "primary": ["aclrt", "aclmdl", "plog", "rts"]},
        {"repo": "driver", "any_of": ["drv", "drvdev", "drvmem", "drvdevice"],
         "primary": ["drv", "drvdev", "drvmem", "drvdevice"]},
        {"repo": "asc-devkit", "any_of": ["ascendc", "ascendckernel", "atvc", "atvoss"],
         "primary": ["ascendc", "ascendckernel", "atvc", "atvoss"]},
        {"repo": "pyasc", "any_of": ["pyasc"], "primary": ["pyasc"]},
        {"repo": "oam-tools", "any_of": ["msaicerr", "aicoreerror", "oam"],
         "primary": ["msaicerr", "aicoreerror", "oam"]},
    ],
}

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REF_UNRESOLVED = 3
EXIT_FETCH_FAILED = 4
EXIT_LOCAL_MISMATCH = 5

META_NAME = "src-fetch-meta.json"     # 落在 <版本目录>/.git/ 下（不在工作树里，git status 看不见）
TMP_PREFIX = ".tmp-"
TMP_STALE_SECONDS = 6 * 3600          # 半途被杀留下的临时克隆：超过这个岁数由下次运行顺手清掉


def die(code: int, msg: str, tail: str = "✗ 未取得该版本源码") -> int:
    """失败出口：原因 + 可执行的下一步走 stderr；stdout 只留一行**显式的失败声明**当末行。

    末行契约（调用方只看末行也安全）：exit 0 → 末行是版本目录的绝对路径；非零 → 末行是这句声明。
    旧实现失败时也打印路径，正是"agent 以为拿到了对应版本源码"的入口。
    """
    print(f"src_fetch: {msg}", file=sys.stderr)
    print(f"{tail}（exit {code}）")
    return code


def norm_repo(repo: str) -> str:
    """规范化仓库标识：去空白、尾部 .git；返回用于查表的键。"""
    return repo.strip().rstrip("/").removesuffix(".git")


def lookup(repo: str):
    """返回 (canonical_org/repo, [候选 (host, {owner,repo}), ...])；未知仓库返回 (repo, None)。"""
    key = norm_repo(repo)
    if key in KNOWN_REPOS:
        return KNOWN_REPOS[key]
    for k, val in KNOWN_REPOS.items():
        if norm_repo(k).lower() == key.lower():
            return val
    return (key, None)


def clone_url(host: str, owner: str, repo: str) -> str:
    return HOSTS[host].format(owner=owner, repo=repo)


# ---------------------------------------------------------------- 源码位置发现（--find）
# 为什么需要：报错签名只知道"是 CANN 的哪一层"，不知道"在哪个仓"。过去这里只有 exit 3 +
# "给 --url"——把找地址的活推给工程师，而组织仓库清单是可枚举的（一条匿名 API）。这一节
# 把「确定是哪个仓」从人的记忆变成可复现的一步：候选 → 逐个试 ref → 只有一个能解析就自动定。
def signature_tokens(sig: str):
    """报错签名 → 词元集合 + 归一文本。**用词元边界匹配，不做子串匹配**。

    子串匹配的代价实测过：`transformer` 会命中 `ascend-transformer-boost`、`ge` 会命中任何含
    "ge" 的词——候选表被撑大之后，"给候选"就退化成"给人一张全表让他自己找"。所以：
    短词元（<6 字符，如 ge/hccl/aclrt/drv）只做**整词元**匹配；长词元允许前缀匹配
    （aclnnQuantBatchMatMulV3 → aclnnquantbatchmatmul）。
    """
    tokens = set()
    for w in re.findall(r"[A-Za-z0-9]+", sig or ""):
        tokens.add(w.lower())                                # 原词
        parts = [p.lower() for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", w)]
        tokens.update(parts)                                 # 驼峰拆开：HcclAllReduce → hccl/all/reduce
        head, tail = "".join(parts), "_".join(parts)         # 合并形简写：aclnnQuantBatchMatMulV3 → aclnn…matmul
        tokens.add(head)
        for i in range(len(parts)):                          # 连续前缀：HcclAllReduce → hcclall
            for j in range(i + 1, len(parts) + 1):
                tokens.add("".join(parts[i:j]))
        for sep in ("_", "-", "::"):                         # 分隔符闭合的复合词：hccl_comm_init → hccl_comm_init
            tokens.update(p.lower() for p in w.split(sep) if p)
        flat = head + tail
    flat_all = "".join(sorted(tokens))
    return tokens, flat_all + (sig or "").lower().replace("_", "").replace("-", "")


def boundary_components(tok: str) -> set:
    """词元里「真边界」处的部件：`hcclAllReduce` → {hccl, hcclall, …}（前界 + 大小写转换点）。

    用来挡假阳性：`geometry` 里的 `ge` 不是边界（在词中间，前后没有大小写转换），所以不该命中
    `ge` 层；而 `hcclAllReduce` 的 `hccl`、`aclnnFlashAttentionScore` 的 `aclnn` 都是真边界。
    只做 startswith/endswith 会把这两类混为一谈——实测 `geometry error` 就这样命中了 `ge`。
    """
    out = set()
    for m in re.finditer(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z0-9])(?=[A-Z][a-z])", tok):
        out.add(tok[:m.start()].lower())
    return out


def _kw_hit(kw: str, toks, flat: str) -> bool:
    """单关键词命中判定（**宽松**：用于算分排序）。

    **词元边界**（长词允许前后缀）：`HcclAllReduce` 拆出的 `hcclall` 要能被 `hccl` 命中；
    `aclnnQuantBatchMatMulV3` 要能被 `aclnnquantbatchmatmul` 命中。
    **复合词**（`::` 与 `_` 连接）：`ge::` 这类写法里 `ge` 是独立标识符，不是词元的前缀——
    漏掉这一条实测会让 `ge::GEExecuteRun error` 零候选，而这正是 `ge` 层最常见的报错写法。
    **后缀只认真边界**（见 boundary_components）：`geometry` 不该命中 `ge`，`AllReduce` 也不该
    推出 `l` 去命中 `mul`——后缀匹配额外要求 ≥3 字符，否则三字母关键词会变回子串匹配。
    """
    if kw in toks:
        return True
    if len(kw) >= 6 and (kw in flat or f"::{kw}" in flat or f"_{kw}" in flat):
        return True
    for t in toks:
        if t == kw or t.startswith(kw + "_") or t.startswith(kw + "-"):
            return True
        if re.match(rf"^{re.escape(kw)}(?![a-z])", t):
            return True
        if len(t) >= 3 and t.endswith(kw):
            return True
        if kw in boundary_components(t):
            return True
    return False


def _kw_whole(kw: str, toks) -> bool:
    """**严格**命中：关键词必须是完整词元。用于「哪个仓是主候选」——主候选只能来自整词元，
    宽松的拆词命中（`hcclallreduce` 里的 `hccl`）证据太弱，不足以让脚本自动开始克隆。"""
    return kw in toks


def _rule_score(rule: dict, toks, flat: str):
    """→ (命中分, 是否命中主关键词, 是否只是兜底命中)；all_of 缺一即为 (0, False, False)。"""
    allof = rule.get("all_of") or []
    anyof = rule.get("any_of") or []
    if not allof and not anyof:
        return 0, False, False                               # 规则写空 = 不命中（别静默全命中）
    if allof and not all(_kw_hit(k, toks, flat) for k in allof):
        return 0, False, False
    score = 2 * len(allof)
    if anyof and not any(_kw_hit(k, toks, flat) for k in anyof):
        return 0, False, False
    score += 2 if anyof else 0
    discrim_hit = any(_kw_hit(k, toks, flat) for k in (rule.get("discriminators") or []))
    if not discrim_hit:
        score += 2 if any(_kw_hit(k, toks, flat) for k in (rule.get("base") or [])) else 0
    primary = any(_kw_whole(k, toks) for k in (rule.get("primary") or []))
    return score, primary, (bool(rule.get("fallback")) and not discrim_hit)


def candidate_repos(org: str, sig: str):
    """签名 → [(repo, why, 命中分)]：主候选优先 → 非兜底优先 → 分高优先 → 表内顺序（稳定）。"""
    rules = ORG_SIGNATURE_REPOS.get(org, [])
    if not rules:
        return []
    kws = {r["repo"]: r for r in ORG_SIGNATURE_KEYWORDS.get(org, [])}
    toks, flat = signature_tokens(sig)
    hits = {}
    for r in rules:
        score, primary, fallback = _rule_score(kws.get(r["repo"], {}), toks, flat)
        if score:
            hits[r["repo"]] = (score, primary, fallback)
    why = {r["repo"]: r["why"] for r in rules}
    order = {r["repo"]: i for i, r in enumerate(rules)}      # 同分时按表内声明顺序（稳定）
    ranked = sorted(hits.items(),
                    key=lambda kv: (not kv[1][1], kv[1][2], -kv[1][0], order[kv[0]]))
    return [(repo, why[repo], score) for repo, (score, _p, _f) in ranked]


def is_fallback_candidate(org: str, sig: str, repo: str) -> bool:
    """该候选是否只是**兜底**命中（公共前缀命中、没有判别词）：兜底候选不构成"唯一候选"。"""
    kws = {r["repo"]: r for r in ORG_SIGNATURE_KEYWORDS.get(org, [])}
    toks, flat = signature_tokens(sig)
    _score, _primary, fallback = _rule_score(kws.get(repo, {}), toks, flat)
    return fallback


def self_test() -> int:
    """表不变量：关键词小写、仓名在候选表里存在、匹配表能被几条真实签名命中。

    为什么值得一个自测：这类表**坏了不报错，只是静默零候选**——诊断中表现为"没找到源码仓"，
    看起来像上游没有这个仓。把不变量钉成断言是唯一能让它响亮失败的形态。
    """
    problems = []
    repos = {r["repo"] for r in ORG_SIGNATURE_REPOS.get("cann", [])}
    for rule in ORG_SIGNATURE_KEYWORDS.get("cann", []):
        repo = rule.get("repo")
        if repo not in repos:
            problems.append(f"关键词规则指向候选表里没有的仓：{repo}")
        for field in ("any_of", "all_of"):
            for kw in rule.get(field) or []:
                if kw != kw.lower():
                    problems.append(f"{repo}.{field} 关键词含大写（会静默不匹配）：{kw}")
    cases = [
        ("HcclCommInitRootInfo failed", "hccl"),
        ("HcclAllReduce failed, rank table", "hccl"),
        ("ge::GEExecuteRun error", "ge"),
        ("aclnnQuantBatchMatMulV3 execute failed", "ops-math"),
        ("ACL_ERROR_RT_DEVICE_MEM_ERROR", "runtime"),
        ("drvDeviceOpen failed", "driver"),
        ("AscendC::KernelLaunch error", "asc-devkit"),
        ("opproto ImplyType not found", "metadef"),
        ("msaicerr 解析 aicore error", "oam-tools"),
        ("aclnnFlashAttentionScore failed", "ops-transformer"),
        ("aclnnBatchMatMul failed", "ops-math"),
        ("Conv2D aclnn error", "ops-cv"),
    ]
    for sig, expect in cases:
        got = [c[0] for c in candidate_repos("cann", sig)]
        if expect not in got:
            problems.append(f"签名「{sig}」应命中 {expect}，实际 {got or '无候选'}")
    if problems:
        print("✗ src_fetch 匹配表自测失败：", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"✓ src_fetch 匹配表自测通过（{len(cases)} 条真实签名、"
          f"{len(repos)} 个候选仓、{len(ORG_SIGNATURE_KEYWORDS.get('cann', []))} 条关键词规则）")
    return 0


def org_repo_catalog(org: str, sig: str = "", offline: bool = False, limit: int = 3):
    """→ (candidates, note)：候选仓清单。catalog 拉不到（离线/被限流）时 note 说明原因。

    复用 gc_docs 的 `/orgs/<org>/repos` 分页（同一事实源，不再写一份 API 客户端）。
    `--offline` 只在**签名关键词表**上做匹配、不联网——这是 CI 与断网现场的降级路径。
    零候选就如实返回零候选：不许用"仓名是签名子串"这种兜底（实测 `geometry error` 会被
    判成 `ge` 层——假阳性比零候选更糟，它会让调用方拿着错仓去读源码）。"""
    cands = candidate_repos(org, sig)
    if offline:
        return cands[:limit], "离线模式：未枚举组织仓库（候选来自签名关键词表）"
    try:
        import gc_docs                                        # 延迟导入：只有这条路要联网
        rows = gc_docs.api_pages(f"/orgs/{org}/repos", per_page=100)
    except Exception as e:                                    # 网络/限流：降级，不静默
        return cands[:limit], f"组织仓库清单拉取失败（{type(e).__name__}）——候选来自签名关键词表"
    desc = {r.get("path") or r.get("name"): (r.get("description") or "") for r in rows}
    if not cands:
        return [], (f"{org} 组织共 {len(rows)} 仓，但签名没命中任何已知层——"
                    f"用 `python3 scripts/gc_docs.py repos --org {org}` 列全表，"
                    f"或向工程师要报错目录")
    out = []
    for repo, why, score in cands[:limit]:
        if repo in desc:
            out.append((repo, why, score))
    missing = [c[0] for c in cands[:limit] if c[0] not in desc]
    note = ""
    if missing:
        note = (f"⚠ 组织里没有这些仓（曾用名/已改名/已归档？）：{', '.join(missing)}——"
                f"用 `--list` 与 gc_docs repos 复核")
    return out, note


def print_candidates(org: str, cands, note: str, ref: str, header: str = "候选源码仓"):
    """打给人看（也打给 agent 读）：候选 + 判据 + 下一步命令。**不替人选**。"""
    print(f"{header}（{org} 组织，ref={ref or '(默认分支)'}）：")
    for i, (repo, why, _score) in enumerate(cands, 1):
        print(f"  {i}) {org}/{repo} —— {why}")
    if note:
        print(f"  {note}")
    print("  判据：报错栈里的命名空间/接口前缀（aclnn*/Hccl*/ge::/aclrt*）比算子名更硬；"
          "拿不准就问工程师「这个报错在你们那的 CANN 安装目录里落在哪个子目录」。")
    if len(cands) > 1:
        print("  建议：CANN 各仓共用同一套版本号，所以「版本对得上」不能唯一定位——"
              "决定的是报错栈里的命名空间/接口前缀。定不下来就问工程师一句："
              "这个报错在你们那的 CANN 安装目录里落在哪个子目录。")


def resolve_across_candidates(cands, ref: str):
    """候选逐个试 ref → ([(host, slot, url, resolved), ...], [(repo, url, 原因), ...])。

    "只有一个能解析"是**证据**而不是猜测：版本对不上的仓解析不出这个 tag，解析本身因此是一
    次廉价自证。**多个都能解析时不能替人选**（同名 tag 很常见）——交回去由调用方按报错栈定。
    """
    hits, tried = [], []
    for host, slot in cands:
        url = slot["url"] if host == "custom" else clone_url(host, slot["owner"], slot["repo"])
        print(f"尝试解析 {url} 的 ref「{ref or '(默认分支)'}」")
        res, err = resolve_ref(url, ref)
        if res:
            hits.append((host, slot, url, res))
            print(f"  ✓ {slot.get('owner','')}/{slot.get('repo','')} 有该 ref"
                  f"（{res['kind']} {res['name']}）")
        else:
            tried.append((f"{slot.get('owner','')}/{slot.get('repo','')}", url, err))
            print(f"  ✗ 解析不到：{err}")
    return hits, tried


def run(cmd, check=False) -> bool:
    try:
        subprocess.run(cmd, check=check, stdout=None if check else subprocess.DEVNULL)
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


def progress(cmd):
    """把一条将执行的 git 命令打到 stdout（trace tool_calls 的原材料：哪个源不可达）。"""
    print("  $", " ".join(cmd))


def git_out(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p


def looks_like_sha(s: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{7,40}", (s or "").strip()))


def ref_aliases(ref: str):
    """ref 的写法变体（有序）：原样优先，其次 v 前缀容错（0.26.0 ↔ v0.26.0）。

    为什么必须有：issue/环境里写的是版本号（0.26.0），上游 tag 常是 v0.26.0。旧实现只按原样 fetch，
    失败后**静默**判"不匹配"并 exit 0——那是"agent 以为拿到了对应版本"的入口之一。
    """
    r = (ref or "").strip()
    out = [r]
    if len(r) > 1 and r[0] in "vV" and r[1].isdigit():
        out.append(r[1:])
    elif r[:1].isdigit():
        out.append("v" + r)
    return out


def refs_equivalent(a: str, b: str) -> bool:
    """两个 ref 写法是否指同一版本（仅用于本地复用的**容错匹配**；命中会明确打印出来）。"""
    a, b = (a or "").strip(), (b or "").strip()
    return a == b or a in ref_aliases(b) or b in ref_aliases(a)


def ls_remote(url: str, patterns):
    """`git ls-remote <url> <patterns...>` → (refname→sha 字典, 错误串)。(None, err) = 源不可达。"""
    p = git_out(["git", "ls-remote", url, *patterns])
    if p.returncode != 0:
        text = (p.stderr or p.stdout or "").strip()
        return None, text.splitlines()[-1] if text else "ls-remote 失败"
    have = {}
    for line in p.stdout.splitlines():
        if "\t" not in line:
            continue
        sha, name = line.split("\t", 1)
        have[name.strip()] = sha.strip()
    return have, ""


def remote_head(url: str):
    """远程默认分支 → ({kind: default, name, sha, requested}, "")；失败 (None, 原因)。"""
    p = git_out(["git", "ls-remote", "--symref", url, "HEAD"])
    if p.returncode != 0:
        return None, "ls-remote --symref 失败（源不可达）"
    branch, sha = "", ""
    for line in p.stdout.splitlines():
        if line.endswith("\tHEAD"):
            if line.startswith("ref:"):
                branch = line.split()[1].removeprefix("refs/heads/")
            else:
                sha = line.split("\t", 1)[0]
    if not sha:
        return None, "远程 HEAD 不可解析"
    return {"kind": "default", "name": branch or "HEAD", "sha": sha, "requested": ""}, ""


def resolve_ref(url: str, ref: str):
    """把用户给的 ref 解析为 {kind, name, sha, requested}；解析不了 → (None, 原因)。

    tag 优先于同名分支（源码分析几乎总是钉 tag）；annotated tag 取 `^{}`（提交）而非 tag 对象。
    """
    r = (ref or "").strip()
    if not r:
        return remote_head(url)
    if looks_like_sha(r):
        return {"kind": "commit", "name": r.lower(), "sha": r.lower(), "requested": r}, ""
    pats = []
    for name in ref_aliases(r):
        pats += [f"refs/tags/{name}", f"refs/tags/{name}^{{}}", f"refs/heads/{name}"]
    have, err = ls_remote(url, pats)
    if have is None:
        return None, err
    for name in ref_aliases(r):
        tag, deref, br = f"refs/tags/{name}", f"refs/tags/{name}^{{}}", f"refs/heads/{name}"
        if deref in have:
            return {"kind": "tag", "name": name, "sha": have[deref], "requested": r}, ""
        if tag in have:
            return {"kind": "tag", "name": name, "sha": have[tag], "requested": r}, ""
        if br in have:
            return {"kind": "branch", "name": name, "sha": have[br], "requested": r}, ""
    return None, f"源可达但找不到「{r}」对应的 tag/分支（已试 v 前缀容错）"


def numeric_version(name: str):
    """tag/分支名里的前导数字版本 → (0, 26, 0)（`v0.26.0rc1` 与 `0.26.0` 都得到 (0,26,0)）。"""
    m = re.match(r"[vV]?(\d+(?:\.\d+)*)", (name or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def version_key(name: str):
    """**版本序**排序 key：v0.26.0rc1 > v0.9.2rc1（按字典序则相反）。"""
    parts = re.split(r"(\d+)", (name or "").lstrip("vV"))
    return [(1, int(p)) if p.isdigit() else (0, p) for p in parts if p != ""]


def available_tags(url: str):
    """该源的全部 tag（不在这里筛选——怎么给由 tag_hint 按请求的 ref 决定）。"""
    p = git_out(["git", "ls-remote", "--tags", url])
    if p.returncode != 0:
        return []
    return sorted({ln.split("\t", 1)[1].split("refs/tags/")[-1]
                   for ln in p.stdout.splitlines()
                   if "\t" in ln and "refs/tags/" in ln and not ln.rstrip().endswith("^{}")})


def tag_hint(ref: str, tags):
    """解析不到该 ref 时给**一行能照做**的提示 → str（无话说则空串）。

    真实世界发现（vllm-ascend）：0.26 系列只发了 rc，`v0.26.0` 不存在、真实 tag 是 `v0.26.0rc1`；
    而"按字典序取末 10 个"会把 `v0.26.0rc1` 埋在 `v0.9.x` 之后——最需要它的时候恰恰没给出来。
    所以先找**版本号相同**的（rc/后缀差异），再退到同 major.minor 系列，最后才是版本序最新若干。
    """
    if not tags:
        return ""
    base = numeric_version(ref)
    if base:
        same_num = sorted([t for t in tags if numeric_version(t) == base], key=version_key)
        if same_num:
            return f"版本号相同、只差后缀的可用 tag：{', '.join(same_num[:6])}（请求的 tag 本身不存在）"
        if len(base) >= 2:
            series = sorted([t for t in tags if numeric_version(t)[:2] == base[:2]], key=version_key)
            if series:
                return (f"同 {'.'.join(str(x) for x in base[:2])} 系列的可用 tag："
                        f"{', '.join(series[-6:])}")
    return f"该源版本序最新的 tag：{', '.join(sorted(tags, key=version_key)[-8:])}"


def head_sha(path: Path):
    p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(path),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def describe_head(path: Path) -> str:
    """人读用：精确 tag，否则短 hash。"""
    for args in (["describe", "--tags", "--exact-match"], ["log", "-1", "--format=%h"]):
        p = subprocess.run(["git"] + args, cwd=str(path),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout.strip()
    return "?"


def meta_path(version_dir: Path) -> Path:
    return version_dir / ".git" / META_NAME


def read_meta(version_dir: Path):
    try:
        return json.loads(meta_path(version_dir).read_text(encoding="utf-8"))
    except Exception:
        return None


def write_meta(version_dir: Path, meta: dict):
    write_text_lf(meta_path(version_dir), json.dumps(meta, ensure_ascii=False, indent=2) + "\n")


def version_token(res: dict) -> str:
    """版本目录名 = 解析后的 ref（tag/分支名原样，commit 用 sha-<12>）。"""
    if res["kind"] == "commit":
        return "sha-" + res["name"][:12]
    return str(res["name"]).replace("/", "__")


def iter_version_dirs(repo_dir: Path):
    """某仓库下已有的版本目录（排除临时克隆与点目录）。"""
    if not repo_dir.is_dir():
        return []
    return [d for d in sorted(repo_dir.iterdir())
            if d.is_dir() and not d.name.startswith(".") and (d / ".git").exists()]


def verify_version_dir(version_dir: Path):
    """**离线**核对一个版本目录 → (ok, 原因, meta)。不联网也能判"这个目录是不是那个版本"。

    依据是目录内 .git/src-fetch-meta.json 记录的实际 HEAD（克隆落地后回填），与当前 HEAD 对照——
    目录被外部 checkout 走、克隆半途被杀，都在这里被判出来，而不是被静默复用。
    """
    meta = read_meta(version_dir)
    head = head_sha(version_dir)
    if head is None:
        return False, "不是可用的 git 工作树（缺 .git 或仓库损坏）", meta
    if meta is None:
        return False, "无 src-fetch 版本标记（旧布局手工 clone 的目录？）——无法确认它是哪个版本", meta
    if head != str(meta.get("sha", "")):
        return False, (f"HEAD {head[:12]} 与标记的 {str(meta.get('sha', ''))[:12]} 不一致"
                       "（目录被外部改过/克隆未完成）"), meta
    return True, "", meta


def match_local_meta(meta, ref: str):
    """本地标记是否对应用户请求的 ref → "exact" | "sha" | "tolerant" | None。"""
    if not meta:
        return None
    r = (ref or "").strip()
    if not r:
        return "exact" if meta.get("ref_kind") == "default" else None
    if meta.get("ref_name") == r or meta.get("ref_requested") == r:
        return "exact"
    if looks_like_sha(r) and str(meta.get("sha", "")).startswith(r.lower()):
        return "sha"
    if refs_equivalent(str(meta.get("ref_name", "")), r):
        return "tolerant"
    return None


def find_local(repo_dir: Path, ref: str):
    """本地匹配该 ref 的版本目录 → [(dir, how, ok, 原因, meta)]。**不联网**。"""
    out = []
    for d in iter_version_dirs(repo_dir):
        meta = read_meta(d)
        how = match_local_meta(meta, ref)
        if how is None:
            continue
        ok, why, meta = verify_version_dir(d)
        out.append((d, how, ok, why, meta))
    return out


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def human_size(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024.0
    return f"{v:.1f} GB"


def mtime_date(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
    except OSError:
        return "?"


def cleanup_stale_tmp(repo_dir: Path):
    """顺手清掉半途被杀留下的临时克隆（超 TMP_STALE_SECONDS；best-effort，不报错）。"""
    if not repo_dir.is_dir():
        return
    for d in repo_dir.glob(TMP_PREFIX + "*"):
        try:
            if time.time() - d.stat().st_mtime > TMP_STALE_SECONDS:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def clone_into(url: str, res: dict, tmp: Path, depth: str) -> bool:
    """把对应版本浅克隆到 tmp（tmp 必须是不存在的路径）。

    `-c advice.detachedHead=false`：钉 tag 必然进 detached HEAD，而 git 那段"你在游离头指针上"的建议
    会混进 agent 看到的输出里（trace tool_calls 的噪声），让它看起来像出了岔子——这里去掉。
    """
    quiet = ["git", "-c", "advice.detachedHead=false"]
    if res["kind"] == "commit":
        cmd = [*quiet, "clone", "--depth", depth, url, str(tmp)]
        progress(cmd)
        if not run(cmd, check=True):
            return False
        cmd = ["git", "-C", str(tmp), "fetch", "--depth", depth, "origin", res["name"]]
        progress(cmd)
        if not run(cmd, check=True):
            return False
        cmd = [*quiet, "-C", str(tmp), "checkout", "--detach", res["name"]]
        progress(cmd)
        return run(cmd, check=True)
    cmd = [*quiet, "clone", "--depth", depth, "--branch", res["name"], url, str(tmp)]
    progress(cmd)
    return run(cmd, check=True)


def install_version(tmp: Path, target: Path, meta: dict):
    """临时克隆 → 版本目录（原子 rename；并发时失败者复用赢家）→ (结果, 说明)。"""
    write_meta(tmp, meta)
    if target.exists():
        ok, why, _ = verify_version_dir(target)
        shutil.rmtree(tmp, ignore_errors=True)
        return ("reused", "另一进程已产出该版本") if ok else ("conflict", why)
    try:
        os.rename(tmp, target)          # 同文件系统内原子；目标已存在则抛 OSError
    except OSError:
        ok, why, _ = verify_version_dir(target)
        shutil.rmtree(tmp, ignore_errors=True)
        return ("reused", "另一进程并发产出，已复用") if ok else ("conflict", why)
    return "installed", ""


def list_versions(cache_root: Path, only_repo: str = ""):
    """本地缓存清单：有哪些仓库、哪些版本（体积/时间/HEAD）。"""
    print(f"源码缓存：{cache_root}")
    if not cache_root.is_dir():
        print("  （还没有任何源码缓存）")
        return
    repos = []
    for org in sorted(p for p in cache_root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for repo in sorted(p for p in org.iterdir() if p.is_dir() and not p.name.startswith(".")):
            repos.append((f"{org.name}/{repo.name}", repo))
    if only_repo:
        key = norm_repo(only_repo).lower()
        tail = key.split("/")[-1]
        repos = [(name, p) for name, p in repos if name.lower() == key or name.split("/")[-1].lower() == tail]
    if not repos:
        print(f"  （没有匹配「{only_repo}」的仓库缓存）")
        return
    for name, repo_dir in repos:
        versions = iter_version_dirs(repo_dir)
        legacy = (repo_dir / ".git").exists()
        print(f"\n{name}  —— {len(versions)} 个版本" + ("  ⚠ 另有旧布局单检出" if legacy else ""))
        if not versions:
            print("  （无版本目录）")
        for d in versions:
            meta = read_meta(d)
            ok, why, _ = verify_version_dir(d)
            head = str((meta or {}).get("sha", ""))[:12] or str(head_sha(d) or "?")[:12]
            print(f"  {d.name:<24} {human_size(dir_size(d)):>9}  {mtime_date(d)}  HEAD={head}"
                  + ("" if ok else f"  ⚠ {why}"))
        if legacy:
            print(f"  ⚠ 旧布局单检出（{describe_head(repo_dir)}）：{repo_dir}/.git")
            print("    不参与版本复用、新版也不会动它；要留就手工 mv 进 <版本>/ 目录，否则删掉即可")


def prune_version(repo_dir: Path, ref: str) -> int:
    """手工删除某版本目录（无自动 GC：正在被别的 agent 分析的版本不能自己消失）。"""
    cands = [d for d in iter_version_dirs(repo_dir)
             if d.name == ref or match_local_meta(read_meta(d), ref)]
    if not cands:
        have = ", ".join(d.name for d in iter_version_dirs(repo_dir)) or "（无）"
        return die(EXIT_USAGE, f"本地没有匹配「{ref}」的版本目录（现有：{have}）", tail="✗ 未执行删除")
    if len(cands) > 1:
        return die(EXIT_USAGE, f"「{ref}」匹配到多个版本目录：{', '.join(d.name for d in cands)}——请用完整目录名",
                   tail="✗ 未执行删除")
    print(f"删除 {cands[0]}（{human_size(dir_size(cands[0]))}）")
    shutil.rmtree(cands[0])
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description="确定性获取对应版本的源码")
    ap.add_argument("repo", nargs="?", help="仓库标识（已知名 / org/repo；未知需 --url）")
    ap.add_argument("--ref", default="", help="版本 tag/commit（源码分析依赖对应版本；空 = 默认分支）")
    ap.add_argument("--url", default="", help="自定义/私有 clone URL（内网、未知仓库时提供；脚本不碰凭据）")
    ap.add_argument("--dest", default=None, help="本地缓存根目录（默认主检出 src-code/，见 --local）")
    ap.add_argument("--local", action="store_true", help="缓存根用当前检出（默认锚到主检出，跨 worktree 共享）")
    ap.add_argument("--force", action="store_true", help="本地目录版本不符/损坏时删掉重拉（否则非零退出）")
    ap.add_argument("--depth", default="1", help="clone 深度（默认浅拉 1，够 grep/读）")
    ap.add_argument("--list", action="store_true", help="列出已知仓库与 host")
    ap.add_argument("--list-versions", action="store_true", help="列出本地缓存的仓库与版本")
    ap.add_argument("--prune", action="store_true", help="删除 --ref 指定的本地版本目录（无自动 GC）")
    ap.add_argument("--find", nargs="?", const="", default=None, metavar="签名",
                    help="只知道报错签名、不知道在哪个仓时用：枚举组织仓 → 给候选 → 能唯一解析就自动取"
                         "（签名必填；枚举别的组织配 --org）")
    ap.add_argument("--org", default="cann", help="--find 枚举的组织（默认 cann）")
    ap.add_argument("--offline", action="store_true", help="--find 不联网：只按签名关键词表给候选")
    ap.add_argument("--self-test", action="store_true",
                    help="校验签名→候选仓匹配表（大小写/仓名/真实签名命中）；表坏了只会静默零候选")
    ap.add_argument("--root", default=None, help="仓库根目录（默认：本脚本上两级）")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.list:
        print("已知仓库 → 候选 source：")
        for key, (canonical, cands) in KNOWN_REPOS.items():
            print(f"  {key:24s} -> {canonical}  ({'; '.join(c for c, _ in cands)})")
        return EXIT_OK

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    # --dest 归一为绝对路径：契约是"stdout 末行 = 绝对路径"，相对路径会让调用方拼错地方
    explicit = Path(args.dest).expanduser().resolve() if args.dest else None
    cache_root, where = resolve_src_code(root, explicit=explicit, local=args.local)

    if args.list_versions:
        print(f"（{WHERE_LABEL_SRC.get(where, where)}）")
        list_versions(cache_root, args.repo or "")
        return EXIT_OK

    # `--find` 的签名是**显式值**，不占「仓名」这个位置参数：`nargs="?"` 会把
    # `--find --offline "签名"` 里的 "签名" 当成位置参数 repo（实测：仓='/签名'、签名空 →
    # 走"去 GitHub 试这个仓名"），把不带签名的调用变成猜地址。写错命令行不该有静默语义。
    find_sig = args.find or ""
    if not args.repo and args.find is None:
        return die(EXIT_USAGE, "未指定 repo（--list 看已支持仓库，--list-versions 看本地缓存）")

    canonical, cands = lookup(args.repo or "")
    if args.url:
        cands = [("custom", {"url": args.url})]
        canonical = canonical or norm_repo(args.repo or "")
        print(f"自定义 URL：{args.url}")

    # 源码位置发现：只知道签名、不知道在哪个仓时，先枚举组织仓给候选，再逐个试 ref。
    # 只有一个能解析 → 直接按它取（证据是"版本对得上"）；≥2 → 交回工程/工程师选，不猜。
    if args.find is not None and not find_sig:
        return die(EXIT_USAGE, "--find 必须给报错签名（例：--find \"HcclAllReduce failed\"）——"
                               "没有签名就没有候选判据（枚举整个组织等于把 82 仓全表丢给调用方）")
    if args.find is not None and cands is None and not args.url:
        found, note = org_repo_catalog(args.org, find_sig, offline=args.offline)
        if found:
            print_candidates(args.org, found, note, args.ref,
                             header=f"签名「{find_sig}」的候选源码仓")
        # 显式给了仓名 → **以它为准**（人的指定比脚本的候选更权威；静默改用另一个仓
        # 会让判断链断在这里，而输出看起来一切正常）。候选表照打，作为"脚本本来会猜哪个"的对照。
        if args.repo:
            given = norm_repo(args.repo)
            if "/" in given:                     # org/repo 形态：尊重给的 org，不再套 --org
                owner, rname = given.split("/", 1)
                candidates = [("gitcode", {"owner": owner, "repo": rname}),
                              ("github", {"owner": owner, "repo": rname})]
            else:                                # 裸仓名：按 --org 组织下试，再回退到 GitHub 同名仓
                candidates = [("gitcode", {"owner": args.org, "repo": given}),
                              ("github", {"owner": args.org, "repo": given})]
            canonical, cands = f"{candidates[0][1]['owner']}/{candidates[0][1]['repo']}", candidates
            why = f"签名没命中已知层，按你给的仓名试：{canonical}" if not found else \
                  f"以你给的仓名 {canonical} 为准（候选表仅作对照；不对就按候选编号重跑）"
            print(why + ("（「%s」没进已知表也没有 /——按组织仓名处理）" % args.repo
                         if "/" not in given else ""))
        elif not found:
            return die(EXIT_REF_UNRESOLVED,
                       f"签名「{find_sig}」在 {args.org} 里没命中任何候选仓"
                       + (f"；{note}" if note else ""))
        else:
            if args.offline and len(found) == 1:
                # `--offline` 是「不联网」的承诺：唯一候选也不能顺手去联网核对 ref 再拉取
                # （那样断网现场会得到一条拉取失败，看起来像"上游没有这个仓"）。
                # 只有本地已核对通过的同版本才能复用，否则如实说清楚要什么。
                slot = {"owner": args.org, "repo": found[0][0]}
                local = find_local(cache_root / args.org / found[0][0], args.ref)
                ok_local = [d for d, _how, ok, _why, _m in local if ok]
                if ok_local:
                    print(f"离线模式：本地已有核对通过的版本 → 复用 {ok_local[0]}")
                    canonical, cands = f"{args.org}/{found[0][0]}", [("gitcode", slot)]
                else:
                    return die(EXIT_REF_UNRESOLVED,
                               f"离线模式只给候选、不拉取：签名唯一命中 {args.org}/{found[0][0]}，"
                               f"但本地没有它的「{args.ref or '(默认分支)'}」缓存。"
                               f"去掉 --offline 可按该候选拉取；或先确认它是哪个仓再拉")
            only_fallback = (len(found) == 1
                             and is_fallback_candidate(args.org, find_sig, found[0][0]))
            if len(found) == 1 and not only_fallback:
                slot = {"owner": args.org, "repo": found[0][0]}
                canonical, cands = f"{slot['owner']}/{slot['repo']}", [("gitcode", slot)]
                print(f"唯一候选 → {canonical}")
            elif only_fallback:
                return die(EXIT_REF_UNRESOLVED,
                           f"签名只命中到「{args.org}/{found[0][0]}」这一层的**公共前缀**"
                           f"（没有判别词：算子名/接口名）——它能证明是这一层，不能证明就是这个仓。"
                           f"按报错栈里的算子名/接口名重试 `--find`，或问工程师那个报错在 CANN "
                           f"安装目录里落在哪个子目录；确认是它再跑 "
                           f"`python3 scripts/src_fetch.py {args.org}/{found[0][0]} --ref {args.ref}`")
            else:
                cds = [("gitcode", {"owner": args.org, "repo": r}) for r, _w, _s in found]
                hits, tried = resolve_across_candidates(cds, args.ref)
                if not hits:
                    print("  没有候选能解析出这个 ref——候选里选一个给准确版本，或让工程师报出"
                          "CANN 安装目录下的子目录名：", file=sys.stderr)
                    for repo, url, err in tried:
                        print(f"    {repo}: {err}", file=sys.stderr)
                    return die(EXIT_REF_UNRESOLVED,
                               f"{len(found)} 个候选都没有 ref「{args.ref or '(默认分支)'}」")
                if len(hits) == 1:
                    slot = hits[0][1]
                    canonical, cands = f"{args.org}/{slot['repo']}", [hits[0][:2]]
                    print(f"唯一能解析该 ref 的候选 → {canonical}（按它取）")
                else:
                    names = "、".join(f"{args.org}/{c[1]['repo']}" for c in hits)
                    return die(EXIT_REF_UNRESOLVED,
                               f"{len(hits)} 个候选都有 ref「{args.ref or '(默认分支)'}」——"
                               f"同名 tag 不足以定位，**不能替人选**：{names}。"
                               f"按报错栈的命名空间定一个，再跑 `python3 scripts/src_fetch.py "
                               f"{args.org}/<repo> --ref {args.ref}`；"
                               f"或问工程师那个报错在 CANN 安装目录里落在哪个子目录")

    if cands is None:
        if "/" in canonical:
            cands = [("github", {"owner": canonical.split("/")[0], "repo": canonical.split("/")[1]})]
            print(f"未知仓库，默认走 GitHub：{canonical}")
        else:
            return die(EXIT_USAGE, f"未知仓库「{args.repo}」（无 / 且不在已知表）——给 --url 或 org/repo")

    org, repo = canonical.split("/", 1)
    repo_dir = cache_root / org / repo

    if args.prune:
        if not args.ref:
            return die(EXIT_USAGE, "--prune 需要 --ref 指明删哪个版本（--list-versions 看现有版本）", tail="✗ 未执行删除")
        if not repo_dir.is_dir():
            return die(EXIT_USAGE, f"本地没有该仓库的缓存：{repo_dir}", tail="✗ 未执行删除")
        return prune_version(repo_dir, args.ref)

    # ① 本地优先（**不联网**）：版本目录名 + 目录内标记就是答案
    local = find_local(repo_dir, args.ref)
    for d, how, ok, why, meta in local:
        if ok:
            note = "（按 v 前缀容错匹配）" if how == "tolerant" else ""
            print(f"复用 {d}（{meta.get('ref_kind')} {meta.get('ref_name')}，HEAD 已核对{note}）")
            print(f"缓存：{describe_src(cache_root, where)}")
            print(str(d))
            return EXIT_OK
    bad_local = [(d, why) for d, _how, ok, why, _m in local if not ok]

    # ② 需要联网：解析 ref（逐候选源）；解析不到就非零退出，并给可用 tag
    resolved, url_used, failures = None, "", []
    for host, slot in cands:
        url = slot["url"] if host == "custom" else clone_url(host, slot["owner"], slot["repo"])
        print(f"尝试解析 {url} 的 ref「{args.ref or '(默认分支)'}」")
        res, err = resolve_ref(url, args.ref)
        if res:
            resolved, url_used = res, url
            break
        failures.append(f"{url}: {err}")
        hint = tag_hint(args.ref, available_tags(url))
        if hint:
            print(f"    {hint}")

    if resolved is None:
        for line in failures:
            print(f"  ✗ {line}", file=sys.stderr)
        if bad_local:
            d, why = bad_local[0]
            return die(EXIT_LOCAL_MISMATCH,
                       f"本地有该版本的目录但核对不通过：{d}（{why}）——"
                       "确认它就是该版本就用 --force 重拉（会删掉该目录）")
        return die(EXIT_REF_UNRESOLVED,
                   f"未能解析 ref「{args.ref or '(默认分支)'}」：tag 名可能与预期不同（已自动容错 v 前缀）。"
                   "按上面列出的可用 tag 重试，或让用户确认版本号。"
                   "**不要用 web 搜索代替取对应版本源码**")

    # ③ 版本目录已在（token 命中但标记不符/损坏）
    target = repo_dir / version_token(resolved)
    if target.exists() and not (target / ".git").exists():
        if not any(target.iterdir()):     # 空壳目录不携带任何信息，直接清掉
            print(f"清理空目录 {target}（无 .git、也无内容）")
            shutil.rmtree(target)
    if target.exists():
        ok, why, _ = verify_version_dir(target)
        if ok:
            print(f"复用 {target}（本地已有该版本，HEAD 已核对）")
            print(f"缓存：{describe_src(cache_root, where)}")
            print(str(target))
            return EXIT_OK
        if not args.force:
            return die(EXIT_LOCAL_MISMATCH,
                       f"本地已有 {target} 但核对不通过：{why}——"
                       "确认它就是该版本就加 --force 重拉（会删掉该目录后重新克隆）")
        print(f"--force：删除核对不通过的 {target}")
        shutil.rmtree(target)

    # ④ 拉取：临时目录 → 校验 → 原子 rename 进版本目录
    cleanup_stale_tmp(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)
    tmp = repo_dir / f"{TMP_PREFIX}{version_token(resolved)}-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"拉取 {resolved['name']}（{resolved['kind']}）→ {target}")
    if not clone_into(url_used, resolved, tmp, args.depth):
        shutil.rmtree(tmp, ignore_errors=True)
        return die(EXIT_FETCH_FAILED,
                   f"拉取失败：{url_used}（ref {resolved['name']}）——网络/私网不可达时用 --url 给可达地址；"
                   "注意：本地已有的**其他**版本仍在，但该版本确实没取到")
    head = head_sha(tmp)
    expect = str(resolved["sha"])
    ok_sha = bool(head) and (head == expect or (resolved["kind"] == "commit" and head.startswith(expect)))
    if not ok_sha:
        shutil.rmtree(tmp, ignore_errors=True)
        return die(EXIT_FETCH_FAILED,
                   f"拉到的 HEAD（{str(head)[:12]}）与 {resolved['name']} 解析出的提交（{expect[:12]}）不一致——"
                   "拒绝把它当成本版本源码")
    meta = {
        "repo": canonical, "url": url_used, "ref_requested": args.ref,
        "ref_kind": resolved["kind"], "ref_name": resolved["name"],
        "sha": head, "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }
    result, why = install_version(tmp, target, meta)
    if result == "conflict":
        return die(EXIT_LOCAL_MISMATCH,
                   f"目标目录 {target} 在本次拉取期间被其他进程产出且核对不通过：{why}（重试或 --force）")
    print(f"{'产出' if result == 'installed' else '复用'} {target}"
          + (f"（{why}）" if why else "（新增版本；其他版本目录保留不动）"))
    print(f"缓存：{describe_src(cache_root, where)}")
    print(str(target))
    return EXIT_OK


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
