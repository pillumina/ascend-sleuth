#!/usr/bin/env python3
# verify_references.py —— 校验 references/ 先验知识层（ADR-0008）
#
# 设计决策见 docs/adr/0008-prior-knowledge-framework.md §8：
#   - 强校验基础元信息（id/type/title/summary/sources/last_verified/status）
#   - type 必须已登记在 references/_types.yaml（schema_required 决定强校验字段）
#   - 按来源类型强校验子字段（official-doc / engineer-input / case-derived）
#   - 深审：case-derived + methodology 从全库 case 的 ref_knowledge 派生计数，
#     < 3 条引用时不允许 status: active（引用数不存储于 reference 本体）
#   - case 侧 ref_knowledge 强校验（ADR-0008 §7）：ref 必须存在于 references/（防
#     悬挂引用）、role 必须合法（signature-source / fix-methodology / root-cause-context）
#   - skill 侧绑定强校验（EV-2026-037）：skill 支撑文件里的 ref-id 绑定
#     （skills/diagnose/references/collect-gates.yaml）必须指向存在且 active 的词条——
#     散文里硬编码 ref-id 会静默腐化（曾把不存在的 profiling-performance-fault-patterns
#     当已有落点写进 SKILL），绑定落成数据后由 CI 兜住
#   - reference 层入口门槛比 case 更严（ADR-0008：reference 比 case 更宝贵）
#
# 用法：
#   python3 scripts/verify_references.py            # 校验并报告
#   python3 scripts/verify_references.py --check    # 同（CI 模式，对称 build_index）
#
# 依赖：PyYAML（pip install pyyaml）

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("需要 PyYAML：pip install pyyaml")

from _yaml import load_file   # noqa: E402  （解析后端单一事实源，快路径见 _yaml.py）

VALID_STATUSES = {"draft", "active", "pending-review", "deprecated"}
VALID_SOURCE_TYPES = {"official-doc", "engineer-input", "case-derived"}
VALID_ROLES = {"signature-source", "fix-methodology", "root-cause-context"}  # ADR-0008 §7
VALID_VERIFICATIONS = {"auto-extracted", "cross-checked-source"}  # ADR-0008 §4.2（可选字段）

SOURCE_REQUIRED = {
    "official-doc": ["url", "version", "fetched_at"],
    "engineer-input": ["engineer", "input_session", "confirmed_at"],
    "case-derived": ["cases", "extracted_at"],
}

# methodology 深审：case-derived 来源需 ≥3 条 case 引用（派生计数）才可 active
METHODOLOGY_MIN_CASE_REFS = 3


# 解析结果按路径记忆：refs 在三处被解析（id 集、id 查重、逐条校验），而一次校验里文件不会变
# ——实测 351 个文件被解析 699 次，多出来的那一半是纯粹的重复劳动（面板的判决要跑这条链路）。
# 缓存只对**只读用法**成立：本脚本只读字段、只往 errors 追加，从不改写 doc（加字段/改字段前
# 先想清楚共享同一份的后果）。错误文档同样进缓存：同一份坏文件的报错不会有第二次不同的样子。
_parsed_cache = {}


def load_yaml(path: Path):
    key = str(path)
    if key not in _parsed_cache:
        try:
            _parsed_cache[key] = load_file(path) or {}
        except yaml.YAMLError as e:
            _parsed_cache[key] = {"__yaml_error__": str(e)}
    return _parsed_cache[key]


def check_case_ref_links(root: Path, ref_ids: set):
    """扫描 case 侧 ref_knowledge：派生引用计数 + 校验 ref 存在性与 role 合法性。

    ADR-0008 §7：一条关系只存一处（case 侧），反向视图（哪些 case 引用了某
    reference）是派生的、不存储——counts 供深审（case-derived methodology
    引用数 <3 不允许 active）使用。ref 存在性与 role 合法性是 CI 强校验：
    悬挂引用与非法 role 直接红。"""
    counts = {}
    errors = []
    kdir = root / "knowledge"
    if not kdir.exists():
        return counts, errors
    for path in sorted(kdir.rglob("*.yaml")):
        if not is_entry_file(path):      # 生成物 / 下划线目录非词条
            continue
        rel = str(path.relative_to(root))
        doc = load_yaml(path)
        if not (isinstance(doc, dict) and not doc.get("__yaml_error__")):
            continue
        for case in doc.get("cases", []) or []:
            if not isinstance(case, dict):
                continue
            cid = case.get("id", "?")
            for entry in case.get("ref_knowledge", []) or []:
                if not isinstance(entry, dict):
                    errors.append(f"{rel} (case {cid}): ref_knowledge 条目不是 mapping")
                    continue
                rid = entry.get("ref")
                if not rid:
                    errors.append(f"{rel} (case {cid}): ref_knowledge 条目缺少 ref")
                    continue
                counts[rid] = counts.get(rid, 0) + 1
                if rid not in ref_ids:
                    errors.append(
                        f"{rel} (case {cid}): ref_knowledge.ref '{rid}' 不存在于 references/（悬挂引用）"
                    )
                role = entry.get("role")
                if role is not None and role not in VALID_ROLES:
                    errors.append(
                        f"{rel} (case {cid}): ref_knowledge.role '{role}' 非法"
                        f"（合法: {', '.join(sorted(VALID_ROLES))}）"
                    )
    return counts, errors


