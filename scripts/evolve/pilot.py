"""真实 diagnose pilot 编排：隔离 worktree + 任务清单 + 结果收集。

本模块不调用模型、不 judge；task/judge 仍由 subagent 执行。它保证 baseline 与
candidate 的样本、目录、trace 隔离，避免手工拼命令时写错路径或混用真实 traces。
"""

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .candidate import create_workspace, validate_candidate
from .contracts import PROTOCOL_VERSION, Conclusion, Run, Version, now_iso
from .decision import decide_binary, required_exclusive_wins
from .knowledge_usage import compare as compare_knowledge
from .knowledge_usage import from_trace as knowledge_from_trace
from .policy import policy_hash
from .records import ConclusionStore, RunStore
from .source_usage import compare as compare_source
from .source_usage import from_trace as source_from_trace
from .tool_usage import compare as compare_tools
from .tool_usage import from_trace as tool_from_trace
import yaml


class PilotError(ValueError):
    pass


def _short_id(sample_id: str) -> str:
    matches = re.findall(r"(?:^|[-_])(\d{3,6})(?=$|[-_])", sample_id)
    return matches[-1] if matches else sample_id


def _read_samples(paths: List[str]) -> List[Dict[str, Any]]:
    out = []
    for path in paths:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("id"):
            raise PilotError(f"invalid sample file: {path}")
        out.append({"id": str(data["id"]), "short_id": _short_id(str(data["id"])),
                    "path": str(Path(path).resolve()), "expected": data.get("expected")})
    short_ids = [item["short_id"] for item in out]
    if len(set(short_ids)) != len(short_ids):
        raise PilotError("sample short_id collision; use unique issue ids")
    return out


