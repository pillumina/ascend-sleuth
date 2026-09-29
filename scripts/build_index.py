#!/usr/bin/env python3
# build_index.py —— 生成索引的**两个面**（Tier 2 阶段一）
#
#   knowledge/_index.yaml              总表（机器面）：嵌套 YAML，面板 / 排序器 / 门按字段读它
#   knowledge/_index/<ns>__<cat>.list  读侧视图（人/agent 面）：**一行一条 case** 的文本
#
# 设计决策见 docs/adr/0002-retrieval-no-rag-lightweight-index.md（不上向量检索、索引由生成器产）
# 与 docs/adr/0004-capacity-governance.md（格子容量 + 本文件末尾那节读侧形态与上限口径）：
#   - 两个面都是生成物，提交进 git，随 case 变更一起 diff / 评审
#   - 把"阶段一只加载索引字段"从 prompt 纪律变成结构保证：阶段一 = 读命中 (ns×category)
#     的那一份读侧视图（类分片按 category、ns 分片兜底，均由本脚本生成）
#   - 读侧视图为什么不是 YAML（2026-09-29，EV-2026-160）：阶段一由人/agent 读，YAML 的缩进、
#     引号、字段名、嵌套在百余条规模上要多花 40% token（同一格实测 23449 → 14154），
#     而那些字符对判断没有贡献。信息不丢：字段一一对应，只有 `file`（可由 id 推出，全库
#     实测零例外）与 `hash`（只服务新鲜度门）不进读侧。
#   - 每条 case 记 content hash 在总表里，--check 校验新鲜度（groom 每次跑，可挂 CI）
#
# 一致性门是**覆盖检查**，不是逐字节相同（2026-09-22；起因：并发提交时生成物天天撞）：
#   `--check`     每条 case 的读侧行与总表条目都在、且与 case 内容对得上；
#   `--canonical` 附带「与重新生成一遍逐字节相同」的自检——**不作门**，只在归一化后确认用。
#   为什么门不能是逐字节：生成物随 PR 提交，两个人并发时文件会以「内容齐全、顺序不同」
#   的形态合到一起，那是**对的**；逐字节把它判红，就逼人再跑一遍收尾命令。
#   头注不含数字（条数 / 容量 / 日期）：数字进 git 就会在并发合并时撞行、或漂移成错的数。
#   要数字现算：`python3 scripts/index_counts.py`；要读入成本现算：`scripts/index_read_cost.py`。
#
# 两个面**故意都不配 merge=union**：总表还是嵌套 YAML（行级合并会拼坏），读侧视图虽然已是
# 平铺行、但同一格的并发仍会在总表上撞一次——所以冲突动作没变：重跑本脚本（机械、无判断）。
# 若将来把总表也压成平铺列表，两处才谈得上开 union（见 .gitattributes 的注释）。
#
# 用法：
#   python3 scripts/build_index.py              # 重新生成总表 + 全部读侧视图（改动后跑它，都提交）
#   python3 scripts/build_index.py --check      # 门：覆盖检查（有问题 exit 1，报错给重跑命令）
#   python3 scripts/build_index.py --check --canonical   # 附带逐字节自检（归一化后确认用）
#
# 依赖：PyYAML（pip install pyyaml）。_archive/ 下的退休 case 不进活跃索引
# （复活检查由 groom 直接读目录完成）。

import argparse
import hashlib
import re
import sys
from pathlib import Path

from _lexical import tokens_of
from _stdio import write_text_lf

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：pip install pyyaml")

# ADR-0004 容量治理：soft_cap 触发拆分评估，hard_cap 强制拆分。
# 均为初始估计，服从 roadmap「参数治理」——metrics 实测后按理论 §4.4 复核。
SOFT_CAP = 30
HARD_CAP = 60


def case_hash(path: Path) -> str:
    # 归一 CRLF 后再哈希：本哈希**按字节**算，而 Windows 上文件可能被写成 CRLF。
    # 不归一的话，Windows 重建索引并提交后，Linux CI 检出的是 LF → 哈希对不上 →
    # `--check` 判 STALE（红），而失败信息只说"过期"，看不出是行尾所致。
    # LF 文件归一后不变，故对已有索引是无操作。
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]


