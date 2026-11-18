"""把 trace 源增量归因到可复核的组件证据；状态幂等。"""

from pathlib import Path
from typing import Any, Dict, Optional

from .trace_source import LocalTraceSource, TraceSource
from .regions import recommend
from .trace_state import TraceState, attribute_trace


def sync(root: Path, state_path: Path, source: Optional[TraceSource] = None,
         source_id: str = "local") -> Dict[str, Any]:
    source = source or LocalTraceSource(root, source_id=source_id, prefer_main=True)
    refs = source.list_traces()
    state = TraceState.load(Path(state_path), source_id)
    stats = {"source_id": source_id, "traces": len(refs), "new": 0,
             "changed": 0, "reused": 0, "events": 0, "components": {}}
    attributions = []
    active_ids = []
    for ref in refs:
        active_ids.append(ref.id)
        cached = state.cached(ref.id, ref.sha256)
        if cached is not None:
            stats["reused"] += 1
            item = cached
        else:
            previous = state.data["processed"].get(ref.id)
            stats["changed" if previous else "new"] += 1
            item = attribute_trace(source.fetch_trace(ref))
            state.put(item)
        attributions.append(item)
        stats["events"] += len(item.get("events") or [])
        for event in item.get("events") or []:
            component = event.get("component") or "(未归因)"
            bucket = stats["components"].setdefault(
                component, {"events": 0, "hard": 0, "traces": []},
            )
            bucket["events"] += 1
            bucket["hard"] += 1 if event.get("hard") else 0
            if ref.id not in bucket["traces"]:
                bucket["traces"].append(ref.id)
    state.prune(active_ids)
    stats["snapshot_id"] = state.set_snapshot(refs)
    state.save()
    stats["state_path"] = str(state_path)
    stats["regions"] = recommend(stats["components"])
    stats["experiment"] = experiment_spec(stats)
    stats["attributions"] = attributions
    return stats


def experiment_spec(stats: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    regions = stats.get("regions") or []
    if not regions:
        return None
    region = regions[0]
    return {
        "target_kind": region.get("target_kind", "skill"),
        "target_skill": region["skill"],
        "mutable_region": region["region"],
        "hard": region["hard"],
        "events": region["events"],
        "snapshot_id": stats.get("snapshot_id"),
        "source_id": stats.get("source_id"),
        "stages": {"attribute": "attribute.trace_rule",
                   "select_region": "select.region_hardcount"},
    }


def status(state_path: Path) -> Dict[str, Any]:
    # status 不推断 source；只读文件，避免为了看状态去扫 traces。
    import json
    path = Path(state_path)
    if not path.exists():
        return {"available": False, "state_path": str(path)}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "available": True,
        "state_path": str(path),
        "source_id": data.get("source_id"),
        "snapshot_id": data.get("snapshot_id"),
        "traces": len(data.get("processed") or {}),
        "attribution_schema": data.get("attribution_schema"),
    }
