# -*- coding: utf-8 -*-
"""只读 DB 适配层：rank 级 analysis.db 与主 profiler DB 的统一读取。

设计来源：prof_plan 03_统一数据契约 / 04_skill迁移与验收（M1 范围）。
TEXT 导出缺失时，本模块提供与 TEXT 等价的基础数据视图（step/window 摘要与
通信汇总），并把能力探测、单位、scope 语义集中在此，供 detect / advisor /
cluster / compare / insight 共用，禁止各脚本自行实现 SQL。

已验证 schema（真实样本 db/ddp_level1_20261012_033349、db/qwen3_8b_tp4_100，
详见 references/db_support.md）：
  analysis.db::StepTraceTime   列值单位 us；step 可为 NULL（NULL = 采集窗，
                               不是训练 step）；deviceId 列可有可无。
  analysis.db::CommAnalyzer{Time,Bandwidth,Matrix}  时间列单位 ms（经带宽
                               反推验证：transit_size/transit_time/bandwidth
                               与 MB/ms/GB·s^-1 自洽）；step 列为 'step2'
                               形式或常量 'step'，不能当训练 step id。
  主 DB::RANK_DEVICE_MAP / HOST_INFO / SESSION_TIME_INFO / STEP_TIME
                               STEP_TIME 缺失表示无框架 step 起止。

WAL 纪律：带 -wal 的库用 mode=ro 打开（可读已提交数据）；仅对确认无 WAL
的静态库使用 immutable=1。禁止对含 WAL 的库用 immutable（会漏读已提交行）。
"""

import os
import re
import sqlite3
import math
from contextlib import closing
from pathlib import Path

from lib.common import is_junk

ANALYSIS_DB = 'analysis.db'
# capture window 的派生 step 标签前缀（写入派生产物时必须可辨识、非数字，
# 避免被误认为训练 step；契约见 references/db_support.md）
WINDOW_PREFIX = 'w'

_COMM_STEP_RE = re.compile(r'^step(\d+)$', re.IGNORECASE)

# StepTraceTime 列 -> TEXT step_trace_time.csv 列名（单位均为 us，直接对齐）
STEP_TRACE_COLUMNS = {
    'computing': 'Computing',
    'communication_not_overlapped': 'Communication(Not Overlapped)',
    'overlapped': 'Overlapped',
    'communication': 'Communication',
    'free': 'Free',
    'stage': 'Stage',
    'bubble': 'Bubble',
    'communication_not_overlapped_and_exclude_receive':
        'Communication(Not Overlapped and Exclude Receive)',
    'preparing': 'Preparing',
}


def open_ro(path):
    """WAL 感知的只读连接；库不存在或打不开时抛 sqlite3.Error 由调用方处理。"""
    path = str(path)
    if os.path.exists(path + '-wal'):
        uri = f'file:{Path(path).as_posix()}?mode=ro'
    else:
        uri = f'file:{Path(path).as_posix()}?mode=ro&immutable=1'
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_names(conn):
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error:
        return set()


def columns(conn, table):
    try:
        return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
    except sqlite3.Error:
        return set()


def _probe(apo, filename, wanted):
    """打开 apo 下指定库并返回 (conn, tables)；库缺失/无目标表时 conn=None。"""
    path = os.path.join(apo, filename)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        return None, set()
    try:
        conn = open_ro(path)
    except sqlite3.Error:
        return None, set()
    tables = table_names(conn)
    if not (tables & wanted):
        conn.close()
        return None, tables
    return conn, tables


def find_main_db(apo):
    """返回主 profiler DB 路径（ascend_pytorch/mindspore_profiler_*.db 或 msprof_*.db）。"""
    try:
        names = sorted(fn for fn in os.listdir(apo) if not is_junk(fn))
    except OSError:
        return None
    for fn in names:
        if re.match(r'^(ascend_(pytorch|mindspore)_profiler_|msprof_).*\.db$', fn) \
                and os.path.getsize(os.path.join(apo, fn)) > 0:
            return os.path.join(apo, fn)
    return None


def open_main_db(apo):
    """返回 (conn|None, path|None)：主 DB 的 WAL 感知只读连接。"""
    path = find_main_db(apo)
    if not path:
        return None, None
    try:
        return open_ro(path), path
    except sqlite3.Error:
        return None, path