# 签名面字面量（EV-2026-111）：从 quickly_check 的 expected 正则里挑**纯字面量**分支放进行内，
# 让阶段一能在不读 case 本体的情况下按"报错原文命中"排序（此前行内只有 score，排序只能按分数，
# 而实测 score 与相关性无关：25 条 fixture 上 top3 只有 5/25）。
_SIG_RE = re.compile(r"^[\w.\- ]{5,32}$")


def sig_literals(case) -> list:
    """quickly_check.expected 的字面量分支 → 去重、上限 6 条。

    只收纯字面量（字母/数字/下划线/点/连字符/空格，5~32 字符）：带正则元字符的分支
    （`\\(\\d+\\)`、`.*`）在输入里匹配不到字面量，放进行里只是噪音。取不到就返回空。
    """
    out = []
    for group in (case.get("quickly_check") or {}).values():
        exp = str((group or {}).get("expected") or "")
        if not exp.startswith("regex:"):
            continue
        for alt in exp[len("regex:"):].split("|"):
            alt = alt.strip()
            if _SIG_RE.match(alt) and alt not in out:
                out.append(alt)
    return out[:6]


def _range_str(v) -> str:
    """range / cann / hdk 这类取值 → 可读串。**字符串要原样用，不能逐字符 join**。

    为什么要防（2026-09-29 实测）：schema 期望这几项是列表，但库里有一条 case 把 `cann` 写成了
    字符串 `"<9.1.0.beta2"`——`",".join("<9.1.0.beta2")` 会把它拆成
    `<,9,.,1,.,0,.,b,e,t,a,2` 写进索引行，软匹配时读的人只会看到一串乱码。
    这里只让**渲染**健壮；那条 case 的字段类型属 compat 面（高风险），不在本次改动里改。
    """
    if isinstance(v, str):
        return v.strip()
    return ",".join(str(x) for x in (v or []))


def compat_summary(compat) -> str:
    """compat 列表压成一行可 grep 的概要："fw A >=1.0,<2.0; fw B >=3.0 (cann:>=8.0)" """
    if not compat:
        return ""
    parts = []
    for c in compat:
        fw = c.get("framework", "?")
        rng = _range_str(c.get("ranges"))
        extra = []
        if c.get("cann"):
            extra.append("cann:" + _range_str(c["cann"]))
        if c.get("hdk"):
            extra.append("hdk:" + _range_str(c["hdk"]))
        s = f"{fw} {rng}".strip()
        if extra:
            s += " (" + "; ".join(extra) + ")"
        parts.append(s)
    return "; ".join(parts)


def quickly_check_summary(qc) -> dict:
    """只保留阶段一过滤所需字段：command_template + expected（rank_selector 等细节留在全量 body）"""
    out = {}
    for key in ("primary", "fallback"):
        block = (qc or {}).get(key)
        if not block:
            continue
        out[key] = {
            "command": block.get("command_template", ""),
            "expected": block.get("expected", ""),
        }
    return out


