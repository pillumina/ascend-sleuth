"""Read a supplied cluster export without rewriting it or inventing metadata."""
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sqlite3

from lib.common import to_f
from lib.rank_timing import legacy_zero_fields


DB_NAMES = ('cluster_analysis.db', 'cluster.db', 'cluster_communication_analyzer.db')
STEP_TABLES = ('ClusterStepTraceTime', 'step_statistic_info')
STEP_CSV = 'cluster_step_trace_time.csv'
TIME_FIELDS = {
    'computing': ('Computing', 'compute_time'),
    'communication_not_overlapped': ('Communication(Not Overlapped)', 'pure_communication_time'),
    'communication': ('Communication', 'communication_time'),
    'overlapped': ('Overlapped', 'overlap_communication_time'),
    'free': ('Free', 'free_time'),
    'stage': ('Stage', 'stage_time'),
    'bubble': ('Bubble', 'bubble_time'),
    'preparing': ('Preparing',),
}
INDEX_FIELDS = ('dp_index', 'pp_index', 'tp_index')


def open_db(path):
    if not path:
        return sqlite3.connect(':memory:')
    path = Path(path).resolve()
    mode = '?mode=ro' if Path(str(path) + '-wal').exists() else '?mode=ro&immutable=1'
    return sqlite3.connect(path.as_uri() + mode, uri=True)


def db_tables(conn):
    return {row[0].lower(): row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def base_info(conn, tables):
    for name in ('clusterbaseinfo', 'cluster_base_info'):
        if name in tables:
            columns = {row[1].lower() for row in conn.execute(f'PRAGMA table_info("{tables[name]}")')}
            if {'key', 'value'} <= columns:
                return dict(conn.execute(f'SELECT key, value FROM "{tables[name]}"'))
    return {}


def source_signature(db_path, csv_path):
    files = [db_path, csv_path, str(db_path) + '-wal' if db_path else None]
    signatures = []
    for name in files:
        if name and Path(name).is_file():
            path = Path(name).resolve()
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if stat.st_size <= 1024 * 1024 else None
            signatures.append([str(path), stat.st_size, stat.st_mtime_ns, digest])
    return signatures


def nonnegative(value):
    result = to_f(value, None)
    return result if result is not None and result >= 0 else None


def _pick(row, *keys):
    return next((row[key.lower()] for key in keys if key.lower() in row), None)


def _rank_rows(records):
    for row in records:
        row = {key.lower(): value for key, value in row.items() if key}
        kind = _pick(row, 'type')
        if 'type' in row and str(kind).strip().lower() != 'rank':
            continue
        rank = str(_pick(row, 'index', 'rank_id', 'rank')).strip()
        if not rank.isdecimal():
            continue
        step = str(_pick(row, 'step', 'step_id')).strip()
        step = 'prof' if step.lower() in ('', 'null', 'none', 'nan') else step
        values = {key: nonnegative(_pick(row, key, *aliases)) for key, aliases in TIME_FIELDS.items()}
        values.update({key: nonnegative(row.get(key)) for key in INDEX_FIELDS})
        if values['stage'] is not None:
            yield step, int(rank), values


def read_steps(conn, tables, csv_path, info):
    rows = []
    for name in STEP_TABLES:
        table = tables.get(name.lower())
        if table:
            cursor = conn.execute(f'SELECT * FROM "{table}"')
            columns = [col[0] for col in cursor.description]
            rows = list(_rank_rows(dict(zip(columns, row)) for row in cursor))
            if rows:
                break
    if not rows and csv_path:
        with Path(csv_path).open(encoding='utf-8-sig', newline='') as stream:
            rows = list(_rank_rows(csv.DictReader(stream)))
    if not rows:
        raise ValueError('集群输出缺少可用的 Rank/Step/Stage 时间行')

    unique = {}
    zero_fields = legacy_zero_fields(info)
    unknown = defaultdict(set)
    for key in ('missing_required_metrics', 'unknown_summary_metrics'):
        try:
            by_rank = json.loads(info.get(key) or '{}')
        except (TypeError, ValueError):
            continue
        if isinstance(by_rank, dict):
            for rank, fields in by_rank.items():
                if isinstance(fields, list):
                    unknown[str(rank)].update(fields)
    for step, rank, values in rows:
        for column, (field, *_) in TIME_FIELDS.items():
            if field in unknown[str(rank)] and (column not in ('communication', 'overlapped')
                                                or field in zero_fields.get(str(rank), ())):
                values[column] = None
        if values['stage'] is None:
            continue
        comm, overlap, uncovered = (values[k] for k in ('communication', 'overlapped', 'communication_not_overlapped'))
        if uncovered is None and comm is not None and overlap is not None and comm >= overlap:
            values['communication_not_overlapped'] = comm - overlap
        if (step, rank) in unique and unique[step, rank] != values:
            raise ValueError(f'集群输出包含冲突的 Rank/Step 摘要：rank {rank}，step {step}')
        unique[step, rank] = values
    if not unique:
        raise ValueError('集群输出没有可用的 Stage 时间')
    return [(step, rank, values) for (step, rank), values in sorted(unique.items())]


def install_steps(conn, steps):
    """Expose the supported step schema to the existing recipes in this connection."""
    fields = (*TIME_FIELDS, *INDEX_FIELDS)
    conn.execute('CREATE TEMP TABLE ClusterStepTraceTime (step TEXT, type TEXT, "index" INTEGER, '
                 + ', '.join(f'{key} REAL' for key in fields) + ')')
    conn.executemany('INSERT INTO temp.ClusterStepTraceTime VALUES (' + ','.join('?' for _ in range(3 + len(fields))) + ')',
                     ((step, 'rank', rank, *(values[key] for key in fields)) for step, rank, values in steps))