# skill 侧 ref-id 绑定（EV-2026-037）：`<skill>/references/*-gates.yaml` 把
# 「category → 采集面词条」的绑定从 SKILL 散文搬成数据。校验：**至少一个绑定文件存在**
# （约定后缀发现——删掉文件不等于检查静默消失）+ 结构合法 + 每个 id 存在且 active。
SKILL_BINDING_GLOB = "skills/**/references/*-gates.yaml"
VALID_GATE_KINDS = {"probe", "conditional", "procedure"}
FALLBACK_CATEGORIES = {"interrupt", "precision", "performance"}


def is_entry_file(path: Path) -> bool:
    """词条文件判定：跳过 `_` 前缀（`_types.yaml` 与生成物）与生成物分片目录。

    为什么单列一个函数而不是在两处各写一遍 `startswith("_")`：分片目录
    （`_procedure-index/`）是**本仓唯一一处"生成物在子目录里"**——原先只判文件名前缀，
    它一出现就被当成词条文件校验（21 处"缺少 id/type/title…"），而真正的修法不是把
    这些报错逐个压掉，是让"什么算词条"只有一处定义。"""
    if path.name.startswith("_"):
        return False
    return not any(part.startswith("_") for part in path.parts[:-1])


def legal_categories(root: Path) -> set:
    """合法 category 取值 = triage-tree 性质层的取值（单一数据源，防手写集合漂移）。

    category 是闸门与词条加载的检索键——拼错一个字母会让闸门静默不触发、
    或让词条在对应类别下静默不加载，两者都是无声失效，必须机械校验。"""
    doc = load_yaml(root / "triage-tree.yaml")
    cats = set()
    if isinstance(doc, dict):
        # 顶层键是 `sides:`（侧，不带 category）与 `natures:`（性质，带 category）。
        # 退休的 `branches:` 桶读起来会静默返回空集，然后整批校验退回 FALLBACK——
        # 那正是"拼错一个字母却没人报"的形态，所以这里点名读 `natures`。
        for b in doc.get("natures") or []:
            if isinstance(b, dict) and b.get("category"):
                cats.add(str(b["category"]))
    return cats or set(FALLBACK_CATEGORIES)