def collect(root: Path):
    """扫 knowledge/**/*.yaml → {namespace: {category: [索引条目, ...]}}
    ADR-0004：目录按 (framework × category) 分层；索引按格子分组，
    格子是阶段一实际被扫的单元，cap 语义精确到格子。"""
    namespaces = {}
    kdir = root / "knowledge"
    for path in sorted(kdir.rglob("*.yaml")):
        rel = path.relative_to(kdir)
        if rel.parts[0] in ("_archive", "_index") or path.name == "_index.yaml":
            continue
        # 路径一律用 POSIX 分隔符（Windows 上 str(Path(...)) 会给反斜杠，
        # 生成物与 Linux 不一致 → --check 永久红、分片名也会被当成子目录）
        ns = "/".join(rel.parts[:-1])
        # ADR-0004：目录按 (framework × category) 分层，但 ns 停在工作负载层
        # （triage 路由到框架，category 是正交轴的格子维度，从 case 字段取）
        # inference 与 training 对称折叠（2026-08-31 修复：此前只折叠 inference，
        # training 保留三级导致面板渲染出重复 category 标签）
        parts = rel.parts
        if len(parts) >= 3 and parts[0] in ("inference", "training") and parts[2] != "platforms":
            ns = "/".join(parts[:2])
        # common/ 无框架层：common/<category>/<case>.yaml → ns 停在 common（2026-09-09，
        # 首批跨框架共性 case 落 common/ 时引入；此前 common/ 为空，未触发该分支）
        elif len(parts) >= 2 and parts[0] == "common":
            ns = "common"
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for case in doc.get("cases", []):
            category = case.get("category", "")
            # 三分类强制（废弃 other）：非法 category 直接红——路由层依赖 category 分发，
            # other 会变成不可达格子（2026-08 重分类 5 条 other 的教训）
            if category not in CATEGORIES:
                raise ValueError(
                    f"{path}: case {case.get('id', '?')} category {category!r} 非法"
                    "（三分类强制：interrupt / precision / performance，无 other）"
                )
            namespaces.setdefault(ns, {}).setdefault(category, []).append({
                "id": case.get("id", ""),
                # F5 行宽压缩（EV-2026-030）：title 截 160、platforms 移除、tags 截 6
                "title": (case.get("title", "")[:160] + ("…" if len(case.get("title", "") or "") > 160 else "")),
                "category": category,
                "tags": (case.get("tags") or [])[:6],
                "compat": compat_summary(case.get("compat")),
                "confidence": {
                    # ADR-0004 修正：索引只保留排序所需的 score；
                    # hits/misdiagnoses 是学习环动态字段（Beta 后验），留在 case 本体，
                    # 由 groom 置信度重算读取，不进入检索视图（避免学习环每次更新全量重建索引）。
                    "score": (case.get("confidence") or {}).get("score"),
                },
                # F2 行瘦身（EV-2026-023）：索引只留 symptoms 首条摘要（~120 字）作阶段一
                # 过滤；完整 symptoms/quickly_check 移 case 本体，阶段二加载候选后验证。
                "symptoms": [
                    (s[:120] + ("…" if len(s) > 120 else ""))
                    for s in (case.get("symptoms") or [])[:1]
                ],
                # EV-2026-111：签名面字面量 + token 集合入行——阶段一按"报错原文命中 → token 交集
                # → score"排序的唯一依据。实测（25 条 fixture）：只有 score 时 top3=5；只加 sig=10；
                # sig+tok=13（中位名次 20 → 3）。tok 取全部症状的 token（上限 12），因为判别信号
                # 常只在第二条症状里，而 symptoms 摘要只留首条 120 字（实测后者会漏掉一半信号）。
                "sig": sig_literals(case),
                "tok": sorted(tokens_of(
                    str(case.get("title", "")) + " "
                    + " ".join(str(x) for x in (case.get("symptoms") or []))
                ))[:12],
                "file": (Path("knowledge") / rel).as_posix(),
                "hash": case_hash(path),
            })
    return namespaces


def shard_slug(ns: str) -> str:
    """namespace → 读侧视图的文件名（/ → __，避免目录层级）。扩展名是 `.list`：**它不是 YAML**。"""
    return ns.replace("/", "__") + ".list"


SHARD_SUFFIX = ".list"
LEGACY_SHARD_SUFFIX = ".yaml"      # 2026-09-29 前的分片扩展名（读侧换成文本行后回收）


def shard_path(root: Path, ns: str) -> Path:
    return root / "knowledge" / "_index" / shard_slug(ns)


# ---------------------------------------------------------------------------
# 读侧视图（阶段一实际读的那份）——一行一条 case
# ---------------------------------------------------------------------------
# 字段与总表行一一对应，缺省字段整段省略（省行宽）；`category` 只在 ns 兜底分片里才有区分度，
# 但两个面共用同一套投影，冗余三个 token 换"一处定义"。`file` 与 `hash` 不进读侧：
# 前者可由 id 推出（`knowledge/<ns>/<category>/<id>.yaml`，全库实测零例外），后者只服务新鲜度门。
READ_FIELDS = ("id", "category", "title", "symptoms", "sig", "tok", "compat", "tags", "score")
SEP = " | "


def _cell(v) -> str:
    """值 → 单行、且不含行内分隔符的字符串。

    `|` 折成 `¦`：它同时是字段分隔符，出现在值里会把一行切成两截（解析回来就错了）。
    换行折成空格：一行一条是硬约束（grep 命中即整条）。
    """
    return " ".join(str(v or "").split()).replace("|", "¦")


