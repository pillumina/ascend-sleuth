"""RSI 计划：多源信号 -> 归因 -> 可变异区 -> 实验 spec。

只读、可重复；不调用模型。agent 归因/选点在这里只标记为需要，由
self-evolve 的 subagent 执行，不在 Python 里伪调用。
"""

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .regions import recommend
from .replay_source import scan_failures


def _trace_signals(state_path: Optional[Path]) -> Dict[str, Any]:
    if not state_path or not Path(state_path).exists():
        return {"available": False, "components": {}, "snapshot_id": None}
    try:
        data = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "components": {}, "snapshot_id": None,
                "error": str(exc)}
    components: Dict[str, Dict[str, int]] = {}
    for item in (data.get("processed") or {}).values():
        attribution = item.get("attribution") or {}
        for event in attribution.get("events") or []:
            name = event.get("component") or "(未归因)"
            bucket = components.setdefault(name, {"events": 0, "hard": 0})
            bucket["events"] += 1
            bucket["hard"] += 1 if event.get("hard") else 0
    return {
        "available": True, "components": components,
        "snapshot_id": data.get("snapshot_id"), "trace_count": len(data.get("processed") or {}),
    }


def _metrics_signals(metrics: Dict[str, Any]) -> Dict[str, Any]:
    timeline = metrics.get("timeline") or {}
    freshness = metrics.get("freshness") or {}
    components: Dict[str, Dict[str, int]] = {}
    if timeline.get("available"):
        feedback = metrics.get("feedback") or {}
        if isinstance(feedback, dict) and all(
            int(feedback.get(key) or 0) == 0 for key in ("resolved", "not_resolved", "partial")
        ):
            components["feedback_capture"] = {"events": 1, "hard": 0}
    for key in ("live", "structural"):
        item = freshness.get(key) or {}
        if item.get("available") and item.get("stale"):
            components[f"metrics_{key}_stale"] = {"events": 1, "hard": 0}
    freshness_available = any(
        isinstance(item, dict) and item.get("available")
        for item in (freshness or {}).values()
    )
    return {
        "available": bool(timeline.get("available") or freshness_available),
        "components": components,
        "snapshot_id": (timeline.get("latest_period") or {}).get("period"),
    }


def _replay_signals(report_path: Optional[Path],
                    holdout_numbers: Optional[set] = None) -> Dict[str, Any]:
    if report_path and Path(report_path).is_dir():
        return scan_failures(Path(report_path).parent, Path(report_path), holdout_numbers)
    if not report_path or not Path(report_path).exists():
        return {"available": False, "components": {}, "snapshot_id": None}
    try:
        data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "components": {}, "snapshot_id": None,
                "error": str(exc)}
    components: Dict[str, Dict[str, int]] = {}
    for failure in data.get("failures") or []:
        name = str(failure.get("component") or "(未归因)")
        bucket = components.setdefault(name, {"events": 0, "hard": 0})
        bucket["events"] += 1
        bucket["hard"] += 1 if failure.get("hard") else 0
    return {
        "available": True, "components": components,
        "snapshot_id": data.get("snapshot_id") or data.get("period"),
        "sample_count": len(data.get("samples") or []),
    }


DEFAULT_STAGES = {
    "attribute": "attribute.trace_rule",
    "select_region": "select.region_hardcount",
    "select_candidate": "select.best",
    "propose": "propose.agent",
    "judge": "judge.subagent",
    "gate": "gate.paired",
}


def _stages(config: Optional[Dict[str, str]]) -> Dict[str, str]:
    from .stages import get_stage
    resolved = dict(DEFAULT_STAGES)
    for point, stage_id in (config or {}).items():
        spec = get_stage(str(stage_id))
        if spec.point != point:
            raise ValueError(f"stage {stage_id!r} is {spec.point}, not {point!r}")
        resolved[point] = spec.id
    if set(resolved) != set(DEFAULT_STAGES):
        raise ValueError("experiment.stages must cover all RSI points")
    return resolved