def read_step_trace(apo):
    """读 analysis.db::StepTraceTime。

    返回 list[dict]，每行：
      scope_kind: 'step'（step 非空）| 'capture_window'（step 为 NULL）
      step_id: str|None          原始 step 标识；窗口行保持 None，禁止伪造
      window_id: 'w{n}'          会话内 1-based 稳定窗口序
      device_id: int|None        deviceId 列（rank≠device，二者需分别保存）
      metrics: {csv列名: value|None}   单位 us；NULL 保留为 None
      source: 'analysis.db:StepTraceTime'
    无表/无行返回 []。
    """
    conn, _ = _probe(apo, ANALYSIS_DB, {'StepTraceTime'})
    if conn is None:
        return []
    try:
        with closing(conn):
            cols = columns(conn, 'StepTraceTime')
            select = ['step'] + [c for c in STEP_TRACE_COLUMNS if c in cols]
            has_device = 'deviceId' in cols
            if has_device:
                select.append('deviceId')
            rows = []
            window_seq = 0
            for row in conn.execute(
                    f'SELECT {", ".join(select)} FROM StepTraceTime ORDER BY rowid'):
                step = row['step']
                metrics = {}
                for db_col, csv_col in STEP_TRACE_COLUMNS.items():
                    if db_col in cols:
                        v = row[db_col]
                        try:
                            value = float(v)
                            metrics[csv_col] = value if math.isfinite(value) else None
                        except (TypeError, ValueError, OverflowError):
                            metrics[csv_col] = None
                if step is None or str(step).strip() == '':
                    window_seq += 1
                    rows.append({'scope_kind': 'capture_window', 'step_id': None,
                                 'window_id': f'{WINDOW_PREFIX}{window_seq}',
                                 'device_id': row['deviceId'] if has_device else None,
                                 'metrics': metrics,
                                 'source': 'analysis.db:StepTraceTime'})
                else:
                    rows.append({'scope_kind': 'step', 'step_id': str(step).strip(),
                                 'window_id': None,
                                 'device_id': row['deviceId'] if has_device else None,
                                 'metrics': metrics,
                                 'source': 'analysis.db:StepTraceTime'})
        return rows
    except sqlite3.Error:
        return []


def read_comm_time(apo):
    """读 analysis.db::CommAnalyzerTime（时间单位 ms）。

    返回 list[dict]：op/group/type、start_timestamp(us，源值)、
    elapse/transit/wait/synchronization/idle(ms)、step_raw、step_id
    （仅当 step 列形如 'step2' 时解析出 '2'，否则 None）。
    """
    conn, _ = _probe(apo, ANALYSIS_DB, {'CommAnalyzerTime'})
    if conn is None:
        return []
    out = []
    try:
        with closing(conn):
            for row in conn.execute('SELECT * FROM CommAnalyzerTime'):
                raw = row['step']
                m = _COMM_STEP_RE.match(str(raw or '').strip())
                out.append({
                    'op': row['hccl_op_name'], 'group': str(row['group_name']),
                    'type': row['type'] or 'collective',
                    'start_timestamp': row['start_timestamp'],
                    'elapse_ms': row['elapse_time'], 'transit_ms': row['transit_time'],
                    'wait_ms': row['wait_time'],
                    'synchronization_ms': row['synchronization_time'],
                    'idle_ms': row['idle_time'],
                    'step_raw': raw, 'step_id': m.group(1) if m else None,
                    'source': 'analysis.db:CommAnalyzerTime'})
    except sqlite3.Error:
        return []
    return out


def read_comm_bandwidth(apo):
    """读 analysis.db::CommAnalyzerBandwidth（transit_size MB / 时间 ms / 带宽 GB/s）。"""
    conn, _ = _probe(apo, ANALYSIS_DB, {'CommAnalyzerBandwidth'})
    if conn is None:
        return []
    out = []
    try:
        with closing(conn):
            for row in conn.execute('SELECT * FROM CommAnalyzerBandwidth'):
                m = _COMM_STEP_RE.match(str(row['step'] or '').strip())
                out.append({
                    'op': row['hccl_op_name'], 'group': str(row['group_name']),
                    'transport_type': row['transport_type'] or '',
                    'transit_size_mb': row['transit_size'],
                    'transit_time_ms': row['transit_time'],
                    'bandwidth_gbps': row['bandwidth'],
                    'large_packet_ratio': row['large_packet_ratio'],
                    'package_size_mb': row['package_size'],
                    'count': row['count'], 'total_duration_ms': row['total_duration'],
                    'step_id': m.group(1) if m else None,
                    'type': row['type'] or 'collective',
                    'source': 'analysis.db:CommAnalyzerBandwidth'})
    except sqlite3.Error:
        return []
    return out


def read_comm_matrix(apo):
    """读 analysis.db::CommAnalyzerMatrix（src/dst rank、size MB、时间 ms、带宽 GB/s）。"""
    conn, _ = _probe(apo, ANALYSIS_DB, {'CommAnalyzerMatrix'})
    if conn is None:
        return []
    out = []
    try:
        with closing(conn):
            cols = columns(conn, 'CommAnalyzerMatrix')
            for row in conn.execute('SELECT * FROM CommAnalyzerMatrix'):
                m = _COMM_STEP_RE.match(str(row['step'] or '').strip())
                out.append({
                    'op': row['hccl_op_name'], 'group': str(row['group_name']),
                    'src_rank': row['src_rank'], 'dst_rank': row['dst_rank'],
                    'transport_type': row['transport_type'] or '',
                    'op_name': (row['op_name'] or '') if 'op_name' in cols else '',
                    'transit_size_mb': row['transit_size'],
                    'transit_time_ms': row['transit_time'],
                    'bandwidth_gbps': row['bandwidth'],
                    'step_id': m.group(1) if m else None,
                    'type': 'p2p' if str(row['type'] or '').strip() == 'p2p' else 'collective',
                    'source': 'analysis.db:CommAnalyzerMatrix'})
    except sqlite3.Error:
        return []
    return out


