#!/usr/bin/env python3
# verify_proposals.py —— 校验 proposals/ideas/ 的 idea 卡结构
#
# 目的（原则二：不变量写进结构）：idea 卡是自演进的知识资产（同 knowledge/ 纪律，
# 随 PR 进出），schema 漂移会让状态机/授权/追溯链失去机器可校验性。把"卡必须记录
# 什么、字段怎么组织"从约定变成 CI 可校验的结构。
#
# 校验内容：
#   1. 文件为合法 YAML mapping
#   2. 必填字段齐全：id/layer/title/status/authorization/dimension/created_at/
#      hypothesis/validation/risk/principle_refs/decisions
#   3. id 匹配 EV-YYYY-NNN 且全局唯一
#   4. status ∈ 合法词表（candidate/proposed/in_experiment/pending_merge/adopted/
#      validated/rolled_back/superseded/rejected/re-iterate + 蓝图态 unconfirmed_valid/
#      unconfirmed/stale——蓝图态触发后启用）
#   5. authorization ∈ {auto, review, dual}
#   6. dimension ∈ {architecture, evolvability, maintainability, observability, process}
#   7. layer ∈ {L1, L2, L3}
#   8. supersedes/superseded_by 引用的卡 id 存在（若填）
#   9. decisions 为列表，元素含 who/when/conclusion（若非空）
#   10. validation.method ∈ {golden_replay, tally_recheck, metrics_compare, issue_replay}
#
# 用法：python3 scripts/verify_proposals.py [--check] [--root <repo>]
# 返回非零 = 校验失败。--check 与默认行为一致（对称 build_index / verify_references / verify_metrics）。

import argparse
import re
import sys
from pathlib import Path

import yaml

VALID_STATUS = {
    "candidate", "proposed", "in_experiment", "pending_merge", "adopted",
    "validated", "rolled_back", "superseded", "rejected", "re-iterate",
    # 蓝图态（pipeline §11.1：触发条件到才启用）
    "unconfirmed_valid", "unconfirmed", "stale",
}
VALID_AUTH = {"auto", "review", "dual"}
VALID_DIM = {"architecture", "evolvability", "maintainability", "observability", "process"}
VALID_LAYER = {"L1", "L2", "L3"}
VALID_METHOD = {"golden_replay", "tally_recheck", "metrics_compare", "issue_replay"}
REQUIRED = [
    "id", "layer", "title", "status", "authorization", "dimension", "created_at",
    "hypothesis", "validation", "risk", "principle_refs", "decisions",
]
ID_RE = re.compile(r"^EV-\d{4}-\d{3,}$")


def load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"__yaml_error__": str(e)}


def check_idea(path: Path, ids: dict, errors: list):
    rel = str(path)
    doc = load_yaml(path)
    if "__yaml_error__" in doc:
        errors.append(f"{rel}: YAML 解析失败: {doc['__yaml_error__']}")
        return
    if not isinstance(doc, dict):
        errors.append(f"{rel}: 顶层必须是 mapping")
        return

    # 必填字段
    for f in REQUIRED:
        if f not in doc:
            errors.append(f"{rel}: 缺必填字段 {f}")
    # id 格式与唯一
    cid = doc.get("id")
    if cid is not None:
        if not ID_RE.match(str(cid)):
            errors.append(f"{rel}: id '{cid}' 不匹配 EV-YYYY-NNN 格式")
        if cid in ids:
            errors.append(f"{rel}: id '{cid}' 重复（已在 {ids[cid]}）")
        else:
            ids[cid] = rel
    # 枚举校验
    if doc.get("status") not in VALID_STATUS:
        errors.append(f"{rel}: status '{doc.get('status')}' 不在合法词表")
    if doc.get("authorization") not in VALID_AUTH:
        errors.append(f"{rel}: authorization '{doc.get('authorization')}' 非法")
    if doc.get("dimension") not in VALID_DIM:
        errors.append(f"{rel}: dimension '{doc.get('dimension')}' 非法")
    if doc.get("layer") not in VALID_LAYER:
        errors.append(f"{rel}: layer '{doc.get('layer')}' 非法（L1/L2/L3）")
    # validation.method
    v = doc.get("validation")
    if isinstance(v, dict) and v.get("method") not in VALID_METHOD:
        errors.append(f"{rel}: validation.method '{v.get('method')}' 非法")
    # decisions 结构
    d = doc.get("decisions")
    if d is not None:
        if not isinstance(d, list):
            errors.append(f"{rel}: decisions 必须是列表")
        else:
            for i, entry in enumerate(d):
                if not isinstance(entry, dict):
                    errors.append(f"{rel}: decisions[{i}] 必须是 mapping")
                else:
                    for k in ("who", "when", "conclusion"):
                        if k not in entry:
                            errors.append(f"{rel}: decisions[{i}] 缺 '{k}'")


def resolve_supersedes(root: Path, errors: list, ids: dict):
    """supersedes/superseded_by 交叉引用校验（须在收集完所有 id 后跑）。"""
    for f in sorted((root / "proposals" / "ideas").glob("*.yaml")):
        doc = load_yaml(f)
        if not isinstance(doc, dict):
            continue
        for ref_field in ("supersedes",):
            refs = doc.get(ref_field)
            if isinstance(refs, list):
                for ref in refs:
                    if ref not in ids:
                        errors.append(f"{f}: supersedes 引用不存在的卡 {ref}")
        sb = doc.get("superseded_by")
        if sb and sb not in ids:
            errors.append(f"{f}: superseded_by 引用不存在的卡 {sb}")


def main():
    ap = argparse.ArgumentParser(description="校验 proposals/ideas/ 的 idea 卡结构")
    ap.add_argument("--check", action="store_true", help="CI 模式（与默认一致）")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args()

    root = args.root.resolve()
    ideas_dir = root / "proposals" / "ideas"
    if not ideas_dir.exists():
        print(f"proposals/ideas/ 不存在（{ideas_dir}）——跳过（未初始化）")
        return

    errors = []
    ids = {}
    for f in sorted(ideas_dir.glob("*.yaml")):
        check_idea(f, ids, errors)
    resolve_supersedes(root, errors, ids)

    if errors:
        print(f"verify_proposals: {len(errors)} 个问题")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    n = len(ids)
    print(f"verify_proposals: OK（{n} 张卡通过校验）")


if __name__ == "__main__":
    main()
