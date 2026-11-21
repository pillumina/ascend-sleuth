# -*- coding: utf-8 -*-
"""Proposal -> candidate -> pilot -> judge -> gate -> archive 编排。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml
from typing import Any, Callable, Dict, List, Optional

from .experiments import ExperimentError, validate_experiment
from .candidate import diff_workspace, rollback_workspace
from .knowledge_usage import compare as compare_knowledge
from .pilot import collect as pilot_collect, decide as pilot_decide, prepare as pilot_prepare
from .source_usage import compare as compare_source
from .records import ExperimentStore
from .rsi_store import RSIStore
from .proposal_engine import Proposal, ProposalArchive, ProposalEngine


class FlowError(ValueError):
    pass


def run_proposal(root: Path, proposal: Proposal, samples: List[str], output: Path,
                 policy: Dict[str, Any], judge: Optional[Path],
                 archive: ProposalArchive,
                 runner: Optional[Callable[[Dict[str, Any]], None]] = None,
                 baseline_traces: Optional[Path] = None,
                 reuse_index: Optional[int] = None,
                 exploratory: bool = False,
                 card: Optional[str] = None,
                 dry_run: bool = False) -> Dict[str, Any]:
    if not proposal.candidate:
        raise FlowError("proposal has no candidate; provide draft.candidate")
    root, output = Path(root), Path(output)
    candidate_path = output.parent / f"{proposal.id}.candidate.json"
    candidate_path.write_text(json.dumps(proposal.candidate, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    tasks = pilot_prepare(root, candidate_path, samples, output, policy=policy,
                          baseline_traces=baseline_traces)
    workspace = tasks.get("workspace")
    if workspace:
        try:
            diff = diff_workspace(Path(workspace))
            proposal.artifact["diff"] = diff
            proposal.artifact["diff_kind"] = "unified"
            proposal.artifact["stats"] = {
                "files": len(proposal.artifact.get("files") or []),
                "additions": sum(1 for line in diff.splitlines()
                                 if line.startswith("+") and not line.startswith("+++")),
                "deletions": sum(1 for line in diff.splitlines()
                                 if line.startswith("-") and not line.startswith("---")),
            }
            proposal.artifact["base_rev"] = (proposal.candidate or {}).get("base_rev")
            if card:
                proposal.artifact["ev_card"] = str(card)
        except Exception:
            pass
    if dry_run:
        return {"dry_run": True, "candidate": proposal.candidate, "tasks": tasks,
                "workspace": tasks.get("workspace"), "output": str(output)}
    if judge is None:
        raise FlowError("judge is required unless dry_run")
    if runner is None:
        raise FlowError("runner is required unless dry_run")
    if runner is not None:
        runner(tasks)
    _reject_fallback(tasks)
    judge_data = _load_judge(judge, tasks)
    collected = pilot_collect(output, judge=judge)
    result = pilot_decide(output, judge, policy, reuse_index=reuse_index,
                          proposal=proposal.id, card=card, exploratory=exploratory)
    decision = (result.get("conclusion") or {}).get("decision") or "unknown"
    proposal.status = decision
    proposal.decision = decision
    proposal.conclusion_ref = str(output.parent / "conclusions.jsonl")
    proposal.workspace = str(tasks.get("workspace") or "")
    if decision != "accept" and proposal.workspace:
        rollback_workspace(Path(root), Path(proposal.workspace))
        proposal.rolled_back = True
    archive.append(proposal)
    experiment = _experiment_record(proposal, tasks, judge, decision,
                                    result.get("conclusion") or {}, collected,
                                    exploratory=exploratory, card=card)
    ExperimentStore.for_base(archive.path.parent).append(experiment)
    event = RSIStore(archive.path.parent).record_experiment(
        proposal.to_dict(), experiment, result.get("conclusion") or {},
        tasks, collected, decision)
    return {"candidate": proposal.candidate, "tasks": tasks, "collected": collected,
            "conclusion": result.get("conclusion"), "decision": decision,
            "experiment": experiment, "event": event}


def _side_scores(judge: Dict[str, Any], side: str, samples: List[str]) -> Dict[str, float]:
    raw = judge.get(side) or {}
    if not isinstance(raw, dict):
        raise FlowError(f"judge.{side} must be an object")
    values = [float(raw[s]) for s in samples if s in raw]
    if len(values) != len(samples):
        raise FlowError(f"judge.{side} is missing samples")
    return {sample: float(raw[sample]) for sample in samples}


def _load_judge(judge: Path, tasks: Dict[str, Any]) -> Dict[str, Any]:
    try:
        data = json.loads(Path(judge).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FlowError(f"cannot read judge: {exc}") from exc
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    if not meta.get("agent"):
        raise FlowError("judge provenance missing: meta.agent is required")
    samples = [str(row.get("short_id") or row.get("id"))
               for row in tasks.get("samples") or []]
    for side in ("baseline", "candidate"):
        scores = data.get(side)
        if not isinstance(scores, dict):
            raise FlowError(f"judge.{side} must be an object")
        for sample in samples:
            if sample not in scores:
                raise FlowError(f"judge.{side} missing sample {sample}")
            if scores[sample] not in (0, 1, True, False):
                raise FlowError(f"judge.{side}.{sample} must be 0 or 1")
    return data


def _reject_fallback(tasks: Dict[str, Any]) -> None:
    for sample in tasks.get("samples") or []:
        sid = str(sample.get("short_id") or sample.get("id"))
        for arm in tasks.get("arms") or {}:
            path = Path(tasks["arms"][arm]["trace_dir"]) / f"{sid}.yaml"
            if not path.exists():
                continue
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                raise FlowError(f"unreadable trace {path}: {exc}") from exc
            if doc.get("adapter_fallback"):
                raise FlowError(
                    f"adapter fallback trace is not valid evidence: {path}")


def _usage_evidence(collected: Dict[str, Any], key: str, comparator) -> Optional[Dict[str, Any]]:
    arms = collected.get("arms") or {}
    baseline = [row[key] for row in arms.get("baseline") or [] if row.get(key)]
    candidate = [row[key] for row in arms.get("candidate") or [] if row.get(key)]
    if not baseline or not candidate:
        return None
    try:
        return comparator({"samples": baseline}, {"samples": candidate})
    except ValueError:
        return None


def _stage_reports(proposal: Proposal, tasks: Dict[str, Any], judge_data: Dict[str, Any],
                   decision: str, conclusion: Dict[str, Any],
                   collected: Dict[str, Any], baseline: Dict[str, int],
                   candidate: Dict[str, int]) -> List[Dict[str, Any]]:
    samples = [str(row.get("short_id") or row.get("id")) for row in tasks.get("samples") or []]
    candidate_info = proposal.candidate if isinstance(proposal.candidate, dict) else {}
    arms = collected.get("arms") or {}
    counts = {arm: len(rows or []) for arm, rows in arms.items()}
    score_rows = [
        "{}：对照 {} / 候选 {}".format(sid, baseline.get(sid, "—"), candidate.get(sid, "—"))
        for sid in samples
    ]
    return [
        {"id": "attribute", "label": "问题归因", "state": "recorded",
         "summary": "使用了 {} 个真实样本：{}".format(len(samples), "、".join(samples)),
         "fields": samples},
        {"id": "select_region", "label": "改动范围", "state": "recorded",
         "summary": "目标组件：{}".format(proposal.component or "未记录"),
         "fields": [proposal.component] if proposal.component else []},
        {"id": "select_candidate", "label": "候选选择", "state": "recorded",
         "summary": "候选：{}".format(candidate_info.get("candidate_id") or "未记录"),
         "fields": [str(candidate_info.get(key)) for key in ("candidate_id", "file", "base_rev")
                    if candidate_info.get(key)]},
        {"id": "propose", "label": "改动提案", "state": "recorded",
         "summary": proposal.summary or "没有提案摘要",
         "fields": [str(item) for item in (proposal.expected, proposal.risk, proposal.rollback)
                    if item]},
        {"id": "execute", "label": "执行", "state": "recorded" if counts else "empty",
         "summary": "对照 {} 条 / 候选 {} 条".format(counts.get("baseline", "—"),
                                                       counts.get("candidate", "—")),
         "fields": ["样本数：{}".format(len(samples))] + [
             "{}：{} 条".format(arm, count) for arm, count in counts.items()]},
        {"id": "judge", "label": "评分", "state": "recorded" if score_rows else "empty",
         "summary": "逐样本评分如下", "fields": score_rows},
        {"id": "gate", "label": "结论", "state": "recorded" if decision else "empty",
         "summary": "{} · {}".format(decision or "未判定", conclusion.get("reason") or ""),
         "fields": [decision] if decision else []},
    ]


def _sample_context(tasks: Dict[str, Any]) -> List[Dict[str, Any]]:
    context = []
    for row in tasks.get("samples") or []:
        title = ""
        path = row.get("path")
        if path:
            try:
                doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
                title = str(((doc.get("input") or {}).get("title")) or "")
            except (OSError, yaml.YAMLError):
                title = ""
        context.append({
            "id": str(row.get("short_id") or row.get("id") or ""),
            "title": title,
        })
    return context


def _experiment_record(proposal: Proposal, tasks: Dict[str, Any], judge: Path,
                       decision: str, conclusion: Dict[str, Any],
                       collected: Dict[str, Any], *, exploratory: bool = False,
                       card: Optional[str] = None) -> Dict[str, Any]:
    data = json.loads(Path(judge).read_text(encoding="utf-8"))
    samples = [str(row.get("short_id") or row.get("id")) for row in tasks.get("samples") or []]
    baseline = _side_scores(data, "baseline", samples)
    candidate = _side_scores(data, "candidate", samples)
    record = {
        "target_kind": proposal.target,
        "target_component": proposal.component,
        "algorithm": "agent_draft",
        "algorithm_version": "v1",
        "execution": "subagent",
        "decision": decision,
        "samples": samples,
        "sample_context": _sample_context(tasks),
        "baseline": {"score": sum(baseline.values()) / len(baseline),
                     "samples": samples, "per_sample": baseline},
        "candidate": {"score": sum(candidate.values()) / len(candidate),
                      "samples": samples, "per_sample": candidate},
        "eval_profile_id": "subagent_judge",
        "eval_ready": False,
        "summary": proposal.summary,
        "proposal": proposal.id,
        "ev_card": card,
        "proposal_snapshot": proposal.to_dict(),
        "conclusion_snapshot": conclusion,
        "judge_meta": data.get("meta") if isinstance(data.get("meta"), dict) else None,
        "judge_sha256": hashlib.sha256(Path(judge).read_bytes()).hexdigest(),
        "exploratory": bool(exploratory),
        "stage_reports": _stage_reports(proposal, tasks, data, decision,
                                        conclusion, collected, baseline, candidate),
    }
    if proposal.component == "diagnose.knowledge_usage":
        usage = _usage_evidence(collected, "knowledge_usage", compare_knowledge)
        if usage is not None:
            record["knowledge_usage"] = usage
    if proposal.component == "diagnose.source_usage":
        usage = _usage_evidence(collected, "source_usage", compare_source)
        if usage is not None:
            record["source_usage"] = usage
    if conclusion.get("b") is not None:
        record["paired"] = {"b": conclusion["b"], "c": conclusion["c"],
                            "n": conclusion["n"],
                            "alpha_eff": conclusion.get("alpha_eff", 0.1)}
    try:
        return validate_experiment(record)
    except ExperimentError as exc:
        raise FlowError(f"experiment record invalid: {exc}") from exc
