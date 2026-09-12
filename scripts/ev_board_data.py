#!/usr/bin/env python3
# ev_board_data.py —— 自演进看板数据汇总（EV 卡 + timeline + 容量 + 归因聚合）
#
# 供 DSH 面板（dsh-plugins/ev-panel）host 侧调用：一次性汇总 proposals/ideas/、
# metrics/timeline.yaml、knowledge/_index.yaml 头注、归因事件按需聚合
# （component_tally 逻辑：trace attribution + .s2-replay/attributions.yaml）、
# .s2-replay/attributions.yaml 为 JSON，stdout 输出。确定性逻辑（原则二）：解析与
# 聚合进脚本，agent/面板只读聚合结果。
#
# 用法：python3 scripts/ev_board_data.py [--root <repo>]

import argparse
import datetime
import glob
import json
import re
import sys
from pathlib import Path

import yaml

# 允许 import 同目录脚本（component_tally 按需聚合复用）
sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_yaml(path):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"__error__": str(e)}


def parse_index_header(text):
    """knowledge/_index.yaml 头注容量行：'#   容量(inference/vllm-ascend): interrupt=36/30, ...'"""
    caps = {}
    for line in text.splitlines():
        m = re.match(r"#\s*容量\(([^)]+)\):\s*(.*)$", line.strip())
        if not m:
            continue
        ns = m.group(1)
        cells = {}
        for part in m.group(2).split(","):
            cm = re.match(r"\s*(\w+)=(\d+)/(\d+)", part)
            if cm:
                cells[cm.group(1)] = {"count": int(cm.group(2)), "cap": int(cm.group(3))}
        if cells:
            caps[ns] = cells
    return caps


# EV 卡状态词表 v5（schema 校验源：scripts/verify_proposals.py VALID_STATUS）。
# 面板旧版曾按 v1 词表（candidate/proposed/pending_merge/adopted/rolled_back）分组——
# 那些状态在 v5 下永不出现，而 rejected/superseded 从未被渲染。词表以校验器为准，不各自维护。
VALID_STATUS = ("in_experiment", "validated", "rejected", "superseded")
TERMINAL_STATUS = ("validated", "rejected", "superseded")
# 卡龄超过该天数仍未闭合 → 标 stale（面板"待办优先"条据此提示）
STALE_DAYS = 14
# 触及面的"本期"窗口（滚动天数）。为什么不用"批"：批边界（攒批 PR）没有落在卡上，
# 编一个批概念只会引入不可核对的数字；滚动窗口人人能自己验算。
SURFACE_WINDOW_DAYS = 7
# 外部 ground truth 的验证方式（仓库"客观评分源优先"排序的前两档）：golden 回放与
# issue-replay 对照，其判据来自系统之外；其余（metrics_compare 自定口径、scan_review 自审）
# 不算外部证据。判据 evidence_weak 用它算占比。
EXTERNAL_METHODS = ("golden_replay", "issue_replay")

PR_RE = re.compile(r"(?:PR|#)\s?#?(\d{2,6})")


def extract_pr_refs(text):
    """从卡文本里抽 PR/issue 号（决策链里常写「随 PR #97 供人审」）。"""
    if not text:
        return []
    out = []
    for m in PR_RE.finditer(str(text)):
        n = m.group(1)
        if n not in out:
            out.append(n)
    return out[:5]


# ===========================================================================
# 确定性"触及面"派生：EV 卡 → 这批改动落在机器的哪一层
#
# 为什么不给卡加一个 `axis` 字段让 agent 自己填：agent 自报既是弱观测（同 `procedure_follow`
# 的先例：只可作趋势，不可作验收），又是**可被刷的靶子**——系统会学会写能通过的标签。
# 所以轴从**卡里已经写下的仓库路径**反推，三个性质是刻意的：
#   - 确定性：同一份卡文本必得同一个轴（没有 LLM、没有时间依赖）；
#   - 可审计：归因依据字段与依据路径随轴一起给出，人可核对为什么是这一层；
#   - 对存量成立：不必给 57 张历史卡补写字段（补写只造事后叙述，原则十）。
#
# 边界（面板必须原样这么说，不得简写成"改进维度"）：轴记的是**改动落在哪一层**，
# 既不是"作者想优化什么"（意图），也不是"变好了多少"（那是能力轴，当前不可解读）。
#
# 轴映射与字段优先级是**实现事实**（对应 metrics_health 的 IMPLEMENTED_* 分工），
# 阈值在 proposals/gates.yaml（数据）。
# ===========================================================================

