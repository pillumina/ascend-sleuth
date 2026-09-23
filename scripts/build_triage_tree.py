#!/usr/bin/env python3
# build_triage_tree.py —— 重建 triage-tree.yaml（生成物）← triage-tree.d/*.yaml（源，一性质一文件）
#
# 路由分两层（本脚本守的就是这条分层）：
#   负载类型（training / inference）—— 由工程师的事实确定，**不由症状词判**，所以不进这一层的数据。
#     合法负载类型与各自的目录面在 protocol 的 `workload_types:` 里，诊断时先定负载类型再取候选分支。
#   性质（interrupt / precision / performance）—— 在负载类型内按症状判，**训推共用一份词表**，
#     一性质一个源文件，落进生成物的 `natures:`。
#
# 为什么要有源/生成物这一层（2026-09-22，起因：并发提交时路由层总撞在同一个文件上）：
#   `triage-tree.yaml` 原先**既是源、又是所有人加词的目标**——一个文件里放着全部分支，
#   谁都得往它里面加行，两人给同一分支加词就落在同一段文本上，冲突要人判断"留哪一份"——
#   判断错了就静默丢一条路由词，而丢词的表现是"本该命中的分支没命中"，没有任何报错。
#
#   改法与仓库既有模式一致（`metrics/timeline.d/<期号>.yaml` → 生成的 `metrics/timeline.yaml`；
#   `knowledge/` 的 case 文件 → 生成的 `knowledge/_index.yaml`）：
#     源    `triage-tree.d/<序号>-<性质>.yaml` —— 一性质一个文件，改哪性质只碰哪个文件
#     清单  `triage-tree.d/00-protocol.md` 的 `sources:` —— 哪个文件出哪个性质（拼接口径的唯一写点）
#     生成物 `triage-tree.yaml`                —— 由本脚本从源拼出来，CI 校验覆盖
#   另配 `.gitattributes` 的 `merge=union`：两人同一天给同一性质加词时按行取并集，**两边都留住**，
#   合流不需要人工判断（重复行由本脚本报出来，删一行即可）。
#
#   拼接**逐字保留**：每个源文件里 `natures:` 之后的文本原样进入生成物（含行内注释与对齐）。
#   生成物的两个顶层键是 `workload_types:`（负载类型层）与 `natures:`（性质层）。原先的 `branches:` 桶
#   随分层退休——不再给别名：YAML 别名会让那份列表在文件里出现两遍（读的人以为有两结构），
#   而它换来的只是"读侧一个字都不用改"。路由数据每次诊断现读，改两处读点比留一份看起来
#   像双源的东西便宜（同一条道理也写在 `00-protocol.md` 里）。
#
# 用法：
#   python3 scripts/build_triage_tree.py            # 重建（写文件）
#   python3 scripts/build_triage_tree.py --check    # 逐字节自检（不作门）：是否与「重新拼一遍」相同
#   python3 scripts/build_triage_tree.py --check-coverage   # 覆盖检查（门）：每条症状组都在聚合里
#   python3 scripts/build_triage_tree.py --check-sources    # 只校验源文件本身
#   python3 scripts/build_triage_tree.py --print    # 只打印重建结果，不写文件
#
# 性质顺序 = protocol 里 `sources:` 的顺序（`10-`、`20-` … 序号是给人看的对应，不直接排序）：
# diagnose 按顺序匹配，先命中先路由。新性质加在末尾，不要改已有文件的编号。

import argparse
import sys
from pathlib import Path

import yaml

SRC_DIR_REL = Path("triage-tree.d")
OUT_REL = Path("triage-tree.yaml")
PROTOCOL_NAME = "00-protocol.md"
NATURE_CAP = 30          # 性质数上限（文件头长期写着 ≤30；此前无人守，现在由本脚本守）
CATEGORIES = ("interrupt", "precision", "performance")
REQUIRED_NATURE_KEYS = ("id", "category", "symptoms", "search_namespaces", "fallback")
SIDE_PREFIX = "<side>/"   # 性质层检索面里表示"由哪种负载类型展开"的记号（负载类型不在症状层判）
REQUIRED_WORKLOAD_TYPE_KEYS = ("id", "label", "namespaces", "fallback")

