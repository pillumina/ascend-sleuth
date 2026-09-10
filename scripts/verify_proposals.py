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
#   4. status ∈ 合法词表（in_experiment/validated/rejected/superseded——产卡即执行，
#      无 candidate 待办态；EV 卡 = agent 决策档案，不含 git 合入态；v5 词表）
#   5. authorization ∈ {auto, review, dual}
#   6. dimension ∈ {architecture, evolvability, maintainability, observability, process}
#   7. layer ∈ {L1, L2, L3}
#   8. supersedes/superseded_by 引用的卡 id 存在（若填）
#   9. decisions 为列表，元素含 who/when/conclusion（若非空）；type ∈ {proposal, action,
#      eval, decision} 若填（生命周期阶段标注，pipeline §7）
#   10. validation.method ∈ {golden_replay, metrics_compare, issue_replay, scan_review}（2026-09 去 tally_recheck——台账复测已改归因事件复测；scan_review 补"指引面/文档面改动"——不跑检索 golden，scan + 人审，见 evolve-check 分级）
#   11. 生命周期完整性（pipeline §7「生命周期完整性规则」）：
#       - 终态卡（validated/rejected/superseded）必须有 agent 决策记录
#       - validated 后 actual_cost.tokens 必填（成本审计缺口；口径与面板 ev_board_data
#         的 audit_gaps 对齐——面板报的缺口与 CI 报的缺口必须是同一件事）
#       - 终态卡但 decisions 全无 = 审计缺口（卡不完整）
#   12. principle_refs：必须是 1-11 的整数列表（设计原则编号，非中文字符串）
#   13. 在实验卡不完整（2026-09-10 补；对账 evolve-check §3.5「执行或验证完成而卡仍停
#       in_experiment = 卡不完整」——此前 SKILL.md 声称本脚本会报，实际只校验终态卡）：
#       in_experiment 且已记 action **且** eval 但无 decision = 状态未推进 → 报错。
#       只记 action（验证还在跑）是正常中间态，不报——首版写成"action 或 eval"时
#       立刻在产卡当轮的 EV-2026-044 上误报，据此收紧为"两者都完成"。
#   14. 僵尸卡（同上补）：in_experiment 且 created_at 超 STALE_DAYS 仍无 decision → 报错
#       （防卡静默烂在实验态；天数口径与面板 scripts/ev_board_data.py 的 STALE_DAYS 一致）。
#   15. source_signals 溯源齐备：非空列表且每条含 trajectory（卡必须指到本轮执行出处——
#       无出处则无法回放归因，卡就只是叙述）。
#
# CI：kb-checks 的 proposal-audit job 跑本脚本（proposals/** 已在触发路径里）。
# 注意：exec-log（metrics/skill-exec-log.yaml）是 .gitignore 运行时件、CI 上不存在，
# 因此 verify_exec_log.py 不进 CI，改由 evolve-check 收尾自查（见 skills/evolve-check 第 4 步）。
#
# 用法：python3 scripts/verify_proposals.py [--check] [--root <repo>]
# 返回非零 = 校验失败。--check 与默认行为一致（对称 build_index / verify_references / verify_metrics）。

import argparse
import datetime
import re
import sys
from pathlib import Path

import yaml