# 顺序即优先级（first match wins）；前缀命中即归属，不再看后面的轴。
SURFACE_AXES = (
    ("判断更准", ("triage-tree.yaml", "knowledge/", "references/")),
    ("闸门更硬", (".github/", "eval/", "metrics/gates.yaml", "proposals/gates.yaml",
                  "scripts/verify_", "scripts/holdout", "scripts/check_",
                  "scripts/panel_render_check.js", "scripts/rehearse_")),
    ("看得见", ("scripts/", "dsh-plugins/", "traces/", ".s2-replay/", "metrics/")),
    ("走得顺", ("skills/", "docs/", "proposals/", "examples/", "CLAUDE.md", "README.md",
                "CONTEXT.md")),
)
UNATTRIBUTED = "未归因"

# 字段优先级：**改动落点优先于证据引用**。evidence/trajectory 里引用的文件未必是改动的文件，
# 所以它是弱归因；强度随轴一起给出，面板不得把弱归因读成强归因。
SURFACE_FIELD_ORDER = (
    ("action", "强"),            # decisions[type=action].conclusion —— 改动的自述
    ("title", "中"),
    ("hypothesis", "中"),
    ("success_criteria", "弱"),
    ("trajectory", "弱"),
)

_REPO_DIRS = (r"(?:skills|scripts|docs|knowledge|references|metrics|eval|dsh-plugins"
              r"|examples|postmortems|proposals|\.github|\.s2-replay|\.ixn-replay)")
SURFACE_PATH_RE = re.compile(
    r"(?<![\w./-])(" + _REPO_DIRS + r"/[A-Za-z0-9_./+-]+"
    r"|triage-tree\.yaml|CLAUDE\.md|README\.md|CONTEXT\.md)")
# 只认**反引号内**的路径：散文里的半截路径（`metrics/timeline`）不是引用，认了就是噪声
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
# 运行时件/被忽略件：它们**本就不该在检出里**，缺席不是腐烂（否则判据全是假红）
SURFACE_SKIP_PREFIX = (
    "traces/", ".s2-replay/", ".ixn-replay/", ".auto-fetch/", "eval-reports/",
    "src-code/", ".flow-replay/", "postmortems/inbox/",
    "proposals/sessions/", "proposals/tasks/", "proposals/reviews/",
    "proposals/experiments/", "knowledge/_archive/",
    "metrics/skill-exec-log.yaml", "metrics/ev-measure-log.yaml",
)


def scan_refs(text):
    """**死指针**用的扫描：反引号内的**字面**仓库路径（去重保序）。

    glob / 占位符 / 运行时件都不算引用——否则判据满是假红（实测过：不收紧时 154 个"路径"里
    58 个"不存在"，大半是 `docs/*.md`、`.s2-replay/arena/` 这类根本不该在检出里的东西）。
    """
    out = []
    for raw in BACKTICK_RE.findall(text or ""):
        cand = raw.strip().rstrip(".,;:()，。；：）").rstrip("/")
        if not cand or not SURFACE_PATH_RE.fullmatch(cand):
            continue
        if any(ch in cand for ch in "*?[]<>"):
            continue
        if "YYYY" in cand or "NNN" in cand:
            continue
        if any(cand == p.rstrip("/") or cand.startswith(p) for p in SURFACE_SKIP_PREFIX):
            continue
        if cand not in out:
            out.append(cand)
    return out


def scan_refs_loose(text):
    """**轴派生**用的扫描：不要求反引号，允许 glob 与半截路径（去重保序）。

    与 `scan_refs` 的两处差异都是刻意的，因为两者回答的是**不同的问题**：
      - 死指针问"卡点名的文件还在不在"→ 必须是字面路径（glob 无法判存在性，半截路径是噪声）；
      - 轴派生问"这张卡在说机器的哪一层"→ 证据里的 `eval/golden/*.fixture.yaml`、
        `metrics/timeline` 同样是有效线索，滤掉反而大面积漏判（实测：只用反引号口径时
        57 张卡有 **37 张**归因不出来，用本口径 0 张）。
    """
    out = []
    for p in SURFACE_PATH_RE.findall(text or ""):
        p = p.rstrip(".,;:()，。；：）")
        if p and p not in out:
            out.append(p)
    return out


