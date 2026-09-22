#!/usr/bin/env python3
# build_index.py —— 生成 knowledge/_index.yaml（Tier 2 阶段一的结构化索引）
#
# 设计决策见 docs/adr/0002-retrieval-no-rag-lightweight-index.md：
#   - 索引是生成物，提交进 git，随 case 变更一起 diff / 评审
#   - 把"阶段一只加载索引字段"从 prompt 纪律变成结构保证：阶段一 = 读命中 (ns×category)
#     的最小分片（总表 + ns 分片 + 类分片均由本脚本生成，见 render_shard/render）
#   - 每条 case 记 content hash，--check 校验新鲜度（groom 每次跑，可挂 CI）
#
# 一致性门是**覆盖检查**，不是逐字节相同（2026-09-22；起因：并发提交时生成物天天撞）：
#   `--check`     每条 case 的索引行都在（分片与总表）、且与 case 内容逐字段一致；
#   `--canonical` 附带「与重新生成一遍逐字节相同」的自检——**不作门**，只在归一化后确认用。
#   为什么门不能是逐字节：本文件与分片随 PR 提交，两个人并发时文件会以「内容齐全、顺序不同」
#   的形态合到一起，那是**对的**；逐字节把它判红，就逼人再跑一遍收尾命令，白拿 union 的收益。
#   头注不含数字（条数 / 容量 / 日期）：数字进 git 就会在并发合并时撞行、或漂移成错的数。
#   要数字现算：`python3 scripts/index_counts.py`（面板与体检脚本走同一条路径）。
#
# 索引**故意不配 merge=union**：它是嵌套结构（namespaces → ns → category → 条目），
# union 是行级文本合并，两人在同一格各加一条时两段插入会被拼成不合法的 YAML（实测 parser 报错）。
# 所以同一个格子的并发仍会撞一次，解决动作是重跑本脚本（机械、无判断）；不同格子不碰同一个文件。
#
# 用法：
#   python3 scripts/build_index.py              # 重新生成总表 + 全部分片（改动后跑它，两者都提交）
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


def compat_summary(compat) -> str:
    """compat 列表压成一行可 grep 的概要："fw A >=1.0,<2.0; fw B >=3.0 (cann:>=8.0)" """
    if not compat:
        return ""
    parts = []
    for c in compat:
        fw = c.get("framework", "?")
        rng = ",".join(c.get("ranges", []) or [])
        extra = []
        if c.get("cann"):
            extra.append("cann:" + ",".join(c["cann"]))
        if c.get("hdk"):
            extra.append("hdk:" + ",".join(c["hdk"]))
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
            if category not in ("interrupt", "precision", "performance"):
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
    """namespace → 分片文件名（/ → __，避免目录层级）。"""
    return ns.replace("/", "__") + ".yaml"


def shard_path(root: Path, ns: str) -> Path:
    return root / "knowledge" / "_index" / shard_slug(ns)


