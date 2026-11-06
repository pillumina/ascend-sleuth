"""Shared analysis rows: real steps, or one synthetic whole-prof step.

Raw files are never rewritten. ``prof`` is an analysis label, not a framework
iteration or an inference request. All consumers use the same TEXT/DB policy.
"""
import math
import hashlib
import os
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation

from lib.common import read_csv_rows, read_json
from lib import prof_data

WHOLE_PROF_STEP = 'prof'
WHOLE_PROF_SCOPE = 'whole_prof'
METRIC_KEYS = tuple(prof_data.STEP_TRACE_COLUMNS.values())
CACHE_ENV = 'CLUSTER_ANALYSIS_SCOPE_CACHE'
_cache_file = None


def use_cache_file(path):
    """Run-local reuse of P0's normalized rows; never writes input artifacts."""
    global _cache_file
    _cache_file = path


def input_signature(apo):
    files = []
    try:
        for name in sorted(os.listdir(apo)):
            path = os.path.join(apo, name)
            if os.path.isfile(path) and name.endswith(('.csv', '.json', '.db', '.db-wal')):
                stat = os.stat(path)
                item = {'name': name, 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
                if stat.st_size <= 1024 * 1024:
                    with open(path, 'rb') as source:
                        item['sha256'] = hashlib.sha256(source.read()).hexdigest()
                files.append(item)
    except OSError:
        pass
    return files


def load_steps(apo):
    """Reuse P0 rows only while all source sizes/mtimes, including WAL, match."""
    cache = read_json(_cache_file or os.environ.get(CACHE_ENV, ''), {}) or {}
    if not isinstance(cache, dict):
        cache = {}
    entry = cache.get('cards', {}).get(os.path.normcase(os.path.abspath(apo)))
    if cache.get('version') == 1 and isinstance(entry, dict) and entry.get('signature') == input_signature(apo):
        rows = entry.get('rows')
        if isinstance(rows, list) and all(isinstance(r, dict) and {'Step', '_scope', '_source'} <= r.keys() for r in rows):
            return rows
    return _load_steps_uncached(apo)


def valid_step_id(value):
    return value is not None and str(value).strip().lower() not in (
        '', 'none', 'null', 'nan', 'n/a', 'unknown')


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _integer_ns(value, unit='ns'):
    try:
        value = Decimal(str(value)) * (1000 if unit == 'us' else 1)
        return int(value) if value.is_finite() else None
    except (ValueError, TypeError, InvalidOperation, OverflowError):
        return None


def _db_bounds(apo):
    start, end = prof_data.read_session_bounds(apo)
    if start is not None and end is not None and end > start:
        return start, end, 'main_db:SESSION_TIME_INFO'
    conn, _ = prof_data.open_main_db(apo)
    if conn is not None:
        with closing(conn):
            tables = prof_data.table_names(conn)
            # No event join: extrema are only a fallback capture-span estimate.
            starts, ends = [], []
            for table in ('OVERLAP_ANALYSIS', 'TASK', 'COMMUNICATION_OP', 'CANN_API'):
                if table not in tables or not {'startNs', 'endNs'} <= prof_data.columns(conn, table):
                    continue
                try:
                    row = conn.execute(f'SELECT MIN(startNs), MAX(endNs) FROM "{table}"').fetchone()
                    left, right = _integer_ns(row[0]), _integer_ns(row[1])
                    if left is not None and right is not None and right > left:
                        starts.append(left)
                        ends.append(right)
                except sqlite3.Error:
                    continue
            if starts:
                return min(starts), max(ends), 'main_db:combined_observed_event_span'
    return None, None, None


def whole_prof_bounds(apo):
    """Integer ns bounds; use a declared session, otherwise observed events."""
    bounds = _db_bounds(apo)
    if bounds[2] == 'main_db:SESSION_TIME_INFO':
        return bounds
    start, end = bounds[:2]
    sources = [bounds[2]] if bounds[2] else []
    # No trace scan for the usual summary-only case; Insight can resolve trace
    # event bounds while streaming events if session metadata is unavailable.
    for filename in ('kernel_details.csv',):
        path = os.path.join(apo, filename)
        if not os.path.isfile(path):
            continue
        from lib.common import iter_csv
        for row in iter_csv(path):
            left = _integer_ns(row.get('Start Time(us)'), 'us')
            duration = _integer_ns(row.get('Duration(us)'), 'us')
            if left is None or duration is None or duration <= 0:
                continue
            right = left + duration
            start = left if start is None else min(left, start)
            end = right if end is None else max(right, end)
        if start is not None:
            sources.append(f'{filename}:observed_event_span')
    trace = os.path.join(apo, 'trace_view.json')
    if os.path.isfile(trace):
        from swimlane_analyzer import iter_trace_events
        try:
            for event in iter_trace_events(trace):
                if event.get('ph') != 'X':
                    continue
                left = _integer_ns(event.get('ts'), 'us')
                duration = _integer_ns(event.get('dur'), 'us')
                if left is None or duration is None or duration <= 0:
                    continue
                start = left if start is None else min(start, left)
                end = left + duration if end is None else max(end, left + duration)
            sources.append('trace_view.json:observed_event_span')
        except (ValueError, OSError):
            pass
    return start, end, '+'.join(sources) or None


def _interval_union_us(conn, type_id, start, end):
    """Ordered cursor, clipped union: duplicate/overlapping intervals count once."""
    total = 0
    left = right = None
    for row in conn.execute('SELECT startNs,endNs FROM OVERLAP_ANALYSIS '
                            'WHERE type=? ORDER BY startNs', (type_id,)):
        a, b = _integer_ns(row[0]), _integer_ns(row[1])
        if a is None or b is None:
            continue
        a, b = max(a, start), min(b, end)
        if b <= a:
            continue
        if right is not None and a <= right:
            right = max(right, b)
        else:
            if right is not None:
                total += right - left
            left, right = a, b
    if right is not None:
        total += right - left
    return total / 1000


def _derived_summary(apo, bounds=None, step_id=WHOLE_PROF_STEP):
    start, end, bounds_source = bounds or whole_prof_bounds(apo)
    if start is None:
        # This scan is only needed when there are no summaries or DB/CSV bounds.
        trace = os.path.join(apo, 'trace_view.json')
        if os.path.isfile(trace):
            from swimlane_analyzer import iter_trace_events
            try:
                for event in iter_trace_events(trace):
                    if event.get('ph') != 'X':
                        continue
                    a = _integer_ns(event.get('ts'), 'us')
                    duration = _integer_ns(event.get('dur'), 'us')
                    if a is None or duration is None or duration <= 0:
                        continue
                    start = a if start is None else min(start, a)
                    end = a + duration if end is None else max(end, a + duration)
            except (ValueError, OSError):
                return []
            if start is not None:
                bounds_source = 'trace_view.json:observed_event_span'
    if start is None or end is None or end <= start:
        return []
    metrics = {key: None for key in METRIC_KEYS}
    metrics['Stage'] = (end - start) / 1000
    source = bounds_source + ':derived_whole_prof'
    conn, _ = prof_data.open_main_db(apo)
    if conn is not None:
        with closing(conn):
            tables = prof_data.table_names(conn)
            if {'ENUM_OVERLAP_ANALYSIS_TYPE', 'OVERLAP_ANALYSIS'} <= tables:
                try:
                    types = {str(r[1]): r[0] for r in conn.execute(
                        'SELECT id,name FROM ENUM_OVERLAP_ANALYSIS_TYPE')}
                    for name, metric in (('COMPUTE', 'Computing'),
                                         ('COMMUNICATION', 'Communication'),
                                         ('COMM_NOT_OVERLAP_COMP', 'Communication(Not Overlapped)'),
                                         ('FREE', 'Free')):
                        if name in types:
                            metrics[metric] = _interval_union_us(conn, types[name], start, end)
                    if metrics['Communication'] is not None and metrics['Communication(Not Overlapped)'] is not None:
                        metrics['Overlapped'] = max(0, metrics['Communication'] - metrics['Communication(Not Overlapped)'])
                    source = 'main_db:OVERLAP_ANALYSIS:interval_union+session_span'
                except sqlite3.Error:
                    pass
    return [dict(metrics, Step=step_id, _scope='step' if step_id != WHOLE_PROF_STEP else WHOLE_PROF_SCOPE,
                 _source=source, _raw_step_ids=[None], _source_rows=0,
                 _start_ns=start, _end_ns=end, _bounds_source=bounds_source,
                 _metric_definition='derived_interval_union; Stage=capture_span')]


def _raw_step_windows(apo):
    """Recognize real framework step boundaries even without summary exports."""
    conn, _ = prof_data.open_main_db(apo)
    if conn is not None:
        with closing(conn):
            if 'STEP_TIME' in prof_data.table_names(conn):
                try:
                    windows = []
                    for row in conn.execute('SELECT id,startNs,endNs FROM STEP_TIME ORDER BY startNs'):
                        left, right = _integer_ns(row[1]), _integer_ns(row[2])
                        if valid_step_id(row[0]) and left is not None and right is not None and right > left:
                            windows.append((str(row[0]).strip(), left, right, 'main_db:STEP_TIME'))
                    if windows:
                        return windows
                except sqlite3.Error:
                    pass
    trace = os.path.join(apo, 'trace_view.json')
    if os.path.isfile(trace):
        from swimlane_analyzer import iter_trace_events
        windows = []
        try:
            for event in iter_trace_events(trace):
                name = str(event.get('name') or '')
                if event.get('ph') != 'X' or not name.startswith('ProfilerStep#'):
                    continue
                step_id = name.removeprefix('ProfilerStep#')
                left, duration = _integer_ns(event.get('ts'), 'us'), _integer_ns(event.get('dur'), 'us')
                if valid_step_id(step_id) and left is not None and duration is not None and duration > 0:
                    windows.append((step_id, left, left + duration, 'trace_view.json:ProfilerStep'))
        except (ValueError, OSError):
            return []
        if windows:
            return windows
    return []


def _load_steps_uncached(apo):
    """TEXT summary first, then analysis.db; no split -> exactly one prof row."""
    rows = read_csv_rows(os.path.join(apo, 'step_trace_time.csv'))
    source = 'step_trace_time.csv'
    if not rows:
        rows = []
        source = 'analysis.db:StepTraceTime'
        for raw in prof_data.read_step_trace(apo):
            rows.append(dict(raw['metrics'], Step=raw['step_id'],
                             _window_ids=raw['window_id']))
    if not rows:
        windows = _raw_step_windows(apo)
        if windows:
            return [row for step_id, left, right, source in windows
                    for row in _derived_summary(apo, (left, right, source), step_id)]
        return _derived_summary(apo)
    has_real_steps = any(valid_step_id(row.get('Step')) for row in rows)
    if has_real_steps:
        result = []
        for i, row in enumerate(rows, 1):
            raw_id = row.get('Step')
            real = valid_step_id(raw_id)
            result.append(dict(row, Step=str(raw_id).strip() if real else f'w{i}',
                               _scope='step' if real else 'capture_window',
                               _source=source, _raw_step_ids=[raw_id], _source_rows=1))
        return result
    # An unlabelled aggregate does not erase valid framework event boundaries.
    windows = _raw_step_windows(apo)
    if windows:
        return [dict(row, _unsegmented_summary_source=source)
                for step_id, left, right, boundary_source in windows
                for row in _derived_summary(apo, (left, right, boundary_source), step_id)]
    metrics = {}
    for key in METRIC_KEYS:
        if any(key in row for row in rows):
            values = [number(row.get(key)) for row in rows]
            metrics[key] = sum(values) if all(v is not None for v in values) else None
    start, end, bounds_source = whole_prof_bounds(apo)
    return [dict(metrics, Step=WHOLE_PROF_STEP, _scope=WHOLE_PROF_SCOPE,
                 _source=source, _raw_step_ids=[row.get('Step') for row in rows],
                 _source_rows=len(rows), _window_ids=WHOLE_PROF_STEP,
                 _start_ns=start, _end_ns=end, _bounds_source=bounds_source,
                 _metric_definition='upstream_summary_sum')]


def scope_of(rows):
    scopes = {r['_scope'] for r in rows}
    return next(iter(scopes)) if len(scopes) == 1 else 'mixed' if scopes else None


def map_comm_step(step_id, rows):
    if scope_of(rows) == WHOLE_PROF_SCOPE:
        return WHOLE_PROF_STEP
    return prof_data.map_comm_step(step_id, {r['_window_ids'] for r in rows if r.get('_window_ids')})


def normalize_communication(data, rows):
    """Re-key all communication/matrix entries for a whole-prof step.

    Preserve each original entry, including repeated names in separate windows,
    rather than overwriting it while changing the key.
    """
    if not data or scope_of(rows) != WHOLE_PROF_SCOPE:
        return data
    merged = {}
    for _, kinds in data.items():
        for kind, operators in kinds.items():
            target = merged.setdefault(kind, {})
            for name, value in operators.items():
                unique = name
                suffix = 2
                while unique in target:
                    unique = f'{name}#source{suffix}'
                    suffix += 1
                target[unique] = dict(value, _original_operator_key=name)
    return {WHOLE_PROF_STEP: merged}
