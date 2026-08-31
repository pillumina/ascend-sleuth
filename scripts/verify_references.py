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


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return {"__yaml_error__": str(e)}


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
        if path.name == "_index.yaml":
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


def check_reference(path: Path, refs_dir: Path, types_registry: dict, case_ref_counts: dict, errors: list):
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
                    dep_fields = ("torch_npu", "torch", "cann", "hdk", "python")
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
                            errors.append(f"{rel}: content.matrix[{j}]（{version or '?'}）缺少依赖组件版本字段（torch_npu/torch/cann/hdk/python）")
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

    # 1) reference 词条 ID 集（先于 case 侧校验；_types.yaml 不是词条）
    ref_ids = set()
    for path in sorted(refs_dir.rglob("*.yaml")):
        if path.name == "_types.yaml":
            continue
        doc = load_yaml(path)
        rid = doc.get("id") if isinstance(doc, dict) else None
        if rid:
            ref_ids.add(rid)

    # 2) case 侧 ref_knowledge：派生计数（深审用）+ ref 存在性/role 合法性强校验
    case_ref_counts, case_errors = check_case_ref_links(root, ref_ids)

    errors = list(case_errors)
    seen_ids = {}
    for path in sorted(refs_dir.rglob("*.yaml")):
        if path.name == "_types.yaml":
            continue
        rel = str(path.relative_to(refs_dir))
        doc = load_yaml(path)
        rid = doc.get("id") if isinstance(doc, dict) else None
        if rid:
            if rid in seen_ids:
                errors.append(f"{rel}: id '{rid}' 与 {seen_ids[rid]} 重复")
            else:
                seen_ids[rid] = rel
        check_reference(path, refs_dir, types_registry, case_ref_counts, errors)

    if errors:
        print(f"references 校验失败（{len(errors)} 处）：")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    n = len([p for p in refs_dir.rglob("*.yaml") if p.name != "_types.yaml"])
    print(f"references 校验通过（{n} 个词条，id 全部唯一）")


if __name__ == "__main__":
    main()
