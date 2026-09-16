#!/usr/bin/env python3
# verify_case_draft.py —— case 草稿/知识库的结构校验（无 checker 的缺口补位）
#
# 为什么需要（实测缺口）：to-postmortem 的流程里有「步骤 4 语义校验」，但**没有对应的
# 确定性工具**——本次写 VLLM-ASC-12430 草稿时，写侧连犯三类字段级错误且都逃过了产出：
#   ① 正文里把 CANN 打成 "CANNN"（错别字，任何检查都不看正文）；
#   ② YAML 双引号标量里内嵌裸 `"`，整份草稿解析失败——直到 groom 才发现；
#   ③ `diagnosis` 漏了「前提核验」这一步，是复核时补的，不是写时被拦下的。
# 三类的共同点：**机械可判、且确定性影响下游**（解析失败 → 索引重建整条链红；
# 字段缺失/枚举错 → 阶段一筛不到、阶段二判不了）。CI 的 build_index 只在 case 进
# knowledge/ 后才会解析它，草稿在 inbox 期间完全没有门。
#
# 本脚本补的就是这段：草稿（inbox）与正式库（knowledge/）同一套判据。
#
# 判据（只做机械可判项，判断性的不碰——原则六）：
#   P0 解析：YAML 可解析（解析失败即红）
#   P0 结构：顶层 cases 为非空 list；每条含必需字段；字段非空
#   P0 枚举：category / severity / fix_type 取值合法
#   P0 交叉：ref_knowledge 的 ref 必须存在于 references/ 且 status: active；role 合法
#   P0 判别式：quickly_check.primary 必须有 command_template 与 expected；
#              expected 的 `regex:` 部分必须可编译；不得含空分支（如 `foo|`——恒真，
#              会让该 case 对任何输入都成为候选，实测 VLLM-ASC-11312 即此形态）
#   P1 诊断：diagnosis 为非空 list，每步含 check
#
# 用法：
#   python3 scripts/verify_case_draft.py <file-or-dir> [...]   # 校验指定草稿/目录
#   python3 scripts/verify_case_draft.py --all                 # 校验 knowledge/ 全库
#   python3 scripts/verify_case_draft.py --all --check         # 同（CI 模式，对称其余校验脚本）
#
# 退出码：0 = 全通过；1 = 有 P0 失败；2 = 仅 P1 提示
#
# 依赖：PyYAML

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml  # noqa: F401
except ImportError:
    sys.exit("需要 PyYAML：pip install pyyaml")

from _yaml import load_file  # noqa: E402  （解析后端单一事实源）
from _stdio import pin_utf8_stdio  # noqa: E402
from exec_log_path import resolve_traces  # noqa: E402  （traces/ 锚主检出，worktree 里没有）

VALID_ROLES = {"signature-source", "fix-methodology", "root-cause-context"}
VALID_CATEGORIES = {"interrupt", "precision", "performance"}
VALID_SEVERITIES = {"benign", "service-affecting", "data-loss-risk"}
VALID_FIX_TYPES = {"env-var", "config-change", "code-patch", "pending-investigation"}

REQUIRED_FIELDS = ("id", "title", "category", "symptoms", "quickly_check",
                   "diagnosis", "root_cause", "fix", "severity", "fix_type")

# 升格闸门（EV-2026-097）：自诊断 case 默认须反馈闭环，未闭环则只认强外部证据并走 owner 双签。
# 为什么按来源分：issue-ingest 管道 case 的"闭环"是维护者结论 / fix PR 已经替它确认过
# （其 verification 档位即证明），现场没有 session 可闭环；自诊断 case 没有任何外部验证，
# 纯推断档（investigation）升格等于把猜测写进知识库。
STRONG_EVIDENCE = {"upstream-fix-merged", "upstream-maintainer-confirmed",
                   "upstream-official-doc", "engineer-report"}
WEAK_EVIDENCE = {"investigation", None, ""}


