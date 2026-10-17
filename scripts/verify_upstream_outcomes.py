#!/usr/bin/env python3
# verify_upstream_outcomes.py —— 用上游 issue / PR 状态查证案例内容，结局折进 validation_record
#
# 为什么需要它：本仓 3.6 指标表里「外部对照闭环」那一行（docs/mechanism/diagnosis-observability.md）
#   的分母是「有上游关联的案例」，分子要有一处去上游查一次并把结局写回；蓝图项「外部对照自动查证」
#   在同一文档的 5.2（改哪里：新增脚本，复用 gh api 外壳与结算回写通道）。此前 4 处 gh 调用
#   （scripts/auto_fetch.py:56、scripts/fetch_issues.py:50、scripts/s2_calibration.py:274、
#   scripts/ev_proposal.py:334）都读 state，但它们分别服务于拉取、建池与改进项指针，没有一处把
#   上游状态写成诊断结局。
#
# 判据边界（人读输出里也印一遍）：
#   - 判得了的：内容对不对——上游是否确认了这个根因 / 修法（issue 关闭为 completed；PR 已合入；
#     更早关闭、没有关闭原因的 issue 由提交关闭）。
#   - 判不了的：现场是否解决——现场特异性只有现场能给。设计文档 5.3 第 13 条已否决让 agent 自动
#     判定现场结局，所以本脚本的读数与写回都不表达现场结局。
#   - 案例没有 upstream 锚点时报「不可对照」，不猜结局。
#   - 查询失败（无 gh、未登录、网络失败、限流）报「不可查证」，不当负结论（不写 inconsistent）。
#
# 单个锚点的三态：
#   verified      上游确认：issue 关闭为 completed；PR 已合入；旧 issue 由提交关闭
#   denied        上游否定：issue 关闭为 not_planned；PR 已关闭但未合入
#   not_verified  仍是 open——不构成验证
#   unverifiable  取不到，或上游没给关闭原因且探不到关闭它的提交 / PR
#
# 一条案例的收敛（多个锚点时只看最强结局，按案例记一次，不按锚点数累加）：
#   任一锚点 verified → validation_record 的 consistent += 1；锚点是该案例的来源或正文引用时记
#   self_consistent（同一份证据不数两次，与 scripts/settle_s2_feedback.py 的独立判据同条）
#   否则，案例的 verification.source 声明 upstream-fix-merged 而某锚点 denied → inconsistent += 1，
#   退出码 1（案例说修复已合入，上游说不修或 PR 未合入，需人处理）
#   否则 → 不写任何字段（not_verified 与 unverifiable 都不是负结论）
#
# 幂等：游标记在共享运行时件 .settle-state.json 的 _upstream_outcomes 下（与
#   settle_trace_feedback / settle_s2_feedback 同一份文件、同一条落点纪律），键是 case id，
#   值是结局签名（锚点、状态、结局的 hash）。同一结局重复跑不重复累加；结局变了（如 open →
#   closed completed）签名跟着变，这时才再记一次。
#
# 写回复核：--apply 写完重新读盘，盘上的 validation_record 与本次要写的一致才推进游标；不一致就
#   报错、留着游标不动（退出码 2）。游标推进与落地是两件事——scripts/settle_trace_feedback.py
#   头注记着 VLLM-ASC-12430 的教训（游标推进了而落地没发生，这笔证据永久不再重试）。
#
# 用法：
#   python3 scripts/verify_upstream_outcomes.py [--dry-run | --apply] [--root <检出>]
#                                               [--case <case-id>] [--json]
#   --dry-run（默认）：只输出将要写的内容，不写任何文件
#   --apply：写回案例 YAML 的 validation_record，并更新游标
#   --case <case-id>：只查这一条案例（单点核对用）
#   --json：机器可读输出（stdout 只有 JSON）
#   退出码：0 = 成功（含「没有可对照的」与「查询失败但报出不可查证」）；1 = 有需人处理的矛盾；
#           2 = 参数或环境不可用（含写回复核不通过）。

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

