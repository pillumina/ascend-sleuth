"""真实 diagnose pilot 编排：隔离 worktree + 任务清单 + 结果收集。

本模块不调用模型、不 judge；task/judge 仍由 subagent 执行。它保证 baseline 与
candidate 的样本、目录、trace 隔离，避免手工拼命令时写错路径或混用真实 traces。
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .candidate import create_workspace, validate_candidate
from .knowledge_usage import from_trace as knowledge_from_trace
from .source_usage import from_trace as source_from_trace
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
                if doc is not None:
                    try:
                        knowledge = knowledge_from_trace(doc)
                    except Exception as exc:  # trace has no usable knowledge events
                        row["usage_error"] = str(exc)
                    else:
                        # usage 的 sample_id 取 pilot 样本 id，不取 trace 里的 session_id：
                        # 两臂的 trace 往往由不同会话写出，session_id 不保证同名。
                        knowledge["sample_id"] = sid
                        row["knowledge_usage"] = knowledge
                    score = (judge_data.get(arm) or {}).get(sid)
                    source_ok = None if score is None else bool(score)
                    try:
                        source = source_from_trace(doc, source_ok=source_ok)
                    except Exception as exc:  # trace may have no source events
                        row["source_usage_error"] = str(exc)
                    else:
                        source["sample_id"] = sid
                        row["source_usage"] = source
            rows.append(row)
        result["arms"][arm] = rows
    result["complete"] = all(
        r["has_trace"] and r["has_output"] for rows in result["arms"].values() for r in rows
    )
    (output / "collect.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                        encoding="utf-8")
    return result
