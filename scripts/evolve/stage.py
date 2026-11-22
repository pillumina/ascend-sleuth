"""test / regression 的通用 stage runner。

stage 注册表只描述样本角色、arm 组成与门禁；执行交给外部 command。
runner 不调用模型，只负责 plan / run / report 三件事。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .candidate import create_workspace, validate_candidate
from .decision import required_exclusive_wins
from .holdout_guard import HoldoutError, is_holdout_source, issue_numbers
from .pilot import _short_id, checkpoint as pilot_checkpoint, collect as pilot_collect
from .pilot import decide as pilot_decide, _judge_counts
from .contracts import now_iso
from .records import ConclusionStore



class StageError(ValueError):
    pass


STAGES = {
    "test": {"purpose": "test", "arms": ("baseline", "candidate"), "gate": "exact"},
    "regression": {"purpose": "regression", "arms": ("candidate",), "gate": "hard"},
}


def _read_stage_config(root: Path) -> Dict[str, Any]:
    path = Path(root) / "eval" / "core" / "test-stage.yaml"
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise StageError(f"cannot read {path}: {exc}") from exc


def _select_samples(root: Path, stage: str, policy: Dict[str, Any],
                    limit: Optional[int], full: bool,
                    where: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    from .samples import SampleStore

    if stage not in STAGES:
        raise StageError(f"unknown stage: {stage}")
    try:
        samples = [s for s in SampleStore(root).read_all()
                   if s.status == "active" and s.purpose == STAGES[stage]["purpose"]]
    except Exception as exc:
        raise StageError(f"cannot read samples: {exc}") from exc
    by_short = {_short_id(s.id): s for s in samples}
    try:
        reserved = issue_numbers(root)
    except HoldoutError as exc:
        raise StageError(str(exc)) from exc
    for sample in samples:
        if reserved and is_holdout_source(sample.source, reserved):
            raise StageError(f"holdout source cannot enter {stage}: {sample.id}")
    if where:
        samples = [sample for sample in samples
                   if all(str((sample.input or {}).get(key)) == value
                          for key, value in where.items())]
        by_short = {_short_id(s.id): s for s in samples}
    if stage == "test":
        config = _read_stage_config(root)
        selected = [str(sid) for sid in config.get("selected") or []]
        if not selected:
            selected = sorted(by_short)[:int((policy.get("samples") or {}).get("test", 4))]
        chosen = [by_short[sid] for sid in selected if sid in by_short]
        target = int((policy.get("samples") or {}).get("test", 4))
        if len(chosen) < target:
            raise StageError(
                f"test stage needs {target} selected samples, found {len(chosen)}"
            )
        samples = chosen
    else:
        runs = (policy.get("cost") or {}).get("runs") or {}
        count = len(samples) if full else int(limit if limit is not None
                                              else runs.get("regression_pairs", 6))
        samples = sorted(samples, key=lambda item: item.id)[:max(0, count)]
    rows = []
    for sample in samples:
        rows.append({
            "id": sample.id,
            "short_id": _short_id(sample.id),
            "path": str((Path(root) / "eval" / "core" / "samples" / f"{sample.id}.yaml")),
            "purpose": sample.purpose,
            "source": sample.source,
            "expected": sample.expected,
        })
    return rows


def _field_accept(root: Path, candidate_id: str) -> bool:
    try:
        rows = ConclusionStore.for_root(root).read()
    except Exception:
        return False
    return any(
        row.get("pool") == "pilot"
        and row.get("decision") == "accept"
        and (row.get("versions") or {}).get("candidate") == candidate_id
        for row in rows
    )


def _verify_seal(root: Path, rows: List[Dict[str, Any]]) -> None:
    config = _read_stage_config(root)
    sealed = config.get("sealed_sha256") or {}
    if not sealed:
        return
    for row in rows:
        sid = row["short_id"]
        expected = sealed.get(sid) or sealed.get(row["id"])
        if not expected:
            raise StageError(f"test sample not sealed: {sid}")
        path = Path(row["path"])
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise StageError(f"test sample changed since seal: {sid}")


def _regression_where(root: Path, candidate: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if candidate is None:
        return None
    path = root / "eval" / "regression-map.yaml"
    if not path.exists():
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    selector = doc.get(candidate.get("target_component")) or doc.get("default") or {}
    where = selector.get("where") if isinstance(selector, dict) else None
    return {str(key): str(value) for key, value in (where or {}).items()}


def _git_head(root: Path) -> str:
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, encoding="utf-8")
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def plan(root: Path, stage: str, output: Path, policy: Dict[str, Any],
         limit: Optional[int] = None, full: bool = False,
         candidate_path: Optional[Path] = None,
         baseline_traces: Optional[Path] = None,
         where: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    root, output = Path(root), Path(output)
    if output.exists():
        raise StageError(f"output already exists: {output}")
    spec = STAGES[stage]
    candidate = None
    candidate_root = root
    if candidate_path is not None:
        candidate = validate_candidate(json.loads(Path(candidate_path).read_text(encoding="utf-8")))
        if stage == "test" and not _field_accept(root, candidate["candidate_id"]):
            raise StageError(f"no accepted field conclusion for candidate {candidate['candidate_id']}")
        candidate_root = output / "candidate-worktree"
        create_workspace(root, candidate, candidate_root)
    if stage == "regression" and where is None:
        where = _regression_where(root, candidate)
    rows = _select_samples(root, stage, policy, limit, full, where=where)
    if stage == "test":
        _verify_seal(root, rows)
    runs = (policy.get("cost") or {}).get("runs") or {}
    alpha = float((policy.get("decision") or {}).get("alpha", 0.10))
    baseline_source = None
    baseline_meta = None
    trace_dir = out_dir = None
    if baseline_traces is not None:
        if stage != "test":
            raise StageError("baseline reuse is only valid for test")
        source = Path(baseline_traces)
        if (source / "traces").is_dir():
            trace_dir, out_dir = source / "traces", source / "out"
        elif (source / "baseline" / "traces").is_dir():
            trace_dir, out_dir = source / "baseline" / "traces", source / "baseline" / "out"
        else:
            raise StageError("baseline traces dir must contain traces/ and out/")
        missing = [row["short_id"] for row in rows
                   if not (trace_dir / f"{row['short_id']}.yaml").is_file()
                   or not (out_dir / f"{row['short_id']}.out.md").is_file()]
        if missing:
            raise StageError("baseline traces incomplete: " + ", ".join(missing))
        meta_path = source / "baseline.json"
        baseline_meta = None
        if meta_path.exists():
            try:
                baseline_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise StageError(f"cannot read {meta_path}: {exc}") from exc
            if candidate is not None and baseline_meta.get("base_rev") and                     baseline_meta.get("base_rev") != candidate.get("base_rev"):
                raise StageError("baseline base_rev does not match candidate")
        baseline_source = str(source)
    arms = {}
    for arm in spec["arms"]:
        arm_root = root if arm == "baseline" else candidate_root
        arms[arm] = {
            "root": str(arm_root),
            "trace_dir": str(output / arm / "traces"),
            "out_dir": str(output / arm / "out"),
        }
    if stage == "test":
        arms["baseline"]["reused"] = baseline_source is not None
    tasks = {
        "stage": stage,
        "root": str(root),
        "gate": spec["gate"],
        "candidate_id": (candidate or {}).get("candidate_id", "HEAD"),
        "candidate": candidate,
        "base_rev": (candidate or {}).get("base_rev") or _git_head(root),
        "samples": rows,
        "arms": arms,
        "budget": {
            "max_pairs": len(rows),
            "max_tokens": runs.get("max_tokens"),
            "early_stop": bool(runs.get("early_stop", True)),
            "alpha": alpha,
            "required_b": required_exclusive_wins(alpha),
            "baseline_reused": baseline_source is not None,
            "baseline_source": baseline_source,
            "baseline_meta": baseline_meta if baseline_source is not None else None,
        },
        "stop_rules": {
            "futility": "b + remaining < required_b",
            "budget": "completed_pairs >= max_pairs",
        },
        "runner": {
            "env": ["SLEUTH_STAGE", "SLEUTH_SAMPLE_ID", "SLEUTH_SHORT_ID",
                    "SLEUTH_ARM", "SLEUTH_TRACE", "SLEUTH_OUT", "SLEUTH_ROOT",
                    "SLEUTH_OUTPUT"],
            "contract": "command must write SLEUTH_TRACE and SLEUTH_OUT for one rollout",
        },
    }
    output.mkdir(parents=True)
    for arm in arms:
        (output / arm / "traces").mkdir(parents=True)
        (output / arm / "out").mkdir(parents=True)
    if baseline_source is not None:
        for row in rows:
            sid = row["short_id"]
            shutil.copyfile(trace_dir / f"{sid}.yaml", output / "baseline" / "traces" / f"{sid}.yaml")
            shutil.copyfile(out_dir / f"{sid}.out.md", output / "baseline" / "out" / f"{sid}.out.md")
    (output / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    return tasks


def run(output: Path, command: List[str], timeout: float = 600.0,
        judge_path: Optional[Path] = None) -> Dict[str, Any]:
    output = Path(output)
    if not command or not all(isinstance(item, str) and item for item in command):
        raise StageError("command must be a non-empty list of non-empty strings")
    tasks = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
    if tasks.get("stage") == "test":
        candidate_id = str(tasks.get("candidate_id") or "")
        if not candidate_id or candidate_id == "HEAD":
            raise StageError("test run requires a candidate-bound task")
        if not _field_accept(Path(tasks.get("root") or "."), candidate_id):
            raise StageError(f"no accepted field conclusion for candidate {candidate_id}")
    completed = 0
    skipped = 0
    for sample in tasks.get("samples") or []:
        sid = sample["short_id"]
        for arm in tasks["arms"]:
            arm_task = tasks["arms"][arm]
            if arm_task.get("reused"):
                skipped += 1
                continue
            trace = output / arm / "traces" / f"{sid}.yaml"
            out = output / arm / "out" / f"{sid}.out.md"
            if trace.exists() and out.exists():
                skipped += 1
                continue
            env = dict(os.environ)
            env.update({
                "SLEUTH_STAGE": tasks["stage"],
                "SLEUTH_SAMPLE_ID": str(sample["id"]),
                "SLEUTH_SHORT_ID": sid,
                "SLEUTH_ARM": arm,
                "SLEUTH_TRACE": str(trace),
                "SLEUTH_OUT": str(out),
                "SLEUTH_ROOT": str(arm_task["root"]),
                "SLEUTH_OUTPUT": str(output),
            })
            try:
                proc = subprocess.run(command, cwd=arm_task["root"], env=env,
                                      timeout=timeout, capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", check=False)
            except subprocess.TimeoutExpired as exc:
                raise StageError(f"{sid}/{arm} timed out after {timeout}s") from exc
            if proc.returncode != 0:
                raise StageError(
                    f"{sid}/{arm} command failed: {proc.returncode}: {proc.stderr[-500:]}"
                )
            if not trace.exists() or not out.exists():
                raise StageError(f"{sid}/{arm} did not write trace and out")
            completed += 1
        if tasks["stage"] == "test" and judge_path is not None:
            stop = pilot_checkpoint(output, Path(judge_path), {})
            if stop["stop"]:
                break
    return {"stage": tasks["stage"], "completed": completed, "skipped": skipped,
            "samples": len(tasks.get("samples") or [])}


def _check_traces(output: Path, tasks: Dict[str, Any]) -> None:
    for sample in tasks.get("samples") or []:
        for arm in tasks.get("arms") or {}:
            path = output / arm / "traces" / f"{sample['short_id']}.yaml"
            if not path.exists():
                continue
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                raise StageError(f"unreadable trace {path}: {exc}") from exc
            if doc.get("adapter_fallback"):
                raise StageError(
                    f"adapter fallback trace is not valid evidence: {path}; "
                    "let the agent write the trace"
                )


def judge(output: Path, agent: str = "dsh", timeout: float = 300.0,
          calibration: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if calibration is not None and not calibration.get("passed"):
        raise StageError("judge calibration did not pass")
    output = Path(output)
    tasks = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
    adapter = Path(__file__).resolve().parents[2] / "scripts" / "judge_adapter.py"
    data: Dict[str, Any] = {
        "baseline": {}, "candidate": {},
        "meta": {
            "agent": agent, "at": now_iso(),
            "calibration": (calibration if calibration is not None
                            else {"passed": False, "status": "not_run"}),
        },
    }
    for arm in tasks.get("arms") or {}:
        for sample in tasks.get("samples") or []:
            sid = sample["short_id"]
            out = output / arm / "out" / f"{sid}.out.md"
            if not out.exists():
                raise StageError(f"cannot judge missing output: {arm}/{sid}")
            score_path = output / "judge" / f"{arm}-{sid}.json"
            env = dict(os.environ)
            env.update({
                "SLEUTH_OUT": str(out),
                "SLEUTH_EXPECTED": json.dumps(sample.get("expected"), ensure_ascii=False),
                "SLEUTH_JUDGE": str(score_path),
                "SLEUTH_SAMPLE_ID": str(sample["id"]),
                "SLEUTH_ARM": arm,
            })
            proc = subprocess.run(
                [sys.executable, str(adapter), "--agent", agent, "--timeout", str(timeout)],
                cwd=str(output), env=env, timeout=timeout + 30, capture_output=True,
                text=True, encoding="utf-8", errors="replace", check=False,
            )
            if proc.returncode != 0:
                raise StageError(f"judge failed for {arm}/{sid}: {proc.stderr[-400:]}")
            data[arm][sid] = int(json.loads(score_path.read_text(encoding="utf-8"))["score"])
    (output / "judge.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                      encoding="utf-8")
    return data


def report(output: Path, stage: str, judge_path: Path,
           policy: Dict[str, Any], *, card: Optional[str] = None,
           update_stage: bool = False) -> Dict[str, Any]:
    output = Path(output)
    tasks = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
    if stage != tasks.get("stage"):
        raise StageError(f"stage mismatch: {stage} vs {tasks.get('stage')}")
    judge = json.loads(Path(judge_path).read_text(encoding="utf-8"))
    meta = judge.get("meta") if isinstance(judge.get("meta"), dict) else {}
    if not meta.get("agent"):
        raise StageError("judge provenance missing: meta.agent is required")
    if stage == "test":
        calibration = meta.get("calibration")
        if not isinstance(calibration, dict) or calibration.get("passed") is not True:
            raise StageError("judge calibration missing or not passed")
    _check_traces(output, tasks)
    if stage == "test":
        candidate_id = str(tasks.get("candidate_id") or "")
        if not candidate_id or candidate_id == "HEAD":
            raise StageError("test report requires a candidate-bound run")
        root = Path(tasks.get("root") or ".")
        if not _field_accept(root, candidate_id):
            raise StageError(f"no accepted field conclusion for candidate {candidate_id}")
        collected = pilot_collect(output, judge=Path(judge_path))
        if not collected.get("complete"):
            raise StageError("test evidence incomplete: trace or output missing")
        counts = _judge_counts(tasks, judge)
        if counts["n"] != len(tasks.get("samples") or []):
            raise StageError("test evidence incomplete: judge scores missing")
        result = pilot_decide(output, Path(judge_path), policy, pool="test", card=card)
        if update_stage:
            path = Path(tasks.get("root") or ".") / "eval" / "core" / "test-stage.yaml"
            if path.exists():
                doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                doc["status"] = "complete"
                doc["decision"] = (result.get("conclusion") or {}).get("decision")
                doc["at"] = now_iso()
                path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                                encoding="utf-8")
        return {"stage": stage, "collected": collected, "decision": result,
                "judge": (judge.get("meta") if isinstance(judge.get("meta"), dict) else None)}
    failed = []
    for sample in tasks.get("samples") or []:
        sid = sample["short_id"]
        trace = output / "candidate" / "traces" / f"{sid}.yaml"
        out = output / "candidate" / "out" / f"{sid}.out.md"
        if not trace.exists() or not out.exists():
            raise StageError(f"regression evidence incomplete: {sid}")
        scores = judge.get("candidate") or {}
        if sid not in scores:
            raise StageError(f"regression judge missing: {sid}")
        if not scores[sid]:
            failed.append(sid)
    return {
        "stage": stage,
        "passed": not failed,
        "n": len(tasks.get("samples") or []),
        "failed": failed,
    }


def load_argv(raw: str) -> List[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StageError(f"command is not valid JSON: {exc}") from exc
    if not isinstance(value, list):
        raise StageError("command must be a JSON list")
    return value