def check_skill_ref_bindings(root: Path, ref_ids: set, active_ids: set, legal_cats: set):
    """校验 skill 支撑文件里的 ref-id 绑定（防悬挂引用 + 防引用非 active 词条）。

    未验证的先验不进诊断上下文——绑定指向 draft/pending-review/deprecated 词条
    与悬挂引用同样危险（前者会把未审内容带进流程），两者都红。"""
    errors = []
    files = sorted(root.glob(SKILL_BINDING_GLOB))
    if not files:
        return [f"未找到 skill 侧绑定文件（约定 {SKILL_BINDING_GLOB}）——绑定表缺失不应静默通过"]
    for path in files:
        rel_file = str(path.relative_to(root))
        doc = load_yaml(path)
        if isinstance(doc, dict) and doc.get("__yaml_error__"):
            errors.append(f"{rel_file}: YAML 解析失败: {doc['__yaml_error__']}")
            continue
        if not isinstance(doc, dict) or not isinstance(doc.get("gates"), list) or not doc.get("gates"):
            errors.append(f"{rel_file}: 缺少非空 gates 列表")
            continue
        seen_gate_ids = set()
        for i, gate in enumerate(doc["gates"]):
            if not isinstance(gate, dict):
                errors.append(f"{rel_file}: gates[{i}] 不是 mapping")
                continue
            gid = gate.get("id")
            if not gid:
                errors.append(f"{rel_file}: gates[{i}] 缺少 id")
                gid = f"gates[{i}]"
            elif gid in seen_gate_ids:
                errors.append(f"{rel_file}: gate id '{gid}' 重复")
            else:
                seen_gate_ids.add(gid)
            # category 单值 / categories 列表两种写法（2026-09 加列表）：一个闸门可能对多个
            # category 都成立（如"已有 profiling 产物时读哪一份"同时服务 performance 与 precision）。
            # 与其复制两份闸门（两份必漂移），不如让数据形态直接表达"多类别共用"。
            cat = gate.get("category")
            cats = gate.get("categories")
            if cat and cats:
                errors.append(f"{rel_file} ({gid}): category 与 categories 只能给一个（避免两份真值）")
            declared = cats if cats else ([cat] if cat else [])
            if not declared:
                errors.append(f"{rel_file} ({gid}): 缺少 category（或 categories）")
            elif not isinstance(declared, list):
                errors.append(f"{rel_file} ({gid}): categories 必须是列表")
            else:
                for c in declared:
                    if c not in legal_cats:
                        errors.append(
                            f"{rel_file} ({gid}): category '{c}' 不在 triage-tree 取值内"
                            f"（{'/'.join(sorted(legal_cats))}）——拼错会让闸门静默不触发"
                        )
            kind = gate.get("kind")
            if kind not in VALID_GATE_KINDS:
                errors.append(
                    f"{rel_file} ({gid}): kind '{kind}' 非法"
                    f"（合法: {', '.join(sorted(VALID_GATE_KINDS))}）"
                )
            elif kind == "procedure":
                # procedure 闸门 = 方法缺口消费点（EV-2026-038）。形态与 probe/conditional 不同：
                # **不在闸门里写症状关键词分支**——症状→流程的选择由词条自身的 title/summary
                # 经流程索引承担（关键词写在闸门里 = 与 triage-tree 双源，必漂移）。
                # 因此这里校验三件：load 必须 full、selector 必须存在、trigger 必填。
                if gate.get("question"):
                    errors.append(f"{rel_file} ({gid}): kind=procedure 不应有 question（不是探询型）")
                if not gate.get("trigger"):
                    errors.append(f"{rel_file} ({gid}): kind=procedure 必须给 trigger（何时该加载流程）")
                if gate.get("load") != "full":
                    errors.append(
                        f"{rel_file} ({gid}): kind=procedure 必须 load: full——"
                        f"摘要行不承载判据（实测与不加载等效，决定性规则会被截断）"
                    )
                sel = gate.get("selector")
                if not sel:
                    errors.append(f"{rel_file} ({gid}): kind=procedure 必须给 selector（流程索引路径）")
                elif not (root / str(sel)).exists():
                    errors.append(f"{rel_file} ({gid}): selector '{sel}' 不存在（索引未生成？）")
            else:
                q = gate.get("question")
                if kind == "probe" and not q:
                    errors.append(f"{rel_file} ({gid}): kind=probe 必须给 question（探询型闸门的形态就是问一句）")
                if q is not None and not isinstance(q, str):
                    errors.append(f"{rel_file} ({gid}): question 只能是字符串或省略（不要写 null 占位）")
                # conditional 允许带 question（2026-09 解禁，原规则是「条件型不预先问」→ 写成了
                # 「不许有 question」，把**时机**约束错当成**存在**约束）：两种形态的区别是
                # **何时问**，不是**有没有问**——probe 在候选加载后立刻问，conditional 只在缺口
                # 出现时才问。源码位置发现正是后者：只有走到源码分析、且候选 ≥2 时才需要问，
                # 而那一刻它必须有一句能照问的话（否则 agent 现场自己编，问句质量无从校验）。
            if kind == "procedure":
                # procedure 闸门不做 refs 绑定（选择器产出的是"本轮该读哪条流程"，非预置清单）
                for rid in gate.get("caveat_refs") or []:
                    if rid not in ref_ids:
                        errors.append(f"{rel_file} ({gid}): caveat_ref '{rid}' 不存在于 references/（悬挂引用）")
                    elif rid not in active_ids:
                        errors.append(f"{rel_file} ({gid}): caveat_ref '{rid}' 非 status: active")
                continue
            branches = gate.get("branches")
            if not isinstance(branches, list) or not branches:
                errors.append(f"{rel_file} ({gid}): 缺少非空 branches 列表")
                continue
            for j, br in enumerate(branches):
                if not isinstance(br, dict):
                    errors.append(f"{rel_file} ({gid}): branches[{j}] 不是 mapping")
                    continue
                when = br.get("when", f"branches[{j}]")
                if not br.get("when"):
                    errors.append(f"{rel_file} ({gid}): branches[{j}] 缺少 when")
                refs = br.get("refs")
                if not isinstance(refs, list) or not refs:
                    errors.append(f"{rel_file} ({gid}/{when}): refs 必须是非空列表")
                    continue
                for rid in refs:
                    if rid not in ref_ids:
                        errors.append(
                            f"{rel_file} ({gid}/{when}): ref '{rid}' 不存在于 references/（悬挂引用）"
                        )
                    elif rid not in active_ids:
                        errors.append(
                            f"{rel_file} ({gid}/{when}): ref '{rid}' 非 status: active"
                            f"（未验证的先验不进诊断上下文）"
                        )
            for rid in gate.get("caveat_refs") or []:
                if rid not in ref_ids:
                    errors.append(f"{rel_file} ({gid}): caveat_ref '{rid}' 不存在于 references/（悬挂引用）")
                elif rid not in active_ids:
                    errors.append(f"{rel_file} ({gid}): caveat_ref '{rid}' 非 status: active")
    return errors


