#!/usr/bin/env python3
"""Phase 3 fallback: advanced (recipe) analysis on cluster_analysis_output.

Implements msprof-analyze cluster recipes organized into FIVE categories:

  拆解对比类  cluster_time_summary, cluster_time_compare_summary,
             module_statistic, calibrate_npu_gpu
  计算类      compute_op_sum, freq_analysis, ep_load_balance,
             computational_op_masking, operator_mfu
  通信类      communication_group_map, communication_time_sum,
             communication_matrix_sum, communication_bandwidth_sum(extra),
             hccl_sum, pp_chart, slow_rank, slow_link, communication_bottleneck
  Host 下发类 cann_api_sum, mstx_sum, free_analysis
  其他        export_summary, mstx2commop, p2p_pairing

Unified protocol: every recipe function is `def recipe_x(ctx) -> (rows|None,
reason|None)`; the registry CATEGORIES (defined after the functions) binds
(name, desc, func) and main() executes them uniformly, recording
status/rows/reason as a transparent capability matrix.

Feasible recipes produce CSV under cluster_analysis_output/recipes/<name>/;
infeasible ones are recorded with status=unsupported and a reason. Step
dimension is preserved wherever the source table has it.

Outputs: cluster_analysis_output/recipes/<name>/*.csv
         cluster_analysis_output/recipes_summary.{md,json} (categories+status)
         RecipeSummary table inside cluster_analysis.db
"""
import argparse
import csv
import glob
import json
import os
import re
import sqlite3
import sys
import traceback
from collections import defaultdict
from itertools import groupby
from pathlib import Path

from lib.common import is_junk, read_csv_rows, read_json, to_f
from lib.cluster_source import base_info, db_tables, install_steps, open_db, read_steps, source_signature
from lib.communication_top import communication_tops
from lib.config import AGG_ROWS, COMM_NAME_PATTERN
from lib.workflow_state import write_json


class Ctx:
    """分析上下文：所有 recipe 函数统一接收 ctx，并返回 (rows|None, reason|None)。"""

    def __init__(self, cur, card_dirs, root, recipes_dir, top_num=20, supplied=False):
        self.cur = cur                    # cluster_analysis.db 游标
        self.card_dirs = card_dirs        # rank -> 本地 PROF 目录
        self.root = root                  # 多卡根目录
        self.recipes_dir = recipes_dir    # recipe csv 输出根目录
        self.top_num = top_num            # hccl_sum TopN
        self.supplied = supplied
        self.communication_summary = None


def norm_op(name):
    """hcom_allReduce__909_0_1 -> hcom_allReduce (strip instance suffixes)."""
    return re.sub(r'__\d+(_\d+)*$', '', name)


