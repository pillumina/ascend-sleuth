"""临时 metrics 目录夹具（只给测试用）。"""

from pathlib import Path

TIMELINE = """\
periods:
- period: 2026-W35
  kind: live
  recorded_at: '2026-08-31'
  metrics:
    sessions_total: 7
    tier2_hit: 3
    feedback_capture: {resolved: 1, not_resolved: 0, partial: 0}
- period: 2026-W36
  kind: replay
  recorded_at: '2026-09-01'
  metrics:
    case_total: 42
- period: 2026-W36-live
  kind: live
  recorded_at: '2026-09-02'
  metrics:
    sessions_total: 11
    tier2_hit: 4
    feedback_capture: {resolved: 2, not_resolved: 1, partial: 0}
"""

GATES = """\
freshness: {live_snapshot_max_age_days: 7}
gates:
- {id: cell_read_soft_tok, dimension: capacity_cell_read_tok, op: '>', value: 8000}
health: {case_low_confidence_score: 0.5}
"""

EXEC = """\
records:
- {seq: 1, skill: issue-ingest, at: '2026-11-01T10:00:00', version: abc, source: issue-ingest}
- {seq: 2, skill: evolve-check, at: '2026-11-02T10:00:00', version: def, source: evolve-check}
"""

ENTRY = """\
covered: {deployment: ascend-sleuth, runs: 2, weeks: [2026-W42]}
cases:
  C-1: {totals: {selected: 1, loaded: 1, resolved: 1, misdiagnosed: 0, self_resolved: 0}}
  C-2: {totals: {selected: 0, loaded: 0, resolved: 0, misdiagnosed: 0, self_resolved: 0}}
references:
  R-1: {hits: 1}
tools:
  read: {calls: 2}
cold: {cases: 172}
cold_never_looked_up: [a, b]
"""


def write_metrics(root: Path) -> Path:
    root = Path(root)
    metrics = root / "metrics"
    (metrics / "entry-activity").mkdir(parents=True, exist_ok=True)
    (metrics / "timeline.yaml").write_text(TIMELINE, encoding="utf-8")
    (metrics / "gates.yaml").write_text(GATES, encoding="utf-8")
    (metrics / "skill-exec-log.yaml").write_text(EXEC, encoding="utf-8")
    (metrics / "entry-activity" / "ascend-sleuth.yaml").write_text(ENTRY, encoding="utf-8")
    return root