def load_reference_index(root: Path):
    """references/ 下所有词条的 id → (status, path)。用于校验 ref_knowledge 悬挂/非 active。"""
    index = {}
    refs = root / "references"
    if not refs.is_dir():
        return index
    for path in sorted(refs.rglob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            data = load_file(path)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("id") and data.get("type"):
            index[data["id"]] = (data.get("status"), path)
    return index


def check_regex(expected: str, where: str, fail):
    """expected 形如 `regex:<pat>`；校验可编译且无空分支（空分支恒真）。"""
    if not isinstance(expected, str) or not expected.strip():
        fail(f"{where}: expected 为空")
        return
    pat = expected[len("regex:"):] if expected.startswith("regex:") else expected
    try:
        re.compile(pat)
    except re.error as exc:
        fail(f"{where}: expected 的 regex 不可编译（{exc}）：{expected!r}")
        return
    # 空分支：顶层或分组内的 `|` 两侧为空，如 `foo|`、`a|b|`、`(|x)`
    if re.search(r"(\|(?=[|)])|(?<=[|(])\|)", pat) or pat.endswith("|"):
        fail(f"{where}: expected 含空分支（恒真，会让该 case 对任何输入都成为候选）：{expected!r}")


def check_case(case, path: Path, ref_index: dict, fail, warn):
    cid = case.get("id") or "<无 id>"
    where = f"{path.name}#{cid}"

    for field in REQUIRED_FIELDS:
        if field not in case or case[field] in (None, "", [], {}):
            fail(f"{where}: 缺必需字段或为空 `{field}`")

    if case.get("category") not in VALID_CATEGORIES:
        fail(f"{where}: category 非法 `{case.get('category')}`（合法：{sorted(VALID_CATEGORIES)}）")
    if case.get("severity") not in VALID_SEVERITIES:
        fail(f"{where}: severity 非法 `{case.get('severity')}`（合法：{sorted(VALID_SEVERITIES)}）")
    if case.get("fix_type") not in VALID_FIX_TYPES:
        fail(f"{where}: fix_type 非法 `{case.get('fix_type')}`（合法：{sorted(VALID_FIX_TYPES)}）")

    qc = case.get("quickly_check")
    if isinstance(qc, dict):
        for key in ("primary", "fallback"):
            branch = qc.get(key)
            if branch is None:
                if key == "primary":
                    fail(f"{where}: quickly_check 缺 primary")
                continue
            if not isinstance(branch, dict):
                fail(f"{where}: quickly_check.{key} 不是映射")
                continue
            for sub in ("command_template", "expected"):
                if not branch.get(sub):
                    fail(f"{where}: quickly_check.{key} 缺 `{sub}`")
            if branch.get("expected"):
                check_regex(branch["expected"], f"{where} quickly_check.{key}", fail)
    elif "quickly_check" in case:
        fail(f"{where}: quickly_check 不是映射")

    steps = case.get("diagnosis")
    if isinstance(steps, list):
        if not steps:
            fail(f"{where}: diagnosis 为空")
        for i, step in enumerate(steps, 1):
            # 步骤有两种形态：判别式（check）与命令式（command_template + expected），
            # 允许任一种；两者都没有才是空步。schema 见 CLAUDE.md 的 case schema 节。
            if not isinstance(step, dict):
                fail(f"{where}: diagnosis 第 {i} 步不是映射")
                continue
            if not any(step.get(k) for k in ("check", "command_template", "expected")):
                fail(f"{where}: diagnosis 第 {i} 步既无 `check` 也无 `command_template`/`expected`（空步）")
    elif "diagnosis" in case:
        fail(f"{where}: diagnosis 不是列表")

    for entry in case.get("ref_knowledge") or []:
        if not isinstance(entry, dict):
            fail(f"{where}: ref_knowledge 条目不是映射")
            continue
        rid, role = entry.get("ref"), entry.get("role")
        if role not in VALID_ROLES:
            fail(f"{where}: ref_knowledge role 非法 `{role}`（合法：{sorted(VALID_ROLES)}）")
        if rid not in ref_index:
            fail(f"{where}: ref_knowledge 悬挂引用 `{rid}`（references/ 下无此 id）")
        elif ref_index[rid][0] != "active":
            fail(f"{where}: ref_knowledge 指向非 active 词条 `{rid}`（status={ref_index[rid][0]}）")


def case_source_session_of(case):
    """草稿的 source_session；缺则 None（→ 视为管道 case，升格闸门不适用）。"""
    v = case.get("source_session")
    return v if isinstance(v, str) and v else None


def trace_feedback_outcome(root: Path, sid: str):
    """来源 trace 的 feedback.outcome；取不到返回 None。

    traces/ 是 gitignored 的共享运行时件、锚在主检出——worktree 里通常不存在，故必须走
    `resolve_traces()` 解析，不能假定 `<root>/traces/`。
    """
    traces_dir = resolve_traces(root)
    p = Path(traces_dir) / (sid + ".yaml")
    if not p.exists():
        return None
    try:
        d = load_file(p) or {}
    except Exception:
        return None
    return (d.get("feedback") or {}).get("outcome")


def gate_case(case, path: Path, root: Path, fail, warn):
    """升格闸门（EV-2026-097）。返回 'pass' | 'cosign' | 'block' | 'skip'。"""
    cid = case.get("id") or "<无 id>"
    where = f"{path.name}#{cid}"
    sid = case_source_session_of(case)
    if not sid:
        # 管道 case：外部验证已构成闭环证据，闸门不适用（保持既有行为）
        return "skip"

    outcome = trace_feedback_outcome(root, sid)
    ver = (case.get("verification") or {}).get("source")

    if outcome == "resolved":
        return "pass"
    if ver in STRONG_EVIDENCE:
        warn(f"{where}: 自诊断且未闭环（来源 trace feedback.outcome={outcome}），"
             f"但 verification={ver} 属强外部证据档 → **需 owner 双签**方可升格（C 方案例外）")
        return "cosign"
    fail(f"{where}: 自诊断且未闭环（来源 trace feedback.outcome={outcome}）、verification={ver} 为纯推断档 "
         f"——升格被拦。三选一：① 等 fix 应用且问题消失后把来源 trace 的 feedback.outcome 置 resolved；"
         f"② 补强外部证据（上游 fix PR / 维护者确认 / 官方文档 / 工程师实测回报）；"
         f"③ 走 owner 双签例外。**别把未验证的推断当已验证知识入库。**")
    return "block"


def check_file(path: Path, ref_index: dict, fail, warn):
    try:
        data = load_file(path)
    except Exception as exc:
        fail(f"{path}: YAML 解析失败 —— {exc}")
        return
    if not isinstance(data, dict) or "cases" not in data:
        fail(f"{path}: 顶层缺 `cases` 键")
        return
    cases = data["cases"]
    if not isinstance(cases, list) or not cases:
        fail(f"{path}: `cases` 必须是非空列表")
        return
    for case in cases:
        if not isinstance(case, dict):
            fail(f"{path}: cases 条目不是映射")
            continue
        check_case(case, path, ref_index, fail, warn)


def collect_targets(root: Path, args):
    paths = []
    if args.all:
        paths.extend(sorted((root / "knowledge").rglob("*.yaml")))
    for t in args.targets:
        p = Path(t)
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        if p.is_dir():
            paths.extend(sorted(p.rglob("*.yaml")))
        else:
            paths.append(p)
    # 跳过分片与生成物：knowledge/_index*/ 下是检索视图（文件名如 training__verl.yaml，
    # 不以 `_` 开头，故必须按目录判），不是 case 本体。
    def is_view(p: Path) -> bool:
        return p.name.startswith("_") or any(part.startswith("_index") for part in p.parts)

    return [p for p in paths if not is_view(p)]


def main():
    pin_utf8_stdio()
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="case 草稿/知识库结构校验")
    ap.add_argument("targets", nargs="*", help="草稿文件或目录（缺省配合 --all）")
    ap.add_argument("--all", action="store_true", help="校验 knowledge/ 全库")
    ap.add_argument("--root", default=None, help="仓库根（闸门读 traces/ 用；默认当前目录）")
    ap.add_argument("--check", action="store_true", help="CI 模式（输出口径与其他校验脚本一致）")
    ap.add_argument("--gate", action="store_true",
                    help="升格闸门（用 --root 指定仓库根以读 traces/；默认当前目录）。"
                         "只对带 source_session 的自诊断草稿生效，管道 case 跳过")
    args = ap.parse_args()

    if not args.all and not args.targets:
        ap.error("给至少一个目标，或用 --all")

    targets = collect_targets(root, args)
    targets = [p for p in targets if p.exists()]
    if not targets:
        print("verify_case_draft: 无目标文件（跳过）")
        return 0

    ref_index = load_reference_index(root)
    fails, warns = [], []

    def fail(msg):
        fails.append(msg)

    def warn(msg):
        warns.append(msg)

    for path in targets:
        check_file(path, ref_index, fail, warn)

    # 升格闸门（EV-2026-097）：结构检查之外，另判「自诊断 case 是否够格升格」
    gate_stats = None
    if args.gate:
        gate_root = Path(args.root).resolve() if getattr(args, "root", None) else Path.cwd()
        stats = {"pass": 0, "cosign": 0, "block": 0, "skip": 0}
        for path in targets:
            try:
                data = load_file(path)
            except Exception:
                continue
            for case in (data or {}).get("cases") or []:
                if isinstance(case, dict):
                    stats[gate_case(case, path, gate_root, fail, warn)] += 1
        gate_stats = stats

    for w in warns:
        print(f"  ⚠ {w}")
    for m in fails:
        print(f"  ✗ {m}")

    if gate_stats is not None:
        print(f"  升格闸门：通过 {gate_stats['pass']} · 需双签 {gate_stats['cosign']} · "
              f"拦下 {gate_stats['block']} · 跳过（管道 case）{gate_stats['skip']}")

    if fails:
        print(f"verify_case_draft: {len(fails)} 个问题（{len(targets)} 个文件）")
        return 1
    print(f"verify_case_draft: 通过（{len(targets)} 个文件；references 索引 {len(ref_index)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