def render_shard(ns, cells) -> str:
    n = sum(len(c) for c in cells.values())
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
        "# GENERATED FILE —— 分片（knowledge/_index.yaml 的 " + ns + " 子集），不要手改。",
        "# 随 PR 提交（改 case 的人跑 `python3 scripts/build_index.py`）；",
        "# 本目录配了 merge=union：两人同一天改同一格时，两边的条目都会留住，不产生冲突标记。",
        proto,
        "# 本分片：" + ns,
        "",
    ])
    body = yaml.safe_dump(
        {"namespaces": {ns: cells}},
        allow_unicode=True, sort_keys=False, default_flow_style=False, width=100,
    )
    return header + body


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
        "# 随 PR 提交（谁都能改到它，但本文件配了 merge=union：两边新增的条目都会留住，不产生冲突标记）。",
        "# 阶段一加载协议：本文件是总表（兜底 + 跨库比对）；diagnose 只读命中的最小分片",
        "# （knowledge/_index/<ns>__<category>.yaml；category 未定回退 <ns>.yaml），候选 ≤5 过滤后",
        "# 按 file 字段定位做阶段二全量加载。",
        "# 本文件**不写数字**（条数 / 容量 / 日期）：数字一进 git，两人并发合并时要么撞同一行、",
        "# 要么漂移成错的数。要看数字就现算：`python3 scripts/index_counts.py`",
        "# （容量治理的格子口径见该脚本与 docs/adr/0004）。",
        "# 一致性门是**覆盖检查**（每条 case 的索引行都在、且与 case 内容对得上），不是逐字节相同——",
        "# 逐字节的门会让 union 合并出来的、内容正确的文件变红。要归一化就重跑一次生成器。",
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
    """已提交分片里的 {case id: 索引行} → (rows, broken)。

    broken 收集两类"不能挑一份信"的情况：① 分片里有 git 冲突标记（不该出现——本目录配了
    union 合并）；② 同一条 case 在两片里内容不同（说明有一片没重建）。
    """
    rows, broken = {}, []
    shard_dir = root / "knowledge" / "_index"
    for p in sorted(shard_dir.glob("*.yaml")):
        raw = p.read_text(encoding="utf-8")
        if any(m in raw for m in ("<<<<<<<", ">>>>>>>")):
            broken.append(f"{p.name}: 有 git 冲突标记——重跑 `python3 scripts/build_index.py`（分片是生成物，不必手判留哪份）")
            continue
        try:
            doc = yaml.safe_load(raw) or {}
        except Exception as e:
            broken.append(f"{p.name}: YAML 解析失败（{e}）——重跑 `python3 scripts/build_index.py`")
            continue
        for cells in (doc.get("namespaces") or {}).values():
            for cases in cells.values():
                for c in cases or []:
                    if not isinstance(c, dict) or not c.get("id"):
                        continue
                    cid = c["id"]
                    if cid in rows and rows[cid] != c:
                        broken.append(f"{p.name}: {cid} 的索引行与别的分片不一致——有分片没重建，重跑 `python3 scripts/build_index.py`")
                    rows[cid] = c
    return rows, broken


def shard_hashes(root: Path):
    """{case id: hash}（旧接口，兼容既有测试/调用）。"""
    rows, broken = shard_rows(root)
    return {cid: (row or {}).get("hash") for cid, row in rows.items()}, broken