def read_rank_device(apo):
    """rank/device 映射：主 DB RANK_DEVICE_MAP 优先，回退 StepTraceTime.deviceId。

    返回 (rank_id|None, device_id|None, source)；rank_id 仍以 profiler_info
    为准（detect_prof.read_rank），此处只补 device 侧证据。
    """
    conn, _ = open_main_db(apo)
    if conn is not None:
        try:
            with closing(conn):
                if 'RANK_DEVICE_MAP' in table_names(conn):
                    rows = conn.execute('SELECT rankId, deviceId FROM RANK_DEVICE_MAP').fetchall()
                    if rows:
                        return rows[0]['rankId'], rows[0]['deviceId'], 'main_db:RANK_DEVICE_MAP'
        except sqlite3.Error:
            pass
    for r in read_step_trace(apo):
        if r['device_id'] is not None:
            return None, r['device_id'], 'analysis.db:StepTraceTime.deviceId'
    return None, None, None


def read_host_info(apo):
    """主 DB HOST_INFO 真实主机信息；缺失返回 (None, None, None)。"""
    conn, _ = open_main_db(apo)
    if conn is None:
        return None, None, None
    try:
        with closing(conn):
            if 'HOST_INFO' in table_names(conn):
                rows = conn.execute('SELECT hostUid, hostName FROM HOST_INFO').fetchall()
                if rows:
                    return str(rows[0]['hostUid']), str(rows[0]['hostName']), 'main_db:HOST_INFO'
    except sqlite3.Error:
        pass
    return None, None, None


def read_session_bounds(apo):
    """主 DB SESSION_TIME_INFO 的 (startNs, endNs)；缺失返回 (None, None)。"""
    conn, _ = open_main_db(apo)
    if conn is None:
        return None, None
    try:
        with closing(conn):
            if 'SESSION_TIME_INFO' in table_names(conn):
                rows = conn.execute(
                    'SELECT startTimeNs, endTimeNs FROM SESSION_TIME_INFO').fetchall()
                if rows and rows[0]['startTimeNs'] is not None:
                    return int(rows[0]['startTimeNs']), int(rows[0]['endTimeNs'])
    except (sqlite3.Error, TypeError, ValueError):
        pass
    return None, None


def db_capabilities(apo):
    """逐 view 能力探测（不读全量数据，仅表/列/行数级别）。

    返回 dict：
      step_rows: 有效 step 行数；window_rows: 采集窗行数（step=NULL）
      step_summary: bool（有任一 step/window 摘要行）
      comm_time / comm_bandwidth / comm_matrix: bool
      rank_device_map / host_info / step_time: bool（主 DB）
      sources: 探测到的来源列表
    """
    caps = {'step_rows': 0, 'window_rows': 0, 'step_summary': False,
            'comm_time': False, 'comm_bandwidth': False, 'comm_matrix': False,
            'rank_device_map': False, 'host_info': False, 'step_time': False,
            'sources': []}
    rows = read_step_trace(apo)
    if rows:
        caps['step_rows'] = sum(1 for r in rows if r['scope_kind'] == 'step')
        caps['window_rows'] = sum(1 for r in rows if r['scope_kind'] == 'capture_window')
        caps['step_summary'] = True
        caps['sources'].append('analysis.db:StepTraceTime')
    for key, table in (('comm_time', 'CommAnalyzerTime'),
                       ('comm_bandwidth', 'CommAnalyzerBandwidth'),
                       ('comm_matrix', 'CommAnalyzerMatrix')):
        conn, _ = _probe(apo, ANALYSIS_DB, {table})
        if conn is not None:
            caps[key] = True
            caps['sources'].append(f'analysis.db:{table}')
            conn.close()
    conn, _ = open_main_db(apo)
    if conn is not None:
        try:
            tables = table_names(conn)
            caps['rank_device_map'] = 'RANK_DEVICE_MAP' in tables
            caps['host_info'] = 'HOST_INFO' in tables
            caps['step_time'] = 'STEP_TIME' in tables
            for t, key in (('RANK_DEVICE_MAP', 'main_db:RANK_DEVICE_MAP'),
                           ('HOST_INFO', 'main_db:HOST_INFO'),
                           ('STEP_TIME', 'main_db:STEP_TIME')):
                if t in tables:
                    caps['sources'].append(key)
        finally:
            conn.close()
    return caps


def map_comm_step(step_id, window_ids):
    """把 CommAnalyzer 的 step_id 映射到派生产物的 step 标签。

    'step2' -> '2'；无法解析且恰好只有一个采集窗时归入该窗口标签；
    其余返回 'unknown'（调用方记录告警，不得静默丢弃行）。
    """
    if step_id is not None:
        return step_id
    if len(window_ids) == 1:
        return next(iter(window_ids))
    return 'unknown'