# git 冲突标记：源文件里出现它几乎只有一个原因——这一性质在两边各被改过，且平台那一侧没走 union 驱动
# （例如本地手抄合并、或 .gitattributes 没进那一负载类型）。不特判的话只会报"YAML 解析失败：..."，
# 而人要的答案是"把两份症状都留下"。
CONFLICT_MARKERS = ("<<<<<<<", ">>>>>>>")


def conflict_marked(text: str) -> bool:
    return any(m in text for m in CONFLICT_MARKERS)


def split_protocol(raw: str):
    """protocol 的正文与结构化部分分开：`sources:` / `workload_types:` 之后是数据，之前是散文。

    → (prose, data, errors)。散文进生成物的注释头；数据用来驱动拼接与校验。
    为什么不让本脚本自己去 glob 文件名：那样「哪个文件出哪个性质」会分散在文件名约定里，
    而顺序又是语义（先命中先路由）——顺序得有**一处**说得清的地方，就是这里。
    """
    errors = []
    lines = raw.split("\n")
    keys = [i for i, ln in enumerate(lines)
            if ln.split("#")[0].rstrip() and not ln.startswith((" ", "\t", "#"))
            and ln.split("#")[0].rstrip().endswith(":")]
    if not keys:
        return raw, {}, ["protocol 里没有任何顶层键——至少要有 `sources:`（源文件清单）与 `workload_types:`（合法负载类型）"]
    head = keys[0]
    prose = "\n".join(lines[:head])
    data_text = "\n".join(lines[head:])
    try:
        data = yaml.safe_load(data_text) or {}
    except Exception as e:
        return prose, {}, [f"{PROTOCOL_NAME}: 结构化部分 YAML 解析失败（{e}）"
                           "——`sources:` 与 `workload_types:` 之后必须是合法 YAML"]
    if not isinstance(data, dict):
        return prose, {}, [f"{PROTOCOL_NAME}: `sources:` / `workload_types:` 之后应当是 YAML mapping"]
    return prose, data, errors


def load_source(path: Path, expected_nature: str):
    """→ (nature, block_text, errors)。block_text 是 `natures:` 之后的原文（逐字保留）。"""
    errors = []
    raw = path.read_text(encoding="utf-8")
    if conflict_marked(raw):
        errors.append(
            f"{path.name}: 文件里有 **git 冲突标记**——这一性质在两边各被改过。处置：把两份症状都留下"
            "（union 合并的语义就是两边都留），删掉 <<<<<<< / ======= / >>>>>>> 三行，"
            "再跑 `python3 scripts/build_triage_tree.py`。本目录在 .gitattributes 里配了 merge=union，"
            "正常走平台合并时不会产生这个冲突标记。"
        )
        return None, None, errors
    lines = raw.split("\n")
    if "natures:" not in lines:
        errors.append(f"{path.name}: 顶层缺少 `natures:` 行（本目录里的每个数据文件都是一个性质的源；"
                      "协议与清单在 00-protocol.md 里，用 `sources:` 登记本文件）")
        return None, None, errors
    bi = lines.index("natures:")
    block = "\n".join(lines[bi + 1:])
    if not block.endswith("\n"):
        block += "\n"
    try:
        doc = yaml.safe_load("natures:\n" + block)
    except Exception as e:
        errors.append(f"{path.name}: 性质块 YAML 解析失败：{e}")
        return None, None, errors
    natures = (doc or {}).get("natures") or []
    if len(natures) != 1:
        errors.append(
            f"{path.name}: 应当是**一性质一文件**（natures 列表恰好 1 项），实际 {len(natures)} 项。"
            "一性质一文件是 union 合并能自动留住两边改动的前提；把多个性质混在一个文件里，"
            "合并就又回到「判断留哪份」。拆成 <序号>-<性质>.yaml，并在 00-protocol.md 的 `sources:` 登记。"
        )
        return None, None, errors
    nature = natures[0]
    if isinstance(nature, dict) and nature.get("id") and expected_nature != nature.get("id"):
        errors.append(
            f"{path.name}: 出的性质是 '{nature.get('id')}'，而 {PROTOCOL_NAME} 的 `sources:` 登记的是 "
            f"'{expected_nature}'——两处对不上。改文件名/内容时把 `sources:` 一起改。"
        )
    return nature, block, errors