def check_related_references(root: Path, ref_ids: set, errors: list):
    """`related_references` 必须指向真实存在的词条 id（防悬挂）。

    为什么值得一道门：这个字段是"词条之间不合并、只互链"的落地（relate-don't-merge），
    也是错误码表在**缺行**时唯一的跳板来源。实测 6 处悬挂（如
    `op-internal-sync-and-reduction-fault-patterns` 真 id 是 `op-internal-sync-and-reduction`）
    ——悬挂的链接不会报错，只是点不动：读者按它去找，得到的是一次静默失败。"""
    refs_dir = root / "references"
    for path in sorted(refs_dir.rglob("*.yaml")):
        if not is_entry_file(path):
            continue
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            continue
        rel = path.relative_to(root).as_posix()
        for rid in doc.get("related_references") or []:
            if rid not in ref_ids:
                errors.append(
                    f"{rel}: related_references 里的 '{rid}' 不存在于 references/（悬挂引用——点不动）"
                )
    return errors


def check_error_gap_views(root: Path, errors: list):
    """错误码缺口的两个视图必须一致：族内视图（`content.code_gaps`）⊆ 生成索引（`_code-gaps.yaml`）。

    为什么需要：族内视图让"在这个族里没查到"的当下就能看到"这个码我知道但官方表没有行"，
    它离读者最近；生成索引是完整台账。两份表达同一件事——手工维护的那一份（族内）一旦与
    生成的台账漂移，最小代价的修法不是"记得两边都改"，是让它红。方向只查**族内 ⊆ 台账**：
    族内视图是**节选**（只收本族的码），比台账少是正常的，多出来才是漂移。"""
    gap_path = root / "references" / "errors" / "_code-gaps.yaml"
    if not gap_path.exists():
        errors.append("references/errors/_code-gaps.yaml 不存在——运行 scripts/build_error_gap_index.py 生成")
        return errors
    index = load_yaml(gap_path)
    known = {}
    if isinstance(index, dict):
        for g in index.get("code_gaps") or []:
            if isinstance(g, dict) and g.get("code"):
                known[str(g["code"])] = g
        for g in index.get("no_home") or []:
            if isinstance(g, dict) and g.get("code"):
                known.setdefault(str(g["code"]), None)
    for path in sorted((root / "references" / "errors").glob("*.yaml")):
        if not is_entry_file(path):
            continue
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            continue
        rel = path.relative_to(root).as_posix()
        for i, g in enumerate(((doc.get("content") or {}).get("code_gaps") or [])):
            if not isinstance(g, dict) or not g.get("code"):
                errors.append(f"{rel}: content.code_gaps[{i}] 缺少 code")
                continue
            code = str(g["code"])
            if not (g.get("seen_in") or g.get("no_home")):
                errors.append(
                    f"{rel}: content.code_gaps[{i}]（{code}）既没给 seen_in 也没标 no_home——"
                    f"缺行条目必须指向一个能看的地方，否则与「没有」同形"
                )
            if code not in known:
                errors.append(
                    f"{rel}: content.code_gaps 里的 {code} 不在 references/errors/_code-gaps.yaml"
                    f"（生成索引）中——两个视图漂移了，补进索引或重跑 build_error_gap_index.py"
                )
    return errors


