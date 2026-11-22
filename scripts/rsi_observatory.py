#!/usr/bin/env python3
"""rsi_observatory.py —— RSI 实验台的只读数据桥。

面板（``dsh-plugins/dsh-rsi-observatory``）不读 JSONL，也不解析 RSI 事件：它经 shell 调本脚本，
本脚本只用 ``evolve.store`` 的 ``open_store()`` / ``read()`` / ``history()`` 取证，输出一份归一化
的 JSON。换后端（``sleuth.config.yaml 的 ``evolution.store`` / ``SLEUTH_RSI_STORE_*``）时面板不用改。

为什么不在面板里读文件：存储层已经拆成端口（``store/ports.py``），默认才是本地 JSONL；直接读文件
会把面板绑死在 ``local`` 后端上，也绕开 ``RSIEvent.validate()`` 的 schema 校验。同理，本脚本不读
``conclusions.jsonl`` / ``experiments.jsonl`` / ``proposals.jsonl`` 这些投影——权威流只有 RSIStore。

用法：
  python3 scripts/rsi_observatory.py list --json [--root <检出>] [--base <evolve 目录>]
  python3 scripts/rsi_observatory.py detail --experiment <事件或实验 id> --json --root <检出>

退出码：0 成功；2 参数错；3 store 不可读（坏 JSON 行 / 未知后端）；4 找不到该实验。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _stdio import pin_utf8_stdio  # noqa: E402
from exec_log_path import resolve_checkout_dir  # noqa: E402
from evolve.store import KINDS, SCHEMA as STORE_SCHEMA, open_store  # noqa: E402

VIEW_SCHEMA = "rsi-observatory-v1"
STRING_LIMIT = 4000
MISSING_STAGE = "store 里没有这个阶段"


class ObservatoryNotFound(ValueError):
    """请求的事件 / 实验不在 store 里。"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def resolve_base(root: Optional[str], base: Optional[str]) -> Path:
    """``--base`` 直指 evolve 目录；否则用与 CLI 同一条主检出锚点（worktree 也能读到共享那份）。"""
    if base:
        return Path(base).expanduser()
    anchor = Path(root).expanduser() if root else Path.cwd()
    path, _where, _rel = resolve_checkout_dir("evolve", anchor)
    if path is None:  # 名字不认识时才会发生；保留与 CLI 相同的退化
        return anchor / ".s2-replay" / "evolve"
    return path


def clip_text(value: Any, limit: int = STRING_LIMIT) -> Tuple[Any, bool]:
    """递归截断长字符串：事件里嵌着完整 proposal，``artifact.diff`` 可达几十 KB。"""
    if isinstance(value, str):
        if len(value) > limit:
            return value[:limit] + "\n…（已截断）", True
        return value, False
    if isinstance(value, list):
        out_list: List[Any] = []
        truncated = False
        for item in value:
            clipped, flag = clip_text(item, limit)
            out_list.append(clipped)
            truncated = truncated or flag
        return out_list, truncated
    if isinstance(value, dict):
        out_map: Dict[str, Any] = {}
        truncated = False
        for key, item in value.items():
            clipped, flag = clip_text(item, limit)
            out_map[key] = clipped
            truncated = truncated or flag
        return out_map, truncated
    return value, False