def _trunc(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


def compact_line(row) -> str:
    """一条 case 的索引行 → 读侧视图的一行（`字段: 值`，按 READ_FIELDS 顺序）。

    截断口径与总表行一致（title 160、症状首条 120，见 collect()）：两个面读同一批字段，
    只是排版不同——读侧的判断证据（`sig` 报错字面量、`tok` 关键词、`tags`、`compat`）一个不少。
    """
    score = (row.get("confidence") or {}).get("score")
    fields = [
        ("id", _cell(row.get("id"))),
        ("category", _cell(row.get("category"))),
        ("title", _trunc(_cell(row.get("title")), 160)),
        ("symptoms", _trunc(_cell((row.get("symptoms") or [""])[0]), 120)),
        ("sig", _cell("; ".join(map(str, row.get("sig") or [])))),
        ("tok", _cell("; ".join(map(str, row.get("tok") or [])))),
        ("compat", _cell(row.get("compat"))),
        ("tags", _cell("; ".join(map(str, row.get("tags") or [])))),
        ("score", "" if score is None else str(score)),
    ]
    return SEP.join(f"{k}: {v}" for k, v in fields if v)


def parse_read_line(line: str) -> dict:
    """读侧视图的一行 → {字段: 值}（缺省字段不在结果里）。

    只认「关键词: 值」按首冒号切分：值里的 `|` 在生成时已折成 `¦`，所以字段一定是 SEP 切出来的；
    值里自带冒号（标题、报错原文都可能有）也不影响——切的是每段的第一个 `: `。
    只解析 READ_FIELDS 里的键，别的段落静默跳过（手改进来的杂质不该被当成字段）。
    """
    out = {}
    for part in line.split(SEP):
        k, sep, v = part.partition(": ")
        if sep and k in READ_FIELDS:
            out[k] = v
    return out


def render_shard(ns, cells) -> str:
    # 类分片（ns 含 "__"）与 ns 分片共用本渲染；头注区分加载语义：
    # category 已定 → diagnose 只读类分片（F4 EV-2026-025）；category 未定/缺失 → 回退 ns 分片（F1 EV-2026-022）
    is_cat = "__" in ns
    proto = (
        "# 阶段一加载协议（F1 EV-2026-022 + F4 EV-2026-025）：category 已定时 diagnose 只读命中"
        " (namespace×category) 的类分片，不读整库总表。"
        if is_cat
        else "# 阶段一加载协议（F1 EV-2026-022）：category 未定 / 类分片缺失时 diagnose 回退读本"
        " namespace 分片，不读整库总表。"
    )
    header = "\n".join([
        "# GENERATED FILE —— 阶段一读侧视图（一行一条 case），不要手改。",
        "# 由 scripts/build_index.py 生成、随 PR 提交；字段顺序：" + " / ".join(READ_FIELDS),
        "# 为什么不是 YAML：这份东西由人/agent 读，缩进/引号/字段名/嵌套要多花四成 token（同信息）。",
        "# file 省略（= knowledge/<ns>/<category>/<id>.yaml，全库实测零例外）；hash 只在总表（门用）。",
        "# 软匹配照旧：compat 不符只降置信度、不排除；sig 是报错字面量（逐字命中即强候选）、tok 是关键词。",
        "# 本文件**故意没配 merge=union**：同一格并发仍会在总表上撞一次——重跑 `python3 scripts/build_index.py`。",
        proto,
        "# 本分片：" + ns,
        "",
    ])
    lines = [compact_line(r) for cat in cells for r in cells[cat]]
    return header + "\n".join(lines) + ("\n" if lines else "")


def shard_dirty(root: Path, ns, cells) -> list:
    """返回过期/缺失分片（[] = 新鲜）。"""
    p = shard_path(root, ns)
    if not p.exists():
        return [(ns, "(分片缺失)")]
    if p.read_text(encoding="utf-8") != render_shard(ns, cells):
        return [(ns, "(分片过期)")]
    return []



def render(namespaces) -> str:
    header = "\n".join([
        "# GENERATED FILE —— 由 scripts/build_index.py 生成，不要手改。",
        "# 随 PR 提交。本文件**故意没配 merge=union**（嵌套结构做行级合并会拼坏 YAML，见 .gitattributes）：",
        "# 两人在同一格并发会撞一次，解决动作是重跑 `python3 scripts/build_index.py`（机械、无判断）。",
        "# 阶段一加载协议：本文件是总表（兜底 + 跨库比对）；diagnose 只读命中的最小分片",
        "# （knowledge/_index/<ns>__<category>.yaml；category 未定回退 <ns>.yaml），候选 ≤5 过滤后",
        "# 按 file 字段定位做阶段二全量加载。",
        "# 本文件**不写数字**（条数 / 容量 / 日期）：数字一进 git，两人并发合并时要么撞同一行、",
        "# 要么漂移成错的数。要看数字就现算：`python3 scripts/index_counts.py`",
        "# （容量治理的格子口径见该脚本与 docs/adr/0004）。",
        "# 一致性门是**覆盖检查**（每条 case 的索引行都在、且与 case 内容对得上），不是逐字节相同——",
        "# 逐字节的门会把「两边各加一条、顺序与重新生成不同」的、内容正确的文件判红。要归一化就重跑一次生成器。",
        "# `--canonical` 是那个「重跑后应当逐字节相同」的自检，供收尾/排查用，不作门。",
        "",
    ])
    body = yaml.safe_dump(
        {"namespaces": {k: namespaces[k] for k in sorted(namespaces)}},
        allow_unicode=True, sort_keys=False, default_flow_style=False, width=100,
    )
    return header + body


def stale_entries(root: Path, namespaces):
    """兼容薄壳：只取 hash 层的过期（[(ns, id, file)]）。新代码用 coverage_problems。"""
    problems = coverage_problems(root, namespaces)
    if problems is None:
        return None
    out = []
    for p in problems:
        if "过期" in p or "库里没有" in p or "不可读" in p:
            out.append(("-", p.split("：", 1)[-1].split("（")[0], p))
    return out


def shard_rows(root: Path):
    """已提交的读侧视图 → ({case id: 行原文}, broken)。

    比对单位是**整行原文**（不是解析出来的字段）：门要问的是"这一行是不是生成器会写的那一行"，
    逐字段解析只在需要时做（`parse_read_line`）。broken 收集三类"不能挑一份信"的情况：
    ① 文件里有 git 冲突标记；② 旧形态（`.yaml`）分片还没回收；③ 同一条 case 在两片里行不同。
    """
    rows, broken = {}, []
    shard_dir = root / "knowledge" / "_index"
    for legacy in sorted(shard_dir.glob(f"*{LEGACY_SHARD_SUFFIX}")):
        broken.append(f"{legacy.name}: 旧形态分片（读侧视图现在是 `.list` 文本行）——"
                      "重跑 `python3 scripts/build_index.py` 回收")
    for p in sorted(shard_dir.glob(f"*{SHARD_SUFFIX}")):
        raw = p.read_text(encoding="utf-8")
        if any(m in raw for m in ("<<<<<<<", ">>>>>>>")):
            broken.append(f"{p.name}: 有 git 冲突标记——重跑 `python3 scripts/build_index.py`（生成物，不必手判留哪份）")
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cid = parse_read_line(line).get("id")
            if not cid:
                broken.append(f"{p.name}: 有一行解析不出 id（读侧视图是 `字段: 值 | …`）——"
                              f"重跑 `python3 scripts/build_index.py`：{line[:60]}")
                continue
            if cid in rows and rows[cid] != line:
                broken.append(f"{p.name}: {cid} 的行与别的分片不一致——有分片没重建，重跑 `python3 scripts/build_index.py`")
            rows[cid] = line
    return rows, broken


def shard_lines(root: Path):
    """兼容薄壳：只取行层（[{id: 行原文}, broken]）。"""
    return shard_rows(root)


def duplicate_ids(root: Path):
    """(文件名, id, 次数)：同一条 case 在一个索引文件里出现多次。

    为什么单列：行级合并/重复 rebase 会把同一段**原样保留两份**（内容完全相同 → git 不报冲突，
    行比对也一致），只按 id 建字典的话第二份被静静吃掉——文件里那条重复就一直留着。
    两个面的记法不同：总表是 YAML 缩进条目（`- id: X`），读侧视图是 `id: X | …` 打头的行。
    """
    out = []
    shard_dir = root / "knowledge" / "_index"
    files = [root / "knowledge" / "_index.yaml"] + sorted(shard_dir.glob(f"*{SHARD_SUFFIX}"))
    for p in files:
        if not p.exists():
            continue
        seen = {}
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if p.suffix == SHARD_SUFFIX:
            for line in text.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    cid = parse_read_line(line).get("id")
                    if cid:
                        seen[cid] = seen.get(cid, 0) + 1
        else:
            # 条目是缩进的（总表里还多一层），所以不能用 ^- id:
            for cid in re.findall(r"^\s*- id:\s*(\S+)", text, re.M):
                seen[cid] = seen.get(cid, 0) + 1
        for cid, n in sorted(seen.items()):
            if n > 1:
                out.append((p.name, cid, n))
    return out


CATEGORIES = ("interrupt", "precision", "performance")


def _category_dir_of(rel: Path):
    """case 文件所在目录里**表达性质**的那一层（没有 → None）。

    两层形态（与 collect() 的 ns 口径同源）：
      common/<性质>/a.yaml                → parts[1]
      <负载类型>/<框架>/<性质>/a.yaml      → parts[2]（`platforms/` 是另一层语义，不算）
    目录名不是三个性质之一（如 `knowledge/inference/sglang/` 直接放文件）→ None：
    那种形态下目录不表达性质，没有可对的东西，不报。
    """
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == "common" and parts[1] in CATEGORIES:
        return parts[1]
    if len(parts) >= 4 and parts[0] in ("inference", "training") and parts[2] in CATEGORIES:
        return parts[2]
    return None


def dir_category_problems(root: Path):
    """目录说一个性质、case 字段说另一个性质 → 报。

    为什么值得一道门：`collect()` 的 namespace 从**目录**取、category 从**字段**取。于是一条放在
    `interrupt/` 目录里却写着 `category: precision` 的 case 会静默落进 precision 格子——索引自洽、
    实体也合法，只有**按目录找**的时候错位（人翻目录、以及将来按目录切子族时）。没有任何别的
    信号会报这件事：`--check` 只比对索引与字段、`verify_case_draft.py` 只看字段取值。

    **作用域边界**（别读成"目录层的性质一律管得住"）：只判"目录里表达性质的那一层"，即
    `common/<性质>/` 与 `<负载类型>/<框架>/<性质>/`。`knowledge/<负载类型>/<框架>/platforms/**`
    这一支整体不受本门约束——`collect()` 在那里也不把 `platforms` 当性质层（ns 会把这一层一起
    收进去），门与索引口径一致地不管它。当前库里没有这种形态，且平台背景文档已废弃；写在这里是
    为了下一个改这道门的人知道边界在哪，而不是以为漏了。
    """
    problems = []
    kdir = root / "knowledge"
    for path in sorted(kdir.rglob("*.yaml")):
        rel = path.relative_to(kdir)
        if rel.parts[0] in ("_archive", "_index") or path.name == "_index.yaml":
            continue
        want = _category_dir_of(rel)
        if want is None:
            continue
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            problems.append(f"{path.name}: YAML 读不动（{type(e).__name__}: {str(e)[:60]}）")
            continue
        for case in doc.get("cases", []) or []:
            got = case.get("category")
            if got != want:
                problems.append(
                    f"knowledge/{rel.as_posix()}：case {case.get('id', '?')} 的 category={got!r}"
                    f" 与所在目录 {want}/ 不一致——目录是「按目录找」与子族拆分的依据，"
                    f"改字段或挪文件（两者对齐后才重建索引）"
                )
    return problems


def _rows_of(path: Path):
    """一个索引文件里的 {case id: 索引行}（总表与分片同构）。读不动就抛——调用侧给可执行的话。"""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rows = {}
    for cells in (doc.get("namespaces") or {}).values():
        for cases in cells.values():
            for c in cases or []:
                if isinstance(c, dict) and c.get("id"):
                    rows[c["id"]] = c
    return rows


def coverage_problems(root: Path, namespaces):
    """**覆盖检查**（这是门）：读侧视图与总表是否都收全了 case，且与 case 内容一致。

    为什么门不是"逐字节和重建结果相同"：合并后文件的**内容是对的**（两边各加的条目都在），
    只是条目顺序可能与「重新生成一遍」不同——两个面都**故意没配 merge=union**（总表是嵌套 YAML，
    行级合并会拼坏；同一格并发得重跑一次生成器），而重跑之前的合并结果就是"内容对、顺序不标准"。
    逐字节的门会把那种正确的文件判红，于是又逼人跑一遍收尾命令，白付一次成本。
    所以门只问三件事：每条 case 的读侧行在不在、对不对得上、有没有多余的旧条目。

    **两面的新鲜度分工**：读侧视图只带判断用的字段（title/症状首条/sig/tok/compat/tags/score/
    category），所以"改了 case 里参与索引的字段"会表现为**行不同**；"只改了不参与索引的字段"
    （fix / severity / root_cause / ref_knowledge）在行上看不出来，靠总表的 content hash 抓。
    两面都要全绿，覆盖才算完整——所以本函数对两者都查。
    """
    shard_dir = root / "knowledge" / "_index"
    if not shard_dir.is_dir():
        return None
    problems = []
    rows, broken = shard_rows(root)
    problems += broken
    dup = duplicate_ids(root)
    for name, cid, n in dup:
        problems.append(f"{name} 里 {cid} 出现 {n} 次（重复条目）——重跑 `python3 scripts/build_index.py`")
    expected, want_line = {}, {}
    for ns, cells in namespaces.items():
        for cat, cases in cells.items():
            for c in cases:
                expected[c["id"]] = (f"{ns}__{cat}", c)
                want_line[c["id"]] = compact_line(c)
    for cid, (cell, want) in sorted(expected.items()):
        got = rows.get(cid)
        if got is None:
            problems.append(f"读侧视图缺条目：{cid}（{want['file']}，应在 {cell}）——跑 `python3 scripts/build_index.py`")
        elif got != want_line[cid]:
            problems.append(f"读侧视图这一行与 case 内容对不上：{cid}——case 改了没重建、或行被手改过？"
                            f"跑 `python3 scripts/build_index.py`")
    for cid in sorted(set(rows) - set(expected)):
        problems.append(f"读侧视图里有、库里没有：{cid}——case 被删/移走了没重建，跑 `python3 scripts/build_index.py`")
    # 文件本身的在场与回收：少一片 = 阶段一在某条路径上读不到（退化），多一片 = 退休格子没清
    want_files = set()
    for ns_name, cells in namespaces.items():
        want_files.add(shard_slug(ns_name))
        want_files.update(shard_slug(f"{ns_name}__{cat}") for cat in cells)
    have_files = {p.name for p in shard_dir.glob(f"*{SHARD_SUFFIX}")}
    for name in sorted(want_files - have_files):
        problems.append(f"读侧视图缺失：knowledge/_index/{name}——跑 `python3 scripts/build_index.py`")
    for name in sorted(have_files - want_files):
        problems.append(f"多余的读侧视图（格子已不存在）：knowledge/_index/{name}——跑 `python3 scripts/build_index.py` 回收")
    legacy = sorted(p.name for p in shard_dir.glob(f"*{LEGACY_SHARD_SUFFIX}"))
    if legacy:
        problems.append(f"旧形态分片未回收：{', '.join(legacy)}——跑 `python3 scripts/build_index.py`")

    master = root / "knowledge" / "_index.yaml"
    if not master.exists():
        problems.append("总表不存在（knowledge/_index.yaml）——跑 `python3 scripts/build_index.py`")
    else:
        try:
            mrows = _rows_of(master)
        except Exception as e:
            problems.append(f"总表 YAML 读不动（{type(e).__name__}：{str(e)[:80]}）——"
                            "多半是合并把嵌套结构拼坏了，重跑 `python3 scripts/build_index.py` 归一化")
            mrows = {}
        for cid, (_cell, want) in sorted(expected.items()):
            got = mrows.get(cid)
            if got is None:
                problems.append(f"总表缺条目：{cid}——跑 `python3 scripts/build_index.py`")
            elif got.get("hash") != want["hash"] or got != want:
                # hash 覆盖**整份 case 文件**（含不参与索引的字段）：读侧视图看不出的改动在这里落地
                problems.append(f"总表条目与 case 内容不一致（含 hash）：{cid}——重跑 `python3 scripts/build_index.py`")
        for cid in sorted(set(mrows) - set(expected)):
            problems.append(f"总表里有、库里没有：{cid}——重跑 `python3 scripts/build_index.py`")
    return problems


def canonical_dirty(root: Path, namespaces):
    """逐字节自检（`--canonical`，不作门）：分片与总表是否与"重新生成一遍"完全相同。

    用途是收尾/排查——union 合并后文件通常是"内容对、顺序不标准"，跑一次生成器即归一化，
    这条自检用来确认那一刻确实归位了。**不作 CI 门**：那会把正确的合并结果判红。
    """
    dirty = []
    out = root / "knowledge" / "_index.yaml"
    if not out.exists() or out.read_text(encoding="utf-8") != render(namespaces):
        dirty.append("knowledge/_index.yaml")
    for nsk, cells in namespaces.items():
        for key, payload in [(nsk, cells)] + [(f"{nsk}__{cat}", {cat: cases})
                                              for cat, cases in cells.items()]:
            p = shard_path(root, key)
            if not p.exists() or p.read_text(encoding="utf-8") != render_shard(key, payload):
                dirty.append(f"knowledge/_index/{shard_slug(key)}")
    return dirty


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="覆盖检查（门）：每条 case 的读侧行与总表条目都在、且与 case 内容一致")
    ap.add_argument("--canonical", action="store_true",
                    help="附加逐字节自检（不作门）：确认生成物与「重新生成一遍」完全相同")
    ap.add_argument("--root", default=None, help="仓库根目录（默认：脚本上两级）")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]

    ns = collect(root)
    if args.check:
        # 目录与字段的一致先查：它与索引覆盖无关（错位 case 的索引行是自洽的），
        # 所以不能挂在 coverage_problems 里（那个在分片目录缺失时整块跳过）。
        dir_problems = dir_category_problems(root)
        problems = coverage_problems(root, ns)
        if problems is None:
            print("读侧视图目录不存在（knowledge/_index/）——先运行 scripts/build_index.py 生成")
            for p in dir_problems:
                print(f"索引问题：{p}")
            sys.exit(1)
        problems = dir_problems + problems
        if problems:
            for p in problems:
                print(f"索引问题：{p}")
            if dir_problems:
                print(f"\n{len(problems)} 处，其中「目录与 category 不一致」{len(dir_problems)} 处："
                      "那些是 case 内容问题——改字段或挪文件，重建索引修不了它们。")
            else:
                print(f"\n{len(problems)} 处。生成物（读侧视图与总表）随 PR 提交，跑一次重建即可：")
                print("  python3 scripts/build_index.py")
            sys.exit(1)
        if args.canonical:
            dirty = canonical_dirty(root, ns)
            if dirty:
                print("逐字节自检：以下生成物与「重新生成一遍」不同（内容已覆盖全部 case，只是顺序/注释未归一）：")
                for d in dirty:
                    print(f"  {d}")
                print("归一化（可选，随时可跑）：python3 scripts/build_index.py")
                sys.exit(1)
        n_cases = sum(len(cases) for cells in ns.values() for cases in cells.values())
        n_shards = len(ns) + sum(len(c) for c in ns.values())
        tail = "，且与重新生成一遍逐字节相同" if args.canonical else ""
        print(f"索引覆盖完整：{n_cases} 条 case 的读侧行与总表条目都在（读侧视图 {n_shards} 个）{tail}。")
        return

    out = root / "knowledge" / "_index.yaml"
    write_text_lf(out, render(ns))
    shard_dir = root / "knowledge" / "_index"
    shard_dir.mkdir(exist_ok=True)
    expected = set()
    for nsk, cells in ns.items():
        # ns 级读侧视图（保留：category 未定/回退/其他消费者）
        p = shard_path(root, nsk)
        write_text_lf(p, render_shard(nsk, cells))
        expected.add(p.name)
        # F4（EV-2026-025）：category 级 <ns>__<category>.list——路由已定 category 时
        # 阶段一只读该格，避免整 ns（vllm-ascend 百余行）进上下文
        for cat, cases in cells.items():
            cp = shard_path(root, f"{nsk}__{cat}")
            write_text_lf(cp, render_shard(f"{nsk}__{cat}", {cat: cases}))
            expected.add(cp.name)
    # 回收：① 格子退休后的旧读侧视图；② 2026-09-29 前那一代 `.yaml` 分片（形态已换成文本行）
    for pattern in (f"*{SHARD_SUFFIX}", f"*{LEGACY_SHARD_SUFFIX}"):
        for old in shard_dir.glob(pattern):
            if old.name not in expected:
                old.unlink()
    n_cases = sum(len(cases) for cells in ns.values() for cases in cells.values())
    n_shards = len(ns) + sum(len(c) for c in ns.values())
    print(f"已生成 {out} + {n_shards} 个读侧视图（{n_cases} 条 case）")
    print("读入成本现算：python3 scripts/index_read_cost.py（改上限前先看它）")


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