def check_tool_binding_coverage(root: Path, errors: list):
    """**覆盖环**：每条声明了 category 的 active tool 词条，必须被某个诊断闸门绑定。

    为什么需要：tool 类词条不进候选路由（它们不是 case），背景 summary 层也不按工具名
    收窄到"该跑哪条命令"——**闸门绑定是它们进诊断上下文的唯一入口**。于是"某条工具词条
    没被任何闸门引用"在运行时的唯一表现就是它永远不出现，而没有任何信号会报这件事：
    `check_skill_ref_bindings` 只查"被引用的是否存在且 active"（方向相反）。
    实测（2026-09）38 条 tool 词条里 10 条 interrupt、14 条 performance 未绑定任何闸门——
    其中包含取调用栈、看日志配置、多机网络诊断这类现场最常用的手段。

    边界如实标注（原则十）：本检查保证"有入口"，**不保证入口在对的分支上**（分支语义
    是人的判断）；也不检查非 tool 类词条的消费路径（它们的入口形态不同）。"""
    refs_dir = root / "references"
    bound = set()
    declared = {}          # tool id -> 声明的 categories（供报错时指出该往哪个 category 挂）
    for path in sorted(root.glob(SKILL_BINDING_GLOB)):
        doc = load_yaml(path)
        if not isinstance(doc, dict):
            continue
        for gate in doc.get("gates") or []:
            if not isinstance(gate, dict):
                continue
            for br in gate.get("branches") or []:
                if isinstance(br, dict):
                    bound.update(br.get("refs") or [])
            bound.update(gate.get("caveat_refs") or [])
            bound.update(gate.get("refs") or [])
    for path in sorted((refs_dir / "tools").glob("*.yaml")) if (refs_dir / "tools").exists() else []:
        doc = load_yaml(path)
        if not isinstance(doc, dict) or doc.get("status") != "active":
            continue
        cats = (doc.get("applies_to") or {}).get("categories") or []
        if not cats:
            # 没声明 category 的工具词条无法被"按 category 触发"的闸门取到——它自己就该红。
            errors.append(
                f"{path.relative_to(root)}: tool 词条未声明 applies_to.categories——"
                f"闸门按 category 触发，未声明 = 没有任何触发点能取到它"
            )
            continue
        declared[doc.get("id")] = cats
    for tid, cats in sorted(declared.items()):
        if tid not in bound:
            errors.append(
                f"tool 词条 '{tid}'（categories: {'/'.join(cats)}）未被任何诊断闸门绑定——"
                f"闸门是工具词条进诊断上下文的唯一入口，未绑定等于永不加载。"
                f"在 skills/diagnose/references/collect-gates.yaml 的对应 category 分支里挂上"
            )
    return errors