def validate_nature(nature, path, seen_ids, public):
    """性质字段的确定性校验 → errors / warnings。

    `public` = 负载类型无关的公共目录集合（从 `workload_types:` 各份 namespaces 的交集里取，如 `common/`）：
    性质层的检索面只允许 `<side>/…` 与这些目录，别的写法都算把负载类型塞回症状层。
    """
    errors, warnings = [], []
    nid = nature.get("id")
    if not nid:
        return [f"{path.name}: 性质缺少 id"], []
    if nid in seen_ids:
        errors.append(
            f"{path.name}: 性质 id '{nid}' 与 {seen_ids[nid]} 重复——路由按性质顺序匹配，"
            "重复 id 会让 trace 里的 routed 指向不明。删掉其中一个文件。"
        )
    else:
        seen_ids[nid] = path.name
    stem = path.stem
    if "-" in stem:
        suffix = stem.rsplit("-", 1)[1]
        if suffix != str(nid):
            errors.append(
                f"{path.name}: 文件名结尾是 '{suffix}'，而里面写的性质 id 是 '{nid}'"
                "——文件名是给人找文件的索引（`<序号>-<性质>.yaml`），内容才是路由依据，两处必须同名。"
            )
    for k in REQUIRED_NATURE_KEYS:
        if k not in nature:
            errors.append(f"{path.name}: 性质 '{nid}' 缺少必填键 {k}")
    cat = nature.get("category", "MISSING")
    if cat not in CATEGORIES:
        errors.append(
            f"{path.name}: 性质 '{nid}' 的 category {cat!r} 非法——"
            f"合法取值只有 {' / '.join(CATEGORIES)}（other 已废弃；`uncategorized` 兜底分支已随分层取消："
            "性质判不了时该负载类型三个性质的索引一起加载，见 00-protocol.md 与 diagnosis-procedure.md）"
        )
    syms = nature.get("symptoms")
    if not isinstance(syms, list):
        errors.append(f"{path.name}: 性质 '{nid}' 的 symptoms 应当是列表（每条是一组正则备选）")
    else:
        seen_groups = []
        for i, group in enumerate(syms):
            if not isinstance(group, list) or not group:
                errors.append(f"{path.name}: 性质 '{nid}' 第 {i + 1} 条症状应为非空列表（一组备选写法）")
                continue
            for alt in group:
                if not isinstance(alt, str) or not alt:
                    errors.append(f"{path.name}: 性质 '{nid}' 第 {i + 1} 条症状里有非字符串/空项")
            # 只报**整条重复**（union 合并的产物）：跨组重复同一个词是正常数据（同一形态在不同
            # 证据链里各写一次），报它只会训练人忽略告警。
            key = tuple(group)
            if key in seen_groups:
                warnings.append(
                    f"{path.name}: 性质 '{nid}' 第 {i + 1} 条症状与前面某条完全相同——"
                    "多半是 union 合并把两人加的同一行都留下了，删掉一行即可（不删不影响路由）"
                )
            else:
                seen_groups.append(key)
    sn = nature.get("search_namespaces")
    if not isinstance(sn, list) or not sn or not all(isinstance(x, str) and x for x in sn):
        errors.append(f"{path.name}: 性质 '{nid}' 的 search_namespaces 应为非空字符串列表"
                      "（分层后第一条是 `<side>/<detected_framework>/`：负载类型由工程师的事实定，"
                      "不在症状层判）")
    else:
        # **逐条判**，不是"有一条带 `<side>` 就算过"。只判"存在"会留一个绕过口（独立预核实测）：
        # `['training/<detected_framework>/', '<side>/common/']` 里有 `<side>`，检查放行，
        # 而推理侧展开后变成 `['training/<detected_framework>/', 'inference/common/']`——
        # 推理诊断去查训练目录，这一层要防的机制原样回来，且全套门都是绿的。
        # 判据：每条 namespace 要么是 `<side>/…` 形，要么是一条**负载类型无关**的公共目录
        # （值必须在 `workload_types:` 的某一份 namespaces 里出现过——`common/` 因此自动被允许，
        #  而任何写死某一负载类型的目录都不是"负载类型无关"，因为它们没进过任何负载类型目录面的公共部分）。
        pinned = [x for x in sn if not x.startswith(SIDE_PREFIX) and x not in public]
        if pinned:
            errors.append(
                f"{path.name}: 性质 '{nid}' 的 search_namespaces 里有写死某一负载类型的目录 {pinned}——"
                "分层后性质层不知道自己在哪一种负载类型下，负载类型由 `workload_types:` 给出；只要列表里有一条写死某一种负载类型，"
                "另一种的诊断就会去查这一种的目录（把一个带 `<side>` 的项混在同一条列表里也绕不过，"
                "本检查逐条判）。改成 `<side>/<detected_framework>/`，公共目录只留 `common/` 这类负载类型无关项。"
            )
    return errors, warnings