from _stdio import write_text_lf
from exec_log_path import resolve_checkout_dir
from settle_s2_feedback import case_cites_issue, case_issue_sources, iso_week_now

CURSOR_KEY = "_upstream_outcomes"

# 单个锚点的结局
VERIFIED = "verified"
DENIED = "denied"
NOT_VERIFIED = "not_verified"
UNVERIFIABLE = "unverifiable"
# 一条案例的结局
CONTRADICTION = "contradiction"
NO_ANCHOR = "no_anchor"

OUTCOME_LABEL = {
    VERIFIED: "上游确认",
    DENIED: "上游否定",
    NOT_VERIFIED: "未验证",
    UNVERIFIABLE: "不可查证",
    CONTRADICTION: "矛盾",
    NO_ANCHOR: "不可对照",
}

REC_COUNT_KEYS = ("consistent", "inconsistent", "self_consistent")
REC_KEYS = REC_COUNT_KEYS + ("last_verified",)
MERGED_CLAIM = "upstream-fix-merged"

# 判据边界的一句话。人读输出与 --json 都带上它：外部对照判断不了现场结局。
BOUNDARY = ("外部对照只判断内容对不对（上游是否确认了这个根因或修法），判断不了现场是否解决——"
            "现场特异性只有现场能给（docs/mechanism/diagnosis-observability.md 的 5.3 第 13 条"
            "否决了让 agent 自动判定现场结局）。")

GH_TIMEOUT_S = 50


class GhError(RuntimeError):
    """gh api 取不到（未安装、未登录、网络失败、限流、返回非 JSON）。"""


def _first_line(text, limit=200):
    lines = (text or "").strip().splitlines()
    return (lines[0] if lines else "")[:limit]


