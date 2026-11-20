#!/usr/bin/env python3
"""Phase 2 fallback: cluster analysis without msprof-analyze CLI.

Reads per-card outputs (TEXT 优先：step_trace_time.csv / communication.json /
communication_matrix.json / profiler_metadata.json；TEXT 缺失时回退
analysis.db::StepTraceTime 与 CommAnalyzer*，见 lib/prof_data.py) and builds
<root>/cluster_analysis_output/cluster_analysis.db with the same table
schema as msprof-analyze cluster output, so MindStudio Insight and later
recipes can consume it.

来源可追溯：ClusterBaseInfo 记录 step_source / device_map_source /
host_source / communication_source；NULL 指标计数与未映射 step 计数写入
status_info（不静默补 0 / 丢行）。无分步数据整体使用 prof 汇总标签；原始 NULL-step 保留在来源中。

Units: step trace in us (kept as-is); communication times in ms;
transit size in MB; bandwidth in GB/s.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile

from lib.common import is_junk, read_csv_rows, read_json, to_f
from lib import prof_data
from lib import analysis_scope

CARD_DIR_PATTERN = re.compile(r'.*_ascend_(pt|ms)$')
HOST_FROM_CARD = re.compile(r'^(.*)_\d+_\d+_ascend_(pt|ms)$')

BASE_TABLES = {
    'ClusterBaseInfo': ('key TEXT PRIMARY KEY, value TEXT'),
    'HostInfo': ('hostUid TEXT PRIMARY KEY, hostName TEXT'),
    'RankDeviceMap': ('rankId INTEGER, deviceId INTEGER, hostUid TEXT, profilePath TEXT'),
    'ClusterStepTraceTime': (
        'step TEXT, type TEXT, "index" INTEGER, computing REAL, '
        'communication_not_overlapped REAL, overlapped REAL, communication REAL, '
        'free REAL, stage REAL, bubble REAL, '
        'communication_not_overlapped_and_exclude_receive REAL, preparing REAL, '
        'dp_index INTEGER, pp_index INTEGER, tp_index INTEGER'),
    'CommunicationGroupMapping': (
        'type TEXT, rank_set TEXT, group_name TEXT, group_id TEXT, pg_name TEXT'),
    'ClusterCommunicationTime': (
        'step TEXT, rank_id INTEGER, hccl_op_name TEXT, group_name TEXT, '
        'start_timestamp REAL, elapsed_time REAL, transit_time REAL, wait_time REAL, '
        'synchronization_time REAL, idle_time REAL, '
        'synchronization_time_ratio REAL, wait_time_ratio REAL'),
    'ClusterCommunicationBandwidth': (
        'step TEXT, rank_id INTEGER, hccl_op_name TEXT, group_name TEXT, '
        'band_type TEXT, transit_size REAL, transit_time REAL, bandwidth REAL, '
        'large_packet_ratio REAL, package_size REAL, "count" INTEGER, total_duration REAL'),
    'ClusterCommunicationMatrix': (
        'step TEXT, hccl_op_name TEXT, group_name TEXT, src_rank REAL, dst_rank REAL, '
        'transport_type TEXT, op_name TEXT, transit_size REAL, transit_time REAL, '
        'bandwidth REAL'),
}


def find_card_dirs(root):
    from detect_prof import find_card_dirs as discover
    return discover(root)


def read_rank(card_dir):
    for fn in sorted(os.listdir(card_dir)):
        if is_junk(fn):
            continue
        m = re.match(r'^profiler_info_(\d+)\.json$', fn)
        if m:
            data = read_json(os.path.join(card_dir, fn)) or {}
            return int(data.get('rank_id', m.group(1)))
    return None


def host_of(card_dir):
    m = HOST_FROM_CARD.match(os.path.basename(card_dir))
    if m:
        return m.group(1)
    return 'unknown-host'


def host_uid(hostname):
    return str(int(hashlib.md5(hostname.encode('utf-8')).hexdigest()[:16], 16))


def steps_from_db(apo):
    """Compatibility entry; all analysis rows now use the shared scope policy."""
    rows = analysis_scope.load_steps(apo)
    return rows, rows[0]['_source'] if rows else None


def _window_ids(steps):
    return {r['_window_ids'] for r in steps if r.get('_window_ids')}


def comm_from_db(apo, steps):
    """analysis.db CommAnalyzer* -> communication.json / communication_matrix.json 等价结构。

    时间单位 ms、transit_size MB、带宽 GB/s（与 TEXT JSON 同口径，已由
    transit_size/transit_time/bandwidth 自洽关系验证）。step 标签：'stepN'
    解析为 'N'；无法解析且恰有一个采集窗时归入该窗口标签；否则 'unknown'
    （写库后由 status_info 记录，不静默丢弃）。
    """
    win_ids = _window_ids(steps)
    comm, matrix = {}, {}
    unknown_steps = 0
    for r in prof_data.read_comm_time(apo):
        step = prof_data.map_comm_step(r['step_id'], win_ids)
        unknown_steps += step == 'unknown'
        operators = comm.setdefault(step, {}).setdefault(r['type'], {})
        original_key = f"{r['op']}@{r['group']}"
        key = original_key
        seq = 2
        while key in operators and 'Communication Time Info' in operators[key]:
            key = f'{original_key}#source{seq}'
            seq += 1
        info = operators.setdefault(key, {})
        info['_original_operator_key'] = original_key
        info['Communication Time Info'] = {
            'Start Timestamp(us)': r['start_timestamp'],
            'Elapse Time(ms)': r['elapse_ms'],
            'Transit Time(ms)': r['transit_ms'],
            'Wait Time(ms)': r['wait_ms'],
            'Synchronization Time(ms)': r['synchronization_ms'],
            'Idle Time(ms)': r['idle_ms'],
        }
    for r in prof_data.read_comm_bandwidth(apo):
        step = prof_data.map_comm_step(r['step_id'], win_ids)
        operators = comm.setdefault(step, {}).setdefault(r['type'], {})
        original_key = f"{r['op']}@{r['group']}"
        key = original_key
        seq = 2
        band_name = r['transport_type'] or 'unknown'
        while band_name in (operators.get(key, {}).get('Communication Bandwidth Info') or {}):
            key = f'{original_key}#band{seq}'
            seq += 1
        info = operators.setdefault(key, {})
        info['_original_operator_key'] = original_key
        bands = info.setdefault('Communication Bandwidth Info', {})
        bands[band_name] = {
            'Transit Size(MB)': r['transit_size_mb'],
            'Transit Time(ms)': r['transit_time_ms'],
            'Bandwidth(GB/s)': r['bandwidth_gbps'],
            'Large Packet Ratio': r['large_packet_ratio'],
            'Package Size': r['package_size_mb'],
            'Package Count': r['count'],
            'Total Duration(ms)': r['total_duration_ms'],
        }
    for r in prof_data.read_comm_matrix(apo):
        step = prof_data.map_comm_step(r['step_id'], win_ids)
        operators = matrix.setdefault(step, {}).setdefault(r['type'], {})
        original_key = f"{r['op']}@{r['group']}"
        pair = f"{r['src_rank']}-{r['dst_rank']}"
        key = original_key
        seq = 2
        while pair in operators.get(key, {}):
            key = f'{original_key}#matrix{seq}'
            seq += 1
        links = operators.setdefault(key, {})
        links[pair] = {
            '_original_operator_key': original_key,
            'Transit Size(MB)': r['transit_size_mb'],
            'Transit Time(ms)': r['transit_time_ms'],
            'Transport Type': r['transport_type'],
            'Op Name': r['op_name'],
            'Bandwidth(GB/s)': r['bandwidth_gbps'],
        }
    return comm, matrix, unknown_steps


def collect_card(card_dir):
    apo = os.path.join(card_dir, 'ASCEND_PROFILER_OUTPUT')
    rank = read_rank(card_dir)
    meta = read_json(os.path.join(card_dir, 'profiler_metadata.json')) or {}
    dist = meta.get('distributed_args', {}) if isinstance(meta, dict) else {}
    hostname = host_of(card_dir)
    steps = analysis_scope.load_steps(apo)
    step_source = steps[0]['_source'] if steps else None
    device_id = device_source = None
    _, device_id, device_source = prof_data.read_rank_device(apo)
    real_uid, real_name, host_source = prof_data.read_host_info(apo)
    if real_uid is None:
        real_uid, real_name = host_uid(hostname), hostname
        host_source = 'card_dir_name_inference'
    card = {
        'dir': card_dir,
        'apo': apo,
        'rank': rank,
        'device_id': device_id,
        'device_source': device_source,
        'host': real_name or hostname,
        'host_uid': str(real_uid),
        'host_source': host_source,
        'dist': dist,
        'groups': meta.get('parallel_group_info', {}) if isinstance(meta, dict) else {},
        'steps': steps,
        'step_source': step_source,
        'analysis_scope': analysis_scope.scope_of(steps),
        'comm': read_json(os.path.join(apo, 'communication.json')) or {},
        'comm_source': 'communication.json',
        'matrix': read_json(os.path.join(apo, 'communication_matrix.json')) or {},
        'matrix_source': 'communication_matrix.json',
    }
    if not card['comm'] or not card['matrix']:
        db_comm, db_matrix, db_unknown = comm_from_db(apo, steps)
        card.setdefault('db_unknown_comm_steps', 0)
        card['db_unknown_comm_steps'] += db_unknown
        if not card['comm'] and db_comm:
            card['comm'], card['comm_source'] = db_comm, 'analysis.db:CommAnalyzer*'
        if not card['matrix'] and db_matrix:
            card['matrix'], card['matrix_source'] = db_matrix, 'analysis.db:CommAnalyzerMatrix'
    return card


def parallel_indexes(rank, tp, pp):
    tp = max(1, tp)
    pp = max(1, pp)
    return rank // (tp * pp), (rank // tp) % pp, rank % tp  # dp, pp, tp


def write_cluster_db(root, cards):
    out_dir = os.path.join(root, 'cluster_analysis_output')
    os.makedirs(out_dir, exist_ok=True)
    db_path = os.path.join(out_dir, 'cluster_analysis.db')
    fd, staging_db = tempfile.mkstemp(prefix='cluster-', suffix='.db', dir=out_dir)
    os.close(fd)
    conn = sqlite3.connect(staging_db)
    try:
        build_cluster_db(conn, cards)
    except Exception:
        conn.close()
        os.unlink(staging_db)
        raise
    conn.close()
    os.replace(staging_db, db_path)
    return db_path


def build_cluster_db(conn, cards):
    cur = conn.cursor()
    for table, ddl in BASE_TABLES.items():
        cur.execute(f'CREATE TABLE IF NOT EXISTS {table} ({ddl})')

    # ClusterBaseInfo
    dist0 = cards[0]['dist']
    world = dist0.get('world_size') or len(cards)
    base_info = [
        ('algorithm', dist0.get('algorithm') or 'unknown'),
        ('world_size', str(world)),
        ('tp_size', str(dist0.get('tensor_model_parallel_size', 1))),
        ('pp_size', str(dist0.get('pipeline_model_parallel_size', 1))),
        ('dp_size', str(dist0.get('data_parallel_size', world))),
        ('cp_size', str(dist0.get('context_parallel_size', 1))),
        ('ep_size', str(dist0.get('expert_model_parallel_size', 1))),
        ('rank_card_num', str(len(cards))),
        ('gen_by', 'npu-perf-analyzer cluster_fallback'),
        ('step_time_unit', 'us'),
        ('communication_time_unit', 'ms'),
    ]
    # 数据来源与语义标记（派生产物必须可追溯；wN 标签 = 采集窗，不是训练 step）
    step_sources = sorted({c.get('step_source') or 'none' for c in cards})
    required_metrics = ('Stage', 'Computing', 'Communication(Not Overlapped)', 'Free')
    missing_metrics = {str(c['rank']): sorted({key for row in c['steps'] for key in required_metrics
                                             if analysis_scope.number(row.get(key)) is None})
                       for c in cards}
    missing_metrics = {rank: keys for rank, keys in missing_metrics.items() if keys}
    unknown_metrics = {str(c['rank']): sorted({key for row in c['steps'] for key in analysis_scope.METRIC_KEYS
                                             if analysis_scope.number(row.get(key)) is None}) for c in cards}
    base_info += [
        ('step_source', '+'.join(step_sources)),
        ('analysis_scope', '+'.join(sorted({c.get('analysis_scope') or 'unknown' for c in cards}))),
        ('missing_required_metrics', json.dumps(missing_metrics, ensure_ascii=False)),
        ('unknown_summary_metrics', json.dumps(unknown_metrics, ensure_ascii=False)),
        ('analysis_step_sources', json.dumps({str(c['rank']): [
            {'step': row['Step'], 'scope': row['_scope'], 'raw_step_ids': row['_raw_step_ids'],
             'source_rows': row['_source_rows'], 'definition': row.get('_metric_definition'),
             'bounds_source': row.get('_bounds_source'),
             'start_ns': str(row['_start_ns']) if row.get('_start_ns') is not None else None,
             'end_ns': str(row['_end_ns']) if row.get('_end_ns') is not None else None}
            for row in c['steps']] for c in cards}, ensure_ascii=False)),
        ('step_id_semantics', 'prof = whole supplied prof as one synthetic step; '
                              'w<N> = unlabelled window in mixed input; '
                              'other labels = original step ids'),
        ('device_map_source', '+'.join(sorted({c.get('device_source')
                                               or 'rank_as_device_fallback' for c in cards}))),
        ('host_source', '+'.join(sorted({c.get('host_source')
                                         or 'card_dir_name_inference' for c in cards}))),
        ('communication_source', '+'.join(sorted({c.get('comm_source') or 'none'
                                                  for c in cards}))),
    ]
    cur.executemany('INSERT INTO ClusterBaseInfo VALUES (?, ?)', base_info)

    # HostInfo / RankDeviceMap
    hosts = {}
    for c in cards:
        hosts.setdefault(c['host_uid'], c['host'])
    cur.executemany('INSERT INTO HostInfo VALUES (?, ?)', list(hosts.items()))
    for c in cards:
        # rank != device：优先使用真实 device 映射（RANK_DEVICE_MAP /
        # StepTraceTime.deviceId），仅缺失时回退 rank（来源已记入 device_map_source）
        device = c['device_id'] if c.get('device_id') is not None else c['rank']
        cur.execute('INSERT INTO RankDeviceMap VALUES (?, ?, ?, ?)',
                    (c['rank'], device, c['host_uid'], c['dir']))

    # ClusterStepTraceTime (us)
    tp = int(dist0.get('tensor_model_parallel_size', 1) or 1)
    pp = int(dist0.get('pipeline_model_parallel_size', 1) or 1)
    metric_keys = ('Computing', 'Communication(Not Overlapped)', 'Overlapped',
                   'Communication', 'Free', 'Stage', 'Bubble',
                   'Communication(Not Overlapped and Exclude Receive)', 'Preparing')
    null_metric_cells = 0
    for c in cards:
        for r in c['steps']:
            step = str(r.get('Step', '')).strip()
            if not step:
                continue
            null_metric_cells += sum(1 for k in metric_keys if r.get(k) is None)
            dp_i, pp_i, tp_i = parallel_indexes(c['rank'], tp, pp)
            cur.execute(
                'INSERT INTO ClusterStepTraceTime VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (step, 'rank', c['rank'],
                 to_f(r.get('Computing')),
                 to_f(r.get('Communication(Not Overlapped)')),
                 to_f(r.get('Overlapped')),
                 to_f(r.get('Communication')),
                 to_f(r.get('Free')),
                 to_f(r.get('Stage')),
                 to_f(r.get('Bubble')),
                 to_f(r.get('Communication(Not Overlapped and Exclude Receive)')),
                 to_f(r.get('Preparing')),
                 dp_i, pp_i, tp_i))

    # CommunicationGroupMapping from metadata parallel_group_info
    group_rows = set()
    for c in cards:
        for gname, info in (c['groups'] or {}).items():
            if not isinstance(info, dict):
                continue
            ranks = info.get('global_ranks') or []
            pg = info.get('group_name', '')
            group_rows.add(('collective', '(' + ','.join(str(x) for x in ranks) + ')',
                            gname, '', pg))
    cur.executemany('INSERT INTO CommunicationGroupMapping VALUES (?,?,?,?,?)',
                    sorted(group_rows))

    # ClusterCommunicationTime / Bandwidth (ms / MB / GB/s)
    for c in cards:
        for step, groups in c['comm'].items():
            if c.get('analysis_scope') == 'whole_prof':
                step = analysis_scope.WHOLE_PROF_STEP
            for gtype in ('collective', 'p2p'):
                for op_key, info in (groups.get(gtype) or {}).items():
                    name, _, gid = info.get('_original_operator_key', op_key).partition('@')
                    ti = info.get('Communication Time Info')
                    if ti:
                        cur.execute(
                        'INSERT INTO ClusterCommunicationTime VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                        (step, c['rank'], name, gid,
                         to_f(ti.get('Start Timestamp(us)')),
                         to_f(ti.get('Elapse Time(ms)')),
                         to_f(ti.get('Transit Time(ms)')),
                         to_f(ti.get('Wait Time(ms)')),
                         to_f(ti.get('Synchronization Time(ms)')),
                         to_f(ti.get('Idle Time(ms)')),
                         to_f(ti.get('Synchronization Time Ratio')),
                         to_f(ti.get('Wait Time Ratio'))))
                    for band, bi in (info.get('Communication Bandwidth Info') or {}).items():
                        size = to_f(bi.get('Transit Size(MB)'))
                        ttime = to_f(bi.get('Transit Time(ms)'))
                        if size <= 0 and ttime <= 0:
                            continue  # skip no-traffic band rows (msprof only records real traffic)
                        cur.execute(
                            'INSERT INTO ClusterCommunicationBandwidth VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                            (step, c['rank'], name, gid, band,
                             size,
                             ttime,
                             to_f(bi.get('Bandwidth(GB/s)')),
                             to_f(bi.get('Large Packet Ratio')),
                             to_f(bi.get('Package Size')),
                             int(to_f(bi.get('Package Count'))),
                             to_f(bi.get('Total Duration(ms)'))))

    # ClusterCommunicationMatrix
    for c in cards:
        for step, groups in c['matrix'].items():
            if c.get('analysis_scope') == 'whole_prof':
                step = analysis_scope.WHOLE_PROF_STEP
            for gtype in ('collective', 'p2p'):
                for op_key, links in (groups.get(gtype) or {}).items():
                    name, _, gid = op_key.partition('@')
                    for pair, link in (links or {}).items():
                        name, _, gid = link.get('_original_operator_key', op_key).partition('@')
                        src, _, dst = pair.partition('-')
                        size = to_f(link.get('Transit Size(MB)'))
                        ttime = to_f(link.get('Transit Time(ms)'))
                        if size <= 0 and ttime <= 0:
                            continue  # skip no-traffic links
                        cur.execute(
                            'INSERT INTO ClusterCommunicationMatrix VALUES (?,?,?,?,?,?,?,?,?,?)',
                            (step, name, gid,
                             to_f(src, -1), to_f(dst, -1),
                             link.get('Transport Type', ''),
                             link.get('Op Name', ''),
                             size,
                             ttime,
                             to_f(link.get('Bandwidth(GB/s)'))))

    cur.execute('CREATE TABLE IF NOT EXISTS status_info (id INTEGER PRIMARY KEY AUTOINCREMENT, '
                'key TEXT, value TEXT)')
    cur.execute("INSERT INTO status_info (key, value) VALUES ('Cluster files parsing status', 'FINISH')")
    if null_metric_cells:
        cur.execute("INSERT INTO status_info (key, value) VALUES "
                    "('null_metric_cells_converted_to_zero', ?)", (str(null_metric_cells),))
    unknown_steps = sum(c.get('db_unknown_comm_steps', 0) for c in cards)
    if unknown_steps:
        cur.execute("INSERT INTO status_info (key, value) VALUES "
                    "('comm_rows_with_unmapped_step', ?)", (str(unknown_steps),))
    conn.commit()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, help='multi-card root (cluster_analysis_output parent)')
    parser.add_argument('--force', action='store_true', help='overwrite existing cluster_analysis.db')
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    card_dirs = find_card_dirs(root)
    if not card_dirs:
        print('ERROR: no card dirs (*_ascend_pt / *_ascend_ms) found', file=sys.stderr)
        sys.exit(1)

    out_dir = os.path.join(root, 'cluster_analysis_output')
    db_path = os.path.join(out_dir, 'cluster_analysis.db')
    if os.path.isfile(db_path) and not args.force:
        print(f'EXISTS: {db_path} (use --force to rebuild)')
        sys.exit(0)

    cards = []
    for cd in card_dirs:
        if not os.path.isdir(os.path.join(cd, 'ASCEND_PROFILER_OUTPUT')):
            print(f'skip (no ASCEND_PROFILER_OUTPUT): {cd}')
            continue
        c = collect_card(cd)
        if c['rank'] is None:
            c['rank'] = len(cards)
        if not c['steps'] and not c['comm']:
            print(f'skip (no step/comm data): {cd}')
            continue
        cards.append(c)
    if len(cards) < 2:
        print('ERROR: fewer than 2 usable cards; cluster analysis needs multi-card data',
              file=sys.stderr)
        sys.exit(1)
    cards.sort(key=lambda c: c['rank'])

    db_path = write_cluster_db(root, cards)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    counts = {}
    for t in BASE_TABLES:
        cur.execute(f'SELECT COUNT(*) FROM {t}')
        counts[t] = cur.fetchone()[0]
    conn.close()

    print(f'cluster_analysis.db written: {db_path}')
    for t, n in counts.items():
        print(f'  {t}: {n} rows')
    print('cards: ' + ', '.join(f"rank{c['rank']}"
                                + (f"→dev{c['device_id']}" if c.get('device_id') is not None else '')
                                + f"@{c['host']}" for c in cards))
    step_sources = sorted({c.get('step_source') for c in cards if c.get('step_source')})
    if 'analysis.db:StepTraceTime' in step_sources:
        print(f"step source: {'+'.join(step_sources)}"
              '（采集窗行使用 wN 标签，不是训练 step；见 ClusterBaseInfo.step_id_semantics）')


if __name__ == '__main__':
    main()