def validate_workload_type(wt, where, seen_ids):
    errors = []
    wid = wt.get("id") if isinstance(wt, dict) else None
    if not wid:
        return [f"{PROTOCOL_NAME} {where}: 负载类型缺少 id"]
    if wid in seen_ids:
        errors.append(f"{PROTOCOL_NAME} {where}: 负载类型 id '{wid}' 重复")
    else:
        seen_ids[wid] = where
    for k in REQUIRED_WORKLOAD_TYPE_KEYS:
        if k not in wt:
            errors.append(f"{PROTOCOL_NAME} {where}: 负载类型 '{wid}' 缺少必填键 {k}")
    ns = wt.get("namespaces")
    if not isinstance(ns, list) or not ns or not all(isinstance(x, str) and x for x in ns):
        errors.append(f"{PROTOCOL_NAME} {where}: 负载类型 '{wid}' 的 namespaces 应为非空字符串列表")
    elif not any(str(x).startswith(str(wid) + "/") for x in ns):
        errors.append(
            f"{PROTOCOL_NAME} {where}: 负载类型 '{wid}' 的 namespaces 里没有以 '{wid}/' 打头的目录——"
            "负载类型的目录面必须落在它自己的 knowledge/<负载类型>/ 下，否则两种负载类型会查同一批目录，"
            "分层就白做了。"
        )
    return errors


def public_namespaces(workload_types) -> set:
    """负载类型无关的公共目录 = 每个负载类型的 namespaces 里都出现过的那些（`common/` 就是靠这个进来的）。

    为什么取交集而不是写死 `{"common/"}`：负载类型层是合法负载类型与目录面的唯一写点，公共面由它派生；
    写死一份等于又开了第二个写点，`workload_types:` 改了它不跟着动。
    """
    sets = [set(str(x) for x in (s.get("namespaces") or []))
            for s in workload_types if isinstance(s, dict)]
    sets = [x for x in sets if x]
    return set.intersection(*sets) if sets else set()


