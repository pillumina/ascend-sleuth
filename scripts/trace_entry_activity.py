#!/usr/bin/env python3
"""trace_entry_activity.py —— 把本机诊断记录汇总成条目使用记录的**增量行**（一次知识整理的第 3 步）。

它回答的问题是「这一轮里，哪些条目被选中/被加载/被排除，哪些先验被查了、查的结果是什么，
哪几个工具花了多少时间」。这些量在轨迹与会话日志里都有，但此前没有任何脚本产出它们
（`settle_trace_feedback.py` 头注里那句「数据都在 traces 里，但没有任何脚本产出它」指的就是这件事）。

数据源两处，各有各的失败形态（都不补估值）：

  轨迹 `traces/<session_id>.yaml`   条目触达（选中/加载/排除）、先验三态与消费点、路由与结局
  harness 会话日志                  逐次工具调用与 token 账单；**按会话 id 关联**，关联不上就缺席

产出三样：

  ① 本机明细 `metrics/entry-activity.local/<session_id>.yaml`（gitignored、锚主检出）——
     一次诊断一行，含逐次工具调用明细（命令摘要与文件路径含现场信息，不上仓）。面板读它。
  ② 增量行追加进 `metrics/entry-activity.d/<周>.yaml` 的 `kind: case` / `kind: ref` / `kind: tool`。
  ③ 人读摘要：这一轮覆盖了几个会话、写了多少行、哪些会话取不到账单。

**增量怎么算**：每个会话的累计计数存在游标的 `_entry_activity` 段里，本轮的计数减去上一次的计数
就是要写的行。轨迹是**追加型**的（一次诊断跑几步就多几条事件），所以不能按「会话处理过一次就跳过」
判——那样后来补上的 `feedback`、`excluded_cases` 永远进不了记录。存计数快照则天然只取增量。

**为什么 resolved / misdiagnosed / self_resolved 不在这里写**：那是现场回报的结算，归第 2 步
`settle_trace_feedback.py`（它有逐事件的幂等游标与「自证 vs 独立命中」的判定）。两个脚本各印自己的
`run` 时间戳、各写各的行，同一个 case 在同一轮整理里因此可能有两行、字段互补——聚合按 id 求和。

用法（groom 周批，串行）：

  python3 scripts/trace_entry_activity.py                 # dry-run：只打印将要写的行
  python3 scripts/trace_entry_activity.py --apply         # 追加进源文件 + 更新游标 + 写本机明细
  python3 scripts/trace_entry_activity.py --session <id>  # 只处理某个会话（调试用）

退出码：0 = 成功（含「本轮没有新数据」）；2 = 参数或环境不可用。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import entry_activity as ea  # noqa: E402
import index_read_cost as irc  # noqa: E402
from _stdio import pin_utf8_stdio, write_text_lf  # noqa: E402
from exec_log_path import resolve_rel, resolve_traces  # noqa: E402

# 结算游标同一份文件（gitignored、锚主检出）。为什么共用：两件事都是「本机幂等状态」，
# 开第二份文件就多一处要记得锚主检出的路径。
STATE_REL = Path(".settle-state.json")
CURSOR_KEY = "_entry_activity"

SELF_REPORT = "self-report"
INVESTIGATION = "investigation"
#: 案例 `verification.source` 里可用的档；不在其中的（历史写法）退回 `investigation`。
STRENGTHS = ("upstream-fix-merged", "upstream-official-doc", "upstream-maintainer-confirmed",
             "engineer-report", "investigation", SELF_REPORT)
# 会话日志的文件名**不是固定值**：实测本机 DSH 写的是 `session.v4.jsonl.zstd`，而
# `session_cost.mjs` 与本文原先都写死 `session.jsonl.zstd` —— 于是关联一直失败，
# 成本与工具分布永远是空的，而失败只表现为「本次没记」。按通配找 + 取最新那个。
HARNESS_LOG_PATTERNS = ("session*.jsonl.zstd", "session.jsonl")


# ---------------------------------------------------------------- 会话日志


def harness_home() -> Path:
    return Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))


def find_session_log(sid: str, sessions_root: Path | None = None):
    """会话 id → 会话日志路径；找不到返回 (None, 原因)。"""
    if sessions_root is None:
        sessions_root = harness_home() / "sessions"
    if not sessions_root.is_dir():
        return None, f"会话日志根目录不存在（{sessions_root}）"
    for ws in sorted(sessions_root.iterdir()):
        d = ws / sid
        if not d.is_dir():
            continue
        found = []
        for pat in HARNESS_LOG_PATTERNS:
            found += [p for p in d.glob(pat) if p.is_file()]
        if found:
            return max(found, key=lambda p: p.stat().st_mtime), None
    return None, f"{sessions_root} 下没有 {sid} 的会话日志"


def read_log_text(path: Path):
    """会话日志 → JSONL 文本。

    zstd 解压走 node（Python 标准库没有 zstd，而本仓 scripts/ 一贯零依赖）——**只借它解压**，
    解析仍在 Python 这一处，避免同一套口径两份实现。明文文件（测试夹具）直接读。
    """
    raw = path.read_bytes()
    if raw[:4] != b"\x28\xb5\x2f\xfd":
        return raw.decode("utf-8", "replace")
    node = shutil.which("node")
    if not node:
        return None
    helper = Path(__file__).resolve().parent / "session_cost.mjs"
    r = subprocess.run([node, str(helper), "--decompress", str(path)],
                       capture_output=True, timeout=300)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace")


def _json_events(text: str):
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            yield ev


def read_session_log(path: Path):
    """会话日志 → {tokens, tools, tool_calls}；解不开返回 (None, 原因)。

    tokens 四类按 `(turn, step)` 去重、定稿优先——与 `session_cost.mjs` 同一口径
    （同一 (turn, step) 会同时出现流式与定稿两份，重复计数会让账单虚高）。
    """
    text = read_log_text(path)
    if text is None:
        return None, "会话日志解不开（node 不可用或文件损坏）"
    attempts, calls, results = {}, {}, {}
    for ev in _json_events(text):
        t, d = ev.get("type"), ev.get("data") or {}
        if t == "assistant/message" and d.get("usage"):
            attempts[(d.get("turn"), d.get("step"))] = (d["usage"], "final")
        elif t == "assistant/chunk" and (d.get("chunk") or {}).get("type") == "usage":
            key = (d.get("turn"), d.get("step"))
            if attempts.get(key, (None, None))[1] != "final":
                attempts[key] = (d["chunk"]["usage"], "stream")
        elif t == "tool/call":
            calls[d.get("callId")] = {"name": d.get("name") or "?", "t": ev.get("time") or 0,
                                      "step": d.get("step"), "args": d.get("arguments") or ""}
        elif t == "tool/result":
            src = ((d.get("message") or {}).get("source") or {})
            cid = src.get("callId")
            if cid:
                content = (d.get("message") or {}).get("content") or []
                err = any(isinstance(c, dict) and c.get("isError") for c in content)
                results[cid] = {"t": ev.get("time") or 0, "error": err,
                                "code": ((d.get("error") or {}).get("name")
                                         or (d.get("error") or {}).get("code") or "")}

    tokens = {"uncached": 0, "cache_read": 0, "cache_write": 0, "out": 0}
    for usage, _kind in attempts.values():
        tokens["uncached"] += int(usage.get("inputTokens") or 0)
        tokens["cache_read"] += int(usage.get("cacheReadTokens") or 0)
        tokens["cache_write"] += int(usage.get("cacheWriteTokens") or 0)
        tokens["out"] += int(usage.get("outputTokens") or 0)

    tool_calls, stats = [], {}
    for cid, c in calls.items():
        r = results.get(cid)
        ms = max(0, int(r["t"]) - int(c["t"])) if (r and c["t"] and r["t"]) else None
        err = bool(r and r["error"])
        code = (r or {}).get("code") or ""
        timeout = err and "timeout" in code.lower()
        tool_calls.append({"tool": c["name"], "step": c["step"], "ms": ms,
                           "ok": not err, "args": _brief_args(c["name"], c["args"]),
                           **({"error": code or "error"} if err else {})})
        s = stats.setdefault(c["name"], {"durs": [], "errors": 0, "timeouts": 0, "calls": 0})
        s["calls"] += 1
        if ms is not None:
            s["durs"].append(ms)
        if err:
            s["errors"] += 1
        if timeout:
            s["timeouts"] += 1
    tool_calls.sort(key=lambda x: (x["step"] or 0, x["ms"] or 0))
    return {"tokens": tokens, "tools": stats, "tool_calls": tool_calls}, None


def _brief_args(name: str, args: str) -> str:
    """命令摘要：只留能认出「读了什么/查了什么」的那一小段，不留全文（明细含现场信息）。"""
    try:
        d = json.loads(args) if args else {}
    except ValueError:
        d = {}
    if not isinstance(d, dict):
        d = {}
    for k in ("pattern", "query", "command", "cmd", "file_path", "path", "filePath", "url"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:160]
    return " ".join(str(args or "").split())[:120]


def percentile(values, q):
    if not values:
        return 0
    xs = sorted(values)
    if len(xs) == 1:
        return int(xs[0])
    pos = (len(xs) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(xs) - 1)
    return int(round(xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)))


# ---------------------------------------------------------------- 轨迹事实


def _ref_ids(ev: dict):
    out = []
    for key in ("ref_ids", "ref_id", "ref"):
        v = ev.get(key)
        if isinstance(v, str) and v.strip() and v.strip() not in out:
            out.append(v.strip())
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str) and x.strip() and x.strip() not in out:
                    out.append(x.strip())
    return out


def _case_ids(ev: dict):
    out = []
    if isinstance(ev.get("case"), str):
        out.append(ev["case"])
    for key in ("candidates", "considered_candidates", "excluded_cases"):
        v = ev.get(key)
        if isinstance(v, list):
            out += [x for x in v if isinstance(x, str)]
    return out


def trace_facts(st) -> dict:
    """轨迹 → 用于记录的事实（纯函数：同样的轨迹得到同样的事实，不读时钟、不读网络）。"""
    trace = st.get("trace") or []
    actions, cases, refs = {}, {}, {}
    routed, hit_case, candidates_seen = "", None, set()
    excluded_from_events = set()
    route_seen = False

    def case(cid):
        return cases.setdefault(cid, {"selected": 0, "loaded": 0, "excluded": 0})

    for ev in trace:
        a = ev.get("action")
        if a:
            actions[a] = actions.get(a, 0) + 1
        if a == "triage" and not route_seen:
            r = ev.get("routed")
            if isinstance(r, list):
                route_seen = True
                for ns in r:
                    if isinstance(ns, str) and ns.strip() and ns.strip().rstrip("/") != "common":
                        routed = ns.strip().rstrip("/")
                        break
        if a == "triage_semantic" and not routed and ev.get("namespace"):
            routed = str(ev["namespace"]).rstrip("/")
        # 一个事件里点名的 case **按集合算**：同一个事件常常同时写 `candidates` 与
        # `considered_candidates`（后者是前者的超集），逐字段加会把同一次触达记两遍
        # ——实测一单 3 条候选被记成 selected 5 / loaded 2。
        sel = set()
        loaded = set()
        excluded = set()
        if a == "hit" and ev.get("case"):
            hit_case = hit_case or str(ev["case"])
            sel.add(str(ev["case"]))
        if a == "load_full":
            loaded |= {c for c in (ev.get("candidates") or []) if isinstance(c, str)}
        if a == "quickly_check" and ev.get("case"):
            # quickly_check 在阶段二的全文之上做验证：点到它即进过候选集、也读过正文。
            sel.add(str(ev["case"]))
            loaded.add(str(ev["case"]))
        for key in ("candidates", "considered_candidates"):
            v = ev.get(key)
            if isinstance(v, list):
                for cid in v:
                    if isinstance(cid, str):
                        candidates_seen.add(cid)
                        sel.add(cid)
        # 被排除 = 检索到但被筛掉。`excluded_cases` 可能挂在任何事件上，也可能只写在顶层
        # （顶层是这一单的汇总）——**同一个 id 只计一次**：事件里出现过就不再记顶层的。
        excluded |= {c for c in (ev.get("excluded_cases") or []) if isinstance(c, str)}
        for cid in sel:
            case(cid)["selected"] += 1
        for cid in loaded:
            case(cid)["loaded"] += 1
        for cid in excluded:
            case(cid)["excluded"] += 1
            excluded_from_events.add(cid)
        if a == "reference_lookup":
            # `lookups` 记「查了一条先验」——事件在就算查过，与三态是否记录无关。三态缺记录的
            # 事件因此表现为 `lookups > hit+miss+skipped`，这个差本身就是记账缺口的读数。
            purpose = ev.get("purpose")
            outcome = ev.get("outcome")
            for rid in _ref_ids(ev):
                r = refs.setdefault(rid, {"lookups": 0, "hit": 0, "miss": 0, "skipped": 0,
                                          "purpose": {}})
                r["lookups"] += 1
                if outcome in ("hit", "miss", "skipped"):
                    r[outcome] += 1
                if purpose:
                    r["purpose"][purpose] = r["purpose"].get(purpose, 0) + 1

    # 顶层 `excluded_cases` 与事件里的同名列表是同一个事实的两种写法：事件里已经记过的
    # 不再从顶层补，否则一单的「被排除」会被算成 2。
    for cid in (st.get("excluded_cases") or []):
        if isinstance(cid, str) and cid not in excluded_from_events:
            case(cid)["excluded"] += 1

    ref_ids_all = []
    for ev in trace:
        if ev.get("action") == "reference_lookup":
            for rid in _ref_ids(ev):
                if rid not in ref_ids_all:
                    ref_ids_all.append(rid)

    fb = st.get("feedback") or {}
    sed = st.get("sedimented") or {}
    out = st.get("outcome") or {}
    return {
        "actions": actions,
        "cases": cases,
        "refs": refs,
        "routed": routed,
        "hit_case": hit_case,
        "candidates_seen": sorted(candidates_seen),
        "ref_ids": ref_ids_all,
        "feedback": fb if isinstance(fb, dict) else {},
        "sedimented": sed if isinstance(sed, dict) else {},
        "outcome": out if isinstance(out, dict) else {},
        "load_index_events": [ev for ev in trace if ev.get("action") == "load_index"],
        "load_full_events": [ev for ev in trace if ev.get("action") == "load_full"],
    }


def strength_of(facts, self_resolved: bool) -> str:
    """结论强度档：自证 → `self-report`；命中案例 → 该案例的 `verification.source`；否则 `investigation`。

    `self-report` 是本文新加的一档，**不进案例的 `verification.source` 枚举**：它描述的是
    「这条结论靠来源会话自己回报站住」，不是「内容被外部验证过」，两者不能同权（文档 3.1）。
    """
    if self_resolved:
        return SELF_REPORT
    src = facts.get("case_verification_source")
    if src in STRENGTHS and src != SELF_REPORT:
        return src
    return INVESTIGATION


def is_self_resolve(sid: str, facts) -> bool:
    """本次的 resolve 是不是「来源会话自证」——该会话正是**这次回报的那条 case** 的产地。

    与 `settle_trace_feedback.py` 的 `is_self_settle()` 同源（两处判同一件事，必须同口径）：
    案例的 `source_session` 指向本会话，或本会话 trace 的 `sedimented.case_id` 就是该案例。
    判的是回报的那条 case，不是命中的那条——两者可以不同（本次命中 9005、最终沉淀成 12430）。
    """
    fb = facts["feedback"]
    if fb.get("outcome") != "resolved":
        return False
    cid = fb.get("case")
    if not cid:
        return False
    sed = facts["sedimented"]
    sed_id = sed.get("case_id") or sed.get("caseId")
    if sed_id and str(cid) == str(sed_id):
        return True
    return facts.get("case_source_session") == sid


# ---------------------------------------------------------------- 索引读入账


def index_read_account(root: Path, facts: dict, case_files: dict, category=None):
    """一次诊断的读入账，四个分项（`index_read_cost.py` 的同一把尺子现算）。

    按会话归属此前没有产出方（见文档 3.1 的「待接」）。这里的口径是**这次会话实际读了哪些面**：
      类视图 / 兜底视图 —— 从 `load_index` 事件与路由结果推出读了哪一份视图，按视图文件现算；
      先验层          —— 这次查过的先验词条文件成本之和；
      阶段二候选全文  —— 这次 `load_full` 取过全文的案例文件成本之和。
    量不出的分项记 None（"量不出"与"免费"必须不同形）。
    """
    account = {"class_view": None, "fallback_view": None, "reference_layer": None,
               "candidates_full": None}
    ns = facts["routed"]
    shard_dir = Path(root) / "knowledge" / "_index"
    views_class, views_fallback = set(), set()
    for ev in facts["load_index_events"]:
        namespaces = ev.get("namespaces") or ([ev["namespace"]] if ev.get("namespace") else [])
        for n in namespaces:
            if not isinstance(n, str) or not n.strip():
                continue
            slug = n.strip().rstrip("/").replace("/", "__")
            c = ev.get("category") or category
            if c:
                views_class.add(shard_dir / f"{slug}__{c}.list")
            else:
                views_fallback.add(shard_dir / f"{slug}.list")
    if not facts["load_index_events"] and ns:
        slug = ns.replace("/", "__")
        (views_class if category else views_fallback).add(
            shard_dir / (f"{slug}__{category}.list" if category else f"{slug}.list"))

    def sum_views(paths):
        if not paths:
            return None
        tot, missing = 0, 0
        for p in sorted(paths):
            if p.exists():
                tot += irc.tok(p.read_text(encoding="utf-8"))
            else:
                missing += 1
        return tot if not missing else None

    account["class_view"] = sum_views(views_class)
    account["fallback_view"] = sum_views(views_fallback)

    ref_files = []
    for rid in facts["ref_ids"]:
        p = facts.get("_ref_paths", {}).get(rid)
        if p:
            ref_files.append(p)
    if ref_files:
        account["reference_layer"] = sum(irc.tok(p.read_text(encoding="utf-8")) for p in ref_files)

    full_files = []
    for ev in facts["load_full_events"]:
        for cid in (ev.get("candidates") or []):
            p = case_files.get(cid)
            if p:
                full_files.append(p)
    if full_files:
        account["candidates_full"] = sum(irc.tok(p.read_text(encoding="utf-8")) for p in full_files)
    return account


def ref_index(root: Path):
    """全库先验 → ({id: 文件路径}, {路径别名: id})。

    别名表解决一个历史写法偏差：schema 要求 `reference_lookup.ref_id` 写**词条 id**，而实际
    trace 里有写文件路径的（`references/fault-patterns/reg-data-movement.yaml`）。记录按 id 建键，
    路径写法若不归一，聚合出来的就是一条 id 是路径的假条目——面板上按 id 点不进任何词条。
    归一表覆盖三种写法：仓库相对路径、裸文件名、去扩展名的文件名。
    """
    by_id, alias = {}, {}
    rdir = Path(root) / "references"
    if not rdir.is_dir():
        return by_id, alias
    for p in sorted(rdir.rglob("*.yaml")):
        if p.name.startswith("_"):
            continue
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not (isinstance(d, dict) and d.get("id")):
            continue
        rid = str(d["id"])
        by_id.setdefault(rid, p)
        rel = p.relative_to(root).as_posix()
        alias.setdefault(rid, rid)
        for key in (rel, p.name, p.stem, str(p)):
            alias.setdefault(key, rid)
    return by_id, alias


def normalize_refs(facts: dict, alias: dict):
    """把 reference_lookup 的值归一到词条 id → (facts 就地改, 未归属清单)。"""
    unattributed, remap = [], {}
    out_refs, out_ids = {}, []
    for rid, v in facts["refs"].items():
        target = alias.get(rid)
        if target is None:
            unattributed.append(rid)
            continue
        remap[rid] = target
        dst = out_refs.setdefault(target, {"lookups": 0, "hit": 0, "miss": 0, "skipped": 0,
                                           "purpose": {}})
        for k in ea.COUNT_KEYS["ref"]:
            dst[k] += int(v.get(k, 0) or 0)
        for p, n in (v.get("purpose") or {}).items():
            dst["purpose"][p] = dst["purpose"].get(p, 0) + int(n or 0)
    for rid in facts["ref_ids"]:
        target = remap.get(rid)
        if target and target not in out_ids:
            out_ids.append(target)
    facts["refs"] = out_refs
    facts["ref_ids"] = out_ids
    return facts, unattributed


def case_index(root: Path):
    """全库案例 → ({id: 文件路径}, {id: verification.source}, {id: source_session})。只读活跃面。"""
    files, ver, src_sess = {}, {}, {}
    kdir = Path(root) / "knowledge"
    if not kdir.is_dir():
        return files, ver, src_sess
    for f in sorted(kdir.rglob("*.yaml")):
        if f.name.startswith("_") or "_archive" in f.parts:
            continue
        try:
            d = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for c in (d.get("cases") or []):
            if not c.get("id"):
                continue
            files[str(c["id"])] = f
            v = c.get("verification") or {}
            if isinstance(v, dict) and v.get("source"):
                ver[str(c["id"])] = str(v["source"])
            if c.get("source_session"):
                src_sess[str(c["id"])] = str(c["source_session"])
    return files, ver, src_sess


# ---------------------------------------------------------------- 游标


def load_state(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def save_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(path, json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _delta(new: dict, old: dict, keys):
    d = {}
    for k in keys:
        v = int(new.get(k, 0) or 0) - int(old.get(k, 0) or 0)
        if v:
            d[k] = v
    return d


def _delta_purpose(new: dict, old: dict):
    d = {}
    for p in ea.PURPOSES:
        v = int((new.get("purpose") or {}).get(p, 0) or 0) - int((old.get("purpose") or {}).get(p, 0) or 0)
        if v:
            d[p] = v
    return d


# ---------------------------------------------------------------- 主流程


def build_records(root: Path, traces_dir: Path, sessions_root, session_ids, apply: bool,
                  run: str, state_path: Path, use_log: bool = True, local_dir: Path | None = None):
    if local_dir is None:
        local_dir = ea.local_dir(root)
    state = load_state(state_path)
    cursor = state.setdefault(CURSOR_KEY, {})
    traces = sorted(traces_dir.glob("*.yaml")) if traces_dir.is_dir() else []
    if session_ids:
        traces = [t for t in traces if t.stem in set(session_ids)]
    if not traces:
        print(f"未找到任何 traces/*.yaml（读的是 {traces_dir}）——本轮没有要汇总的诊断。")
        return 0

    case_files, case_ver, case_src_sess = case_index(root)
    ref_files, ref_alias = ref_index(root)
    case_rows, ref_rows, tool_rows = {}, {}, {}
    covered, notes, detail_written = set(), [], 0
    unattributed = {}

    for tf in traces:
        sid = tf.stem
        try:
            st = yaml.safe_load(tf.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            notes.append(f"[skip] {tf.name}: 解析失败（{e}）——不汇总，保持原状")
            continue
        facts = trace_facts(st)
        facts, unatt = normalize_refs(facts, ref_alias)
        for u in unatt:
            unattributed[u] = unattributed.get(u, 0) + 1
        cid_for_strength = facts["hit_case"] or (facts["sedimented"].get("case_id")
                                                 or facts["sedimented"].get("caseId"))
        facts["case_verification_source"] = case_ver.get(cid_for_strength) if cid_for_strength else None
        # 自证判的是**回报的那条** case 的产地（与命中/沉淀的那条可以不同）。
        fb_case = str(facts["feedback"].get("case") or "")
        facts["case_source_session"] = case_src_sess.get(fb_case) if fb_case else None
        facts["_ref_paths"] = ref_files
        prev = cursor.get(sid) or {}

        log = None
        log_note = None
        if use_log:
            harness_sid = str(st.get("harness_session") or "").strip() or sid
            path, why = find_session_log(harness_sid, sessions_root)
            if path is None:
                log_note = f"{why}（会话成本与工具分布缺席，不补估值）"
            else:
                log, why = read_session_log(path)
                if log is None:
                    log_note = why
        if log_note:
            notes.append(f"  · {sid}: {log_note}")

        # ---- 增量：案例触达 / 先验三态 / 工具分布
        new_cases = {cid: v for cid, v in facts["cases"].items()}
        new_refs = {rid: v for rid, v in facts["refs"].items()}
        new_tools = {name: stats for name, stats in ((log or {}).get("tools") or {}).items()}
        # 工具的三个计数都按**累计值的差**写：会话日志会随续接诊断继续增长，按整份快照写会把
        # 上一轮已经写过的错误再计一遍（实测两轮合计 2 次错误、真实 1 次）。耗时是分布量、
        # 没法存「已写过的耗时列表」（明细不上仓），用累计调用数当切片位置取本轮新增的那一段。
        prev_tools = {name: v for name, v in (prev.get("tools") or {}).items()}
        for name in sorted(new_tools):
            stats = new_tools[name]
            before = prev_tools.get(name) or {}
            base_calls = int(before.get("calls", 0) or 0)
            added_calls = int(stats["calls"]) - base_calls
            added_err = int(stats["errors"]) - int(before.get("errors", 0) or 0)
            added_to = int(stats["timeouts"]) - int(before.get("timeouts", 0) or 0)
            if added_calls <= 0 and added_err <= 0 and added_to <= 0:
                continue
            # 切片位置按「有耗时的调用」的下标算：没有 tool/result 的调用不进 durs，
            # 用 calls 当索引会让切片整体偏移（实测会切空并把分位记成 0）。
            durs = stats["durs"][int(before.get("durs", 0) or 0):]
            t = tool_rows.setdefault(name, {"calls": 0, "errors": 0, "timeouts": 0, "_d": []})
            t["calls"] += max(0, added_calls)
            t["errors"] += max(0, added_err)
            t["timeouts"] += max(0, added_to)
            t["_d"] += durs
            prev_tools[name] = {"calls": int(stats["calls"]), "errors": int(stats["errors"]),
                               "timeouts": int(stats["timeouts"]), "durs": len(stats["durs"])}

        touched_cases = set()
        for cid in sorted(new_cases):
            d = _delta(new_cases[cid], (prev.get("cases") or {}).get(cid) or {}, ea.COUNT_KEYS["case"])
            if not d:
                continue
            row = case_rows.setdefault(cid, {k: 0 for k in ea.COUNT_KEYS["case"]})
            for k, v in d.items():
                row[k] += v
            touched_cases.add(cid)
        for rid in sorted(new_refs):
            d = _delta(new_refs[rid], (prev.get("refs") or {}).get(rid) or {}, ea.COUNT_KEYS["ref"])
            dp = _delta_purpose(new_refs[rid], (prev.get("refs") or {}).get(rid) or {})
            if not d and not dp:
                continue
            row = ref_rows.setdefault(rid, {**{k: 0 for k in ea.COUNT_KEYS["ref"]}, "purpose": {}})
            for k, v in d.items():
                row[k] += v
            for p, v in dp.items():
                row["purpose"][p] = row["purpose"].get(p, 0) + v

        if touched_cases:
            covered.add(sid)

        if apply:
            doc = session_doc(st, sid, facts, log, log_note, case_files, root)
            ea.write_local_record(local_dir, sid, doc)
            detail_written += 1
            new_prev = dict(prev) if log is None else {}
            new_prev.update({
                "cases": {cid: {k: int(v.get(k, 0) or 0) for k in ea.COUNT_KEYS["case"]}
                          for cid, v in new_cases.items()},
                "refs": {rid: {**{k: int(v.get(k, 0) or 0) for k in ea.COUNT_KEYS["ref"]},
                               "purpose": {p: int(n) for p, n in (v.get("purpose") or {}).items()}}
                         for rid, v in new_refs.items()},
                # 会话日志读不到时（缺日志 / 无 node）保留上一次的工具快照：清零会让下一轮
                # 日志可读时把整段调用重新算一次增量（重复计数）。
                "tools": (dict(prev_tools) if log is not None else (prev.get("tools") or {})),
                "folded_at": run,
            })
            cursor[sid] = new_prev

    rows = []
    dep = ea.deployment(root)
    chk, rev = ea.checkout_rev(root), ea.kb_rev(root)
    n_sessions = len(covered)
    for cid in sorted(case_rows):
        rows.append({"run": run, "deployment": dep, "checkout": chk, "kb_rev": rev,
                     "sessions": n_sessions, "kind": "case", "id": cid, **case_rows[cid]})
    for rid in sorted(ref_rows):
        r = ref_rows[rid]
        rows.append({"run": run, "deployment": dep, "checkout": chk, "kb_rev": rev,
                     "sessions": n_sessions, "kind": "ref", "id": rid,
                     **{k: r[k] for k in ea.COUNT_KEYS["ref"]}, "purpose": r["purpose"]})
    for name in sorted(tool_rows):
        t = tool_rows[name]
        rows.append({"run": run, "deployment": dep, "checkout": chk, "kb_rev": rev,
                     "kind": "tool", "id": name, "calls": t["calls"],
                     "p50_ms": percentile(t["_d"], 0.5), "p90_ms": percentile(t["_d"], 0.9),
                     "errors": t["errors"], "timeouts": t["timeouts"]})

    print(f"覆盖 {n_sessions} 个会话；计划写 {len(rows)} 行"
          f"（case {len(case_rows)} / ref {len(ref_rows)} / tool {len(tool_rows)}）。")
    for n in notes:
        print(n)
    if unattributed:
        print("以下 reference_lookup 值归不到任何词条 id（未计入记录，仍留在轨迹里）：")
        for u, n in sorted(unattributed.items()):
            print(f"  · {u}（{n} 次）")
    if not rows:
        print("本轮没有新的条目使用增量（记录已是最新）——不写任何行。")
        return 0
    for r in rows:
        print("  " + ea.format_row(r))
    if not apply:
        print("\n--dry-run（默认）：未写任何文件。确认后加 --apply。")
        return 0

    week = ea.week_of_run(run)
    if week is None:
        print(f"run {run!r} 归不了周——拒绝写入", file=sys.stderr)
        return 2
    f = ea.append_rows(root, week, rows)
    save_state(state_path, state)
    print(f"\n已追加 {len(rows)} 行 → {f}")
    print(f"本机明细 {detail_written} 份 → {local_dir}")
    print(f"游标已更新 → {state_path}")
    return 0


def session_doc(st, sid, facts, log, log_note, case_files, root) -> dict:
    """一次诊断的本机记录（3.1 的字段表）。明细留本机，上仓的只有聚合值。"""
    self_res = is_self_resolve(sid, facts)
    steps = {"count": len(st.get("trace") or [])}
    steps.update({k: v for k, v in sorted(facts["actions"].items())})
    return {
        "session_id": sid,
        "window": {"start": st.get("created_at"), "end": st.get("updated_at")},
        "detected": {"framework": st.get("detected_framework"),
                     "platform": st.get("detected_platform"),
                     "category": st.get("detected_category"),
                     "workload_type": _workload_type(st)},
        "route": {"routed": facts["routed"], "hit_case": facts["hit_case"],
                  "candidates_considered": facts["candidates_seen"]},
        "steps": steps,
        "tool_calls": (log or {}).get("tool_calls") or [],
        "touched": {"cases": sorted(facts["cases"]), "references": sorted(facts["refs"])},
        "outcome": {"status": st.get("status"), "fix_emitted": facts["outcome"].get("fix_emitted"),
                    "stop_reason": st.get("stop_reason")},
        "feedback": facts["feedback"],
        "sedimented": facts["sedimented"],
        "cost": {"tokens": (log or {}).get("tokens") or None,
                 "index_read_tok": index_read_account(root, facts, case_files,
                                                      category=st.get("detected_category"))},
        "strength": strength_of(facts, self_res),
        "harness_session": st.get("harness_session") or None,
        "session_log": log_note or "已关联",
        "kb_rev": st.get("kb_rev"),
    }


def _workload_type(st):
    return st.get("workload_type") or st.get("side")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="写源行、本机明细与游标（默认 dry-run）")
    ap.add_argument("--run", default=None, help="本次运行的标识（默认取当前时间 YYYY-MM-DD-HHMM）")
    ap.add_argument("--root", default=None, help="检出根（默认：脚本上两级）")
    ap.add_argument("--traces-dir", default=None,
                    help="显式指定 traces/（默认解析到主检出共享侧）")
    ap.add_argument("--sessions-root", default=None,
                    help="harness 会话日志根（默认 $DSH_HOME/sessions；测试用）")
    ap.add_argument("--state", default=None, help="本机幂等游标（默认登记在共享运行件里）")
    ap.add_argument("--session", action="append", default=None, help="只处理指定会话（可多次）")
    ap.add_argument("--local-dir", default=None,
                    help="本机明细目录（默认解析到主检出共享侧；测试用）")
    ap.add_argument("--no-session-log", action="store_true",
                    help="不读 harness 会话日志（工具分布与成本缺席；离线/无 node 时用）")
    args = ap.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    traces = Path(args.traces_dir).resolve() if args.traces_dir else resolve_traces(root)
    if args.state:
        state_path = Path(args.state)
    else:
        state_path, _where = resolve_rel(root, STATE_REL)
    run = args.run or ea.now_run()
    return build_records(root, traces, Path(args.sessions_root) if args.sessions_root else None,
                         args.session, args.apply, run, state_path,
                         use_log=not args.no_session_log,
                         local_dir=Path(args.local_dir).resolve() if args.local_dir else None)


if __name__ == "__main__":
    pin_utf8_stdio()
    sys.exit(main())