def check_reference(path: Path, refs_dir: Path, types_registry: dict, case_ref_counts: dict,
                    errors: list, legal_cats: set):
    rel = str(path.relative_to(refs_dir))
    doc = load_yaml(path)
    if isinstance(doc, dict) and doc.get("__yaml_error__"):
        errors.append(f"{rel}: YAML 解析失败: {doc['__yaml_error__']}")
        return
    if not isinstance(doc, dict) or not doc:
        errors.append(f"{rel}: 文件为空或不是 mapping")
        return

    rid = doc.get("id")
    if not rid:
        errors.append(f"{rel}: 缺少 id")

    rtype = doc.get("type")
    if not rtype:
        errors.append(f"{rel}: 缺少 type")
    elif rtype not in types_registry:
        errors.append(f"{rel}: type '{rtype}' 未登记于 references/_types.yaml")

    for field in ("title", "summary"):
        if not doc.get(field):
            errors.append(f"{rel}: 缺少 {field}")

    if not doc.get("last_verified"):
        errors.append(f"{rel}: 缺少 last_verified（人审日期，不可自动戳）")

    status = doc.get("status")
    if not status:
        errors.append(f"{rel}: 缺少 status")
    elif status not in VALID_STATUSES:
        errors.append(f"{rel}: status '{status}' 非法（合法: {', '.join(sorted(VALID_STATUSES))}）")

    # applies_to.categories 取值校验（EV-2026-037）：该字段自 2.5 ② 起参与加载收窄
    # （`_summary-index.yaml` 行携带它）——拼错一个字母会让词条在对应类别下**静默不加载**，
    # 是无声失效，必须机械校验。platforms 无注册表（自由取值），暂不校验（记入遗留）。
    ap = doc.get("applies_to")
    if isinstance(ap, dict) and ap.get("categories") is not None:
        cats = ap.get("categories")
        if not isinstance(cats, list):
            errors.append(f"{rel}: applies_to.categories 必须是列表")
        else:
            for c in cats:
                if c not in legal_cats:
                    errors.append(
                        f"{rel}: applies_to.categories 含 '{c}'——不在 triage-tree 取值内"
                        f"（{'/'.join(sorted(legal_cats))}）；拼错会让该词条静默不加载"
                    )

    # ---- sources ----
    sources = doc.get("sources")
    if not sources:
        errors.append(f"{rel}: 缺少 sources（reference 必须有出处，孤立词条不入库）")
    elif not isinstance(sources, list):
        errors.append(f"{rel}: sources 必须是列表")
    else:
        for i, src in enumerate(sources):
            if not isinstance(src, dict):
                errors.append(f"{rel}: sources[{i}] 不是 mapping")
                continue
            stype = src.get("type")
            if not stype:
                errors.append(f"{rel}: sources[{i}] 缺少 type")
                continue
            if stype not in VALID_SOURCE_TYPES:
                errors.append(f"{rel}: sources[{i}].type '{stype}' 非法")
                continue
            for req in SOURCE_REQUIRED[stype]:
                if not src.get(req):
                    errors.append(f"{rel}: sources[{i}]（{stype}）缺少 {req}")
            # official-doc url 语义是"来源定位符"（ADR-0008 §4.2）：公开 URL 优先，
            # 无公开 URL 时用可移植文档引用（标题+出品方+版本）。
            # 机器特定路径（~/ 或绝对路径）禁止入仓——违反可移植性，且对仓库读者无效。
            if stype == "official-doc":
                u = src.get("url") or ""
                if u.startswith(("~/", "/", "C:\\", "D:\\", "E:\\")):
                    errors.append(
                        f"{rel}: sources[{i}].url 是机器特定路径（'{u}'）——"
                        f"用可移植文档引用（标题+出品方+版本），禁止本地路径（ADR-0008 §4.2）"
                    )
            # verification 是可选字段（ADR-0008 §4.2）：填了必须合法，不填不报错
            verification = src.get("verification")
            if verification is not None and verification not in VALID_VERIFICATIONS:
                errors.append(
                    f"{rel}: sources[{i}].verification '{verification}' 非法"
                    f"（合法: {', '.join(sorted(VALID_VERIFICATIONS))}）"
                )

    # ---- 按 type 的 content 强校验（schema_required）----
    if rtype and rtype in types_registry:
        required = types_registry[rtype].get("schema_required", [])
        content = doc.get("content")
        if not isinstance(content, dict):
            errors.append(f"{rel}: 缺少 content（type '{rtype}' 必须有内容字段）")
        else:
            for key in required:
                val = content.get(key)
                if val is None or val == "" or val == []:
                    errors.append(f"{rel}: content.{key} 缺失（type '{rtype}' 必填）")
            # methodology 特殊：flow 必须 ≥1 步
            if rtype == "methodology":
                flow = content.get("flow")
                if not isinstance(flow, list) or len(flow) == 0:
                    errors.append(f"{rel}: content.flow 必须是非空步骤列表（methodology）")
                if not doc.get("applies_to", {}).get("categories"):
                    errors.append(f"{rel}: applies_to.categories 缺失（methodology 必须声明适用问题类别）")
            # error-code 表形态（ADR-0008 §1.5 / §4.3，kind: table）：
            # errors 非空列表，每个条目必填 code+meaning，表内 code 唯一
            # env-var-table 表形态（kind: table）：variables 非空、条目 name+description、表内 name 唯一
            if rtype == "env-var-table":
                entries = content.get("variables")
                if not isinstance(entries, list) or len(entries) == 0:
                    errors.append(f"{rel}: content.variables 必须是非空列表（env-var-table 表形态，按模块成表）")
                else:
                    seen_names = set()
                    for j, e in enumerate(entries):
                        if not isinstance(e, dict):
                            errors.append(f"{rel}: content.variables[{j}] 不是 mapping")
                            continue
                        name = e.get("name")
                        if not name:
                            errors.append(f"{rel}: content.variables[{j}] 缺少 name")
                        else:
                            if name in seen_names:
                                errors.append(f"{rel}: content.variables[{j}].name '{name}' 表内重复")
                            seen_names.add(name)
                        if not e.get("description"):
                            errors.append(f"{rel}: content.variables[{j}]（{name or '?'}）缺少 description")
            # compat-matrix 表形态（kind: table）：分层成表——表级 layer（base/adapter/framework）
            # + component（主组件名）必填；matrix 非空、条目含 version（主组件版本，表内唯一）+
            # 至少一个依赖组件版本字段（torch_npu/torch/cann/hdk 等）
            if rtype == "compat-matrix":
                layer = content.get("layer")
                if layer not in ("base", "adapter", "framework"):
                    errors.append(f"{rel}: content.layer 必须为 base/adapter/framework（分层成表，不重复声明更底层内容）")
                if not content.get("component"):
                    errors.append(f"{rel}: content.component 缺失（主组件名，如 torch-npu / vllm-ascend）")
                entries = content.get("matrix")
                if not isinstance(entries, list) or len(entries) == 0:
                    errors.append(f"{rel}: content.matrix 必须是非空列表（compat-matrix 表形态，分层成表）")
                else:
                    seen_versions = set()
                    dep_fields = ("torch_npu", "torch", "cann", "hdk", "python", "vllm", "vllm_ascend", "sglang", "transformers", "triton_ascend")
                    for j, e in enumerate(entries):
                        if not isinstance(e, dict):
                            errors.append(f"{rel}: content.matrix[{j}] 不是 mapping")
                            continue
                        version = e.get("version")
                        if not version:
                            errors.append(f"{rel}: content.matrix[{j}] 缺少 version（主组件版本）")
                        else:
                            if version in seen_versions:
                                errors.append(f"{rel}: content.matrix[{j}].version '{version}' 表内重复")
                            seen_versions.add(version)
                        if not any(e.get(f) for f in dep_fields):
                            errors.append(f"{rel}: content.matrix[{j}]（{version or '?'}）缺少依赖组件版本字段（torch_npu/torch/cann/hdk/python/vllm/vllm_ascend/sglang/transformers/triton_ascend）")
                        # 依赖组件版本字段：允许字符串（单个版本）或列表（一对多，如一个 CANN 配多个 HDK）
                        for f in dep_fields:
                            v = e.get(f)
                            if v is not None and not isinstance(v, (str, list)):
                                errors.append(f"{rel}: content.matrix[{j}].{f} 必须是字符串或字符串列表（一对多依赖）")
                            elif isinstance(v, list) and not all(isinstance(x, str) for x in v):
                                errors.append(f"{rel}: content.matrix[{j}].{f} 列表元素必须是字符串")
                # 可选 compat：Y/N 兼容矩阵（行=主组件系列、列=依赖系列）
                compat = content.get("compat")
                if compat is not None:
                    if not isinstance(compat, list) or len(compat) == 0:
                        errors.append(f"{rel}: content.compat 必须是非空列表（Y/N 兼容矩阵，行=主组件系列）")
                    else:
                        for j, row in enumerate(compat):
                            if not isinstance(row, dict):
                                errors.append(f"{rel}: content.compat[{j}] 不是 mapping")
                                continue
                            if not row.get("component"):
                                errors.append(f"{rel}: content.compat[{j}] 缺少 component（主组件系列）")
                            values = {k: v for k, v in row.items() if k != "component"}
                            if not values:
                                errors.append(f"{rel}: content.compat[{j}] 缺少依赖系列列")
                            for k, v in values.items():
                                if v not in ("Y", "N"):
                                    errors.append(f"{rel}: content.compat[{j}].{k} 必须是 Y/N")
            if rtype == "error-code":
                entries = content.get("errors")
                if not isinstance(entries, list) or len(entries) == 0:
                    errors.append(f"{rel}: content.errors 必须是非空列表（error-code 表形态，按组件分族）")
                else:
                    seen_codes = set()
                    for j, e in enumerate(entries):
                        if not isinstance(e, dict):
                            errors.append(f"{rel}: content.errors[{j}] 不是 mapping")
                            continue
                        code = e.get("code")
                        if not code:
                            errors.append(f"{rel}: content.errors[{j}] 缺少 code")
                        else:
                            if code in seen_codes:
                                errors.append(f"{rel}: content.errors[{j}].code '{code}' 表内重复")
                            seen_codes.add(code)
                        if not e.get("meaning"):
                            errors.append(f"{rel}: content.errors[{j}]（{code or '?'}）缺少 meaning")
            # fault-pattern 表形态（kind: table）：patterns 非空、条目 pattern+symptoms 必填、
            # 表内 pattern 唯一、cause 或 fix 至少一个
            if rtype == "fault-pattern":
                entries = content.get("patterns")
                if not isinstance(entries, list) or len(entries) == 0:
                    errors.append(f"{rel}: content.patterns 必须是非空列表（fault-pattern 表形态，按主题域成表）")
                else:
                    seen_patterns = set()
                    for j, e in enumerate(entries):
                        if not isinstance(e, dict):
                            errors.append(f"{rel}: content.patterns[{j}] 不是 mapping")
                            continue
                        pattern = e.get("pattern")
                        if not pattern:
                            errors.append(f"{rel}: content.patterns[{j}] 缺少 pattern")
                        else:
                            if pattern in seen_patterns:
                                errors.append(f"{rel}: content.patterns[{j}].pattern '{pattern}' 表内重复")
                            seen_patterns.add(pattern)
                        if not e.get("symptoms"):
                            errors.append(f"{rel}: content.patterns[{j}]（{pattern or '?'}）缺少 symptoms（日志 grep 签名）")
                        if not (e.get("cause") or e.get("fix")):
                            errors.append(f"{rel}: content.patterns[{j}]（{pattern or '?'}）缺少 cause 或 fix（至少一个）")

    # ---- 深审：case-derived + methodology ----
    # 门槛计数 = 提炼来源 case 数（sources[].cases 长度），不是 ref_knowledge 派生——
    # 后者是"case 主动引用 reference"（正向关系），前者才是"reference 由几条 case 提炼印证"
    # （提炼来源）。用 ref_knowledge 计数会让所有 case-derived methodology 恒为 0（0 条 case
    # 填过 ref_knowledge），门槛形同虚设/永远不达标（2026-08 转正时发现）。
    # 门槛只约束 case-derived 来源的方法论——official-doc（手册/文档提炼）方法论不适用
    # （2026-08 批量转正官方方法论时误报 5 条修复）。
    if rtype == "methodology" and status == "active":
        has_case_derived = any(
            isinstance(s, dict) and s.get("type") == "case-derived"
            for s in (sources or [])
        )
        if not has_case_derived:
            pass
        else:
            case_derived_total = sum(
                len(s.get("cases") or [])
                for s in (sources or [])
                if isinstance(s, dict) and s.get("type") == "case-derived"
            )
            if case_derived_total < METHODOLOGY_MIN_CASE_REFS:
                errors.append(
                    f"{rel}: case-derived methodology 提炼来源 {case_derived_total} 条 case"
                    f"（需 ≥{METHODOLOGY_MIN_CASE_REFS} 才可 active，计数为 sources[].cases 长度）"
                )