def collect_sources(root: Path):
    """→ (prose, natures, workload_types, blocks, errors, warnings)。"""
    src_dir = root / SRC_DIR_REL
    if not src_dir.is_dir():
        return None, [], [], [], [f"源目录不存在：{SRC_DIR_REL}（Tier 1 路由以它为源）"], []
    proto_path = src_dir / PROTOCOL_NAME
    if not proto_path.exists():
        return None, [], [], [], [f"缺少 {SRC_DIR_REL}/{PROTOCOL_NAME}（路由说明、负载类型层与源清单的写点）"], []
    prose, data, errs = split_protocol(proto_path.read_text(encoding="utf-8"))
    errors, warnings = list(errs), []

    manifest = data.get("sources")
    if not isinstance(manifest, list) or not manifest:
        errors.append(f"{PROTOCOL_NAME}: 缺少非空的 `sources:` 清单（哪个源文件出哪个性质）"
                      "——拼接顺序与校验都读它，不能省。")
        manifest = []
    workload_types = data.get("workload_types")
    if not isinstance(workload_types, list) or not workload_types:
        errors.append(f"{PROTOCOL_NAME}: 缺少非空的 `workload_types:` 清单（合法负载类型 + 每种负载类型的目录面与检索顺序）")
        workload_types = []
    seen_workload_types = {}
    for i, wt in enumerate(workload_types):
        if not isinstance(wt, dict):
            errors.append(f"{PROTOCOL_NAME} workload_types[{i}]: 不是 mapping")
            continue
        errors += validate_workload_type(wt, f"workload_types[{i}]", seen_workload_types)
    if len(seen_workload_types) < 2:
        errors.append(f"{PROTOCOL_NAME}: 负载类型少于 2 个（实际 {sorted(seen_workload_types)}）——"
                      "「先分负载类型」这一步没有可选项时不存在，检查 `workload_types:` 是不是被误删了。")

    public = public_namespaces(workload_types)
    natures, blocks, seen_ids, seen_files = [], [], {}, {}
    declared = []
    for i, item in enumerate(manifest):
        if not isinstance(item, dict) or not item.get("file") or not item.get("nature"):
            errors.append(f"{PROTOCOL_NAME} sources[{i}]: 每项要有 `file`（源文件名）与 "
                          "`nature`（该文件出的性质 id）")
            continue
        name, want = str(item["file"]), str(item["nature"])
        if name in seen_files:
            errors.append(f"{PROTOCOL_NAME}: 源文件 {name} 被登记了两次"
                          f"（sources[{seen_files[name]}] 与 sources[{i}]）")
            continue
        seen_files[name] = i
        declared.append(name)
        path = src_dir / name
        if not path.exists():
            errors.append(f"{PROTOCOL_NAME}: sources 登记的 {name} 不存在——"
                          "文件被删/改名后要把 `sources:` 一起改，或把它加回来。")
            continue
        nature, block, errs = load_source(path, want)
        errors += errs
        if nature is None:
            continue
        e, w = validate_nature(nature, path, seen_ids, public)
        errors += e
        warnings += w
        natures.append(nature)
        blocks.append(block)

    for path in sorted(src_dir.glob("*.yaml")):
        if path.name not in seen_files:
            errors.append(f"{SRC_DIR_REL}/{path.name}: 文件没在 {PROTOCOL_NAME} 的 `sources:` 里登记"
                          "——未登记的文件不会被拼进生成物，等于加了词但没生效。")
    if len(seen_ids) > NATURE_CAP:
        errors.append(f"性质数 {len(seen_ids)} 超过上限 {NATURE_CAP}——路由层超限后匹配成本与误吸都会上升")
    return prose, natures, workload_types, blocks, errors, warnings


def render(prose: str, blocks, workload_types) -> str:
    """protocol 散文的每行前加 '# '（空行加 '#'）；再出 `workload_types:` 与 `natures:`（+ branches 别名）。"""
    lines = prose.rstrip("\n").split("\n")
    header = "".join(("# " + ln if ln.strip() else "#") + "\n" for ln in lines)
    sides_text = yaml.safe_dump({"workload_types": workload_types}, allow_unicode=True, sort_keys=False,
                                default_flow_style=False, width=100)
    return (header + "#\n" + "workload_types:\n" + sides_text.split("\n", 1)[1]
            + "\n# 性质层（训推共用一份词表；负载类型由 `workload_types:` 给，不由症状词判）\n"
            + "natures:\n" + "".join(blocks))