def q(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchall()


def card_paths(ctx):
    if getattr(ctx, 'supplied', False):
        return ctx.card_dirs
    return {int(rank): path if path and os.path.isdir(path) else ctx.card_dirs.get(int(rank))
            for rank, path in q(ctx.cur, 'SELECT rankId, profilePath FROM RankDeviceMap')}


# ---------------- 拆解对比类 ----------------

def recipe_cluster_time_summary(ctx):
    """Per (step, rank): time decomposition. Step dimension preserved."""
    rows = q(ctx.cur, 'SELECT step, "index", computing, communication_not_overlapped, '
                      'communication, overlapped, free, stage, bubble, preparing, dp_index, pp_index, tp_index '
                      'FROM ClusterStepTraceTime WHERE type = \'rank\' ORDER BY CAST(step AS INTEGER), "index"')
    out = []
    def rounded(value):
        return None if value is None else round(value, 1)

    def ratio(value, stage):
        return round(value / stage, 4) if value is not None and stage else None

    for step, rank, comp, comm_no, comm, overlap, free, stage, bubble, prep, dp, pp, tp in rows:
        out.append({
            'step': step, 'rank': int(rank), 'computing(us)': rounded(comp),
            'communication_not_overlapped(us)': rounded(comm_no),
            'communication(us)': comm, 'overlapped(us)': overlap, 'free(us)': rounded(free),
            'stage(us)': rounded(stage), 'bubble(us)': rounded(bubble),
            'preparing(us)': rounded(prep),
            'dp_index': dp, 'pp_index': pp, 'tp_index': tp,
            'computing_ratio': ratio(comp, stage),
            'comm_ratio': ratio(comm_no, stage),
            'free_ratio': ratio(free, stage),
        })
    return out, None


def recipe_cluster_time_compare_summary(ctx):
    rows = q(ctx.cur, 'SELECT step, "index", computing, communication_not_overlapped, free, stage '
                      'FROM ClusterStepTraceTime WHERE type = \'rank\' ORDER BY CAST(step AS INTEGER), "index"')
    out = []
    # compare adjacent ranks within the same step
    by_step = defaultdict(list)
    for step, rank, comp, comm_no, free, stage in rows:
        by_step[step].append((int(rank), comp, comm_no, free, stage))
    for step, members in sorted(by_step.items(), key=lambda kv: to_f(kv[0])):
        members.sort()
        for i in range(1, len(members)):
            r0, r1 = members[i - 1], members[i]
            for label, idx in (('computing', 1), ('comm_not_overlapped', 2),
                               ('free', 3), ('stage', 4)):
                base, comp_v = to_f(r0[idx]), to_f(r1[idx])
                out.append({
                    'step': step, 'base_rank': r0[0], 'compare_rank': r1[0],
                    'dimension': label,
                    'base(us)': round(base, 1), 'compare(us)': round(comp_v, 1),
                    'diff(us)': round(comp_v - base, 1),
                    'diff_ratio': round((comp_v - base) / base, 4) if base else None,
                })
    return out, None


def recipe_module_statistic(ctx):
    """Module-level hotspot localization from operator_details.csv call stacks."""
    agg = defaultdict(lambda: {'total_us': 0.0, 'count': 0, 'ops': set()})
    found_any = False
    for rank in sorted(ctx.card_dirs):
        path = os.path.join(ctx.card_dirs[rank], 'ASCEND_PROFILER_OUTPUT', 'operator_details.csv')
        for r in read_csv_rows(path):
            stack = r.get('Call Stack', '')
            dur = to_f(r.get('Device Total Duration(us)')) or \
                to_f(r.get('Host Total Duration(us)'))
            if dur <= 0:
                continue
            found_any = True
            m = re.search(r'([\w\-./]+\.py)\(\d+\):', stack)
            module = m.group(1) if m else '(unknown)'
            e = agg[module]
            e['total_us'] += dur
            e['count'] += 1
            e['ops'].add(r.get('Name', ''))
    if not found_any or not any(mod != '(unknown)' for mod in agg):
        return None, '无 operator_details.csv 调用栈数据'
    out = [{'module': mod, 'total(ms)': round(e['total_us'] / 1000, 3), 'count': e['count'],
            'op_kinds': len(e['ops'])}
           for mod, e in sorted(agg.items(), key=lambda kv: -kv[1]['total_us'])[:50]]
    return out, None


def recipe_calibrate_npu_gpu(ctx):
    return None, '需要 GPU 侧profiling数据，当前数据集不含 GPU 基线'


# ---------------- 计算类 ----------------

def recipe_compute_op_sum(ctx):
    rank_map = card_paths(ctx)
    per_rank = {}
    for rank in sorted(rank_map):
        path = rank_map[rank]
        if not path:
            continue
        stats = read_csv_rows(os.path.join(path, 'ASCEND_PROFILER_OUTPUT', 'op_statistic.csv'))
        if not stats:
            continue
        agg = {}
        for r in stats:
            name = r.get('OP Type', '')
            if COMM_NAME_PATTERN.search(name):
                continue
            t = to_f(r.get('Total Time(us)'))
            agg[name] = {'count': int(to_f(r.get('Count'))), 'total(us)': t,
                         'avg(us)': to_f(r.get('Avg Time(us)')), 'max(us)': to_f(r.get('Max Time(us)'))}
        per_rank[int(rank)] = agg
    out = []
    all_ops = sorted({op for agg in per_rank.values() for op in agg},
                     key=lambda o: -max((per_rank[r][o]['total(us)'] for r in per_rank
                                         if o in per_rank[r]), default=0))
    for op in all_ops[:50]:
        row = {'op': op}
        totals = []
        for rank in sorted(per_rank):
            v = per_rank[rank].get(op)
            row[f'rank{rank}_total(ms)'] = round(v['total(us)'] / 1000, 3) if v else None
            row[f'rank{rank}_count'] = v['count'] if v else 0
            if v:
                totals.append(v['total(us)'])
        if len(totals) >= 2:
            row['max_min_ratio'] = round(max(totals) / min(totals), 3) if min(totals) else None
            row['load_imbalance'] = '⚠' if (row['max_min_ratio'] or 0) > 1.2 else 'ok'
        out.append(row)
    return (out, None) if out else (None, '无卡级 op_statistic.csv 计算算子明细')


def recipe_freq_analysis(ctx):
    """Use recorded clock samples; PMU cycles may sum over multiple cores."""
    freqs = []
    per_rank = []
    rank_map = card_paths(ctx)
    for rank in sorted(rank_map):
        path = rank_map[rank]
        if not path:
            continue
        samples = []
        for db_path in glob.glob(os.path.join(path, 'ASCEND_PROFILER_OUTPUT', '*profiler*.db')):
            conn = None
            try:
                from pathlib import Path
                conn = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
                samples = [to_f(row[0]) for row in conn.execute('SELECT freq FROM AICORE_FREQ')
                           if to_f(row[0]) > 0]
            except sqlite3.Error:
                continue
            finally:
                if conn is not None:
                    conn.close()
            if samples:
                break
        if samples:
            freqs.extend(samples)
            per_rank.append({'rank': rank, 'min_freq(MHz)': min(samples),
                             'max_freq(MHz)': max(samples), 'samples': len(samples)})
    if not freqs:
        return None, '无 AICORE_FREQ 实测频率样本；跨核累计周期与平均核时间不能直接相除推算频率'
    freqs.sort()
    out = [{
        'metric': 'min', 'value(MHz)': round(freqs[0], 1),
    }, {
        'metric': 'p25', 'value(MHz)': round(freqs[len(freqs) // 4], 1),
    }, {
        'metric': 'median', 'value(MHz)': round(freqs[len(freqs) // 2], 1),
    }, {
        'metric': 'p75', 'value(MHz)': round(freqs[len(freqs) * 3 // 4], 1),
    }, {
        'metric': 'max', 'value(MHz)': round(freqs[-1], 1),
    }]
    write_csv(os.path.join(ctx.recipes_dir, 'freq_analysis', 'freq_per_rank.csv'), per_rank)
    return out, None


def recipe_ep_load_balance(ctx):
    try:
        rows = q(ctx.cur, 'SELECT localExpertId, modelStage, rankId, visits, layer '
                          'FROM ExpertHotspotInfo')
    except sqlite3.Error:
        return None, '集群 db 无 ExpertHotspotInfo 表'
    if not rows:
        return None, '无 MoE 专家热点数据（需 MoE 模型且采集开启 expert 统计）'
    agg = defaultdict(lambda: {'visits': 0, 'ranks': set()})
    for eid, stage, rank, visits, layer in rows:
        a = agg[(layer, eid)]
        a['visits'] += to_f(visits)
        a['ranks'].add(rank)
    out = [{'layer': k[0], 'expert_id': k[1], 'visits': int(v['visits']),
            'rank_count': len(v['ranks'])}
           for k, v in sorted(agg.items(), key=lambda kv: -kv[1]['visits'])]
    return out, None


def recipe_computational_op_masking(ctx):
    """Overlap/masking from ClusterStepTraceTime: overlapped vs communication."""
    rows = q(ctx.cur, 'SELECT step, "index", overlapped, communication, communication_not_overlapped '
                      'FROM ClusterStepTraceTime WHERE type = \'rank\' ORDER BY CAST(step AS INTEGER), "index"')
    out = []
    for step, rank, ov, comm, comm_no in rows:
        comm = to_f(comm)
        ov = to_f(ov)
        out.append({
            'step': step, 'rank': int(rank),
            'communication(us)': round(comm, 1),
            'overlapped(us)': round(ov, 1),
            'not_overlapped(us)': round(to_f(comm_no), 1),
            'masking_ratio': round(ov / comm, 4) if comm else None,
        })
    if not out:
        return None, 'ClusterStepTraceTime 无 overlapped 数据'
    return out, None


def recipe_operator_mfu(ctx):
    return None, '需要算子 FLOPs 数据，PROF 文本输出不含 shape-FLOPs 映射'


# ---------------- 通信类 ----------------

def recipe_communication_group_map(ctx):
    rows = q(ctx.cur, 'SELECT type, rank_set, group_name, group_id, pg_name '
                      'FROM CommunicationGroupMapping')
    return [{'type': r[0], 'rank_set': r[1], 'group_name': r[2], 'group_id': r[3],
             'pg_name': r[4]} for r in rows], None


def recipe_communication_time_sum(ctx):
    if ctx.communication_summary is not None:
        return ctx.communication_summary
    rows = ctx.cur.execute('SELECT hccl_op_name, elapsed_time, transit_time, wait_time, '
                           'idle_time, synchronization_time FROM ClusterCommunicationTime')
    agg = defaultdict(lambda: {'n': 0, 'elapse': 0.0, 'transit': 0.0, 'wait': 0.0, 'idle': 0.0,
                               'sync': 0.0, 'max': 0.0, 'min': float('inf')})
    for op, elapse, transit, wait, idle, sync in rows:
        if not op or op in AGG_ROWS:
            continue
        a = agg[norm_op(op)]
        el = to_f(elapse)
        a['n'] += 1
        a['elapse'] += el
        a['max'] = max(a['max'], el)
        a['min'] = min(a['min'], el)
        a['transit'] += to_f(transit)
        a['wait'] += to_f(wait)
        a['idle'] += to_f(idle)
        a['sync'] += to_f(sync)
    out = []
    for op, a in sorted(agg.items(), key=lambda x: -x[1]['elapse']):
        el = a['elapse']
        out.append({
            'op': op, 'count': a['n'],
            'total_elapse(ms)': round(el, 3), 'avg_elapse(ms)': round(el / a['n'], 3),
            'max_elapse(ms)': round(a['max'], 3), 'min_elapse(ms)': round(a['min'], 3),
            'total_wait(ms)': round(a['wait'], 3),
            'total_transit(ms)': round(a['transit'], 3),
            'total_idle(ms)': round(a['idle'], 3),
            'total_sync(ms)': round(a['sync'], 3),
            'wait_ratio': round(a['wait'] / el, 4) if el else 0,
        })
    ctx.communication_summary = (out, None) if out else (None, '无通信时间统计')
    return ctx.communication_summary


def recipe_hccl_sum(ctx):
    """Top-N communication ops with per-rank split (msprof hccl_sum flavor)."""
    rows = ctx.cur.execute('SELECT rank_id, hccl_op_name, elapsed_time FROM ClusterCommunicationTime')
    per = defaultdict(lambda: defaultdict(lambda: {'elapse': 0.0, 'n': 0}))
    ranks = set()
    for rank, op, elapse in rows:
        if rank is None or not op or op in AGG_ROWS:
            continue
        key = norm_op(op)
        e = per[key][int(rank)]
        e['elapse'] += to_f(elapse)
        e['n'] += 1
        ranks.add(int(rank))
    rank_list = sorted(ranks)
    out = []
    for op, rv in sorted(per.items(), key=lambda kv: -sum(v['elapse'] for v in kv[1].values())):
        total = sum(v['elapse'] for v in rv.values())
        row = {'op': op, 'total_elapse(ms)': round(total, 3), 'instances': sum(v['n'] for v in rv.values())}
        for r in rank_list:
            v = rv.get(r)
            row[f'rank{r}(ms)'] = round(v['elapse'], 3) if v else None
        out.append(row)
        if len(out) >= ctx.top_num:
            break
    return (out, None) if out else (None, '无各 Rank 通信时间统计')


def recipe_communication_matrix_sum(ctx):
    rows = q(ctx.cur, 'SELECT src_rank, dst_rank, transport_type, transit_size, transit_time, '
                      'bandwidth FROM ClusterCommunicationMatrix')
    agg = defaultdict(lambda: {'n': 0, 'size': 0.0, 'time': 0.0, 'bw': []})
    for src, dst, tt, size, t, bw in rows:
        key = (int(src), int(dst), tt)
        a = agg[key]
        a['n'] += 1
        a['size'] += to_f(size)
        a['time'] += to_f(t)
        if to_f(bw) > 0:
            a['bw'].append(to_f(bw))
    out = []
    for (src, dst, tt), a in sorted(agg.items(), key=lambda x: -x[1]['size']):
        out.append({
            'src_rank': src, 'dst_rank': dst, 'transport_type': tt, 'link_count': a['n'],
            'total_transit_size(MB)': round(a['size'], 4),
            'total_transit_time(ms)': round(a['time'], 3),
            'avg_bandwidth(GB/s)': round(sum(a['bw']) / len(a['bw']), 4) if a['bw'] else 0,
            'max_bandwidth(GB/s)': round(max(a['bw']), 4) if a['bw'] else 0,
        })
    return out, None


def recipe_communication_bandwidth_sum(ctx):
    rows = q(ctx.cur, 'SELECT band_type, transit_size, transit_time, bandwidth, '
                      'large_packet_ratio FROM ClusterCommunicationBandwidth')
    agg = defaultdict(lambda: {'n': 0, 'size': 0.0, 'time': 0.0, 'bw': [], 'lpr': []})
    for band, size, t, bw, lpr in rows:
        a = agg[band]
        a['n'] += 1
        a['size'] += to_f(size)
        a['time'] += to_f(t)
        if to_f(bw) > 0:
            a['bw'].append(to_f(bw))
            a['lpr'].append(to_f(lpr))
    out = []
    for band, a in sorted(agg.items(), key=lambda x: -x[1]['size']):
        out.append({
            'band_type': band, 'op_count': a['n'],
            'total_transit_size(MB)': round(a['size'], 4),
            'total_transit_time(ms)': round(a['time'], 3),
            'avg_bandwidth(GB/s)': round(sum(a['bw']) / len(a['bw']), 4) if a['bw'] else 0,
            'max_bandwidth(GB/s)': round(max(a['bw']), 4) if a['bw'] else 0,
            'avg_large_packet_ratio': round(sum(a['lpr']) / len(a['lpr']), 4) if a['lpr'] else 0,
        })
    return out, None


def recipe_pp_chart(ctx):
    rows = q(ctx.cur, 'SELECT step, "index", pp_index, computing, communication_not_overlapped, '
                      'free, stage FROM ClusterStepTraceTime WHERE type = \'rank\' ORDER BY CAST(step AS INTEGER), '
                      '"index"')
    by_stage = defaultdict(lambda: {'computing': [], 'comm': [], 'free': [], 'stage': []})
    for step, rank, pp, comp, comm_no, free, stage in rows:
        s = by_stage[(step, to_f(pp))]
        s['computing'].append(to_f(comp))
        s['comm'].append(to_f(comm_no))
        s['free'].append(to_f(free))
        s['stage'].append(to_f(stage))
    if len({k[1] for k in by_stage}) <= 1:
        return None, '无 PP 并行数据（pp_size=1，各 rank 均为同一流水阶段）'
    out = []
    for (step, pp), s in sorted(by_stage.items(), key=lambda kv: (to_f(kv[0][0]), kv[0][1])):
        n = len(s['stage'])
        out.append({
            'step': step, 'pp_stage': int(pp), 'rank_count': n,
            'avg_computing(ms)': round(sum(s['computing']) / n / 1000, 3),
            'avg_comm_not_overlapped(ms)': round(sum(s['comm']) / n / 1000, 3),
            'avg_free(ms)': round(sum(s['free']) / n / 1000, 3),
            'avg_stage(ms)': round(sum(s['stage']) / n / 1000, 3),
        })
    return out, None


def recipe_slow_rank(ctx):
    tables = {r[0] for r in q(ctx.cur, "SELECT name FROM sqlite_master WHERE type='table'")}
    if 'CommunicationGroupMapping' not in tables:
        return None, '无通信组参与 rank 映射，无法对齐 collective 实例'
    expected = {}
    for rank_set, group_name, pg_name in q(ctx.cur, 'SELECT rank_set, group_name, pg_name FROM CommunicationGroupMapping'):
        members = {int(x) for x in re.findall(r'\d+', str(rank_set))}
        for key in (group_name, pg_name):
            if key and len(members) > 1:
                expected[str(key)] = members
    if not expected:
        return None, '无可用于对齐的通信组参与 rank 映射'
    rows = ctx.cur.execute('SELECT step, hccl_op_name, group_name, rank_id, elapsed_time '
                           'FROM ClusterCommunicationTime ORDER BY step, hccl_op_name, group_name')
    votes = defaultdict(int)
    op_votes = defaultdict(lambda: defaultdict(int))
    for (_, op, group), members in groupby(rows, key=lambda row: row[:3]):
        if not op or op in AGG_ROWS or str(group) not in expected:
            continue
        timings = [(int(rank), to_f(elapse, None)) for _, _, _, rank, elapse in members if rank is not None]
        ranks = {rank for rank, _ in timings}
        if ranks != expected[str(group)] or len(timings) != len(ranks) or any(elapse is None for _, elapse in timings):
            continue
        slow = min(timings, key=lambda row: (row[1], row[0]))[0]
        votes[slow] += 1
        op_votes[op][slow] += 1
    total_votes = sum(votes.values()) or 1
    if not votes:
        return None, '没有参与 rank 完整且通信组、step、实例一致的 collective；慢卡证据不足'
    slow_rank_rows = [{'rank': r, 'votes': v, 'vote_ratio': round(v / total_votes, 4)}
                      for r, v in sorted(votes.items(), key=lambda x: -x[1])]
    slow_op_rows = []
    for op, rv in sorted(op_votes.items(), key=lambda x: -sum(x[1].values())):
        for r, v in sorted(rv.items(), key=lambda x: -x[1]):
            slow_op_rows.append({'op': op, 'rank': r, 'votes': v})
    write_csv(os.path.join(ctx.recipes_dir, 'slow_rank', 'slow_op_stats.csv'), slow_op_rows)
    return slow_rank_rows, None


def recipe_slow_link(ctx):
    matrix, m_reason = recipe_communication_matrix_sum(ctx)
    if not matrix:
        return None, m_reason or '通信矩阵无数据'
    bws = [m['avg_bandwidth(GB/s)'] for m in matrix if m['avg_bandwidth(GB/s)'] > 0]
    if not bws:
        return None, '通信矩阵无带宽数据'
    bws_sorted = sorted(bws)
    p25 = bws_sorted[len(bws) // 4]
    p50 = bws_sorted[len(bws) // 2]
    out = []
    for m in matrix:
        bw = m['avg_bandwidth(GB/s)']
        if bw <= 0:
            continue
        level = ('P3(极慢)' if bw < p25 else 'P2(偏慢)' if bw < p50 else 'P1(正常)')
        out.append({**m, 'link_level': level,
                    'bandwidth_pct': round(bw / bws_sorted[-1], 4) if bws_sorted[-1] else 0})
    out.sort(key=lambda x: x['avg_bandwidth(GB/s)'])
    return out, None


def recipe_communication_bottleneck(ctx):
    time_rows, t_reason = recipe_communication_time_sum(ctx)
    if not time_rows:
        return None, t_reason or '无通信时间汇总数据'
    out = []
    for r in time_rows:
        elapse = r['total_elapse(ms)']
        wait = r['total_wait(ms)']
        transit = r['total_transit(ms)']
        idle = r['total_idle(ms)']
        if elapse <= 0:
            kind = 'no_data'
        elif wait / elapse > 0.5:
            kind = 'wait_dominated(慢卡等待)'
        elif idle / elapse > 0.5:
            kind = 'idle_dominated(空转/链路未用满)'
        elif transit / elapse > 0.5:
            kind = 'transit_dominated(带宽受限)'
        else:
            kind = 'mixed'
        out.append({**r, 'bottleneck_type': kind})
    return out, None


# ---------------- Host 下发类 ----------------

def recipe_cann_api_sum(ctx):
    rank_map = card_paths(ctx)
    per_rank = {}
    for rank in sorted(rank_map):
        path = rank_map[rank]
        if not path:
            continue
        apis = read_csv_rows(os.path.join(path, 'ASCEND_PROFILER_OUTPUT', 'api_statistic.csv'))
        agg = {}
        for r in apis:
            if r.get('Level') != 'acl':
                continue
            agg[r.get('API Name', '')] = {'total_us': to_f(r.get('Time(us)')),
                                          'count': int(to_f(r.get('Count')))}
        per_rank[rank] = agg
    if not per_rank:
        return None, '无 api_statistic.csv（Level=acl）数据'
    out = []
    all_apis = sorted({a for agg in per_rank.values() for a in agg},
                      key=lambda a: -max((per_rank[r][a]['total_us'] for r in per_rank
                                          if a in per_rank[r]), default=0))
    for api in all_apis[:40]:
        row = {'api': api}
        for rank in sorted(per_rank):
            v = per_rank[rank].get(api)
            row[f'rank{rank}_total(ms)'] = round(v['total_us'] / 1000, 3) if v else None
            row[f'rank{rank}_count'] = v['count'] if v else 0
        out.append(row)
    return out, None


def recipe_mstx_sum(ctx):
    agg = defaultdict(lambda: {'total_us': 0.0, 'count': 0})
    found = False
    for rank in sorted(ctx.card_dirs):
        path = os.path.join(ctx.card_dirs[rank], 'ASCEND_PROFILER_OUTPUT', 'operator_details.csv')
        for r in read_csv_rows(path):
            name = r.get('Name', '')
            if 'MSTX' in name.upper():
                found = True
                e = agg[name]
                e['total_us'] += to_f(r.get('Host Total Duration(us)'))
                e['count'] += 1
    if not found:
        return None, '无 MSTX 自定义打点数据（需业务代码插入 mstx 打点）'
    return [{'mstx_op': k, 'total(ms)': round(v['total_us'] / 1000, 3), 'count': v['count']}
            for k, v in sorted(agg.items(), key=lambda kv: -kv[1]['total_us'])], None


def recipe_free_analysis(ctx):
    rows = q(ctx.cur, 'SELECT step, "index", free, computing, communication_not_overlapped, stage '
                      'FROM ClusterStepTraceTime WHERE type = \'rank\' ORDER BY CAST(step AS INTEGER), "index"')
    out = []
    for step, rank, free, comp, comm, stage in rows:
        free = to_f(free)
        stage = to_f(stage)
        out.append({
            'step': step, 'rank': int(rank), 'free(us)': round(free, 1),
            'stage(us)': round(stage, 1),
            'free_ratio': round(free / stage, 4) if stage else 0,
            'free_vs_computing': round(free / to_f(comp), 2) if to_f(comp) else None,
            'potential_gain(%)': round(free / stage * 100, 1) if stage else 0,
        })
    return out, None


# ---------------- 其他 ----------------

def recipe_export_summary(ctx):
    """Export per-card API/kernel top statistics as csv (export_summary flavor)."""
    out_dir = os.path.join(ctx.recipes_dir, 'export_summary')
    os.makedirs(out_dir, exist_ok=True)
    exported = []
    for rank in sorted(ctx.card_dirs):
        apo = os.path.join(ctx.card_dirs[rank], 'ASCEND_PROFILER_OUTPUT')
        apis = read_csv_rows(os.path.join(apo, 'api_statistic.csv'))
        apis.sort(key=lambda r: to_f(r.get('Time(us)')), reverse=True)
        p = os.path.join(out_dir, f'api_top_rank{rank}.csv')
        with open(p, 'w', encoding='utf-8', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['API Name', 'Time(us)', 'Count', 'Avg(us)'])
            w.writeheader()
            for r in apis[:100]:
                w.writerow({'API Name': r.get('API Name'), 'Time(us)': r.get('Time(us)'),
                            'Count': r.get('Count'), 'Avg(us)': r.get('Avg(us)')})
        exported.append(f'api_top_rank{rank}.csv')
    if not exported:
        return None, '无各卡 api_statistic.csv'
    return [{'exported_file': f} for f in exported], None


def recipe_mstx2commop(ctx):
    return None, '依赖 MSTX 通信打点数据，当前数据集未采集'


def recipe_p2p_pairing(ctx):
    rows = q(ctx.cur, "SELECT step, hccl_op_name, src_rank, dst_rank, transport_type, op_name, "
                      "transit_size, transit_time, bandwidth FROM ClusterCommunicationMatrix "
                      "WHERE op_name LIKE '%send%' OR op_name LIKE '%receive%' OR op_name LIKE '%p2p%'")
    out = [{'step': r[0], 'link_op': r[1], 'src_rank': int(to_f(r[2], -1)),
            'dst_rank': int(to_f(r[3], -1)), 'transport_type': r[4], 'op_name': r[5],
            'transit_size(MB)': to_f(r[6]), 'transit_time(ms)': to_f(r[7]),
            'bandwidth(GB/s)': to_f(r[8])} for r in rows]
    if not out:
        return None, '无 P2P（send/receive）通信数据，本数据集为纯集合通信'
    return out, None


# ---------------- 注册表：五大类 recipe 清单（name, desc, func） ----------------

CATEGORIES = [
    ('decomposition_compare', '拆解对比类', [
        ('cluster_time_summary', '提供集群训练过程中迭代耗时的拆解，帮助找到性能瓶颈', recipe_cluster_time_summary),
        ('cluster_time_compare_summary', '集群维度性能数据对比能力，支持标杆数据对比（--bp 参数）', recipe_cluster_time_compare_summary),
        ('module_statistic', '针对 PyTorch 模型自动解析模型层级结构，精准定位性能瓶颈', recipe_module_statistic),
        ('calibrate_npu_gpu', '自动对比 NPU 和 GPU 的性能数据，进行跨平台性能校准和瓶颈分析', recipe_calibrate_npu_gpu),
    ]),
    ('compute', '计算类特性', [
        ('compute_op_sum', 'device 侧运行的计算类算子汇总', recipe_compute_op_sum),
        ('freq_analysis', '识别 AI Core 是否存在空闲（800MHz）或异常频率情况', recipe_freq_analysis),
        ('ep_load_balance', 'moe 负载信息汇总分析', recipe_ep_load_balance),
        ('computational_op_masking', '集群训练中不同算子耗时的掩盖计算，分析线性度', recipe_computational_op_masking),
        ('operator_mfu', '基于算子 FLOPs 和 kernel 耗时，计算 kernel 级和 module 级算力利用率（MFU）', recipe_operator_mfu),
    ]),
    ('communication', '通信类特性', [
        ('communication_group_map', '集群场景通信域与并行策略呈现', recipe_communication_group_map),
        ('communication_time_sum', '集群场景通信时间和带宽汇总分析', recipe_communication_time_sum),
        ('communication_matrix_sum', '集群场景通信矩阵汇总分析', recipe_communication_matrix_sum),
        ('hccl_sum', '通信类算子信息汇总，TopN 数量由 --top-num 控制', recipe_hccl_sum),
        ('pp_chart', 'pp 流水图数据分析，针对 pp 并行各阶段耗时分析与可视化', recipe_pp_chart),
        ('slow_rank', '展示各 rank 快慢卡影响次数，识别慢卡原因', recipe_slow_rank),
        ('slow_link', '集群异常耗时算子汇总分析，识别慢卡', recipe_slow_link),
        ('communication_bottleneck', '对长耗时通信算子识别快慢卡，推测造成通信等待的 Host&Device 侧操作', recipe_communication_bottleneck),
    ]),
    ('host_dispatch', 'Host 下发类特性', [
        ('cann_api_sum', 'CANN 层 API 的汇总', recipe_cann_api_sum),
        ('mstx_sum', 'MSTX 自定义打点汇总', recipe_mstx_sum),
        ('free_analysis', '对 Device 侧大块空闲时间自动分析，识别空闲原因', recipe_free_analysis),
    ]),
    ('other', '其他特性', [
        ('export_summary', '数据导出类：导出各卡 API 统计和 Kernel 详情，生成 csv 文件', recipe_export_summary),
        ('mstx2commop', '数据处理类：将 MSTX 通信打点信息转换成通信算子表格式', recipe_mstx2commop),
        ('p2p_pairing', '数据处理类：为 P2P 算子生成全局关联索引 opConnectionId', recipe_p2p_pairing),
    ]),
]

# 扩展 recipe：随全量执行、产出 csv 并计入状态，但不注册 CATEGORIES
# （不进入五大类能力矩阵汇总，定位见 references/recipes_catalog.md）
EXTRA_RECIPES = [
    ('communication_bandwidth_sum', recipe_communication_bandwidth_sum),
]


# ---------------- output ----------------

def write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not rows:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('')
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def local_card_map(root):
    out = {}
    for dirpath, dirnames, _ in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        if rel.count(os.sep) >= 3:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if not is_junk(d)]
        for d in dirnames:
            if re.match(r'.*_ascend_(pt|ms)$', d):
                cd = os.path.join(dirpath, d)
                rank = None
                for fn in sorted(os.listdir(cd)):
                    m = re.match(r'^profiler_info_(\d+)\.json$', fn)
                    if m:
                        info = read_json(os.path.join(cd, fn))
                        rank = int((info or {}).get('rank_id', m.group(1)))
                        break
                if rank is not None:
                    out[rank] = cd
    return out


def build_summary_md(status, data):
    lines = ['# 集群进阶分析汇总（五大类）', '']
    for cat_key, cat_title, recipes in CATEGORIES:
        done = sum(1 for n, _, _ in recipes if status.get(n, {}).get('status') == 'done')
        lines.append(f'## {cat_title}（{done}/{len(recipes)}）')
        lines.append('')
        lines.append('| 分析能力 | 状态 | 说明 |')
        lines.append('|---|---|---|')
        for name, desc, _ in recipes:
            st = status.get(name, {})
            mark = ('✓ 已执行' if st.get('status') == 'done' else
                    f"✗ {'执行失败' if st.get('status') == 'failed' else '不支持'}：{st.get('reason', '')}")
            lines.append(f'| {name} | {mark} | {desc} |')
        lines.append('')
    ts = data.get('cluster_time_summary') or []
    if ts:
        def unit(value, scale, suffix=''):
            return '—' if value is None else f'{value * scale:.1f}{suffix}'

        steps = sorted({str(t['step']) for t in ts})
        lines.append('## 集群时间总览（cluster_time_summary，按 step × rank）')
        lines.append('')
        lines.append('| step | rank | Stage(ms) | 计算(ms) | 未掩盖通信(ms) | 空闲(ms) | 通信占比 | 空闲占比 |')
        lines.append('|---|---|---|---|---|---|---|---|')
        for r in ts:
            times = [unit(r[key], 0.001) for key in
                     ('stage(us)', 'computing(us)', 'communication_not_overlapped(us)', 'free(us)')]
            ratios = [unit(r[key], 100, '%') for key in ('comm_ratio', 'free_ratio')]
            lines.append(f"| {r['step']} | {r['rank']} | " + ' | '.join(times + ratios) + ' |')
        lines.append('')
        lines.append(f"- 共 {len(steps)} 个 step：{', '.join(steps[:10])}"
                     f"{'…' if len(steps) > 10 else ''}")
        lines.append('')
    slow = data.get('slow_rank') or []
    if slow:
        lines.append('## 慢卡识别（slow_rank 投票）')
        lines.append('')
        lines.append('| rank | 被投票次数 | 占比 |')
        lines.append('|---|---|---|')
        for r in slow:
            lines.append(f"| {r['rank']} | {r['votes']} | {r['vote_ratio']*100:.1f}% |")
        lines.append('')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, help='root used to locate available rank Prof data')
    parser.add_argument('--top-num', type=int, default=20, help='hccl_sum TopN')
    parser.add_argument('--cluster-db', help='existing cluster database, opened read-only')
    parser.add_argument('--step-csv', help='existing cluster_step_trace_time.csv')
    parser.add_argument('--output-dir', help='directory for derived recipe CSV and summaries')
    parser.add_argument('--summary-only', action='store_true', help='generate the core Rank × Step summary only')
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    supplied = bool(args.cluster_db or args.step_csv)
    output = Path(args.output_dir or Path(root) / 'cluster_analysis_output').resolve()
    if supplied:
        sources = [Path(path).resolve() for path in (args.cluster_db, args.step_csv) if path]
        if not args.output_dir or any(output == path.parent for path in sources):
            parser.error('specify an --output-dir outside the supplied cluster export')
        signatures = source_signature(args.cluster_db, args.step_csv)
        conn = open_db(args.cluster_db)
    else:
        if args.summary_only:
            parser.error('--summary-only requires --cluster-db or --step-csv')
        db = os.path.join(root, 'cluster_analysis_output', 'cluster_analysis.db')
        if not os.path.isfile(db) or os.path.getsize(db) == 0:
            print(f'ERROR: {db} not found; run cluster analysis first', file=sys.stderr)
            sys.exit(1)
        conn = sqlite3.connect(db)
    cur = conn.cursor()
    output.mkdir(parents=True, exist_ok=True)
    recipes_dir = str(output / 'recipes')
    ctx = Ctx(cur, local_card_map(root), root, recipes_dir, top_num=args.top_num, supplied=supplied)

    status = {}   # name -> {'status': 'done'|'unsupported', 'rows': N, 'reason': str}
    data = {}     # name -> rows (for summary json)
    tables = db_tables(conn)
    quality = base_info(conn, tables)
    summary_path = output / 'recipes_summary.json'
    steps = read_steps(conn, tables, args.step_csv, quality)
    install_steps(conn, steps)
    missing_columns = {key for _, _, values in steps for key, value in values.items() if value is None}
    time_summary, _ = recipe_cluster_time_summary(ctx)
    base_summary = {'analysis_scope': quality.get('analysis_scope'), 'time_summary': time_summary,
                    'step_metrics_normalized': True, 'categories': []}
    if supplied:
        base_summary['source_signature'] = signatures
    # Publish the core report input first so an optional recipe can time out independently.
    write_json(summary_path, base_summary)
    if args.summary_only:
        conn.close()
        return
    comparison_columns = {'computing', 'communication_not_overlapped', 'free'}
    required_columns = {
        'cluster_time_compare_summary': comparison_columns,
        'pp_chart': comparison_columns | {'pp_index'},
        'computational_op_masking': {'overlapped', 'communication', 'computing'},
        'free_analysis': {'free'},
    }

    def execute(name, func):
        absent = required_columns.get(name, set()) & missing_columns
        if absent:
            status[name] = {'status': 'unsupported',
                            'reason': '集群摘要缺少字段：' + ', '.join(sorted(absent))}
            return
        try:
            rows, reason = (time_summary, None) if name == 'cluster_time_summary' else func(ctx)
        except Exception as exc:
            unavailable = supplied and isinstance(exc, sqlite3.OperationalError) and str(exc).startswith(
                ('no such table:', 'no such column:'))
            if not unavailable:
                traceback.print_exc()
            status[name] = {'status': 'unsupported' if unavailable else 'failed',
                            'reason': f'{type(exc).__name__}: {exc}'}
            return
        if rows is None:
            status[name] = {'status': 'unsupported', 'reason': reason or ''}
            return
        status[name] = {'status': 'done', 'rows': len(rows)}
        data[name] = rows
        write_csv(os.path.join(recipes_dir, name, f'{name}.csv'), rows)

    # 统一调度：遍历注册表逐 recipe 执行，单个失败不阻断整体
    for cat_key, cat_title, recipes in CATEGORIES:
        for name, desc, func in recipes:
            execute(name, func)

    # 扩展 recipe：与注册表同协议执行，但不进入能力矩阵（见 recipes_catalog.md）
    for name, func in EXTRA_RECIPES:
        execute(name, func)

    md = build_summary_md(status, data)
    md_path = output / 'recipes_summary.md'
    md_path.write_text(md, encoding='utf-8')

    categories_json = []
    for cat_key, cat_title, recipes in CATEGORIES:
        categories_json.append({
            'key': cat_key, 'title': cat_title,
            'recipes': [{'name': n, 'desc': d, **status.get(n, {'status': 'unsupported'})}
                        for n, d, _ in recipes],
        })
    summary = {
        **base_summary,
        'categories': categories_json,
        'recipes_done': [n for n, s in status.items() if s['status'] == 'done'],
        'recipes_unsupported': {n: s.get('reason') for n, s in status.items()
                                if s['status'] == 'unsupported'},
        'recipes_failed': {n: s.get('reason') for n, s in status.items() if s['status'] == 'failed'},
        'top_comm_by_type': communication_tops(data.get('communication_time_sum', []),
                                               'op', 'total_elapse(ms)')[0],
        'slow_rank': (data.get('slow_rank') or [])[:5],
        'top_bottleneck_ops': (data.get('communication_bottleneck') or [])[:10],
        'free_analysis': data.get('free_analysis', []),
        'hccl_sum': (data.get('hccl_sum') or [])[:10],
        'module_statistic': (data.get('module_statistic') or [])[:15],
        'cann_api_sum': (data.get('cann_api_sum') or [])[:10],
        'freq_analysis': (data.get('freq_analysis') or [])[:8],
        'masking': (data.get('computational_op_masking') or [])[:10],
        'pp_chart': (data.get('pp_chart') or [])[:10],
    }
    write_json(summary_path, summary)
    if not supplied:
        cur.execute('CREATE TABLE IF NOT EXISTS RecipeSummary (recipe_name TEXT PRIMARY KEY, rows INTEGER)')
        cur.execute('DELETE FROM RecipeSummary')
        cur.executemany('INSERT OR REPLACE INTO RecipeSummary VALUES (?, ?)',
                        [(n, s.get('rows', 0)) for n, s in status.items() if s['status'] == 'done'])
        conn.commit()
    conn.close()

    done = len(summary['recipes_done'])
    total = sum(len(rs) for _, _, rs in CATEGORIES) + len(EXTRA_RECIPES)
    print(f'recipes done: {done}/{total} -> {recipes_dir}')
    print(f'summary: {md_path}')
    if data.get('slow_rank'):
        s = data['slow_rank'][0]
        print(f"slow rank: rank {s['rank']} (vote {s['vote_ratio']*100:.0f}%)")
    if summary['recipes_failed']:
        sys.exit(2)


if __name__ == '__main__':
    main()
