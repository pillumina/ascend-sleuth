"""test / regression 的通用 stage runner。

stage 注册表只描述样本角色、arm 组成与门禁；执行交给外部 command。
runner 不调用模型，只负责 plan / run / report 三件事。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .candidate import create_workspace, validate_candidate
from .decision import required_exclusive_wins
from .pilot import _short_id, checkpoint as pilot_checkpoint, collect as pilot_collect
from .pilot import decide as pilot_decide
from .contracts import now_iso



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
                    limit: Optional[int], full: bool) -> List[Dict[str, Any]]:
    from .samples import SampleStore

    if stage not in STAGES:
        raise StageError(f"unknown stage: {stage}")
    try:
        samples = [s for s in SampleStore(root).read_all()
                   if s.status == "active" and s.purpose == STAGES[stage]["purpose"]]
    except Exception as exc:
        raise StageError(f"cannot read samples: {exc}") from exc
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


def _git_head(root: Path) -> str:
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, encoding="utf-8")
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def plan(root: Path, stage: str, output: Path, policy: Dict[str, Any],
         limit: Optional[int] = None, full: bool = False,
         candidate_path: Optional[Path] = None,
         baseline_traces: Optional[Path] = None) -> Dict[str, Any]:
    root, output = Path(root), Path(output)
    if output.exists():
        raise StageError(f"output already exists: {output}")
    spec = STAGES[stage]
    rows = _select_samples(root, stage, policy, limit, full)
    candidate = None
    candidate_root = root
    if candidate_path is not None:
        candidate = validate_candidate(json.loads(Path(candidate_path).read_text(encoding="utf-8")))
        candidate_root = output / "candidate-worktree"
        create_workspace(root, candidate, candidate_root)
    runs = (policy.get("cost") or {}).get("runs") or {}
    alpha = float((policy.get("decision") or {}).get("alpha", 0.10))
    baseline_source = None
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
                raise StageError(f"{sid}/{arm} command failed: {proc.returncode}")
            if not trace.exists() or not out.exists():
                raise StageError(f"{sid}/{arm} did not write trace and out")
            completed += 1
        if tasks["stage"] == "test" and judge_path is not None:
            stop = pilot_checkpoint(output, Path(judge_path), {})
            if stop["stop"]:
                break
    return {"stage": tasks["stage"], "completed": completed, "skipped": skipped,
            "samples": len(tasks.get("samples") or [])}


def report(output: Path, stage: str, judge_path: Path,
           policy: Dict[str, Any], *, card: Optional[str] = None,
           update_stage: bool = False) -> Dict[str, Any]:
    output = Path(output)
    tasks = json.loads((output / "tasks.json").read_text(encoding="utf-8"))
    if stage != tasks.get("stage"):
        raise StageError(f"stage mismatch: {stage} vs {tasks.get('stage')}")
    judge = json.loads(Path(judge_path).read_text(encoding="utf-8"))
    if stage == "test":
        collected = pilot_collect(output, judge=Path(judge_path))
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
        return {"stage": stage, "collected": collected, "decision": result}
    failed = []
    for sample in tasks.get("samples") or []:
        sid = sample["short_id"]
        score = (judge.get("candidate") or {}).get(sid)
        if not score:
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