VALID_STATUS = {
    "in_experiment",              # 产卡即执行（无 candidate 待办态）
    "validated", "rejected", "superseded",
}
VALID_AUTH = {"auto", "review", "dual"}
VALID_DIM = {"architecture", "evolvability", "maintainability", "observability", "process"}
VALID_LAYER = {"L1", "L2", "L3"}
VALID_METHOD = {"golden_replay", "metrics_compare", "issue_replay", "scan_review"}
VALID_DECISION_TYPE = {"proposal", "action", "eval", "decision"}
# 终态卡：生命周期必须闭合（agent 决策记录 + validated 补 actual_cost）
TERMINAL_STATUS = {"validated", "rejected", "superseded"}
# 在实验卡静默超期 = 僵尸卡（口径与面板 scripts/ev_board_data.py 的 STALE_DAYS 一致）
STALE_DAYS = 14
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
    # principle_refs：必须是 1-11 的整数列表（设计原则编号）
    pr = doc.get("principle_refs")
    if pr is not None:
        if not isinstance(pr, list) or not pr:
            errors.append(f"{rel}: principle_refs 必须是非空列表")
        else:
            for x in pr:
                if not isinstance(x, int) or not (1 <= x <= 11):
                    errors.append(f"{rel}: principle_refs 元素 {x!r} 非法——须为 1-11 的整数（设计原则编号）")
    # decisions 结构
    d = doc.get("decisions")
    n_decisions = 0
    if d is not None:
        if not isinstance(d, list):
            errors.append(f"{rel}: decisions 必须是列表")
        else:
            n_decisions = len(d)
            for i, entry in enumerate(d):
                if not isinstance(entry, dict):
                    errors.append(f"{rel}: decisions[{i}] 必须是 mapping")
                else:
                    for k in ("who", "when", "conclusion"):
                        if k not in entry:
                            errors.append(f"{rel}: decisions[{i}] 缺 '{k}'")
                    dt = entry.get("type")
                    if dt is not None and dt not in VALID_DECISION_TYPE:
                        errors.append(f"{rel}: decisions[{i}].type '{dt}' 非法（proposal/action/eval/decision）")

    # source_signals 溯源齐备（卡必须指到本轮执行出处；无出处 = 无法回放归因）
    ss = doc.get("source_signals")
    if not isinstance(ss, list) or not ss:
        errors.append(f"{rel}: source_signals 必须是非空列表（触发信号 + trajectory 出处）")
    else:
        for i, s in enumerate(ss):
            if not isinstance(s, dict):
                errors.append(f"{rel}: source_signals[{i}] 必须是 mapping")
                continue
            if not s.get("trajectory"):
                errors.append(f"{rel}: source_signals[{i}] 缺 trajectory——卡必须指到本轮执行出处"
                              "（产出文件 id / replay 结果 / trace），否则归因无法回放")

    # 生命周期完整性（pipeline §7「生命周期完整性规则」——终态卡必须闭合）
    status = doc.get("status")
    decided_types = {e.get("type") for e in (d or []) if isinstance(e, dict)}
    if status in TERMINAL_STATUS:
        if n_decisions == 0:
            errors.append(f"{rel}: 终态卡（{status}）但 decisions 为空——审计缺口（无 agent 判断结论的终态不可信）")
        elif "decision" not in decided_types:
            errors.append(f"{rel}: 终态卡（{status}）但没有 type: decision 的记录——审计缺口"
                          "（终态必须有一条 agent 判断：采纳/不采纳/换方向 + 依据；"
                          "口径与面板 ev_board_data.audit_gaps 的 no_decision 一致）")
        if status == "validated":
            ac = doc.get("actual_cost")
            tokens = ac.get("tokens") if isinstance(ac, dict) else None
            if tokens is None:
                errors.append(f"{rel}: validated 卡 actual_cost.tokens 未写回——成本审计缺口"
                              "（口径与面板 ev_board_data.audit_gaps 一致：无法量化时写 0 + note 说明口径）")

    # 在实验卡不完整 / 僵尸卡（evolve-check §3.5「卡不完整」的机器可判定形态）
    if status == "in_experiment":
        if {"action", "eval"} <= decided_types and "decision" not in decided_types:
            errors.append(f"{rel}: 卡不完整——已记 action 且 eval 但无 decision，状态仍 in_experiment"
                          "（执行与验证都完成后必须给判断：validated / rejected / superseded）")
        elif "decision" not in decided_types:
            age = age_days(doc.get("created_at"))
            if age is not None and age >= STALE_DAYS:
                errors.append(f"{rel}: 僵尸卡——in_experiment 已 {age} 天（≥{STALE_DAYS}）仍无 decision"
                              "（卡静默烂在实验态；补判断或如实标注未执行）")


def age_days(value, today=None):
    """created_at → 距今天数（int）；不可解析返回 None（不猜、不报假错）。
    YAML 可能给出 date / datetime / str 三种形态，一律归一。"""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        d = value.date()
    elif isinstance(value, datetime.date):
        d = value
    else:
        try:
            d = datetime.date.fromisoformat(str(value)[:10])
        except ValueError:
            return None
    return ((today or datetime.date.today()) - d).days


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
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    main()