def count_entries(refs_dir: Path) -> int:
    """词条计数（**唯一口径**）：`references/**/*.yaml` 递归，跳过生成物（`_` 前缀文件与 `_` 前缀目录）。

    单独成函数是给"降级路径"复用的：`metrics_health.py` 在子进程跑不动时（受限执行环境）
    需要不启子进程就得到词条数。降级值必须与权威值**同口径**——实测教训：那边自己写了一份
    "只数直接子目录"的规则，漏掉 `references/<type>/<family>/x.yaml` 这一层嵌套，得到 127
    而权威是 130。避免漂移的办法不是"对齐两份规则"，是**只留一份**。
    """
    return len([p for p in refs_dir.rglob("*.yaml") if is_entry_file(p)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="CI 模式（与默认行为一致，对称 build_index）")
    ap.add_argument("--root", default=None, help="仓库根目录（默认：脚本上两级）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    refs_dir = root / "references"
    if not refs_dir.exists():
        print(f"references/ 不存在 —— 阶段 2 骨架未落地？")
        sys.exit(1)

    types_path = refs_dir / "_types.yaml"
    types_doc = load_yaml(types_path)
    types_registry = types_doc.get("types", {}) if isinstance(types_doc, dict) else {}
    if not types_registry:
        print(f"FATAL: references/_types.yaml 无法解析或 types 为空")
        sys.exit(1)

    # 1) reference 词条 ID 集 + active 集（先于 case/skill 侧校验；_types.yaml 不是词条）
    ref_ids = set()
    active_ids = set()
    for path in sorted(refs_dir.rglob("*.yaml")):
        if not is_entry_file(path):      # 生成物 / 下划线目录非词条
            continue
        doc = load_yaml(path)
        rid = doc.get("id") if isinstance(doc, dict) else None
        if rid:
            ref_ids.add(rid)
            if doc.get("status") == "active":
                active_ids.add(rid)

    # 2) case 侧 ref_knowledge：派生计数（深审用）+ ref 存在性/role 合法性强校验
    case_ref_counts, case_errors = check_case_ref_links(root, ref_ids)

    # 3) skill 侧绑定：采集闸门表里的 ref-id 必须存在且 active；category 取值合法
    legal_cats = legal_categories(root)
    errors = list(case_errors) + check_skill_ref_bindings(root, ref_ids, active_ids, legal_cats)
    # 3b) 覆盖环（方向相反的那一半）：每条声明了 category 的 tool 词条都要有闸门入口——
    #     "引用了不存在的东西"（3 查）与"存在但没人引用"（3b 查）是两种不同的静默失效
    errors += check_tool_binding_coverage(root, [])
    # 3c) related_references 悬挂：互链是"缺行时的跳板"的来源，断了只是静默点不动
    errors = check_related_references(root, ref_ids, errors)
    # 3d) 错误码缺口的两个视图（族内节选 vs 生成台账）不得漂移
    errors = check_error_gap_views(root, errors)
    seen_ids = {}
    for path in sorted(refs_dir.rglob("*.yaml")):
        if not is_entry_file(path):
            continue
        rel = str(path.relative_to(refs_dir))
        doc = load_yaml(path)
        rid = doc.get("id") if isinstance(doc, dict) else None
        if rid:
            if rid in seen_ids:
                errors.append(f"{rel}: id '{rid}' 与 {seen_ids[rid]} 重复")
            else:
                seen_ids[rid] = rel
        check_reference(path, refs_dir, types_registry, case_ref_counts, errors, legal_cats)

    if errors:
        print(f"references 校验失败（{len(errors)} 处）：")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    n = count_entries(refs_dir)
    print(f"references 校验通过（{n} 个词条，id 全部唯一）")


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