def build_plan(root: Path, trace_state: Optional[Path] = None,
               replay: Optional[Path] = None,
               metrics: Optional[Dict[str, Any]] = None,
               holdout_numbers: Optional[set] = None,
               stages_config: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    root = Path(root)
    trace = _trace_signals(trace_state or (root / ".s2-replay" / "evolve" / "trace-state.json"))
    metric = _metrics_signals(metrics or {})
    replay_data = _replay_signals(replay, holdout_numbers)
    components: Dict[str, Dict[str, int]] = {}
    for source in (trace, metric, replay_data):
        for name, values in (source.get("components") or {}).items():
            bucket = components.setdefault(name, {"events": 0, "hard": 0})
            bucket["events"] += int(values.get("events", 0))
            bucket["hard"] += int(values.get("hard", 0))
    regions = recommend(components)
    stages = _stages(stages_config)
    status = "actionable" if regions else "no_action"
    if not trace.get("available") and not metric.get("available") and not replay_data.get("available"):
        status = "no_sources"
    elif regions and len(regions) > 1 and regions[0]["hard"] == regions[1]["hard"]:
        stages["select_region"] = "select.region_agent"
        status = "needs_agent_selection"
    if not regions and components:
        stages["attribute"] = "attribute.agent"
        status = "needs_agent_attribution"
    region = regions[0] if regions else None
    spec = None
    if region:
        spec = {
            "target_kind": region.get("target_kind", "skill"),
            "target_skill": region["skill"],
            "mutable_region": region["region"],
            "hard": region["hard"],
            "events": region["events"],
        }
    snapshot_parts = [
        str(trace.get("snapshot_id") or ""),
        str(metric.get("snapshot_id") or ""),
        str(replay_data.get("snapshot_id") or ""),
        json.dumps(stages, sort_keys=True),
        json.dumps(components, sort_keys=True),
        json.dumps(regions, sort_keys=True),
        json.dumps(spec, sort_keys=True),
    ]
    snapshot_id = hashlib.sha256("|".join(snapshot_parts).encode("utf-8")).hexdigest()[:12]
    return {
        "status": status,
        "snapshot_id": snapshot_id,
        "sources": {"trace": trace, "metrics": metric, "replay": replay_data},
        "components": components,
        "regions": regions,
        "stages": stages,
        "experiment": spec,
    }


def apply_attribution(plan: Dict[str, Any], payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("attribution must be an object")
    regions = payload.get("regions")
    if not isinstance(regions, list) or not regions:
        raise ValueError("attribution.regions must be a non-empty list")
    from .regions import REGIONS
    normalized = []
    for item in regions:
        if not isinstance(item, dict):
            raise ValueError("attribution.regions entries must be objects")
        region = str(item.get("region") or "")
        if region not in REGIONS:
            raise ValueError(f"unknown region {region!r}")
        evidence = str(item.get("evidence") or "").strip()
        if not evidence:
            raise ValueError("attribution evidence is required")
        confidence = item.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("attribution confidence must be 0..1")
        normalized.append({"region": region, "evidence": evidence, "confidence": confidence})
    plan["agent_attribution"] = normalized
    plan["stages"]["attribute"] = "attribute.agent"
    plan["status"] = "actionable"
    return plan


def apply_selection(plan: Dict[str, Any], payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("selection must be an object")
    region = str(payload.get("region") or "")
    evidence = str(payload.get("evidence") or "").strip()
    from .regions import REGIONS
    if region not in REGIONS:
        raise ValueError(f"unknown region {region!r}")
    if not evidence:
        raise ValueError("selection evidence is required")
    spec = REGIONS[region]
    plan["experiment"] = {
        "target_kind": spec.target_kind,
        "target_skill": spec.skill,
        "mutable_region": region,
        "hard": 0, "events": 0,
    }
    plan["stages"]["select_region"] = "select.region_agent"
    plan["agent_selection"] = {"region": region, "evidence": evidence}
    plan["status"] = "actionable"
    return plan


def save_plan(plan: Dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
        Path(tmp).replace(path)
    finally:
        try:
            Path(tmp).unlink()
        except OSError:
            pass
    return path