def duplicate_ids(root: Path):
    """(文件名, id, 次数)：同一条 case 在一个索引文件里出现多次。

    为什么单列：行级合并/重复 rebase 会把同一段**原样保留两份**（内容完全相同 → git 不报冲突，
    hash 与行比对也一致），只按 id 建字典的话第二份被静静吃掉——文件里那条重复就一直留着。
    """
    out = []
    for p in sorted([root / "knowledge" / "_index.yaml"] + list((root / "knowledge" / "_index").glob("*.yaml"))):
        if not p.exists():
            continue
        seen = {}
        try:
            # 条目是缩进的（总表里还多一层），所以不能用 ^- id:
            for cid in re.findall(r"^\s*- id:\s*(\S+)", p.read_text(encoding="utf-8"), re.M):
                seen[cid] = seen.get(cid, 0) + 1
        except Exception:
            continue
        for cid, n in sorted(seen.items()):
            if n > 1:
                out.append((p.name, cid, n))
    return out


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
    """**覆盖检查**（这是门）：分片与总表是否都收全了 case，且索引行与 case 内容一致。

    为什么门不是"逐字节和重建结果相同"：本目录配了 merge=union——两人同一天改同一格时，
    两边新增的条目都会留在文件里，那份文件**内容是对的**（只是顺序可能与重新生成不同）。
    逐字节的门会把这种正确的文件判红，于是又逼人跑一遍收尾命令，等于把 union 换来的收益还回去。
    所以门只问三件事：每条 case 的索引行在不在、对不对得上、有没有多余的旧条目。
    要归一化（顺序/注释回到生成器口径）随时跑一次 `python3 scripts/build_index.py`，那是可选的。
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
    expected = {}
    for ns, cells in namespaces.items():
        for cat, cases in cells.items():
            for c in cases:
                expected[c["id"]] = (f"{ns}__{cat}", c)
    for cid, (cell, want) in sorted(expected.items()):
        got = rows.get(cid)
        if got is None:
            problems.append(f"分片缺条目：{cid}（{want['file']}，应在 {cell}）——跑 `python3 scripts/build_index.py`")
        elif got.get("hash") != want["hash"]:
            problems.append(f"分片条目过期：{cid}——case 内容变了没重建，跑 `python3 scripts/build_index.py`")
        elif got != want:
            problems.append(f"分片条目与 case 内容不一致：{cid}——索引行被手改过？重跑 `python3 scripts/build_index.py`")
    for cid in sorted(set(rows) - set(expected)):
        problems.append(f"分片里有、库里没有：{cid}——case 被删/移走了没重建，跑 `python3 scripts/build_index.py`")
    # 分片文件本身的在场与回收：少一片 = 阶段一在某条路径上读不到（退化），多一片 = 退休格子没清
    want_files = set()
    for ns_name, cells in namespaces.items():
        want_files.add(shard_slug(ns_name))
        want_files.update(shard_slug(f"{ns_name}__{cat}") for cat in cells)
    have_files = {p.name for p in shard_dir.glob("*.yaml")}
    for name in sorted(want_files - have_files):
        problems.append(f"分片缺失：knowledge/_index/{name}——跑 `python3 scripts/build_index.py`")
    for name in sorted(have_files - want_files):
        problems.append(f"多余分片（格子已不存在）：knowledge/_index/{name}——跑 `python3 scripts/build_index.py` 回收")

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
                problems.append(f"总表缺条目：{cid}——跑 `python3 scripts/build_index.py`（union 合并偶尔会丢一格）")
            elif got.get("hash") != want["hash"] or got != want:
                problems.append(f"总表条目与 case 内容不一致：{cid}——重跑 `python3 scripts/build_index.py`")
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
                    help="覆盖检查（门）：每条 case 的索引行都在分片与总表里且与内容一致")
    ap.add_argument("--canonical", action="store_true",
                    help="附加逐字节自检（不作门）：确认生成物与「重新生成一遍」完全相同")
    ap.add_argument("--root", default=None, help="仓库根目录（默认：脚本上两级）")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]

    ns = collect(root)
    if args.check:
        problems = coverage_problems(root, ns)
        if problems is None:
            print("分片目录不存在（knowledge/_index/）——先运行 scripts/build_index.py 生成")
            sys.exit(1)
        if problems:
            for p in problems:
                print(f"索引问题：{p}")
            print(f"\n{len(problems)} 处。生成物（分片与总表）随 PR 提交，跑一次重建即可：")
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
        print(f"索引覆盖完整：{n_cases} 条 case 的索引行都在（分片 {n_shards} 个）{tail}。")
        return

    out = root / "knowledge" / "_index.yaml"
    write_text_lf(out, render(ns))
    shard_dir = root / "knowledge" / "_index"
    shard_dir.mkdir(exist_ok=True)
    expected = set()
    for nsk, cells in ns.items():
        # ns 级分片（保留：category 未定/回退/其他消费者）
        p = shard_path(root, nsk)
        write_text_lf(p, render_shard(nsk, cells))
        expected.add(p.name)
        # F4（EV-2026-025）：category 级分片 <ns>__<category>.yaml——路由已定 category 时
        # 阶段一只读该 cell，避免整 ns（vllm-ascend 107 行）进上下文
        for cat, cases in cells.items():
            cp = shard_path(root, f"{nsk}__{cat}")
            write_text_lf(cp, render_shard(f"{nsk}__{cat}", {cat: cases}))
            expected.add(cp.name)
    for old in shard_dir.glob("*.yaml"):
        if old.name not in expected:
            old.unlink()
    n_cases = sum(len(cases) for cells in ns.values() for cases in cells.values())
    n_shards = len(ns) + sum(len(c) for c in ns.values())
    print(f"已生成 {out} + {n_shards} 个分片（{n_cases} 条 case）")


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
