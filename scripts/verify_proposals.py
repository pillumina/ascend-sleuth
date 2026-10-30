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
#   16. predicted_effect 带可复现的测量口径（2026-09-10 补，EV-2026-050）：预测必须配
#       `measure`——command + 期望（expect_exit / expect_stdout 至少一项），或如实声明
#       不可度量（command 缺省 + reason 非空）。与第 15 条对称：trajectory 管"问题的出处
#       （可回放）"，measure 管"预测的出处（可复现）"。缺它则 execution §「评审：30s 判定」
#       无从执行——reviewer 只能读全文或直接批，即该节自陈的失效形态「橡皮图章」。
#       存量卡（MEASURE_CUTOVER 之前创建）豁免：给已完成的决策补一条命令不恢复当时的判断，
#       只造事后叙述（原则十）；缺口由 scripts/ev_measure.py --audit 如实报出，不静默跳过。
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
import subprocess
import sys
from pathlib import Path

from _yaml import load_file   # 解析后端单一事实源（快路径见 _yaml.py）

# 「预测的出处」强制生效日（第 16 条，EV-2026-050 的迁移窗口）：本日及之后创建的卡必须带
# 可复现测量口径。本日之前创建的卡豁免——它们已经是做完的决策，补写命令无法恢复当时的判断。
# 缺口可见性由 scripts/ev_measure.py --audit 提供。存量迁移完成后删除本常量与豁免分支。
MEASURE_CUTOVER = datetime.date(2026, 9, 11)

# 目标组件键的生效日：卡契约里 `target_component` 一直是必填（execution.md），
# 但全库 0 张卡填过它，于是"同组件先例咨询"没有任何可查的键（聚合只能退化到"改动落点"）。
# 与 measure 同一条纪律：**只对生效日之后的卡强制**，存量不追溯（补写会形成事后叙述）。
TARGET_CUTOVER = datetime.date(2026, 9, 17)

# 分支记录与自指度量的生效日：与 measure / target 同一条纪律——只对生效日之后的卡强制，
# 存量不追溯（给旧卡补"当时还考虑过什么"只会造事后叙述，原则十）。
ALTERNATIVES_CUTOVER = datetime.date(2026, 10, 31)
EXTERNAL_CUTOVER = datetime.date(2026, 10, 31)

# 演进流程本身的落点。改这些文件的卡，`measure` 常常只能证明"脚本还能跑"——那不足以证明
# "流程变好了"。所以它们额外要一条独立于该流程的效果信号（predicted_effect.external）。
EVOLUTION_FLOW = {
    "skills/evolve-check/SKILL.md",
    "skills/self-evolve/SKILL.md",
    "scripts/ev_proposal.py",
    "scripts/ev_measure.py",
    "scripts/evolve_mode.py",
    "scripts/evolve_intake.py",
    "scripts/evolve_signals.py",
    "scripts/verify_proposals.py",
    "proposals/signals/README.md",
}

# 占位符检测：产卡骨架（examples/sample-idea.yaml）刻意留占位 measure，让"忘了填"在 CI 上
# 响亮失败，而不是带着一条假命令过审（假 command + 自洽的期望 = 假绿，原则十）。
# 只认显式占位词，不收 `[<>]`——shell 重定向与进程替换（`> out`、`<(a)`）是合法命令形态。
# 残留（如实标注）：一条查无此命令的假 command 结构上合法；`ev_measure --run` 会以
# exit 127 判 FAIL，但 --run 不进 CI——命令是否真在测那件事 = 约定强度。
PLACEHOLDER_RE = re.compile(r"待填|占位|TODO|FIXME|XXX|PLACEHOLDER", re.IGNORECASE)

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

# 倒填检测的余量：长寿命分支上写的卡，created_at 可能早于 PR 基线几条街。
BACKDATE_SLACK_DAYS = 7
REQUIRED = [
    "id", "layer", "title", "status", "authorization", "dimension", "created_at",
    "hypothesis", "validation", "risk", "principle_refs", "decisions",
]
ID_RE = re.compile(r"^EV-\d{4}-\d{3,}$")


def load_yaml(path: Path):
    try:
        return load_file(path)
    except Exception as e:
        return {"__yaml_error__": str(e)}