def coverage_problems(root: Path, natures, workload_types, public):
    """**覆盖检查**（这是门）：每个源性质的每条症状组、负载类型层每个字段，是否都在聚合里。

    为什么门不是"逐字节与重新拼接的结果相同"：`triage-tree.yaml` 配了 merge=union
    （两人同一天给同一性质加词时两边都留住），那种合并结果**内容是对的**、只是顺序可能与
    重新拼接不同。逐字节的门会把正确的合并判红，等于把 union 的收益还回去。
    要归一化随时跑一次生成器（那是可选的）。
    """
    out = root / OUT_REL
    if not out.exists():
        return [f"{OUT_REL} 不存在——跑 `python3 scripts/build_triage_tree.py`"]
    try:
        doc = yaml.safe_load(out.read_text(encoding="utf-8")) or {}
    except Exception as e:
        return [f"{OUT_REL} YAML 解析失败（{e}）——重跑 `python3 scripts/build_triage_tree.py`"]
    got = {b.get("id"): b for b in (doc.get("natures") or []) if isinstance(b, dict)}
    got_workload_types = {s.get("id"): s for s in (doc.get("workload_types") or []) if isinstance(s, dict)}
    problems = []
    for nature in natures:
        nid = nature["id"]
        have = got.get(nid)
        if have is None:
            problems.append(f"聚合里缺性质 {nid}——重跑 `python3 scripts/build_triage_tree.py`"
                            "（union 合并偶尔会丢一段）")
            continue
        for key in ("category", "search_namespaces", "fallback"):
            if have.get(key) != nature.get(key):
                problems.append(f"性质 {nid} 的 {key} 与源不一致——重跑 `python3 scripts/build_triage_tree.py`")
        agg_pinned = [x for x in (have.get("search_namespaces") or [])
                      if not str(x).startswith(SIDE_PREFIX) and str(x) not in public]
        if agg_pinned:
            problems.append(f"聚合里性质 {nid} 的检索面写死了某一负载类型 {agg_pinned}"
                            "——重跑 `python3 scripts/build_triage_tree.py`")
        have_groups = [tuple(g) for g in (have.get("symptoms") or [])]
        for group in nature.get("symptoms") or []:
            if tuple(group) not in have_groups:
                problems.append(f"性质 {nid} 里缺症状组 {group}——重跑 `python3 scripts/build_triage_tree.py`")
    for wt in workload_types:
        wid = wt.get("id")
        have = got_workload_types.get(wid)
        if have is None:
            problems.append(f"聚合里缺负载类型 {wid}——重跑 `python3 scripts/build_triage_tree.py`")
            continue
        for key in REQUIRED_WORKLOAD_TYPE_KEYS:
            if have.get(key) != wt.get(key):
                problems.append(f"负载类型 {wid} 的 {key} 与源不一致——重跑 `python3 scripts/build_triage_tree.py`")
    src_ids = {n["id"] for n in natures}
    for nid in sorted(set(got) - src_ids):
        problems.append(f"聚合里有、源里没有的性质 {nid}——重跑 `python3 scripts/build_triage_tree.py`")
    for wid in sorted(set(got_workload_types) - {s.get("id") for s in workload_types}):
        problems.append(f"聚合里有、源里没有的负载类型 {wid}——重跑 `python3 scripts/build_triage_tree.py`")
    # **顺序也是判据**，两条理由：
    #   ① 忠实性：聚合必须忠实渲染源（源才是评审面）；手改聚合的性质顺序，等于让评审过的那份
    #      与跑起来的那份不是同一个东西。集合相等 ≠ 忠实。
    #   ② 路由确有顺序效应：诊断用正则模糊匹配、多个性质弱匹配时按树的先后取用（见
    #      skills/diagnose/references/diagnosis-procedure.md 步骤 2），顺序决定先归哪一类。
    #   症状组之间的顺序不查：同性质内哪条先命中都归到同一性质，是外观。
    got_seq = [b.get("id") for b in (doc.get("natures") or []) if isinstance(b, dict)]
    src_seq = [n["id"] for n in natures]
    if got_seq != src_seq:
        problems.append(f"聚合的性质顺序与源不一致（源：{' → '.join(src_seq)}；聚合：{' → '.join(got_seq)}）"
                        "——顺序决定先命中先归哪一类，重跑 `python3 scripts/build_triage_tree.py`")
    if doc.get("branches") is not None:
        problems.append("聚合里有退休的 `branches:` 桶——分层后只有 `workload_types:` 与 `natures:` 两个顶层键，"
                        "重跑 `python3 scripts/build_triage_tree.py` 归一（留着它读的人会以为有两套结构）")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="重建生成的 triage-tree.yaml（源：triage-tree.d/）")
    ap.add_argument("--check", action="store_true",
                    help="逐字节自检（不作门）：确认聚合与「重新拼接一遍」完全相同")
    ap.add_argument("--check-coverage", action="store_true",
                    help="覆盖检查（门）：源里每个性质的每条症状组、负载类型层每个字段都在聚合里")
    ap.add_argument("--check-sources", action="store_true",
                    help="只校验源文件本身（性质 id 唯一 / category 合法 / <side> 占位 / ≤30 性质 / "
                         "一性质一文件 / 源清单无遗漏）")
    ap.add_argument("--print", dest="do_print", action="store_true", help="只打印，不写文件")
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = ap.parse_args()
    root = args.root.resolve()

    prose, natures, workload_types, blocks, errors, warnings = collect_sources(root)
    for w in warnings:
        print(f"WARN: {w}")
    if errors:
        print(f"{SRC_DIR_REL} 有 {len(errors)} 处问题：")
        for e in errors:
            print(f"  - {e}")
        return 1
    if not blocks:
        print(f"{SRC_DIR_REL} 里没有可拼接的性质——路由层未落地")
        return 1

    wanted = render(prose, blocks, workload_types)
    out_path = root / OUT_REL

    if args.do_print:
        print(wanted)
        return 0

    if args.check_sources:
        print(f"路由源文件合法（{len(blocks)} 个性质 × {len(workload_types)} 个负载类型 ← {SRC_DIR_REL}/）")
        return 0

    if args.check_coverage:
        problems = coverage_problems(root, natures, workload_types, public_namespaces(workload_types))
        if problems:
            for p in problems:
                print(f"路由覆盖问题：{p}")
            print(f"\n{len(problems)} 处。跑一次重建即可（聚合随 PR 提交）：")
            print("  python3 scripts/build_triage_tree.py")
            return 1
        n_groups = sum(len(n.get("symptoms") or []) for n in natures)
        print(f"路由覆盖完整：{len(natures)} 个性质 / {len(workload_types)} 个负载类型 / {n_groups} 组症状"
              f"都在聚合 {OUT_REL} 里。")
        return 0

    if args.check:
        current = out_path.read_text(encoding="utf-8") if out_path.exists() else None
        if current == wanted:
            print(f"triage-tree 聚合与「重新拼接一遍」逐字节相同（{len(blocks)} 个性质 ← {SRC_DIR_REL}/）")
            return 0
        print(f"{OUT_REL} 与重新拼接的结果不同（内容可能已齐全，只是顺序/注释未归一）：")
        print("  归一化（可选，随时可跑）：python3 scripts/build_triage_tree.py")
        if current is None:
            print(f"  （原因：{OUT_REL} 不存在）")
        else:
            try:
                cur_ids = [b.get("id") for b in (yaml.safe_load(current) or {}).get("natures", [])]
            except Exception:
                cur_ids = None
            src_ids = [b.get("id") for b in (yaml.safe_load(wanted) or {}).get("natures", [])]
            if cur_ids is not None and cur_ids != src_ids:
                print(f"  聚合性质：{cur_ids}")
                print(f"  源  性质：{src_ids}")
        return 1

    out_path.write_text(wanted, encoding="utf-8", newline="\n")
    print(f"已重建 {OUT_REL}（{len(blocks)} 个性质 × {len(workload_types)} 个负载类型 ← {SRC_DIR_REL}/）")
    for wt in workload_types:
        print(f"  负载类型 {wt.get('id'):<12} {wt.get('namespaces')}")
    for b in (yaml.safe_load(wanted) or {}).get("natures", []):
        print(f"  - {b.get('id'):<22} category={b.get('category')}  症状组 {len(b.get('symptoms') or [])}")
    return 0


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