def axis_of_paths(paths):
    """路径集 → (轴, 依据路径)；全不命中返回 (None, None)。"""
    for p in paths:
        for name, prefixes in SURFACE_AXES:
            if any(p == pre.rstrip("/") or p.startswith(pre) for pre in prefixes):
                return name, p
    return None, None


def _surface_field_texts(doc):
    decisions = doc.get("decisions") or []
    validation = doc.get("validation") or {}
    signals = doc.get("source_signals") or []
    return {
        "action": " ".join(str(x.get("conclusion") or "") for x in decisions
                           if isinstance(x, dict) and x.get("type") == "action"),
        "title": str(doc.get("title") or ""),
        "hypothesis": str(doc.get("hypothesis") or ""),
        "success_criteria": str(validation.get("success_criteria") or "")
                            if isinstance(validation, dict) else "",
        "trajectory": " ".join(
            str(s.get("evidence") or "") + " " + " ".join(str(t) for t in (s.get("trajectory") or []))
            for s in signals if isinstance(s, dict)),
    }


def derive_surface(doc):
    """卡 → {surface, basis_field, basis_path, basis_strength}（确定性，无 LLM）。"""
    texts = _surface_field_texts(doc)
    for field, strength in SURFACE_FIELD_ORDER:
        axis, path = axis_of_paths(scan_refs_loose(texts.get(field)))
        if axis:
            return {"surface": axis, "basis_field": field, "basis_path": path,
                    "basis_strength": strength}
    # 兜底：全卡文本（强度最弱，如实标注为弱归因）
    axis, path = axis_of_paths(scan_refs_loose(" ".join(texts.values())))
    if axis:
        return {"surface": axis, "basis_field": "card-text", "basis_path": path,
                "basis_strength": "弱"}
    return {"surface": UNATTRIBUTED, "basis_field": None, "basis_path": None,
            "basis_strength": None}


def _all_strings(obj, out=None, depth=0):
    """递归收集文档里的全部字符串（限深，防意外结构导致爆炸）。"""
    if out is None:
        out = []
    if depth > 6:
        return out
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _all_strings(v, out, depth + 1)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _all_strings(v, out, depth + 1)
    return out


def scan_dead_refs(root, doc):
    """卡文本点名、但检出里已不存在**且不受 git 跟踪**的字面路径。

    口径两处刻意收紧（否则判据全是假红，实测过）：
      - 运行时/被忽略件不算腐烂（`SURFACE_SKIP_PREFIX`）；
      - 目录引用去尾斜杠后判存在性（`references/methodologies/` 是目录，不是死指针）。
    强度如实标注：本判据只说明"卡点名的文件不在了"，**不**断言卡的结论因此失效。
    """
    dead = []
    for p in scan_refs(" ".join(_all_strings(doc))):
        if not (root / p).exists():
            dead.append(p)
    return dead


def detect_signal_spread(ideas):
    """按触发信号聚合：卡数、时间跨度、以及"在一张已采纳卡之后又出现"的次数。

    这是最接近 loss 的读数（不需要目标值，只需要"闭上的环别再开"）。但**它今天还不是判据**：
    9 天、57 张卡、56 张 validated 的语料上，"同信号再次触发"既可能是"上次没解决"，也可能是
    "又发现一处同类摩擦"——两者用现有字段区分不了。所以如实降级为**读数**（趋势与异常信号），
    只有当某个信号在卡数上占绝对主导时才升为判据（见 proposals/gates.yaml 的 signal_dominant）。
    """
    by_sig = {}
    for c in ideas:
        if not c.get("id"):
            continue
        names = c.get("signals_all")
        if names is None:      # 兜底：外部构造的 idea dict（无 signals_all）走截断后的列表
            names = [(s or {}).get("signal") for s in (c.get("source_signals") or [])]
        for name in dict.fromkeys(n for n in names if n):
            by_sig.setdefault(str(name), []).append(c)
    rows = []
    for sig, cs in by_sig.items():
        cs = sorted(cs, key=lambda c: str(c.get("created_at") or ""))
        adopted_seen = False
        recurred = []
        for c in cs:
            if c.get("status") == "validated":
                adopted_seen = True
            elif adopted_seen:
                recurred.append(c.get("id"))
        rows.append({
            "signal": sig,
            "cards": len(cs),
            "adopted": sum(1 for c in cs if c.get("status") == "validated"),
            "after_adopted": len(recurred),
            "cards_after_adopted": recurred[:8],
            "first": str(cs[0].get("created_at"))[:10],
            "last": str(cs[-1].get("created_at"))[:10],
        })
    rows.sort(key=lambda r: (-r["cards"], r["signal"]))
    return rows