def as_date(value):
    """YAML 的 date/datetime/str 三种形态 → datetime.date；不可解析返回 None（不猜）。"""
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def exit_code_value(value):
    """expect_exit 归一为 int；bool/None/非数字串 → None（不猜）。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("+-").isdigit():
        return int(value.strip())
    return None


def measure_enforced(doc) -> bool:
    """本卡是否落在「预测必须可复现」的强制范围内（第 16 条的迁移窗口）。"""
    d = as_date(doc.get("created_at"))
    return d is not None and d >= MEASURE_CUTOVER


def check_predicted_effect(doc, rel, errors, enforce: bool):
    """第 16 条：predicted_effect 的出处（可复现）。

    enforce=False（存量卡）时只做形状检查，不要求 measure——豁免是如实可见的，
    不是静默跳过：缺口清单一律由 scripts/ev_measure.py --audit 报出。
    """
    pe = doc.get("predicted_effect")
    if pe is None:
        if enforce:
            errors.append(f"{rel}: 缺 predicted_effect——卡必须写可测预期"
                          "（metric/from/to + measure），否则执行后无可对照（execution §2 信息契约）")
        return
    if not isinstance(pe, dict):
        errors.append(f"{rel}: predicted_effect 必须是 mapping")
        return
    for k in ("metric", "from", "to"):
        v = pe.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            errors.append(f"{rel}: predicted_effect.{k} 缺失或为空"
                          "（metric=测什么，from=改前实测，to=改后应有值）")

    m = pe.get("measure")
    if m is None:
        if enforce:
            errors.append(
                f"{rel}: predicted_effect 缺 measure——预测必须带可复现的测量口径："
                "measure.command 配 expect_exit / expect_stdout 至少一项，"
                "或如实声明不可度量（command 缺省 + reason 非空）。"
                "缺它则「30s 判定」无从执行（reviewer 只能开全文）；"
                "复现方式：python3 scripts/ev_measure.py <card-id>")
        return
    if not isinstance(m, dict):
        errors.append(f"{rel}: predicted_effect.measure 必须是 mapping")
        return

    cmd = m.get("command")
    if isinstance(cmd, str) and cmd.strip():
        if PLACEHOLDER_RE.search(cmd):
            errors.append(f"{rel}: predicted_effect.measure.command 仍是占位符"
                          f"（{cmd.strip()[:60]!r}）——换成真命令；带占位符过审 = 假绿")
        has_expect = (
            exit_code_value(m.get("expect_exit")) is not None
            or (isinstance(m.get("expect_stdout"), str) and m["expect_stdout"].strip())
        )
        if not has_expect:
            errors.append(f"{rel}: predicted_effect.measure 有 command 但无期望——"
                          "没有期望就无法判定符合与否（expect_exit 或 expect_stdout 至少一项）")
    elif cmd is None or (isinstance(cmd, str) and not cmd.strip()):
        reason = m.get("reason")
        if not (isinstance(reason, str) and reason.strip()):
            errors.append(f"{rel}: predicted_effect.measure 既无 command 也无 reason——"
                          "不可度量必须如实声明理由（原则十：诚实退化，不静默留空）")
    else:
        errors.append(f"{rel}: predicted_effect.measure.command 必须是字符串"
                      "（或省略 command 并给 reason 声明不可度量）")


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
    tc = doc.get("target_component")
    created = as_date(doc.get("created_at"))
    if created is not None and created > datetime.date.today():
        errors.append(f"{rel}: created_at 在未来（{created}）——日期是自报的，这条挡掉手误与倒填的反向")
    if created is not None and created >= TARGET_CUTOVER and not (isinstance(tc, str) and tc.strip()):
        errors.append(f"{rel}: 缺 target_component——它是「这个组件改过几次、结局如何」的键"
                      f"（聚合视图 ev_proposal.py --impact 与同组件先例咨询都靠它；"
                      f"生效日 {TARGET_CUTOVER.isoformat()} 之后的卡强制）")
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

    # predicted_effect 的出处（第 16 条）：预测必须可复现，否则不可证伪
    check_predicted_effect(doc, rel, errors, enforce=measure_enforced(doc))

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
    """created_at → 距今天数（int）；不可解析返回 None（不猜、不报假错）。"""
    d = as_date(value)
    if d is None:
        return None
    return ((today or datetime.date.today()) - d).days


def is_backdated(created, base_date, slack_days=BACKDATE_SLACK_DAYS) -> bool:
    """卡是否把 created_at 倒填到基线之前（倒填会绕过各条生效日闸门）。

    强度：**约定**。7 天余量给长寿命分支，不是证明——它让倒填需要理由，而不是让倒填不可能。
    """
    if created is None or base_date is None:
        return False
    return created < base_date - datetime.timedelta(days=slack_days)


def check_backdated_cards(root: Path, base: str, errors: list):
    """PR 里新增的卡不许声称自己写于基线之前太久（`--base <sha>` 时启用）。

    只对"本 PR 新增"的文件判：既有卡的 created_at 是历史，不该被今天的基线重判。
    git 不可用或基线取不到时打印一行说明并跳过——不静默当成通过。
    """
    try:
        r = subprocess.run(["git", "-C", str(root), "diff", "--name-only", "--diff-filter=A",
                            f"{base}...HEAD", "--", "proposals/ideas"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "").strip()[:200])
        added = [ln for ln in r.stdout.splitlines() if ln.endswith(".yaml")]
        r2 = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%cs", base],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r2.returncode != 0 or not r2.stdout.strip():
            raise RuntimeError((r2.stderr or "取不到基线日期").strip()[:200])
        bdate = datetime.date.fromisoformat(r2.stdout.strip())
    except Exception as e:
        print(f"verify_proposals: 跳过倒填检测（{e}）——基线不可达时不一概判绿，也不误报", file=sys.stderr)
        return

    for rel in added:
        f = Path(root) / rel
        d = load_yaml(f)
        created = as_date(d.get("created_at")) if isinstance(d, dict) else None
        if is_backdated(created, bdate):
            errors.append(f"{rel}: created_at {created} 早于基线日期 {bdate} 超过 "
                          f"{BACKDATE_SLACK_DAYS} 天——新增卡倒填日期会绕过生效日闸门"
                          f"（确定写错就改成实际日期；长分支请说明）")


def check_branches_and_self_reference(root: Path, errors: list):
    """跨卡检查：分支记录（alternatives）与演进流程卡的自指度量。

    - 同组件有 rejected / superseded 先例时，新卡必须写清"为什么不重走那条"——否则同一方向
      会被反复重试（先例视图 `ev_proposal.py --impact` 存在，但没人被要求读它的结论）。
    - 改演进流程的卡，`measure` 往往只能证明实现可用；效果必须有流程之外的信号。
    """
    ideas = root / "proposals" / "ideas"
    docs = []
    for f in sorted(ideas.glob("*.yaml")):
        d = load_yaml(f)
        if isinstance(d, dict):
            docs.append((f, d))

    by_target = {}
    for f, d in docs:
        tc = d.get("target_component")
        if isinstance(tc, str) and tc.strip():
            by_target.setdefault(tc.strip(), []).append((f, d))

    for f, d in docs:
        created = as_date(d.get("created_at"))
        alt = d.get("alternatives")

        # 形状：给了就必须是 {option, why_rejected} 列表（evidence 可选）
        if alt is not None:
            if not isinstance(alt, list) or not alt:
                errors.append(f"{f}: alternatives 必须是非空列表")
            else:
                for i, a in enumerate(alt):
                    if not isinstance(a, dict):
                        errors.append(f"{f}: alternatives[{i}] 必须是 mapping")
                        continue
                    for k in ("option", "why_rejected"):
                        if not str(a.get(k) or "").strip():
                            errors.append(f"{f}: alternatives[{i}] 缺 {k}——只有选项、没有"
                                          "否决理由的记录挡不住重试")

        tc = d.get("target_component")
        tc = tc.strip() if isinstance(tc, str) else ""
        if created is None or not tc:
            continue

        # 分支记录：同组件有失败结局的先例
        if created >= ALTERNATIVES_CUTOVER:
            prior = [x for x in by_target.get(tc, [])
                     if x[0] != f and x[1].get("status") in {"rejected", "superseded"}]
            if prior and not (isinstance(alt, list) and alt):
                names = "、".join(x[0].stem for x in prior[:3])
                errors.append(f"{f}: 同组件有失败先例（{names}），缺 alternatives——"
                              "写清「为什么不重走那条」才能过；先例视图 ev_proposal.py --impact")

        # 自指度量：改演进流程的卡要有流程外的效果信号
        if created >= EXTERNAL_CUTOVER and tc in EVOLUTION_FLOW:
            pe = d.get("predicted_effect")
            ext = pe.get("external") if isinstance(pe, dict) else None
            if not str(ext or "").strip():
                errors.append(f"{f}: 改的是演进流程（{tc}），缺 predicted_effect.external——"
                              "measure 只能证明脚本能跑，效果信号要来自流程之外"
                              "（如台账提升率、intake 拒收率、no-signal 比率、单卡合入天数）")
            elif str(ext).strip() == tc:
                errors.append(f"{f}: predicted_effect.external 不能指回被改的组件本身（自指度量不可证伪）")


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
    ap.add_argument("--base", default="",
                    help="PR 基线提交（给了就查新增卡是否倒填日期；push 事件留空跳过）")
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
    check_branches_and_self_reference(root, errors)
    if args.base:
        check_backdated_cards(root, args.base, errors)

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