def prepare(root: Path, candidate_path: Path, samples: List[str],
            output: Path) -> Dict[str, Any]:
    root, output = Path(root), Path(output)
    candidate = validate_candidate(json.loads(Path(candidate_path).read_text(encoding="utf-8")))
    if output.exists():
        raise PilotError(f"output already exists: {output}")
    output.mkdir(parents=True)
    workspace = output / "candidate-worktree"
    info = create_workspace(root, candidate, workspace)
    sample_rows = _read_samples(samples)
    tasks = {"candidate_id": candidate["candidate_id"], "candidate": candidate,
             "workspace": str(workspace), "apply": info,
             "samples": sample_rows,
             "arms": {
                 "baseline": {"root": str(root), "trace_dir": str(output / "baseline" / "traces"),
                              "out_dir": str(output / "baseline" / "out")},
                 "candidate": {"root": str(workspace), "trace_dir": str(output / "candidate" / "traces"),
                               "out_dir": str(output / "candidate" / "out")},
             }}
    (output / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    for arm in ("baseline", "candidate"):
        (output / arm / "traces").mkdir(parents=True)
        (output / arm / "out").mkdir(parents=True)
    return tasks


def collect(output: Path, judge: Optional[Path] = None) -> Dict[str, Any]:
    output = Path(output)
    tasks_path = output / "tasks.json"
    if not tasks_path.exists():
        raise PilotError(f"missing {tasks_path}")
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    judge_data = {}
    if judge is not None:
        judge_path = Path(judge)
        if not judge_path.exists():
            raise PilotError(f"missing judge file: {judge_path}")
        judge_data = json.loads(judge_path.read_text(encoding="utf-8"))
    result = {"candidate_id": tasks.get("candidate_id"), "arms": {}}
    for arm in ("baseline", "candidate"):
        rows = []
        for sample in tasks.get("samples") or []:
            sample_id = sample["id"]
            sid = sample.get("short_id") or _short_id(sample_id)
            trace = output / arm / "traces" / f"{sid}.yaml"
            out = output / arm / "out" / f"{sid}.out.md"
            row = {"sample_id": sid, "source_id": sample_id, "trace": str(trace), "output": str(out),
                   "has_trace": trace.exists(), "has_output": out.exists()}
            if trace.exists():
                doc = None
                try:
                    doc = yaml.safe_load(trace.read_text(encoding="utf-8"))
                except Exception as exc:  # unreadable or malformed trace
                    row["usage_error"] = str(exc)
                if doc is None:
                    if "usage_error" not in row:
                        row["usage_error"] = "trace is empty"
                else:
                    score = (judge_data.get(arm) or {}).get(sid)
                    resolution_ok = None if score is None else bool(score)
                    if score is not None:
                        row["judge"] = score
                    try:
                        knowledge = knowledge_from_trace(doc, resolution_ok=resolution_ok)
                    except Exception as exc:  # trace has no usable knowledge events
                        row["usage_error"] = str(exc)
                    else:
                        # usage 的 sample_id 取 pilot 样本 id，不取 trace 里的 session_id：
                        # 两臂的 trace 往往由不同会话写出，session_id 不保证同名。
                        knowledge["sample_id"] = sid
                        row["knowledge_usage"] = knowledge
                        row["harness_session"] = doc.get("harness_session")
                    source_ok = resolution_ok
                    try:
                        source = source_from_trace(doc, source_ok=source_ok)
                    except Exception as exc:  # trace may have no source events
                        row["source_usage_error"] = str(exc)
                    else:
                        source["sample_id"] = sid
                        row["source_usage"] = source
                    try:
                        tool = tool_from_trace(doc, resolved=resolution_ok)
                    except Exception as exc:  # trace may have no source_analysis events
                        row["tool_usage_error"] = str(exc)
                    else:
                        tool["sample_id"] = sid
                        row["tool_usage"] = tool
            rows.append(row)
        result["arms"][arm] = rows
    result["complete"] = all(
        r["has_trace"] and r["has_output"] for rows in result["arms"].values() for r in rows
    )
    (output / "collect.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")
    return result


# ---------------------------------------------------------------- 记录与判定

def _git_rev(root: Path) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                              check=True, capture_output=True, text=True)
        return proc.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def version_for(tasks: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    """一次 pilot 的版本坐标：协议、策略、两侧知识库、候选、模型。"""
    arms = tasks.get("arms") or {}
    base_root = (arms.get("baseline") or {}).get("root") or "."
    candidate_root = (arms.get("candidate") or {}).get("root") or "."
    version = Version(
        protocol=PROTOCOL_VERSION,
        policy=policy_hash(policy),
        base_kb=_git_rev(Path(base_root)),
        candidate_kb=_git_rev(Path(candidate_root)),
        candidate=str(tasks.get("candidate_id") or "unknown"),
        model="unknown",
        algorithm="subagent-reflection",
        algorithm_version=str((tasks.get("apply") or {}).get("candidate_id") or "manual"),
    ).validate()
    return version.to_dict()


def record_runs(output: Path, policy: Dict[str, Any], base: Optional[Path] = None) -> Dict[str, Any]:
    """把 collect.json 的每条 rollout 写成 Run；重复调用不重复记。"""
    output = Path(output)
    tasks = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
    collect = json.loads((output / "collect.json").read_text(encoding="utf-8"))
    version = version_for(tasks, policy)
    store = RunStore.for_base(Path(base) if base else output.parent)
    existing = {
        (record.get("sample"), (record.get("versions") or {}).get("candidate"),
         record.get("trace_ref"))
        for record in store.read()
    }
    written = 0
    for rows in (collect.get("arms") or {}).values():
        for row in rows:
            key = (row.get("sample_id"), version["candidate"], row.get("trace"))
            if key in existing:
                continue
            metrics = {name: row[name] for name in
                       ("judge", "knowledge_usage", "source_usage", "tool_usage")
                       if row.get(name) is not None}
            run = Run(
                sample=str(row.get("sample_id")), versions=Version.from_dict(version),
                metrics=metrics,
                cost={"tokens": (row.get("knowledge_usage") or {}).get("tokens")}
                if (row.get("knowledge_usage") or {}).get("tokens") is not None else None,
                harness_session=row.get("harness_session"),
                trace_ref=row.get("trace"), at=now_iso(),
            ).validate()
            store.append(run.to_dict())
            existing.add(key)
            written += 1
    return {"written": written, "version": version}


def _required_wins(alpha_eff: float) -> int:
    return required_exclusive_wins(alpha_eff)


def _usage_arms(collect: Dict[str, Any], key: str):
    arms = collect.get("arms") or {}
    baseline = {row["sample_id"]: row.get(key) for row in arms.get("baseline") or []}
    candidate = {row["sample_id"]: row.get(key) for row in arms.get("candidate") or []}
    ids = [sid for sid in sorted(baseline)
           if baseline.get(sid) is not None and candidate.get(sid) is not None]
    return [baseline[sid] for sid in ids], [candidate[sid] for sid in ids]


def _judge_counts(tasks: Dict[str, Any], judge: Dict[str, Any]) -> Dict[str, int]:
    b = c = n = 0
    for sample in tasks.get("samples") or []:
        sid = sample.get("short_id") or _short_id(str(sample.get("id")))
        before = (judge.get("baseline") or {}).get(sid)
        after = (judge.get("candidate") or {}).get(sid)
        if before is None or after is None:
            continue
        n += 1
        if after and not before:
            b += 1
        elif before and not after:
            c += 1
    return {"b": b, "c": c, "n": n}


def decide(output: Path, judge_path: Path, policy: Dict[str, Any], *,
           reuse_index: int = 0, pool: str = "pilot",
           base: Optional[Path] = None) -> Dict[str, Any]:
    """配对判定 + 容量检查，写 Run 与 Conclusion 记录。"""
    output = Path(output)
    if reuse_index < 0:
        raise PilotError("reuse_index must be non-negative")
    tasks = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
    collect = json.loads((output / "collect.json").read_text(encoding="utf-8"))
    judge = json.loads(Path(judge_path).read_text(encoding="utf-8"))
    counts = _judge_counts(tasks, judge)

    constraints: Dict[str, Any] = {}
    for name, key, comparator in (
        ("knowledge", "knowledge_usage", compare_knowledge),
        ("source", "source_usage", compare_source),
        ("tool", "tool_usage", compare_tools),
    ):
        before, after = _usage_arms(collect, key)
        if before and after:
            result = comparator({"samples": before}, {"samples": after})
            constraints[name] = {"decision": result["decision"], "reasons": result["reasons"]}
    constraints_ok = all(item["decision"] != "reject" for item in constraints.values())

    alpha = float((policy.get("decision") or {}).get("alpha", 0.10))
    alpha_eff = alpha / (reuse_index + 1)
    required = _required_wins(alpha_eff)
    target = str((tasks.get("candidate") or {}).get("target_component") or "")
    if "knowledge_usage" in target:
        baseline = {row["sample_id"]: row for row in collect["arms"]["baseline"]}
        candidate = {row["sample_id"]: row for row in collect["arms"]["candidate"]}
        flippable = 0
        for sid in baseline:
            before = (baseline[sid].get("knowledge_usage") or {}).get("hit")
            after = ((candidate.get(sid) or {}).get("knowledge_usage") or {}).get("hit")
            if before or after:
                flippable += 1
    else:
        flippable = counts["n"]

    cost_cfg = policy.get("cost") or {}
    dimension = cost_cfg.get("primary_dimension", "tokens")
    cost_b = cost_c = None
    if dimension == "tokens":
        tokens_b = [(row.get("knowledge_usage") or {}).get("tokens")
                    for row in collect["arms"]["baseline"]]
        tokens_c = [(row.get("knowledge_usage") or {}).get("tokens")
                    for row in collect["arms"]["candidate"]]
        if tokens_b and tokens_c and all(v is not None for v in tokens_b + tokens_c):
            cost_b, cost_c = sum(tokens_b), sum(tokens_c)

    decision = decide_binary(
        counts["b"], counts["c"], counts["n"], alpha=alpha, k=reuse_index,
        cost_b=cost_b, cost_c=cost_c,
        budget=float(cost_cfg.get("B", 0.10)),
        epsilon=float(cost_cfg.get("epsilon", 0.10)),
        delta=float(cost_cfg.get("delta", 0)),
        constraints_ok=constraints_ok,
    )
    result = decision.decision.value
    reason = decision.reason
    capacity_ok = flippable >= required
    if result == "accept" and not capacity_ok:
        result = "insufficient"
        reason = (f"判定容量不足：可翻盘样本 {flippable} < 达成证据所需 {required}；"
                  + reason)
    pool_rows = []
    for sample in tasks.get("samples") or []:
        sid = str(sample.get("short_id") or sample.get("id"))
        try:
            digest = hashlib.sha256(Path(sample["path"]).read_bytes()).hexdigest()
        except (KeyError, OSError):
            digest = "unknown"
        pool_rows.append(f"{sid}:{digest}")
    pool_hash = hashlib.sha256("\n".join(sorted(pool_rows)).encode("utf-8")).hexdigest()[:12]
    conclusion = Conclusion(
        decision=result, reason=reason,
        metrics={
            "capacity": {"flippable": flippable, "required_b": required,
                         "required_b_at_reuse": required, "capacity_ok": capacity_ok},
            "constraints": constraints,
            "main_metric": "resolution",
        },
        cost={"tokens": {"baseline": cost_b, "candidate": cost_c}} if cost_b is not None else None,
        versions=Version.from_dict(version_for(tasks, policy)),
        pool_hash=pool_hash,
        reuse_index=reuse_index, alpha_eff=alpha_eff,
        b=counts["b"], c=counts["c"], n=counts["n"],
        p_value=decision.p_value, delta_q=decision.delta_q,
        cost_ratio=decision.cost_ratio, pool=pool, at=now_iso(),
    ).validate()
    ConclusionStore.for_base(Path(base) if base else output.parent).append(conclusion.to_dict())
    runs = record_runs(output, policy, base=base)
    return {"conclusion": conclusion.to_dict(), "runs": runs, "constraints": constraints}