def gh_api(path: str, timeout: int = GH_TIMEOUT_S):
    """gh api 外壳（写法与 scripts/auto_fetch.py:56 同条，多了三类失败的分辨以便人读）。"""
    try:
        out = subprocess.run(["gh", "api", path], capture_output=True, text=True,
                             timeout=timeout, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise GhError("未找到 gh 命令（未安装或不在 PATH）")
    except subprocess.TimeoutExpired:
        raise GhError(f"gh api 超时（超过 {timeout} 秒）")
    if out.returncode != 0:
        raise GhError(_first_line(out.stderr) or f"gh api 退出码 {out.returncode}")
    try:
        return json.loads(out.stdout or "null")
    except ValueError:
        raise GhError("gh api 返回的不是 JSON（登录失效时可能返回 HTML）")


def normalize_anchor(anchor):
    """锚点 → (repo, kind, number, url, problem)。problem 非空表示这条锚点查不了。"""
    if not isinstance(anchor, dict):
        return None, None, None, None, "锚点不是 mapping"
    repo = str(anchor.get("repo") or "").strip()
    url = anchor.get("url")
    issue, pr = anchor.get("issue"), anchor.get("pr")
    if not repo:
        return None, None, None, url, "锚点缺 repo"
    if issue is not None and pr is not None:
        return repo, None, None, url, "锚点同时写了 issue 与 pr（案例 schema 3.8 要求二选一）"
    if issue is not None:
        kind, number = "issue", issue
    elif pr is not None:
        kind, number = "pr", pr
    else:
        return repo, None, None, url, "锚点缺 issue 与 pr（案例 schema 3.8 要求二选一）"
    try:
        number = int(number)
    except (TypeError, ValueError):
        return repo, kind, None, url, f"锚点号不是整数：{number!r}"
    if number <= 0:
        return repo, kind, None, url, f"锚点号不是正整数：{number}"
    return repo, kind, number, url, None


def _probe_pull(repo, number, api):
    """PR 的合入状态 → (merged, error)。取不到时 merged 为 None。"""
    try:
        payload = api(f"repos/{repo}/pulls/{number}")
    except GhError as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, f"repos/{repo}/pulls/{number} 返回的不是 mapping"
    return bool(payload.get("merged")), None


def _closing_reference(repo, number, api):
    """已关闭但没有关闭原因的旧 issue：探一次 timeline，取关闭它的提交或被引用的 PR。

    只探第一个被引用的 PR（上限一次额外调用），取不到返回 None 并把它报成「不可查证」。
    为什么留着这一支：state_reason 是 2022 年之后才补的字段，更早关闭的 issue 读到 null，
    这时「关联的 fix PR 已合入」是 3.6 与案例 schema 3.8 里另一条确认路径。
    """
    try:
        events = api(f"repos/{repo}/issues/{number}/timeline?per_page=100")
    except GhError:
        return None
    if not isinstance(events, list):
        return None
    pr_number = None
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("event") == "closed" and ev.get("commit_id"):
            return ("commit", str(ev["commit_id"]))
        source = ev.get("source")
        issue = source.get("issue") if isinstance(source, dict) else None
        if pr_number is None and isinstance(issue, dict) and issue.get("pull_request"):
            pr_number = issue.get("number")
    if pr_number is not None:
        return ("pr", pr_number)
    return None


def probe_anchor(anchor, api=None):
    """查一个锚点 → 结果 dict（含 outcome 与 reason）。api 可注入（测试用），默认 gh_api。"""
    api = api or gh_api
    repo, kind, number, url, problem = normalize_anchor(anchor)
    res = {"repo": repo, "kind": kind, "number": number, "url": url, "reachable": False,
           "state": None, "state_reason": None, "is_pr": False, "merged": None,
           "closing_pr": None, "outcome": UNVERIFIABLE, "reason": problem}
    if problem:
        return res
    try:
        payload = api(f"repos/{repo}/issues/{number}")
    except GhError as exc:
        res["reason"] = f"repos/{repo}/issues/{number} 取不到：{exc}"
        return res
    if not isinstance(payload, dict):
        res["reason"] = f"repos/{repo}/issues/{number} 返回的不是 mapping"
        return res

    res["reachable"] = True
    res["state"] = payload.get("state")
    res["state_reason"] = payload.get("state_reason")
    res["is_pr"] = bool(payload.get("pull_request"))

    if res["is_pr"]:
        merged, error = _probe_pull(repo, number, api)
        res["merged"] = merged
        if merged is None:
            if res["state"] == "open":
                res["outcome"], res["reason"] = NOT_VERIFIED, "PR 仍是 open"
            else:
                res["outcome"] = UNVERIFIABLE
                res["reason"] = f"PR 的合入状态取不到：{error}"
        elif merged:
            res["outcome"], res["reason"] = VERIFIED, "PR 已合入"
        elif res["state"] == "open":
            res["outcome"], res["reason"] = NOT_VERIFIED, "PR 仍是 open（未合入）"
        else:
            res["outcome"], res["reason"] = DENIED, "PR 已关闭但未合入"
        return res

    state, state_reason = res["state"], res["state_reason"]
    if state == "open":
        res["outcome"], res["reason"] = NOT_VERIFIED, "issue 仍是 open"
    elif state == "closed" and state_reason == "completed":
        res["outcome"], res["reason"] = VERIFIED, "issue 关闭为 completed"
    elif state == "closed" and state_reason == "not_planned":
        res["outcome"], res["reason"] = DENIED, "issue 关闭为 not_planned"
    elif state == "closed":
        closing = _closing_reference(repo, number, api)
        if closing is None:
            res["outcome"] = UNVERIFIABLE
            res["reason"] = "issue 已关闭但没有关闭原因，也探不到关闭它的提交或 PR"
        elif closing[0] == "commit":
            res["outcome"] = VERIFIED
            res["reason"] = f"issue 由提交 {closing[1][:12]} 关闭"
        else:
            pr_number = closing[1]
            merged, error = _probe_pull(repo, pr_number, api)
            res["closing_pr"], res["merged"] = pr_number, merged
            if merged is None:
                res["outcome"] = UNVERIFIABLE
                res["reason"] = f"issue 由 PR #{pr_number} 关闭，但它的合入状态取不到：{error}"
            elif merged:
                res["outcome"] = VERIFIED
                res["reason"] = f"issue 由已合入的 PR #{pr_number} 关闭"
            else:
                res["outcome"] = DENIED
                res["reason"] = f"issue 由未合入的 PR #{pr_number} 关闭"
    else:
        res["outcome"] = UNVERIFIABLE
        res["reason"] = f"上游返回的 state 读不出来：{state!r}"
    return res


def is_self_referential(case, probe):
    """这个锚点是不是该案例自己的撰写依据（来源 URL 或正文引用）。

    与 scripts/settle_s2_feedback.py:104 的独立判据同条：来源即锚点、或正文点名了这个号，
    都算非独立——把它的状态记成 consistent 等于把同一份证据数两次。
    扫描时排除 upstream 块本身，否则锚点自带的 url 会被当成正文引用。
    """
    number = probe.get("number")
    if number is None:
        return False
    if number in case_issue_sources(case):
        return True
    body = {k: v for k, v in case.items() if k != "upstream"}
    return case_cites_issue(body, number)


def claims_merged_fix(case):
    verification = case.get("verification")
    return isinstance(verification, dict) and verification.get("source") == MERGED_CLAIM


def evaluate_case(case, api=None):
    """一条案例 → 结果 dict：锚点探针、结局、要写的字段（None 表示不写）。"""
    api = api or gh_api
    anchors = case.get("upstream")
    res = {"anchors": [], "outcome": NO_ANCHOR, "field": None, "self_ref": False,
           "reason": "案例没有 upstream 锚点，外部对照没有分母", "verified_reason": None}
    if not isinstance(anchors, list) or not anchors:
        return res

    probes = [probe_anchor(a, api) for a in anchors]
    res["anchors"] = probes
    verified = [p for p in probes if p["outcome"] == VERIFIED]
    denied = [p for p in probes if p["outcome"] == DENIED]

    if verified:
        probe = verified[0]
        self_ref = is_self_referential(case, probe)
        res.update(outcome=VERIFIED, self_ref=self_ref, verified_reason=probe["reason"],
                   field="self_consistent" if self_ref else "consistent",
                   reason=f"上游确认：{probe['reason']}")
        if self_ref:
            res["reason"] += "（锚点是该案例的来源或正文引用，属非独立命中）"
    elif denied and claims_merged_fix(case):
        res.update(outcome=CONTRADICTION, field="inconsistent",
                   reason=("案例声明修复已合入（verification.source=upstream-fix-merged），"
                           "上游却是：" + "；".join(p["reason"] for p in denied)))
    elif any(p["outcome"] in (VERIFIED, DENIED, NOT_VERIFIED) for p in probes):
        res.update(outcome=NOT_VERIFIED,
                   reason="锚点没给出确认（" + "；".join(p["reason"] for p in probes) + "）")
    else:
        res.update(outcome=UNVERIFIABLE,
                   reason="；".join(p["reason"] for p in probes))
    return res


def outcome_signature(case_result):
    """结局签名：锚点集合 + 结局 + 要写的字段。同一结局重复跑得到同一个签名。"""
    parts = sorted(
        f"{p.get('repo')}#{p.get('number')}:{p.get('outcome')}:{p.get('state')}:"
        f"{p.get('state_reason')}:{p.get('merged')}"
        for p in case_result["anchors"]
    )
    payload = {"outcome": case_result["outcome"], "field": case_result["field"], "anchors": parts}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _as_count(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def plan_record(case, field, week):
    """算出写回后的 validation_record → (写前, 写后)。形状与 settle_s2_feedback 同条。"""
    existing = case.get("validation_record")
    existing = dict(existing) if isinstance(existing, dict) else {}
    after = {k: _as_count(existing.get(k)) for k in REC_COUNT_KEYS}
    after[field] = after.get(field, 0) + 1
    after["last_verified"] = week
    before = {k: existing.get(k) for k in REC_KEYS}
    return before, after


def update_record_text(text, record):
    """在案例 YAML 文本里更新或插入 validation_record 块（行级，保留注释与字段顺序）。

    插入锚点是**案例块的起始行**（`cases:` 之后的第一个列表项），与
    `scripts/settle_s2_feedback.py` 同一条：案例的第一个字段不一定是 `id`（YAML 不要求
    字段顺序），锚 `- id:` 会在那种文件上整条跳过写回，而跳过只是一行 warn。
    返回 (新文本, 是否改了)；找不到列表项时返回 (原文, False)。
    """
    lines = text.split("\n")
    item_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("- "):
            item_idx = i
            break
    if item_idx is None:
        return text, False
    field_indent = (len(lines[item_idx]) - len(lines[item_idx].lstrip())) + 2
    key_idx = None
    for i, line in enumerate(lines):
        if (line.strip().startswith("validation_record:")
                and len(line) - len(line.lstrip()) == field_indent):
            key_idx = i
            break

    values = {k: str(record[k]) for k in REC_KEYS}
    if key_idx is None:
        pad = " " * field_indent
        block = ["", pad + "validation_record:  # 外部对照累积（verify_upstream_outcomes 结算；"
                         "只记内容被上游确认，不记现场是否解决）"]
        block += [pad + "  " + f"{k}: {values[k]}" for k in REC_KEYS]
        lines[item_idx + 1:item_idx + 1] = block
        return "\n".join(lines), True

    seen = set()
    end = key_idx + 1
    j = key_idx + 1
    while j < len(lines):
        line = lines[j]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            j += 1
            continue
        if len(line) - len(line.lstrip()) <= field_indent:
            break
        child_pad = " " * (field_indent + 2)
        for k in REC_KEYS:
            if k not in seen and stripped.startswith(k + ":"):
                lines[j] = f"{child_pad}{k}: {values[k]}"
                seen.add(k)
        end = j + 1
        j += 1
    missing = [k for k in REC_KEYS if k not in seen]
    if missing:
        child_pad = " " * (field_indent + 2)
        lines[end:end] = [f"{child_pad}{k}: {values[k]}" for k in missing]
    return "\n".join(lines), True


def read_case_record(path, case_id):
    """从盘上重读这条案例的 validation_record（写回复核用）；读不动或没有返回 None。"""
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    for case in (doc or {}).get("cases") or []:
        if isinstance(case, dict) and case.get("id") == case_id:
            record = case.get("validation_record")
            return record if isinstance(record, dict) else None
    return None


def record_matches(record, wanted):
    """盘上的记录与本次要写的是否一致（四个键逐个比）。"""
    if not isinstance(record, dict):
        return False
    for k in REC_COUNT_KEYS:
        if _as_count(record.get(k)) != wanted[k]:
            return False
    return str(record.get("last_verified") or "") == str(wanted["last_verified"])


def record_intact(path, case_id, field):
    """游标说结算过时，盘上还看得见那次落地吗（计数与日期都在）。"""
    record = read_case_record(path, case_id)
    if not isinstance(record, dict):
        return False
    return _as_count(record.get(field)) > 0 and bool(str(record.get("last_verified") or ""))


def _iter_cases(kb_root: Path):
    """knowledge/ 下活跃案例 → (path, case)；跳过 _archive/ 与 _index*。"""
    cases, bad = [], []
    for path in sorted(kb_root.rglob("*.yaml")):
        rel = path.relative_to(kb_root)
        if "_archive" in rel.parts or path.name.startswith("_index"):
            continue
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            bad.append((str(rel), f"{type(exc).__name__}: {exc}"))
            continue
        for case in (doc or {}).get("cases") or []:
            if isinstance(case, dict):
                cases.append((path, case))
    return cases, bad


def _print_anchor(index, total, probe):
    target = f"{probe.get('repo')}#{probe.get('number')}" if probe.get("number") else str(probe.get("repo"))
    if not probe.get("reachable"):
        print(f"  锚点 {index}/{total} {target}：{probe.get('reason')}")
        return
    detail = f"state={probe.get('state')} state_reason={probe.get('state_reason')}"
    if probe.get("is_pr"):
        detail += f" merged={probe.get('merged')}"
    print(f"  锚点 {index}/{total} {target}：{detail} → {probe.get('reason')}")


def _print_case(case_result, show_boundary=False):
    """打印一条案例的结局。show_boundary：单点核对（--case）时逐条重复那句边界，
    全库跑时只说在页首与小结里，避免同一句印上百遍。"""
    label = OUTCOME_LABEL.get(case_result["outcome"], case_result["outcome"])
    print(f"[{label}] {case_result['case']}（{case_result['path']}）")
    total = len(case_result["anchors"])
    for i, probe in enumerate(case_result["anchors"], 1):
        _print_anchor(i, total, probe)
    action = case_result["action"]
    if action in ("plan", "write", "repair"):
        field = case_result["field"]
        before = case_result["before"].get(field)
        before = 0 if before is None else before
        print(f"  结局：{case_result['reason']}")
        print(f"  validation_record.{field}：{before} → {case_result['after'][field]}；"
              f"last_verified → {case_result['after']['last_verified']}")
        if action == "plan":
            print("  （dry-run：未写盘）")
        elif action == "repair":
            print("  已写回（游标说结算过，盘上没有落地痕迹，本次补写）")
        else:
            print("  已写回")
        if show_boundary and field != "inconsistent":
            print("  边界：这一条说明上游确认了内容；现场是否解决只有现场能给，本脚本不判、也不写。")
    elif action == "skip":
        print(f"  结局未变（签名 {case_result['sig']}），不重复累加。")
    else:
        print(f"  结局：{case_result['reason']}")
        print("  未写任何字段。")


def load_cursor_state(state_path: Path):
    """读共享游标文件（与 settle_trace_feedback / settle_s2_feedback 同一份、同一处落点）。

    这一份自己读而不复用 load_cursors：后者解析失败时把告警打到 stdout，会破坏
    --json 的输出契约（stdout 只有 JSON）。本键（_upstream_outcomes）没有历史台账要迁，
    所以也不需要那一支。
    """
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[warn] 游标文件解析失败（{exc}）——按空游标处理；同一结局不会累加两次的条件"
              f"由写回复核与签名共同保证", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def save_cursor(state_path: Path, cursor_state, settled):
    """把 `_upstream_outcomes` 写回共享游标文件（保留文件里别的键）。"""
    cursor_state[CURSOR_KEY] = settled
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(state_path, json.dumps(cursor_state, ensure_ascii=False, indent=2) + "\n",
                  encoding="utf-8")


def run(root, apply=False, case_id=None, as_json=False, api=None, week=None) -> int:
    api = api or gh_api
    week = week or iso_week_now()
    root = Path(root).resolve()
    kb_root = root / "knowledge"

    if not root.is_dir():
        print(f"verify_upstream_outcomes：--root 不是目录：{root}", file=sys.stderr)
        return 2
    if not kb_root.is_dir():
        print(f"verify_upstream_outcomes：{kb_root} 不存在——知识库读不动", file=sys.stderr)
        return 2

    state_path, where, _rel = resolve_checkout_dir("settle-state", root)
    cursor_state = load_cursor_state(state_path)
    settled = dict(cursor_state.get(CURSOR_KEY) or {})

    all_cases, parse_failures = _iter_cases(kb_root)
    if case_id:
        selected = [(path, case) for path, case in all_cases if case.get("id") == case_id]
        if not selected:
            print(f"verify_upstream_outcomes：--case {case_id} 在 {kb_root} 下找不到", file=sys.stderr)
            return 2
    else:
        selected = all_cases

    results, write_failures, planned, written, repaired, skipped = [], [], [], [], [], []
    anchor_count = 0
    for path, case in selected:
        cid = case.get("id") or path.stem
        case_result = evaluate_case(case, api)
        case_result["case"] = cid
        case_result["path"] = str(path)
        if case_result["anchors"]:
            anchor_count += 1

        if case_result["field"]:
            before, after = plan_record(case, case_result["field"], week)
            case_result["before"], case_result["after"] = before, after
            sig = outcome_signature(case_result)
            case_result["sig"] = sig
            previous = settled.get(cid) or {}
            if previous.get("sig") == sig:
                action = "skip" if record_intact(path, cid, case_result["field"]) else "repair"
            else:
                action = "write" if apply else "plan"
            case_result["action"] = action
            if action == "plan":
                planned.append(cid)
            elif action in ("write", "repair"):
                text = path.read_text(encoding="utf-8")
                new_text, changed = update_record_text(text, after)
                if not changed:
                    write_failures.append(
                        (cid, f"{path.name}：未定位 validation_record 的插入点（找不到 `- id:` 行）"))
                else:
                    try:
                        write_text_lf(path, new_text, encoding="utf-8")
                    except OSError as exc:
                        write_failures.append((cid, f"写盘失败：{exc}"))
                    else:
                        on_disk = read_case_record(path, cid)
                        if record_matches(on_disk, after):
                            settled[cid] = {"sig": sig, "outcome": case_result["outcome"],
                                            "field": case_result["field"], "settled_at": week}
                            (repaired if action == "repair" else written).append(cid)
                            # 逐条落游标：整轮要查的网络调用可能上百次，中途被打断时
                            # 已落地的那些不能丢（丢了下一轮就会重复累加）。
                            try:
                                save_cursor(state_path, cursor_state, settled)
                            except OSError as exc:
                                write_failures.append(
                                    (cid, f"游标写不进去（本条已落地，但下一轮会重复累加）：{exc}"))
                        else:
                            write_failures.append(
                                (cid, f"写回复核不通过：盘上是 {on_disk}，本次要写的是 {after}"))
            else:
                skipped.append(cid)
        else:
            case_result["action"] = "none"
        results.append(case_result)

    if apply and (written or repaired):
        # 正常情况下每落一条已经在循环里写过游标；这里补一次是为了覆盖「落地成功、
        # 但逐条写游标时被跳过」的情形（不改变结果，只保证文件在）。
        try:
            save_cursor(state_path, cursor_state, settled)
        except OSError as exc:
            print(f"verify_upstream_outcomes：游标写不进去：{exc}", file=sys.stderr)
            return 2

    contradictions = [r["case"] for r in results if r["outcome"] == CONTRADICTION]
    no_anchor = [r["case"] for r in results if r["outcome"] == NO_ANCHOR]
    summary = {
        "verified": sum(1 for r in results if r["field"] in ("consistent", "self_consistent")),
        "consistent": sum(1 for r in results if r["field"] == "consistent"),
        "self_consistent": sum(1 for r in results if r["field"] == "self_consistent"),
        "contradiction": len(contradictions),
        "not_verified": sum(1 for r in results if r["outcome"] == NOT_VERIFIED),
        "unverifiable": sum(1 for r in results if r["outcome"] == UNVERIFIABLE),
        "no_anchor": len(no_anchor),
        "planned": len(planned),
        "written": len(written),
        "repaired": len(repaired),
        "skipped": len(skipped),
    }

    if as_json:
        report = {
            "root": str(root),
            "week": week,
            "applied": bool(apply),
            "cursor": str(state_path),
            "cursor_location": where,
            "cases_scanned": len(all_cases),
            "cases_with_anchor": anchor_count,
            "results": results,
            "write_failures": [{"case": c, "problem": p} for c, p in write_failures],
            "parse_failures": [{"file": f, "problem": p} for f, p in parse_failures],
            "summary": summary,
            "boundary": BOUNDARY,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("verify_upstream_outcomes：外部对照查证")
        print(f"根检出：{root}")
        print(f"游标：{state_path}（{where}）")
        print(f"范围：knowledge/ 下 {len(all_cases)} 条案例")
        print(f"边界：{BOUNDARY}")
        if case_id:
            print(f"（--case {case_id}：只查这一条）")
        print()

        if no_anchor:
            shown = "、".join(no_anchor[:10])
            more = f"（另有 {len(no_anchor) - 10} 条，用 --json 取全量）" if len(no_anchor) > 10 else ""
            print(f"[不可对照] {len(no_anchor)} 条案例没有 upstream 锚点：{shown}{more}")
            print("  没有上游关联的案例等现场回报，这里的「不可对照」不是负结论。\n")

        # 逐条展开的只有三类：本次会写 / 已写的（有变化）、矛盾（要人处理）、--case 指定的那条。
        # 其余按结局汇总成一行——整轮重跑时上百条「结局未变」逐条印会盖住真正要看的那几条。
        printed = set()
        for case_result in results:
            interesting = (case_id is not None
                           or case_result["outcome"] == CONTRADICTION
                           or case_result["action"] in ("plan", "write", "repair"))
            if case_result["outcome"] != NO_ANCHOR and interesting:
                _print_case(case_result, show_boundary=bool(case_id))
                printed.add(id(case_result))

        rest = [r for r in results if r["outcome"] != NO_ANCHOR and id(r) not in printed]
        for outcome, label in ((VERIFIED, "结局未变，不重复累加"),
                               (NOT_VERIFIED, "锚点没给出确认，未写任何字段"),
                               (UNVERIFIABLE, "取不到上游状态，未写任何字段")):
            group = [r["case"] for r in rest if r["outcome"] == outcome]
            if not group:
                continue
            shown = "、".join(group[:10])
            more = f"（另有 {len(group) - 10} 条，用 --json 取全量）" if len(group) > 10 else ""
            print(f"[{OUTCOME_LABEL[outcome]}] {len(group)} 条案例{label}：{shown}{more}")
        if not any(r["outcome"] != NO_ANCHOR for r in results):
            print("没有带上游锚点的案例。\n")

        for cid, problem in write_failures:
            print(f"[写回失败] {cid}：{problem}（游标未推进，下次重跑会重试）", file=sys.stderr)
        for rel, problem in parse_failures:
            print(f"[解析失败] knowledge/{rel}：{problem}", file=sys.stderr)

        print()
        print(f"小结：有锚点 {anchor_count} 条案例"
              f"（上游确认 {summary['verified']}：独立 {summary['consistent']}、非独立 "
              f"{summary['self_consistent']}；矛盾 {summary['contradiction']}；"
              f"未验证 {summary['not_verified']}；不可查证 {summary['unverifiable']}）；"
              f"不可对照 {summary['no_anchor']} 条")
        if contradictions:
            print(f"需人处理（{len(contradictions)} 条）：{'、'.join(contradictions[:10])}"
                  f"{'（另有 %d 条）' % (len(contradictions) - 10) if len(contradictions) > 10 else ''}")
            print("  这些案例声明修复已合入，锚点对应的上游 item 否认。先判是改锚点（指向修复 PR）"
                  "还是改案例结论；本次已按复审信号记 inconsistent。")
        if apply:
            print(f"本次写回 {len(written)} 条、补写 {len(repaired)} 条、跳过 {len(skipped)} 条；"
                  f"游标 → {state_path}")
        elif planned:
            print(f"本次将写回 {len(planned)} 条（dry-run 未写任何文件；确认后加 --apply，"
                  f"再走 knowledge_modification PR）")
        else:
            print("本次没有要写回的内容（dry-run 未写任何文件）。")

    if write_failures or parse_failures:
        return 2
    if contradictions:
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description="用上游 issue / PR 状态查证案例内容，写进 validation_record")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="只输出将要写的内容（默认）")
    mode.add_argument("--apply", action="store_true", help="写回案例 YAML 与游标")
    ap.add_argument("--root", type=Path, default=Path("."), help="检出根（默认当前目录）")
    ap.add_argument("--case", help="只查这一条案例 id（单点核对用）")
    ap.add_argument("--json", action="store_true", help="机器可读输出（stdout 只有 JSON）")
    args = ap.parse_args()
    return run(args.root, apply=args.apply, case_id=args.case, as_json=args.json)


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main())
