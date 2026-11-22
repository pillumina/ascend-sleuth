"""真实 diagnose pilot 编排：隔离 worktree + 任务清单 + 结果收集。

本模块不调用模型、不 judge；task/judge 仍由 subagent 执行。它保证 baseline 与
candidate 的样本、目录、trace 隔离，避免手工拼命令时写错路径或混用真实 traces。
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .candidate import create_workspace, validate_candidate
from .contracts import PROTOCOL_VERSION, Conclusion, Run, Version, now_iso
from .decision import decide_binary, required_exclusive_wins
from .knowledge_usage import compare as compare_knowledge
from .harness_usage import read_session
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


def _read_samples(paths: List[str], root: Optional[Path] = None) -> List[Dict[str, Any]]:
    out = []
    holdout = None
    sample_store = None
    if root is not None:
        from .samples import SampleStore
        sample_store = SampleStore(root=Path(root))
        from .holdout_guard import HOLDOUT_REL, HoldoutError, is_holdout_source, issue_numbers
        if (Path(root) / HOLDOUT_REL).exists():
            try:
                holdout = issue_numbers(Path(root))
            except HoldoutError as exc:
                raise PilotError(str(exc)) from exc
    for path in paths:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("id"):
            raise PilotError(f"invalid sample file: {path}")
        if sample_store is not None:
            stored = sample_store.load(str(data["id"]))
            if stored is not None:
                errors = sample_store.admission_errors(stored)
                if stored.status != "active":
                    errors.append(f"status={stored.status}, not active")
                if stored.purpose != "evaluation":
                    errors.append(f"purpose={stored.purpose}, not evaluation")
                if errors:
                    raise PilotError(f"sample not admitted: {path}: " + "; ".join(errors))
                data = stored.to_dict()
        purpose = str(data.get("purpose") or "")
        if purpose in ("test", "regression", "feedback"):
            raise PilotError(
                f"sealed sample cannot be used in pilot: {data['id']} (purpose={purpose})"
            )
        if holdout and is_holdout_source(str(data.get("source") or data["id"]), holdout):
            raise PilotError(
                f"holdout sample cannot be used in pilot: {data['id']} "
                f"(source={data.get('source')})"
            )
        out.append({"id": str(data["id"]), "short_id": _short_id(str(data["id"])),
                    "path": str(Path(path).resolve()), "expected": data.get("expected")})
    short_ids = [item["short_id"] for item in out]
    if len(set(short_ids)) != len(short_ids):
        raise PilotError("sample short_id collision; use unique issue ids")
    return out


def prepare(root: Path, candidate_path: Path, samples: List[str],
            output: Path, policy: Optional[Dict[str, Any]] = None,
            baseline_traces: Optional[Path] = None) -> Dict[str, Any]:
    root, output = Path(root), Path(output)
    candidate = validate_candidate(json.loads(Path(candidate_path).read_text(encoding="utf-8")))
    if output.exists():
        raise PilotError(f"output already exists: {output}")
    output.mkdir(parents=True)
    workspace = output / "candidate-worktree"
    info = create_workspace(root, candidate, workspace)
    sample_rows = _read_samples(samples, root=root)
    runs = ((policy or {}).get("cost") or {}).get("runs") or {}
    max_pairs = runs.get("max_pairs")
    if max_pairs is None:
        max_pairs = len(sample_rows)
    max_pairs = min(int(max_pairs), len(sample_rows))
    alpha = float(((policy or {}).get("decision") or {}).get("alpha", 0.10))
    required = required_exclusive_wins(alpha)
    min_pairs = int(((policy or {}).get("samples") or {}).get("field_eval", 0) or 0)
    baseline_source = None
    baseline_meta = None
    if baseline_traces is not None:
        if not runs.get("baseline_reuse", True):
            raise PilotError("baseline reuse is disabled by cost.runs.baseline_reuse")
        source = Path(baseline_traces)
        if (source / "traces").is_dir():
            trace_dir, out_dir = source / "traces", source / "out"
        elif (source / "baseline" / "traces").is_dir():
            trace_dir, out_dir = source / "baseline" / "traces", source / "baseline" / "out"
        else:
            raise PilotError("baseline traces dir must contain traces/ and out/")
        missing = []
        for row in sample_rows:
            sid = row["short_id"]
            if not (trace_dir / f"{sid}.yaml").is_file() or not (out_dir / f"{sid}.out.md").is_file():
                missing.append(sid)
        if missing:
            raise PilotError("baseline traces incomplete: " + ", ".join(missing))
        baseline_meta = None
        meta_path = source / "baseline.json"
        if meta_path.exists():
            try:
                baseline_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise PilotError(f"cannot read {meta_path}: {exc}") from exc
            if baseline_meta.get("base_rev") and baseline_meta.get("base_rev") != candidate.get("base_rev"):
                raise PilotError("baseline base_rev does not match candidate")
        baseline_source = str(source)
    tasks = {"stage": "pilot", "candidate_id": candidate["candidate_id"], "candidate": candidate,
             "workspace": str(workspace), "apply": info,
             "samples": sample_rows,
            "budget": {
                 "max_pairs": max_pairs,
                 "max_tokens": runs.get("max_tokens"),
                 "early_stop": bool(runs.get("early_stop", True)),
                 "alpha": alpha,
                 "required_b": required,
                 "min_pairs": min_pairs,
                 "baseline_reused": baseline_source is not None,
                 "baseline_source": baseline_source,
                 "baseline_meta": baseline_meta if baseline_source is not None else None,
             },
             "stop_rules": {
                 "futility": "b + remaining < required_b",
                 "budget": "completed_pairs >= max_pairs",
                 "tokens": ("tokens >= max_tokens" if runs.get("max_tokens") is not None else None),
             },
             "arms": {
                 "baseline": {"root": str(root), "trace_dir": str(output / "baseline" / "traces"),
                              "out_dir": str(output / "baseline" / "out"),
                              "reused": baseline_source is not None},
                 "candidate": {"root": str(workspace), "trace_dir": str(output / "candidate" / "traces"),
                               "out_dir": str(output / "candidate" / "out")},
             }}
    (output / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    for arm in ("baseline", "candidate"):
        (output / arm / "traces").mkdir(parents=True)
        (output / arm / "out").mkdir(parents=True)
    if baseline_source is not None:
        for row in sample_rows:
            sid = row["short_id"]
            shutil.copyfile(trace_dir / f"{sid}.yaml", output / "baseline" / "traces" / f"{sid}.yaml")
            shutil.copyfile(out_dir / f"{sid}.out.md", output / "baseline" / "out" / f"{sid}.out.md")
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
                elif doc.get("adapter_fallback"):
                    raise PilotError(
                        f"adapter fallback trace is not valid evidence: {trace}")
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
                        # baseline 与 candidate 的 trace 往往由不同会话写出，session_id 不保证同名。
                        knowledge["sample_id"] = sid
                        row["knowledge_usage"] = knowledge
                        row["harness_session"] = doc.get("harness_session")
                        usage = read_session(row["harness_session"])
                        model = doc.get("model") or (usage or {}).get("model")
                        if isinstance(model, str) and model:
                            row["model"] = model
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
                              check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return proc.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _worktree_patch(root: Path) -> str:
    """候选 worktree 未提交补丁的哈希；没有差异时返回空串。"""
    try:
        proc = subprocess.run(["git", "-C", str(root), "diff", "HEAD", "--", "."],
                              check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    if not proc.stdout.strip():
        return ""
    return hashlib.sha256(proc.stdout.encode("utf-8")).hexdigest()[:12]


def models_from_collect(collect: Dict[str, Any]) -> Optional[str]:
    models = sorted({row.get("model") for rows in (collect.get("arms") or {}).values()
                     for row in rows
                     if isinstance(row.get("model"), str) and row["model"]})
    return ",".join(models) or None


def version_for(tasks: Dict[str, Any], policy: Dict[str, Any],
                model: Optional[str] = None) -> Dict[str, Any]:
    """一次 pilot 的版本坐标：协议、策略、两侧知识库、候选、模型。"""
    arms = tasks.get("arms") or {}
    base_root = (arms.get("baseline") or {}).get("root") or "."
    candidate_root = (arms.get("candidate") or {}).get("root") or "."
    base_kb = _git_rev(Path(base_root))
    patch = _worktree_patch(Path(candidate_root))
    if patch == "unknown":
        candidate_kb = "unknown"
    elif patch == "":
        candidate_kb = base_kb
    else:
        candidate_kb = f"{base_kb}+patch:{patch}"
    version = Version(
        protocol=PROTOCOL_VERSION,
        policy=policy_hash(policy),
        base_kb=base_kb,
        candidate_kb=candidate_kb,
        candidate=str(tasks.get("candidate_id") or "unknown"),
        model=model or tasks.get("model") or "unknown",
        algorithm="subagent-reflection",
        algorithm_version=str((tasks.get("apply") or {}).get("candidate_id") or "manual"),
    ).validate()
    return version.to_dict()


def record_runs(output: Path, policy: Dict[str, Any], base: Optional[Path] = None) -> Dict[str, Any]:
    """把 collect.json 的每条 rollout 写成 Run；重复调用不重复记。"""
    output = Path(output)
    tasks = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
    collect = json.loads((output / "collect.json").read_text(encoding="utf-8"))
    version = version_for(tasks, policy, model=models_from_collect(collect))
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


def _tokens_used(collect: Dict[str, Any]) -> int:
    return sum(
        int((row.get("knowledge_usage") or {}).get("tokens") or 0)
        for rows in (collect.get("arms") or {}).values()
        for row in rows
        if (row.get("knowledge_usage") or {}).get("tokens") is not None
    )


def checkpoint(output: Path, judge_path: Path, policy: Dict[str, Any], *,
               reuse_index: int = 0) -> Dict[str, Any]:
    """读完当前已产出的 rollouts，判断是否应停止继续跑。"""
    output = Path(output)
    tasks = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
    judge = json.loads(Path(judge_path).read_text(encoding="utf-8"))
    collected = collect(output, judge=judge_path)
    counts = _judge_counts(tasks, judge)
    budget = tasks.get("budget") or {}
    max_pairs = int(budget.get("max_pairs") or len(tasks.get("samples") or []))
    alpha = float(budget.get("alpha", 0.10))
    required = int(budget.get("required_b") or required_exclusive_wins(alpha))
    completed = counts["n"]
    remaining = max(0, max_pairs - completed)
    tokens = _tokens_used(collected)
    max_tokens = budget.get("max_tokens")
    early_stop = bool(budget.get("early_stop", True))
    futility = counts["b"] + remaining < required
    budget_stop = completed >= max_pairs
    token_stop = max_tokens is not None and tokens >= int(max_tokens)
    stop = early_stop and (futility or budget_stop or token_stop)
    if budget_stop:
        reason = "budget"
    elif token_stop:
        reason = "tokens"
    elif futility:
        reason = "futility"
    else:
        reason = "continue"
    return {
        "stop": stop,
        "reason": reason,
        "b": counts["b"],
        "c": counts["c"],
        "n": completed,
        "max_pairs": max_pairs,
        "remaining": remaining,
        "required_b": required,
        "tokens": tokens,
        "max_tokens": max_tokens,
        "early_stop": early_stop,
        "baseline_reused": bool(budget.get("baseline_reused", False)),
        "would_stop": futility or budget_stop or token_stop,
    }


def decide(output: Path, judge_path: Path, policy: Dict[str, Any], *,
           reuse_index: Optional[int] = None, pool: str = "pilot",
           card: Optional[str] = None,
           proposal: Optional[str] = None,
           base: Optional[Path] = None,
           exploratory: bool = False) -> Dict[str, Any]:
    """配对判定 + 容量检查，写 Run 与 Conclusion 记录。"""
    output = Path(output)
    if reuse_index is not None and reuse_index < 0:
        raise PilotError("reuse_index must be non-negative")
    tasks = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
    collect = json.loads((output / "collect.json").read_text(encoding="utf-8"))
    if not collect.get("complete"):
        raise PilotError("pilot evidence is incomplete; trace/out missing")
    judge = json.loads(Path(judge_path).read_text(encoding="utf-8"))
    counts = _judge_counts(tasks, judge)

    constraints: Dict[str, Any] = {}
    all_ids = sorted({row["sample_id"] for row in collect["arms"]["baseline"]})
    for name, key, comparator in (
        ("knowledge", "knowledge_usage", compare_knowledge),
        ("source", "source_usage", compare_source),
        ("tool", "tool_usage", compare_tools),
    ):
        before, after = _usage_arms(collect, key)
        if before and after:
            result = comparator({"samples": before}, {"samples": after})
            constraints[name] = {
                "decision": result["decision"], "reasons": result["reasons"],
                "paired": len(before), "missing": len(all_ids) - len(before),
            }
    component = str((tasks.get("candidate") or {}).get("target_component") or "")
    required = {"diagnose.knowledge_usage": "knowledge",
                "diagnose.source_usage": "source"}.get(component)
    efficiency_reasons = {
        "efficiency_regressed",
        "no_efficiency_improvement",
        "elapsed_inconclusive",
    }
    if required and required in constraints:
        decision = constraints[required]["decision"]
        if decision == "reject":
            reasons = set(constraints[required].get("reasons") or [])
            constraints_ok = bool(reasons) and reasons.issubset(efficiency_reasons)
        elif decision == "accept":
            constraints_ok = True
        else:
            constraints_ok = exploratory
    else:
        constraints_ok = all(
            item["decision"] != "reject"
            or set(item.get("reasons") or []).issubset(efficiency_reasons)
            for item in constraints.values()
        )

    pool_rows = []
    for sample in tasks.get("samples") or []:
        sid = str(sample.get("short_id") or sample.get("id"))
        try:
            digest = hashlib.sha256(Path(sample["path"]).read_bytes()).hexdigest()
        except (KeyError, OSError):
            digest = "unknown"
        pool_rows.append(f"{sid}:{digest}")
    pool_hash = hashlib.sha256("\n".join(sorted(pool_rows)).encode("utf-8")).hexdigest()[:12]
    store = ConclusionStore.for_base(Path(base) if base else output.parent)
    if reuse_index is None:
        reuse_index = sum(
            1 for record in store.read()
            if record.get("pool") == pool
            and record.get("pool_hash") == pool_hash
        )
    alpha = float((policy.get("decision") or {}).get("alpha", 0.10))
    alpha_eff = alpha / (reuse_index + 1)

    cost_cfg = policy.get("cost") or {}
    dimension = str(cost_cfg.get("primary_dimension") or "tokens")
    cost_field = {"time": "elapsed_ms", "calls": "tool_calls", "rounds": "tool_calls"}.get(
        dimension, dimension)
    base_rows = {row["sample_id"]: row for row in collect["arms"]["baseline"]}
    cand_rows = {row["sample_id"]: row for row in collect["arms"]["candidate"]}
    cost_dimensions = {}
    for name in ("tokens", "elapsed_ms", "tool_calls", "full_body_reads"):
        pairs = []
        for sample_id in sorted(set(base_rows) & set(cand_rows)):
            tb = (base_rows[sample_id].get("knowledge_usage") or {}).get(name)
            if tb is None:
                tb = (base_rows[sample_id].get("source_usage") or {}).get(name)
            tc = (cand_rows[sample_id].get("knowledge_usage") or {}).get(name)
            if tc is None:
                tc = (cand_rows[sample_id].get("source_usage") or {}).get(name)
            if tb is not None and tc is not None:
                pairs.append((tb, tc))
        if pairs:
            cost_dimensions[name] = {
                "baseline": sum(pair[0] for pair in pairs),
                "candidate": sum(pair[1] for pair in pairs),
                "paired": len(pairs),
            }
    chosen = cost_dimensions.get(cost_field) or cost_dimensions.get("tokens")
    cost_b = chosen["baseline"] if chosen else None
    cost_c = chosen["candidate"] if chosen else None
    cost_paired = chosen["paired"] if chosen else 0

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
    min_pairs = 1 if exploratory else int(
        (tasks.get("budget") or {}).get("min_pairs")
        or (policy.get("samples") or {}).get("field_eval") or 0)
    if exploratory and result in ("insufficient", "reject") and counts["c"] == 0 and counts["n"] > 0:
        cost_ratio = getattr(decision, "cost_ratio", None)
        if result == "insufficient" or (
                cost_ratio is not None
                and cost_ratio < 1.0):
            result = "accept"
            reason = ("exploratory accept: usage constraint not production-grade; "
                      f"cost_ratio={cost_ratio} (b={counts['b']}, c={counts['c']}, n={counts['n']})")
    if counts["n"] < min_pairs:
        result = "insufficient"
        reason = f"capacity_short: n={counts['n']} < min_pairs={min_pairs}"
    version = version_for(tasks, policy, model=models_from_collect(collect))
    for record in store.read():
        if (
            record.get("pool_hash") == pool_hash
            and record.get("b") == counts["b"]
            and record.get("c") == counts["c"]
            and record.get("n") == counts["n"]
            and record.get("decision") == result
            and record.get("reuse_index") == reuse_index
            and record.get("alpha_eff") == alpha_eff
            and (record.get("versions") or {}).get("candidate_kb") == version["candidate_kb"]
            and (record.get("versions") or {}).get("candidate") == version["candidate"]
            and (record.get("versions") or {}).get("policy") == version["policy"]
            and (record.get("metrics") or {}).get("constraints") == constraints
        ):
            runs = record_runs(output, policy, base=base)
            return {"conclusion": record, "runs": runs,
                    "constraints": constraints, "duplicate": True}
    conclusion = Conclusion(
        decision=result, reason=reason,
        metrics={
            "constraints": constraints,
            "cost_primary": dimension,
            "cost_dimensions": cost_dimensions,
            "main_metric": "resolution",
            "judge": (judge.get("meta") if isinstance(judge.get("meta"), dict) else None),
            "budget": {
                "max_pairs": int((tasks.get("budget") or {}).get("max_pairs")
                                 or len(tasks.get("samples") or [])),
                "used_pairs": counts["n"],
                "min_pairs": min_pairs,
                "tokens": _tokens_used(collect),
                "early_stop": bool((tasks.get("budget") or {}).get("early_stop", True)),
                "baseline_reused": bool((tasks.get("budget") or {}).get("baseline_reused", False)),
            },
        },
        cost=({dimension: {"baseline": cost_b, "candidate": cost_c},
               "paired": cost_paired, "missing": len(all_ids) - cost_paired}
              if cost_b is not None else None),
        versions=Version.from_dict(version),
        pool_hash=pool_hash,
        reuse_index=reuse_index, alpha_eff=alpha_eff,
        b=counts["b"], c=counts["c"], n=counts["n"],
        p_value=decision.p_value, delta_q=decision.delta_q,
        cost_ratio=decision.cost_ratio, pool=pool, card=card,
        proposal=proposal, at=now_iso(),
    ).validate()
    store.append(conclusion.to_dict())
    runs = record_runs(output, policy, base=base)
    return {"conclusion": conclusion.to_dict(), "runs": runs, "constraints": constraints}