def collect_measure_runs(root):
    """EV 卡预测的实测记录（共享运行件）——"声明了可复现判据却从没被测过"的观测面。

    解析失败/文件缺席如实退化（`state`），不把"没有记录"读成"都测过了"，也不读成"都没测"：
    两者由 `runs` 与 `cards` 共同决定，读侧只看这两个数。
    """
    try:
        import exec_log_path
    except Exception as e:
        return {"present": False, "state": "unavailable", "note": f"exec_log_path 不可用: {e}",
                "runs": 0, "cards": [], "by_verdict": {}, "last": None}
    path, where = exec_log_path.resolve_rel(root, exec_log_path.MEASURE_LOG_REL)
    note = exec_log_path.describe(path, where)
    if not path.exists():
        return {"present": False, "state": "missing", "note": note, "path": str(path),
                "where": where, "runs": 0, "cards": [], "by_verdict": {}, "last": None}
    d = load_yaml(path)
    if not isinstance(d, dict):
        return {"present": False, "state": "unparsable", "note": note, "path": str(path),
                "where": where, "runs": 0, "cards": [], "by_verdict": {}, "last": None}
    records = [r for r in (d.get("records") or []) if isinstance(r, dict)]
    by_verdict = {}
    cards = []
    for r in records:
        v = str(r.get("verdict") or "?")
        by_verdict[v] = by_verdict.get(v, 0) + 1
        cid = r.get("card")
        if cid and cid not in cards:
            cards.append(cid)
    return {"present": True, "state": "ok", "note": note, "path": str(path), "where": where,
            "runs": len(records), "cards": cards, "by_verdict": by_verdict,
            "last": records[-1] if records else None}


def days_since(value):
    """created_at（date/datetime/str）→ 距今天数；无法解析返回 None。"""
    if value is None:
        return None
    if hasattr(value, "timetuple"):
        d = value
    else:
        s = str(value).strip()[:10]
        try:
            d = datetime.date.fromisoformat(s)
        except ValueError:
            return None
    return (datetime.date.today() - datetime.date(d.year, d.month, d.day)).days


def compact_decisions(decisions):
    """决策链瘦身：完整结论留给 detail RPC，列表页只带前 60 字摘要。"""
    out = []
    for x in decisions or []:
        if not isinstance(x, dict):
            continue
        concl = str(x.get("conclusion") or "")
        out.append({
            "who": x.get("who"),
            "when": x.get("when"),
            "type": x.get("type"),
            "summary": concl[:60],
            "length": len(concl),
        })
    return out


def full_decisions(decisions):
    out = []
    for x in decisions or []:
        if not isinstance(x, dict):
            continue
        out.append({
            "who": x.get("who"),
            "when": x.get("when"),
            "type": x.get("type"),
            "conclusion": x.get("conclusion"),
        })
    return out


def audit_gaps(doc, days_open):
    """卡自审：机制要求 vs 实际字段的缺口（诚实退化——面板报出来，不粉饰）。

    依据 docs/mechanism/pipeline.md §7「生命周期完整性规则」与 verify_proposals.py：
      - 终态卡必须有 decision 记录（审计缺口）
      - validated 卡 actual_cost 必填（成本审计缺口）
      - 执行/验证完成而卡停在 in_experiment = 卡不完整（机制推进，不靠 agent 记得改状态）
    """
    gaps = []
    status = doc.get("status")
    decisions = doc.get("decisions") or []
    types = [x.get("type") for x in decisions if isinstance(x, dict)]

    if status in TERMINAL_STATUS and "decision" not in types:
        gaps.append({"kind": "no_decision", "text": "终态卡缺 decision 记录（审计缺口）"})

    if status == "validated":
        ac = doc.get("actual_cost")
        tokens = ac.get("tokens") if isinstance(ac, dict) else None
        if tokens is None:
            gaps.append({"kind": "no_cost", "text": "validated 卡 actual_cost 未写回（成本审计缺口）"})

    if status == "in_experiment" and "decision" in types:
        gaps.append({"kind": "status_lag", "text": "已记 decision 但状态仍 in_experiment（状态未推进）"})

    if status == "in_experiment" and days_open is not None and days_open >= STALE_DAYS:
        gaps.append({"kind": "stale", "text": f"在实验 {days_open} 天未闭合（超 {STALE_DAYS} 天）"})

    return gaps