def dict_of(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def text_of(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def number_of(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def build_source(store: Any) -> Dict[str, Any]:
    return {
        "base": str(store.base),
        "backend": str(getattr(store.config, "backend", "") or ""),
        "path": str(store.path) if store.path is not None else None,
        "storeSchema": STORE_SCHEMA,
        "kinds": list(KINDS),
    }


def experiment_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """只取 experiment 事件，按时间倒序；同秒按 event_id 稳定。"""
    out = [row for row in rows if row.get("kind") == "experiment"]
    out.sort(key=lambda row: (str(row.get("at") or ""), str(row.get("event_id") or "")),
              reverse=True)
    return out


def decision_of(data: Dict[str, Any]) -> str:
    experiment = dict_of(data.get("experiment"))
    conclusion = dict_of(data.get("conclusion"))
    rollout = dict_of(data.get("rollout"))
    return (text_of(experiment.get("decision")) or text_of(conclusion.get("decision"))
            or text_of(rollout.get("decision")))


def rolled_back_of(data: Dict[str, Any]) -> bool:
    proposal = dict_of(data.get("proposal"))
    rollout = dict_of(data.get("rollout"))
    return bool(proposal.get("rolled_back")) or bool(rollout.get("rolled_back"))


def paired_of(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    experiment = dict_of(data.get("experiment"))
    conclusion = dict_of(data.get("conclusion"))
    paired = experiment.get("paired")
    if isinstance(paired, dict) and all(key in paired for key in ("b", "c", "n")):
        return {"b": paired.get("b"), "c": paired.get("c"), "n": paired.get("n")}
    if any(key in conclusion for key in ("b", "c", "n")):
        return {"b": conclusion.get("b"), "c": conclusion.get("c"), "n": conclusion.get("n")}
    return None


def score_of(data: Dict[str, Any], side: str) -> Optional[float]:
    experiment = dict_of(data.get("experiment"))
    item = dict_of(experiment.get(side))
    return number_of(item.get("score"))


def row_gaps(data: Dict[str, Any]) -> List[str]:
    """列表行只放轻量缺口；完整缺口在 detail 里算。"""
    gaps: List[str] = []
    if not dict_of(data.get("conclusion")):
        gaps.append("no_conclusion")
    if not decision_of(data):
        gaps.append("unknown_decision")
    if rolled_back_of(data):
        gaps.append("rolled_back")
    return gaps


def build_stages(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """优先读实验记录里的 stage_reports；旧记录才回退到字段派生。"""
    proposal = dict_of(data.get("proposal"))
    experiment = dict_of(data.get("experiment"))
    recorded = experiment.get("stage_reports")
    if isinstance(recorded, list) and recorded:
        stages = []
        for item in recorded:
            if not isinstance(item, dict) or not text_of(item.get("id")):
                continue
            stages.append({
                "id": text_of(item.get("id")),
                "label": text_of(item.get("label")) or text_of(item.get("id")),
                "state": text_of(item.get("state")) or "empty",
                "summary": text_of(item.get("summary")),
                "fields": [str(field) for field in (item.get("fields") or [])
                           if str(field).strip()],
            })
        if stages:
            return stages
    experiment = dict_of(data.get("experiment"))
    conclusion = dict_of(data.get("conclusion"))
    rollout = dict_of(data.get("rollout"))

    def node(stage_id: str, label: str, fields: List[str], summary: str) -> Dict[str, Any]:
        if not fields:
            return {"id": stage_id, "label": label, "state": "empty", "fields": [],
                    "summary": MISSING_STAGE}
        return {"id": stage_id, "label": label, "state": "evidence", "fields": fields,
                "summary": summary}

    sample_ids = [str(item) for item in (experiment.get("samples") or []) if str(item)]
    stages: List[Dict[str, Any]] = [
        node("attribute", "问题归因", sample_ids,
             "使用 {} 个真实样本：{}".format(len(sample_ids), "、".join(sample_ids))),
        node("select_region", "改动范围",
             [str(experiment.get("target_component"))] if experiment.get("target_component") else [],
             "目标组件：{}".format(experiment.get("target_component") or "未记录")),
        node("select_candidate", "候选选择",
             [str(item) for item in (
                 dict_of(proposal.get("candidate")).get("candidate_id"),
                 dict_of(proposal.get("candidate")).get("file"),
                 dict_of(proposal.get("candidate")).get("base_rev"),
             ) if item],
             "候选：{}".format(dict_of(proposal.get("candidate")).get("candidate_id") or "未记录")),
    ]

    propose_fields = [f"data.proposal.{key}" for key in ("artifact", "expected", "risk", "rollback")
                      if proposal.get(key)]
    files = dict_of(proposal.get("artifact")).get("files")
    file_count = len(files) if isinstance(files, list) else 0
    propose_summary = "{} · {} 个文件 · 预期{}".format(
        text_of(proposal.get("target")) or "目标未写",
        file_count,
        "已写" if proposal.get("expected") else "未写",
    )
    stages.append(node("propose", "提案", propose_fields, propose_summary))

    execute_fields = [f"data.rollout.{key}" for key in ("arms", "samples", "workspace")
                      if rollout.get(key) not in (None, "", {}, [])]
    arms = dict_of(rollout.get("arms"))
    if arms:
        execute_summary = "baseline {} / candidate {} 条 rollout".format(
            arms.get("baseline", "—"), arms.get("candidate", "—"))
    else:
        execute_summary = "没有 arms 计数"
    stages.append(node("execute", "执行", execute_fields, execute_summary))

    judge_fields = []
    if experiment.get("baseline"):
        judge_fields.append("data.experiment.baseline")
    if experiment.get("candidate"):
        judge_fields.append("data.experiment.candidate")
    if experiment.get("samples"):
        judge_fields.append("data.experiment.samples")
    if conclusion.get("b") is not None or conclusion.get("c") is not None:
        judge_fields.append("data.conclusion.b/c/n")
    baseline = score_of(data, "baseline")
    candidate = score_of(data, "candidate")
    if baseline is not None or candidate is not None:
        judge_summary = "均分 baseline {} / candidate {}".format(
            "—" if baseline is None else f"{baseline:.4f}",
            "—" if candidate is None else f"{candidate:.4f}",
        )
    elif paired_of(data):
        paired = paired_of(data) or {}
        judge_summary = "b={} c={} n={}".format(paired.get("b"), paired.get("c"), paired.get("n"))
    else:
        judge_summary = "没有评分记录"
    stages.append(node("judge", "评分", judge_fields, judge_summary))

    gate_fields = [f"data.conclusion.{key}" for key in ("decision", "reason", "alpha_eff", "p_value")
                   if conclusion.get(key) not in (None, "")]
    if gate_fields:
        gate_summary = text_of(conclusion.get("decision")) or "未记录判定"
        reason = text_of(conclusion.get("reason"))
        if reason:
            gate_summary += " · " + (reason if len(reason) <= 60 else reason[:60] + "…")
    else:
        gate_summary = "没有判定记录"
    stages.append(node("gate", "判定", gate_fields, gate_summary))
    return stages


def build_gaps(data: Dict[str, Any], history: List[Dict[str, Any]]) -> List[str]:
    gaps: List[str] = []
    conclusion = dict_of(data.get("conclusion"))
    if not conclusion:
        gaps.append("no_conclusion")
    elif not conclusion.get("cost"):
        gaps.append("no_cost")
    if not decision_of(data):
        gaps.append("unknown_decision")
    if not dict_of(data.get("rollout")):
        gaps.append("no_rollout")
    if rolled_back_of(data):
        gaps.append("rolled_back")
    experiment_events = [row for row in history if row.get("kind") == "experiment"]
    if len(experiment_events) > 1:
        gaps.append("id_collision")
    return gaps


def event_summary(row: Dict[str, Any]) -> str:
    kind = text_of(row.get("kind"))
    data = dict_of(row.get("data"))
    if kind == "experiment":
        return "实验记录 · " + (decision_of(data) or "未判定")
    if kind == "proposal":
        return "提案 " + (text_of(dict_of(data.get("proposal")).get("id"))
                         or text_of(data.get("id")))
    if kind == "decision":
        return "判定 " + (text_of(data.get("decision")) or "未记录")
    if kind == "rollout":
        return "执行记录 " + (text_of(data.get("decision")) or "未记录")
    if kind == "archive":
        return "归档记录"
    return kind or "事件"


def event_row(row: Dict[str, Any]) -> Dict[str, Any]:
    data, truncated = clip_text(dict_of(row.get("data")))
    return {
        "eventId": str(row.get("event_id") or ""),
        "kind": str(row.get("kind") or ""),
        "at": str(row.get("at") or ""),
        "proposalId": row.get("proposal_id"),
        "experimentId": row.get("experiment_id"),
        "summary": event_summary(row),
        "data": data,
        "truncated": truncated,
    }


def build_list(rows: List[Dict[str, Any]], source: Dict[str, Any]) -> Dict[str, Any]:
    experiments: List[Dict[str, Any]] = []
    proposals: Dict[str, Dict[str, Any]] = {}
    events = experiment_rows(rows)
    for row in events:
        data = dict_of(row.get("data"))
        proposal = dict_of(data.get("proposal"))
        experiment = dict_of(data.get("experiment"))
        experiment_id = str(row.get("experiment_id") or "")
        proposal_id = str(row.get("proposal_id") or proposal.get("id") or "")
        at = str(row.get("at") or "")
        context = experiment.get("sample_context")
        context = context if isinstance(context, list) else []
        problem = ""
        for item in context:
            if isinstance(item, dict) and text_of(item.get("title")):
                problem = text_of(item.get("title"))
                break
        experiments.append({
            "eventId": str(row.get("event_id") or ""),
            "at": at,
            "experimentId": experiment_id,
            "proposalId": proposal_id,
            "title": (text_of(proposal.get("summary")) or text_of(experiment.get("summary"))
                      or "(未命名实验)"),
            "problem": problem,
            "sampleContext": context,
            "target": text_of(proposal.get("target")) or text_of(experiment.get("target_kind")),
            "component": (text_of(proposal.get("component"))
                          or text_of(experiment.get("target_component"))),
            "decision": decision_of(data),
            "baselineScore": score_of(data, "baseline"),
            "candidateScore": score_of(data, "candidate"),
            "paired": paired_of(data),
            "rolledBack": rolled_back_of(data),
            "gaps": row_gaps(data),
        })
        if not proposal_id:
            continue
        item = proposals.get(proposal_id)
        if item is None:
            item = {
                "proposalId": proposal_id,
                "title": text_of(proposal.get("summary")) or "(未命名提案)",
                "problem": problem,
                "target": text_of(proposal.get("target")),
                "component": text_of(proposal.get("component")),
                "eventId": str(row.get("event_id") or ""),
                "at": at,
                "status": text_of(proposal.get("status")),
                "decision": decision_of(data),
                "artifactKind": text_of(proposal.get("artifact_kind")),
                "files": list(dict_of(proposal.get("artifact")).get("files") or []),
                "expected": text_of(proposal.get("expected")),
                "risk": text_of(proposal.get("risk")),
                "rollback": text_of(proposal.get("rollback")),
                "rolledBack": rolled_back_of(data),
                "experimentIds": [],
            }
            proposals[proposal_id] = item
        if experiment_id and experiment_id not in item["experimentIds"]:
            item["experimentIds"].append(experiment_id)

    proposal_list = sorted(proposals.values(),
                           key=lambda item: (str(item.get("at") or ""),
                                             str(item.get("proposalId") or "")),
                           reverse=True)
    other_events = len(rows) - len(events)
    return {
        "schema": VIEW_SCHEMA,
        "generatedAt": now_iso(),
        "source": source,
        "counts": {"events": len(rows), "experiments": len(experiments),
                   "proposals": len(proposal_list)},
        "experiments": experiments,
        "proposals": proposal_list,
        "warnings": ([f"有 {other_events} 条非 experiment 事件不在列表里（history 里仍可查看）"]
                     if other_events else []),
    }


def find_target(rows: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    events = experiment_rows(rows)
    for row in events:
        if str(row.get("event_id") or "") == key:
            return row
    for row in events:
        if str(row.get("experiment_id") or "") == key:
            return row
    raise ObservatoryNotFound("store 里没有 experiment {!r}".format(key))


def build_detail(rows: List[Dict[str, Any]], store: Any, key: str,
                 source: Dict[str, Any]) -> Dict[str, Any]:
    target = find_target(rows, key)
    data = dict_of(target.get("data"))
    experiment_id = str(target.get("experiment_id") or "")
    if experiment_id:
        history = store.history(experiment_id=experiment_id)
    else:
        history = [target]

    proposal, proposal_truncated = clip_text(dict_of(data.get("proposal")))
    record, record_truncated = clip_text(dict_of(data.get("experiment")))
    conclusion, conclusion_truncated = clip_text(dict_of(data.get("conclusion")))
    rollout, rollout_truncated = clip_text(dict_of(data.get("rollout")))

    return {
        "schema": VIEW_SCHEMA,
        "generatedAt": now_iso(),
        "source": source,
        "experiment": {
            "eventId": str(target.get("event_id") or ""),
            "at": str(target.get("at") or ""),
            "experimentId": experiment_id,
            "proposalId": str(target.get("proposal_id") or ""),
        },
        "proposal": proposal,
        "record": record,
        "conclusion": conclusion,
        "rollout": rollout,
        "stages": build_stages(data),
        "history": [event_row(row) for row in history],
        "gaps": build_gaps(data, history),
        "truncated": any((proposal_truncated, record_truncated,
                          conclusion_truncated, rollout_truncated)),
        "notes": ["七个环节按实验执行顺序排列；没有记录的环节会显示为空。",
                  "数据只来自实验记录库（RSIStore），不读派生文件。"],
    }


def command_list(args: argparse.Namespace) -> int:
    base = resolve_base(args.root, args.base)
    store = open_store(base)
    rows = store.read()
    payload = build_list(rows, build_source(store))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def command_detail(args: argparse.Namespace) -> int:
    base = resolve_base(args.root, args.base)
    store = open_store(base)
    rows = store.read()
    payload = build_detail(rows, store, args.experiment, build_source(store))
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RSI 实验台只读数据桥")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--root", default=None, help="检出根（默认当前目录；解析到主检出）")
        target.add_argument("--base", default=None, help="evolve 目录（跳过主检出解析，测试用）")
        target.add_argument("--json", action="store_true", help="输出 JSON（当前唯一格式）")

    listing = sub.add_parser("list", help="实验与提案索引")
    common(listing)
    listing.set_defaults(func=command_list)

    detail = sub.add_parser("detail", help="一条实验的明细与 history")
    common(detail)
    detail.add_argument("--experiment", required=True, help="事件 id（E-…）或实验 id（EX-…）")
    detail.set_defaults(func=command_detail)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ObservatoryNotFound as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return 4
    except Exception as exc:  # 读侧失败一律归到 3，stderr 保留原文
        print("error: {}: {}".format(type(exc).__name__, exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    pin_utf8_stdio()
    raise SystemExit(main())
