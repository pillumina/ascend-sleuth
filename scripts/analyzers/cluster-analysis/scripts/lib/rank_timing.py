"""Normalize rank timings and embed the same chart in both HTML reports."""
from collections import defaultdict
import json
from pathlib import Path

from lib.common import to_f


_ASSETS = Path(__file__).resolve().parents[1] / 'report_assets'
_TIME_FIELDS = (
    ('stage(us)', 'stage', 'Stage', 'stage_time'),
    ('communication(us)', 'communication', 'Communication', 'communication_time'),
    ('free(us)', 'free', 'Free', 'free_time'),
    ('overlapped(us)', 'overlapped', 'Overlapped', 'overlap_communication_time'),
    ('communication_not_overlapped(us)', 'communication_not_overlapped',
     'Communication(Not Overlapped)', 'pure_communication_time'),
    ('computing(us)', 'computing', 'Computing', 'compute_time'),
)


def _get(row, fields):
    return next((row[key] for key in fields if key in row), None)


def _label_order(label):
    return (0, int(label), label) if label.isdecimal() else (1, 0, label)


def legacy_zero_fields(base_info):
    """Older fallback DBs recorded unknown optional timings as zero."""
    if base_info.get('optional_step_values') == 'null':
        return {}
    try:
        unknown = json.loads(base_info.get('unknown_summary_metrics', '{}'))
    except (TypeError, ValueError):
        return {}
    if not isinstance(unknown, dict):
        return {}
    optional = {'Communication', 'Overlapped'}
    return {rank: sorted(optional.intersection(fields)) for rank, fields in unknown.items()
            if isinstance(fields, list) and optional.intersection(fields)}


def rank_timing_panel(rows, legacy_fields=None):
    legacy_fields = legacy_fields or {}
    steps = defaultdict(dict)
    ranks = set()
    for row in rows:
        rank = _get(row, ('rank', 'rank_id', 'index', 'Index'))
        step = _get(row, ('step', 'step_id', 'Step'))
        if rank is None or rank == '' or step is None or step == '':
            continue
        rank, step = str(rank), str(step)
        stage, comm, free, overlap, pure_comm, compute = [
            to_f(_get(row, fields), None) for fields in _TIME_FIELDS]
        unknown = legacy_fields.get(rank, ())
        if comm == 0 and 'Communication' in unknown:
            comm = None
        if overlap == 0 and 'Overlapped' in unknown:
            overlap = None
        if overlap is None and comm is not None and pure_comm is not None and comm >= pure_comm:
            overlap = comm - pure_comm
        pure_compute = max(0, compute - overlap) if compute is not None and overlap is not None else None
        times = (stage, comm, free, overlap, pure_comm, pure_compute)
        ranks.add(rank)
        steps[step][rank] = [round(value / 1000, 6) if value is not None else None for value in times]

    if not steps:
        return '<p>暂无逐卡耗时数据。</p>'
    ranks = sorted(ranks, key=_label_order)
    index = {rank: i for i, rank in enumerate(ranks)}
    data = {'ranks': ranks, 'steps': [[step, [[index[rank], *times] for rank, times in steps[step].items()]]
                                    for step in sorted(steps, key=_label_order)]}
    payload = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    template = (_ASSETS / 'rank_timing.html').read_text(encoding='utf-8')
    script = (_ASSETS / 'rank_timing.js').read_text(encoding='utf-8')
    return template.replace('{{RANK_TIMING_JS}}', script).replace('{{RANK_TIMING_DATA}}', payload)