def collect_ideas(root):
    ideas = []
    for f in sorted((root / "proposals" / "ideas").glob("*.yaml")):
        d = load_yaml(f)
        if not isinstance(d, dict) or "__error__" in d:
            ideas.append({"file": f.name, "error": d.get("__error__", "解析失败")})
            continue
        days_open = days_since(d.get("created_at"))
        decisions = d.get("decisions") or []
        # 决策链全文参与 PR 号提取（「随 PR #97 供人审」这类追溯指针只在结论里）
        blob = " ".join(str(x.get("conclusion") or "") for x in decisions if isinstance(x, dict))
        validation = d.get("validation") or {}
        surface = derive_surface(d)
        dead_refs = scan_dead_refs(root, d)
        ideas.append({
            "id": d.get("id"),
            "title": d.get("title"),
            "layer": d.get("layer"),
            "status": d.get("status"),
            "authorization": d.get("authorization"),
            "dimension": d.get("dimension"),
            "risk": d.get("risk"),
            "principle_refs": d.get("principle_refs") or [],
            # 触发信号：signal 名 + 证据一句话（面板列表页够用；完整 trajectory 进 detail）
            "source_signals": [
                {
                    "signal": s.get("signal"),
                    "evidence": s.get("evidence"),
                    "trajectory": s.get("trajectory") or [],
                }
                for s in (d.get("source_signals") or [])[:3] if isinstance(s, dict)
            ],
            # 信号名全量（列表页只带前 3 条证据，但**聚合口径必须看全量**——
            # 实测差异：只看前 3 条时 process_friction 计 22 张，全量是 27 张）
            "signals_all": [s.get("signal") for s in (d.get("source_signals") or [])
                            if isinstance(s, dict) and s.get("signal")],
            "hypothesis": d.get("hypothesis"),
            "predicted_effect": d.get("predicted_effect"),
            "validation": {
                "method": validation.get("method"),
                "success_criteria": validation.get("success_criteria"),
                "baseline": validation.get("baseline"),
            },
            "gate": (d.get("gate") or {}).get("condition") if isinstance(d.get("gate"), dict) else d.get("gate"),
            "actual_cost": d.get("actual_cost"),
            "estimated_cost": d.get("estimated_cost"),
            "decisions": compact_decisions(decisions),
            "decision_count": len(decisions),
            "created_at": d.get("created_at"),
            "days_open": days_open,
            "pr_refs": extract_pr_refs(blob),
            "supersedes": d.get("supersedes") or [],
            "superseded_by": d.get("superseded_by"),
            # 派生：面板"待办优先"与自审用
            "gaps": audit_gaps(d, days_open),
            # 派生（确定性）：触及面 + 依据字段强度 + 已消失的点名路径
            "surface": surface["surface"],
            "surface_basis": {"field": surface["basis_field"], "path": surface["basis_path"],
                              "strength": surface["basis_strength"]},
            "dead_refs": dead_refs,
            "file": f.name,
        })
    return ideas


def collect_idea_detail(root, idea_id):
    """单卡全文（点开才拉）：完整决策链 + 验证标准 + 证据轨迹 + 门控。"""
    for f in sorted((root / "proposals" / "ideas").glob("*.yaml")):
        d = load_yaml(f)
        if not isinstance(d, dict) or "__error__" in d or d.get("id") != idea_id:
            continue
        validation = d.get("validation") or {}
        return {
            "id": d.get("id"),
            "title": d.get("title"),
            "status": d.get("status"),
            "layer": d.get("layer"),
            "authorization": d.get("authorization"),
            "dimension": d.get("dimension"),
            "risk": d.get("risk"),
            "created_at": d.get("created_at"),
            "hypothesis": d.get("hypothesis"),
            "predicted_effect": d.get("predicted_effect"),
            "validation": {
                "method": validation.get("method"),
                "baseline": validation.get("baseline"),
                "success_criteria": validation.get("success_criteria"),
                "rollback": validation.get("rollback"),
            },
            "gate": d.get("gate"),
            "actual_cost": d.get("actual_cost"),
            "estimated_cost": d.get("estimated_cost"),
            "principle_refs": d.get("principle_refs") or [],
            "source_signals": d.get("source_signals") or [],
            "decisions": full_decisions(d.get("decisions")),
            "supersedes": d.get("supersedes") or [],
            "superseded_by": d.get("superseded_by"),
            "file": f.name,
        }
    return None


def collect_stats(ideas):
    """自演进度量：面板首屏"系统最近做了什么"用（比"一共几张卡"有意义）。"""
    ok = [c for c in ideas if c.get("id")]
    total = len(ok)
    by_status = {}
    for c in ok:
        st = c.get("status") or "unknown"
        by_status[st] = by_status.get(st, 0) + 1

    adopted = by_status.get("validated", 0)
    terminal = sum(by_status.get(s, 0) for s in TERMINAL_STATUS)
    # 采纳率只在终态卡上算（in_experiment 未判决，分母不含）
    adoption_rate = round(adopted / terminal, 3) if terminal else None

    by_method = {}
    for c in ok:
        m = ((c.get("validation") or {}).get("method")) or "未标"
        by_method[m] = by_method.get(m, 0) + 1

    by_signal = {}
    for c in ok:
        for s in c.get("source_signals") or []:
            name = (s or {}).get("signal")
            if name:
                by_signal[name] = by_signal.get(name, 0) + 1

    costs = []
    for c in ok:
        ac = c.get("actual_cost")
        t = ac.get("tokens") if isinstance(ac, dict) else None
        if isinstance(t, (int, float)):
            costs.append(t)

    open_days = [c["days_open"] for c in ok if isinstance(c.get("days_open"), int)]
    gap_cards = [c for c in ok if c.get("gaps")]
    stale = [c for c in ok if c.get("status") == "in_experiment" and isinstance(c.get("days_open"), int)
             and c["days_open"] >= STALE_DAYS]

    # ---- 触及面（确定性派生）与时间窗 ----
    # 窗口用滚动天数而不是"批"：批边界（攒批 PR）没有落在卡上，编一个只会引入不可核对的数字。
    by_surface = {}
    for c in ok:
        s = c.get("surface") or UNATTRIBUTED
        by_surface[s] = by_surface.get(s, 0) + 1
    window = SURFACE_WINDOW_DAYS
    cutoff = datetime.date.today() - datetime.timedelta(days=window - 1)
    by_surface_recent = {}
    for c in ok:
        d = _as_date(c.get("created_at"))
        if d is None or d < cutoff:
            continue
        s = c.get("surface") or UNATTRIBUTED
        by_surface_recent[s] = by_surface_recent.get(s, 0) + 1
    basis_strength = {}
    for c in ok:
        st = ((c.get("surface_basis") or {}).get("strength")) or "未归因"
        basis_strength[st] = basis_strength.get(st, 0) + 1
    # 归类依据按**字段名**计（面板据此显示"改动说明/证据引用/…"）：强度是内部三档，
    # 字段名才是人能核对的那个东西——"强/弱"说了等于没说，读者要知道依据取自哪里。
    by_basis_field = {}
    for c in ok:
        f = ((c.get("surface_basis") or {}).get("field")) or "未归因"
        by_basis_field[f] = by_basis_field.get(f, 0) + 1

    # ---- 已消失的点名路径（判据 pointer_rot 的分子） ----
    dead_cards = [(c.get("id"), c.get("dead_refs") or []) for c in ok if c.get("dead_refs")]
    dead_paths = sorted({p for _cid, ps in dead_cards for p in ps})

    # ---- 待合入积压：已验证但决策链里没有合入指针（判据 backlog 的分子） ----
    backlog = [c.get("id") for c in ok
               if c.get("status") == "validated" and not c.get("pr_refs")]

    # ---- 验证证据强度：外部 ground truth 占比（判据 evidence_weak 的分母/分子） ----
    # 口径来自仓库自己的"客观评分源优先"排序：golden / issue-replay 是**系统之外**的
    # ground truth；metrics_compare 是自定口径的机械测量；scan_review 是自审。
    external = sum(1 for c in ok
                   if (c.get("validation") or {}).get("method") in EXTERNAL_METHODS)

    spreads = detect_signal_spread(ok)
    top_signal = spreads[0] if spreads else None

    return {
        "total": total,
        "by_status": by_status,
        "adoption_rate": adoption_rate,
        "terminal_count": terminal,
        "by_method": by_method,
        "by_signal": by_signal,
        "cost_total": sum(costs) if costs else None,
        "cost_median": sorted(costs)[len(costs) // 2] if costs else None,
        "cost_cards": len(costs),
        "oldest_open_days": max(open_days) if open_days else None,
        "gap_count": len(gap_cards),
        "gap_cards": [c["id"] for c in gap_cards],
        "stale_count": len(stale),
        "stale_cards": [c["id"] for c in stale],
        # ---- 以下为 2026-09 新增（只增键，旧键语义不变） ----
        "by_surface": by_surface,
        "by_surface_recent": by_surface_recent,
        "surface_window_days": window,
        "surface_basis_strength": basis_strength,
        "by_basis_field": by_basis_field,
        "dead_ref_cards": [cid for cid, _ps in dead_cards],
        "dead_ref_paths": dead_paths,
        "dead_ref_count": len(dead_paths),
        "backlog_count": len(backlog),
        "backlog_cards": backlog[:20],
        "external_ground_truth": external,
        "external_ratio": round(external / terminal, 3) if terminal else None,
        "negative_terminal": (by_status.get("rejected", 0) + by_status.get("superseded", 0)),
        "signal_spread": spreads,
        "top_signal": top_signal,
        "top_signal_share": (round(top_signal["cards"] / total, 3)
                             if top_signal and total else None),
    }


def _as_date(value):
    """created_at → date；无法解析返回 None（与 days_since 同一口径，不各写一份）。"""
    if value is None:
        return None
    if hasattr(value, "timetuple") and not isinstance(value, str):
        return datetime.date(value.year, value.month, value.day)
    try:
        return datetime.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def collect_skill_exec(root):
    """统一执行记录（exec-log）——让面板看得见 evolve-check 是否真的在收尾运行。

    为什么需要这一格（2026-09-10 审计）：exec-log 先前只被 evolve-check 第 1 步读，
    面板与 metrics 都不看它，于是"收尾跑了但无信号"与"根本没跑"在数据上完全不可区分——
    机制是否在运作无法证伪。解析复用 scripts/tail_exec_log.py（单一事实源：datetime
    归一 / 文件缺失退化只在一处实现，防两处漂移）。

    语义边界（2026-09-10 修）：exec-log 从"各 worktree 各持一份的检出内文件"改为
    **同一克隆共享**（主检出 metrics/，见 scripts/exec_log_path.py）——从此代理在任意
    worktree 收尾落的记录，本面板（读用户会话的 cwd）就能看到，且 worktree 清理不再
    丢数据。仍不假装的部分：**跨克隆/跨机不聚合**；共享件是 read-modify-write，
    写侧持锁（并发实测：无锁 16 次写入只剩 3 条）。note/sharing 字段随数据一起递给
    面板，防把本地读数误读成全系统读数。
    """
    try:
        import tail_exec_log
    except Exception as e:  # 不该发生；如实标注而非伪造数据
        return {"present": False, "state": "unavailable", "note": f"tail_exec_log 不可用: {e}",
                "total": 0, "recent": [], "evolve_check_runs": 0, "last_evolve_check": None,
                "by_skill": {}}
    records, state, path, where = tail_exec_log.load_records(root)
    rows = [tail_exec_log.summarize(r) for r in records if isinstance(r, dict)]
    ev = [r for r in rows if r["skill"] == "evolve-check"]
    by_skill = {}
    for r in rows:
        by_skill[r["skill"]] = by_skill.get(r["skill"], 0) + 1
    # 无信号收尾也落记录（products 为空 + reason 含"无演进信号"）——单独计数，
    # 这样"跑了且无信号"是可观测的，而不是消失在沉默里。
    no_signal = [r for r in ev if not r["products"] and "无演进信号" in r["decision_reason"]]
    return {
        "present": state == "ok",
        "state": state,
        "note": tail_exec_log.describe(path, where),
        "path": str(path),
        "where": where,
        "aggregate": tail_exec_log.aggregate(rows),
        "total": len(rows),
        "recent": rows[-5:],
        "by_skill": by_skill,
        "evolve_check_runs": len(ev),
        "evolve_check_no_signal": len(no_signal),
        "last_evolve_check": ev[-1] if ev else None,
    }


def collect_timeline(root):
    """每期的关键指标，供面板画趋势。

    **必须保留分母**（2026-09 修一处口径缺陷）：旧实现把 `{ok, total}` 压成 `ok`
    （`v if not isinstance(v, dict) else v.get("ok", v)`），于是三期的路由准确率
    "3/3" 渲染成三根等高的柱子、标签只有一个孤零零的 "3"——趋势既读不懂也无法判读。
    metrics.md 的口径纪律本来就写着"比例类指标务必连同分母解读"，这里是它在读侧的落实。
    比例类一律给 `{ok, total}`（total 缺失时如实为 None，不编分母）。
    """
    path = root / "metrics" / "timeline.yaml"
    if not path.exists():
        return []
    d = load_yaml(path)
    if not isinstance(d, dict):
        return []
    RATIOS = ("routed_accuracy", "misdiagnosis_rate", "candidate_recall")
    SCALARS = ("tier2_hit", "sessions_total")
    out = []
    for p in d.get("periods") or []:
        if not isinstance(p, dict):
            continue
        m = p.get("metrics") or {}
        row = {
            "period": p.get("period"),
            "kind": p.get("kind"),
            "title": (p.get("title") or "")[:60],
        }
        for k in RATIOS:
            v = m.get(k)
            if isinstance(v, dict) and "ok" in v:
                row[k] = {"ok": v.get("ok"), "total": v.get("total")}
            elif isinstance(v, (int, float)):
                row[k] = {"ok": v, "total": None}
        for k in SCALARS:
            v = m.get(k)
            if isinstance(v, (int, float)):
                row[k] = v
        fc = m.get("feedback_capture")
        if isinstance(fc, dict):
            row["feedback_capture_total"] = sum(
                v for v in fc.values() if isinstance(v, (int, float)))
        out.append(row)
    return out


def collect_tally(root):
    """归因事件按需聚合（2026-09 重构：无常驻 metrics/component-tally.yaml 表——
    从 trace attribution + s2 候选现聚合，语义同 component_tally.py）。"""
    # 复用 component_tally 的聚合逻辑（同仓库脚本，直接导入避免双源漂移）
    import component_tally
    entries = component_tally.scan_traces(root) + component_tally.scan_replay_attributions(root)
    if not entries:
        return []
    agg = component_tally.aggregate(entries)
    return [
        {"id": comp, **v, "traces": sorted(v["traces"])}
        for comp, v in sorted(agg.items(), key=lambda x: -(x[1]["trace_mis"] + x[1]["s2_candidate"]))
    ]


def collect_s2_attrib(root):
    path = root / ".s2-replay" / "attributions.yaml"
    if not path.exists():
        return None
    d = load_yaml(path)
    return d.get("attributions") if isinstance(d, dict) else None


def main():
    ap = argparse.ArgumentParser(description="自演进看板数据汇总")
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--detail", metavar="EV-YYYY-NNN",
                    help="只输出该卡的全文（面板点开时按需拉取，避免列表页背全文）")
    args = ap.parse_args()
    root = args.root.resolve()

    # 单卡全文模式：面板 host 的 ev-idea-detail RPC 走这条路
    if args.detail:
        detail = collect_idea_detail(root, args.detail)
        if detail is None:
            print(json.dumps({"ok": False, "error": "未找到卡 " + args.detail}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, "idea": detail}, ensure_ascii=False, default=str))
        return 0

    ideas = collect_ideas(root)
    timeline = collect_timeline(root)
    index_path = root / "knowledge" / "_index.yaml"
    capacity = parse_index_header(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    tally = collect_tally(root)
    s2_attrib = collect_s2_attrib(root)
    skill_exec = collect_skill_exec(root)
    measure_runs = collect_measure_runs(root)

    # 卡状态机分布（词表以 verify_proposals 为准；unknown 说明卡有 schema 问题）
    status_count = {}
    for c in ideas:
        st = c.get("status") or "unknown"
        status_count[st] = status_count.get(st, 0) + 1

    payload = {
        "ideas": ideas,
        "idea_count": len(ideas),
        "status_count": status_count,
        "stats": collect_stats(ideas),
        "timeline": timeline,
        "capacity": capacity,
        "tally": tally,
        "s2_attrib": s2_attrib,
        "skill_exec": skill_exec,
        "measure_runs": measure_runs,
        "stale_days": STALE_DAYS,
        "surface_window_days": SURFACE_WINDOW_DAYS,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    print(json.dumps(payload, ensure_ascii=False, default=str))


if __name__ == "__main__":
    from _stdio import pin_utf8_stdio
    pin_utf8_stdio()
    sys.exit(main() or 0)
