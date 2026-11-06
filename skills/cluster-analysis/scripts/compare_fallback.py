#!/usr/bin/env python3
"""Phase 4 fallback: compare the max/min communication-ratio cards.

Selects baseline (min comm ratio) and compare (max comm ratio) cards from
step_trace_time.csv, then builds msprof-compare-equivalent results:
performance_comparison_result_{compare}_{base}.xlsx + compare_analysis_result.json
(prof-compare style middleware with insights).

xlsx 列布局对齐原生 msprof-analyze compare 输出（vendor prof-compare 按固定列下标
解析，schema 不一致会导致列错位/整表解析为 0）。
"""
import argparse
import csv
import json
import os
import re
import sys

from lib.common import is_junk, read_csv_rows, read_json as _read_json, to_f
from lib.config import AGG_ROWS, COMM_NAME_PATTERN
from lib import prof_data
from lib import analysis_scope

CARD_DIR_PATTERN = re.compile(r'.*_ascend_(pt|ms)$')


def read_json(path):
    """历史行为：缺失/损坏返回 {}（其余脚本为 None），经 lib 显式 default 保持。"""
    return _read_json(path, default={})


def find_cards(root):
    """收集可比较的卡：TEXT step CSV 优先，缺失时回退 analysis.db StepTraceTime。

    采集窗行（NULL step）使用 wN 标签参与窗口对齐比较；scope 标记随卡返回，
    结论须按 step / capture_window 分别解释。单位 us（两来源同口径）。
    """
    from detect_prof import find_card_dirs
    cards = find_card_dirs(root)
    out = []
    for cd in sorted(cards):
        apo = os.path.join(cd, 'ASCEND_PROFILER_OUTPUT')
        st = analysis_scope.load_steps(apo)
        if not st:
            continue
        scope, step_source = analysis_scope.scope_of(st), st[0]['_source']
        rank = None
        for fn in sorted(os.listdir(cd)):
            m = re.match(r'^profiler_info_(\d+)\.json$', fn)
            if m:
                info = read_json(os.path.join(cd, fn))
                rank = int(info.get('rank_id', m.group(1)))
                break
        agg = {}
        for key in ('Computing', 'Communication(Not Overlapped)', 'Communication', 'Free', 'Stage'):
            values = [analysis_scope.number(row.get(key)) for row in st]
            agg[key] = sum(values) / len(values) if all(v is not None for v in values) else None
        # Selecting by communication ratio requires an actual numerator and denominator.
        if agg['Stage'] is None or agg['Stage'] <= 0 or agg['Communication(Not Overlapped)'] is None:
            continue
        out.append({'dir': cd, 'apo': apo, 'rank': rank if rank is not None else len(out),
                    'trace': agg, 'comm_ratio': agg['Communication(Not Overlapped)'] / agg['Stage']
                    if agg['Stage'] else 0, 'steps': len(st),
                    'step_ids': sorted(str(r.get('Step')) for r in st),
                    'scope': scope, 'step_source': step_source})
    out.sort(key=lambda c: c['rank'])
    return out


def avg_step_trace(card):
    return card['trace']


def compare_overall(base, comp):
    dims = [('E2E Time', 'Stage'), ('Computing Time', 'Computing'),
            ('Uncovered Communication Time', 'Communication(Not Overlapped)'),
            ('Free Time', 'Free')]
    rows, insights = [], []
    stage_b, stage_c = base['trace']['Stage'], comp['trace']['Stage']
    for label, key in dims:
        b_us, c_us = base['trace'][key], comp['trace'][key]
        if b_us is None or c_us is None:
            continue
        b, c = b_us / 1000, c_us / 1000
        ratio = (c - b) / b if b else None
        # 列序对齐 vendor overall_metrics.py: 0 维度名, 1-3 base duration(ms)/
        # ratio/number, 4-6 comp 同, 7 diff(ms), 8 diff_ratio; Diff(ms) 为附加列。
        # 模板按 ms 渲染 OverallMetrics（step_trace_time.csv 源值为 us，需 /1000）
        rows.append({'Dimension': label,
                     'Baseline(ms)': round(b, 2),
                     'Baseline Ratio(%)': round(b_us / stage_b * 100, 2) if stage_b else 0,
                     'Baseline Number': '-',
                     'Compare(ms)': round(c, 2),
                     'Compare Ratio(%)': round(c_us / stage_c * 100, 2) if stage_c else 0,
                     'Compare Number': '-',
                     'Diff Duration(ms)': round(c - b, 2),
                     'Diff Ratio': round(ratio, 4) if ratio is not None else '',
                     'Diff(ms)': round(c - b, 3)})
        if ratio is not None and abs(ratio) > 0.01:
            insights.append({'dimension': label, 'diff_ms': round(c - b, 3),
                             'diff_ratio': round(ratio, 4),
                             'direction': 'degraded' if ratio > 0 else 'improved'})
    insights.sort(key=lambda x: -abs(x['diff_ms']))
    return rows, insights


def compare_op_statistic(base, comp):
    def agg(card):
        out = {}
        for r in read_csv_rows(os.path.join(card['apo'], 'op_statistic.csv')):
            out[r.get('OP Type', '')] = {'total': to_f(r.get('Total Time(us)')),
                                         'count': int(to_f(r.get('Count'))),
                                         'avg': to_f(r.get('Avg Time(us)')),
                                         'max': to_f(r.get('Max Time(us)'))}
        return out
    a, b = agg(base), agg(comp)
    rows = []
    for op in set(a) | set(b):
        va, vb = a.get(op), b.get(op)
        t_base = va['total'] if va else 0
        t_comp = vb['total'] if vb else 0
        diff = t_comp - t_base
        ratio = diff / t_base if t_base else None
        # 列序对齐 vendor operator.py: 0 No., 1 算子名, 2-3 base duration(ms)/calls,
        # 4-5 comp 同, 6 diff(ms), 7 diff_ratio; is_comm 为附加列
        rows.append({'No.': len(rows) + 1,
                     'Op Type': op,
                     'Baseline Total Time(ms)': round(t_base / 1000, 3),
                     'Baseline Calls': va['count'] if va else 0,
                     'Compare Total Time(ms)': round(t_comp / 1000, 3),
                     'Compare Calls': vb['count'] if vb else 0,
                     'Diff Duration(ms)': round(diff / 1000, 3),
                     'Diff Ratio': round(ratio, 4) if ratio is not None else 'NEW',
                     'is_comm': bool(COMM_NAME_PATTERN.search(op))})
    rows.sort(key=lambda r: r['Diff Duration(ms)'], reverse=True)
    return rows


def compare_kernel(base, comp):
    if not all(os.path.isfile(os.path.join(c['apo'], 'kernel_details.csv')) for c in (base, comp)):
        return []  # Unavailable on either side; do not fabricate a one-sided regression.
    def agg(card):
        out = {}
        with open(os.path.join(card['apo'], 'kernel_details.csv'), encoding='utf-8',
                  errors='replace') as f:
            for r in csv.DictReader(f):
                name = r.get('Name', '')
                d = to_f(r.get('Duration(us)'))
                shape = r.get('Input Shapes') or r.get('Input Shape') or r.get('Shape') or ''
                dtype = r.get('Input Data Types') or r.get('Input Data Type') or ''
                key = (name, shape, dtype, r.get('Accelerator Core', ''))
                e = out.setdefault(key, {'total': 0.0, 'count': 0, 'max': 0.0,
                                          'min': float('inf'),
                                          'core': r.get('Accelerator Core', ''),
                                          'shape': shape, 'dtype': dtype})
                e['total'] += d
                e['count'] += 1
                e['max'] = max(e['max'], d)
                e['min'] = min(e['min'], d)
                if not e['shape']:
                    e['shape'] = (r.get('Input Shapes') or r.get('Input Shape')
                                  or r.get('Shape') or '')
        for e in out.values():
            if e['min'] == float('inf'):
                e['min'] = 0
        return out
    a, b = agg(base), agg(comp)
    rows = []
    for key in sorted(set(a) | set(b)):
        name = key[0]
        va, vb = a.get(key), b.get(key)
        t_base = va['total'] if va else 0
        t_comp = vb['total'] if vb else 0
        diff = t_comp - t_base
        ratio = diff / t_base if t_base else None
        b_avg = round(va['total'] / va['count'], 1) if va else 0
        c_avg = round(vb['total'] / vb['count'], 1) if vb else 0
        # 列序对齐 vendor kernel.py parse_compare: 0 No., 1 Kernel Name, 2 Input Shape,
        # 3-6 base total/avg/max/min(us), 7 base_calls, 8-11 comp 同, 12 comp_calls,
        # 13 total_ratio, 14 avg_ratio; Core Type/Diff Total 等为附加列
        rows.append({'No.': len(rows) + 1,
                     'Kernel Name': name,
                     'Input Shape': (va or vb or {}).get('shape', ''),
                     'Baseline Total(us)': round(t_base, 1),
                     'Baseline Avg(us)': b_avg,
                     'Baseline Max(us)': round(va['max'], 1) if va else 0,
                     'Baseline Min(us)': round(va['min'], 1) if va else 0,
                     'Baseline Calls': va['count'] if va else 0,
                     'Compare Total(us)': round(t_comp, 1),
                     'Compare Avg(us)': c_avg,
                     'Compare Max(us)': round(vb['max'], 1) if vb else 0,
                     'Compare Min(us)': round(vb['min'], 1) if vb else 0,
                     'Compare Calls': vb['count'] if vb else 0,
                     'Total Ratio': round(t_comp / t_base, 4) if t_base else 'NEW',
                     'Avg Ratio': round(c_avg / b_avg, 4) if b_avg else 'NEW',
                     'Core Type': (va or vb)['core'],
                     'Diff Total(us)': round(diff, 1),
                     'Diff Total Ratio': round(ratio, 4) if ratio is not None else 'NEW',
                     'is_comm': bool(COMM_NAME_PATTERN.search(name))})
        rows[-1]['Input Data Type'] = (va or vb)['dtype']
    rows.sort(key=lambda r: r['Diff Total(us)'], reverse=True)
    return rows


def compare_api(base, comp):
    def agg(card):
        out = {}
        for r in read_csv_rows(os.path.join(card['apo'], 'api_statistic.csv')):
            out[r.get('API Name', '')] = {'total': to_f(r.get('Time(us)')),
                                          'count': int(to_f(r.get('Count')))}
        return out
    a, b = agg(base), agg(comp)
    rows = []
    for api in set(a) | set(b):
        va, vb = a.get(api), b.get(api)
        t_base = va['total'] if va else 0
        t_comp = vb['total'] if vb else 0
        b_calls = va['count'] if va else 0
        c_calls = vb['count'] if vb else 0
        b_avg = round(t_base / b_calls, 3) if b_calls else 0
        c_avg = round(t_comp / c_calls, 3) if c_calls else 0
        # 列序对齐 vendor api_compare.py: 0 No., 1 API 名, 2-5 base total/self/avg(ms)/
        # calls, 6-9 comp 同, 10-13 total/self/avg/calls_ratio; Diff(ms) 为附加列
        # （api_statistic.csv 无 self 耗时，self=total）
        rows.append({'No.': len(rows) + 1,
                     'API Name': api,
                     'Baseline Total(ms)': round(t_base / 1000, 3),
                     'Baseline Self(ms)': round(t_base / 1000, 3),
                     'Baseline Avg(ms)': round(t_base / 1000 / b_calls, 3) if b_calls else 0,
                     'Baseline Calls': b_calls,
                     'Compare Total(ms)': round(t_comp / 1000, 3),
                     'Compare Self(ms)': round(t_comp / 1000, 3),
                     'Compare Avg(ms)': round(t_comp / 1000 / c_calls, 3) if c_calls else 0,
                     'Compare Calls': c_calls,
                     'Total Ratio': round(t_comp / t_base, 4) if t_base else 'NEW',
                     'Self Ratio': round(t_comp / t_base, 4) if t_base else 'NEW',
                     'Avg Ratio': round(c_avg / b_avg, 4) if b_avg else 'NEW',
                     'Calls Ratio': round(c_calls / b_calls, 4) if b_calls else 'NEW',
                     'Diff(ms)': round((t_comp - t_base) / 1000, 3)})
    rows.sort(key=lambda r: r['Diff(ms)'], reverse=True)
    return rows


def compare_communication(base, comp):
    def agg(card):
        cj = read_json(os.path.join(card['apo'], 'communication.json'))
        out = {}
        if cj:
            for step, groups in cj.items():
                for gtype in ('collective', 'p2p'):
                    for op_key, info in (groups.get(gtype) or {}).items():
                        name = op_key.split('@')[0]
                        if name in AGG_ROWS:
                            continue
                        ti = info.get('Communication Time Info', {})
                        e = out.setdefault(name, {'total': 0.0, 'wait': 0.0, 'transit': 0.0,
                                                  'count': 0, 'max': 0.0, 'min': float('inf')})
                        ms = to_f(ti.get('Elapse Time(ms)'))
                        e['total'] += ms
                        e['max'] = max(e['max'], ms)
                        e['min'] = min(e['min'], ms)
                        e['wait'] += to_f(ti.get('Wait Time(ms)'))
                        e['transit'] += to_f(ti.get('Transit Time(ms)'))
                        e['count'] += 1
            return out
        # communication.json 缺失：回退 analysis.db CommAnalyzerTime（同为 ms）
        for r in prof_data.read_comm_time(card['apo']):
            name = str(r['op'] or '').split('@')[0]
            if not name or name in AGG_ROWS:
                continue
            e = out.setdefault(name, {'total': 0.0, 'wait': 0.0, 'transit': 0.0,
                                      'count': 0, 'max': 0.0, 'min': float('inf')})
            ms = to_f(r['elapse_ms'])
            e['total'] += ms
            e['max'] = max(e['max'], ms)
            e['min'] = min(e['min'], ms)
            e['wait'] += to_f(r['wait_ms'])
            e['transit'] += to_f(r['transit_ms'])
            e['count'] += 1
        for e in out.values():
            if e['min'] == float('inf'):
                e['min'] = 0
        return out
    a, b = agg(base), agg(comp)
    rows = []
    for op in set(a) | set(b):
        va, vb = a.get(op), b.get(op)
        t_base = va['total'] if va else 0
        t_comp = vb['total'] if vb else 0
        b_calls = va['count'] if va else 0
        c_calls = vb['count'] if vb else 0
        # 列序对齐 vendor communication.py: 0 No., 1 Comm Op, 2 Task Name(空=汇总行),
        # 3-7 base calls/total/avg/max/min(us), 8-12 comp 同, 13-14 附加位,
        # 15 diff(us), 16 diff_ratio。源 communication.json 为 ms，模板按 us 渲染，需 x1000
        rows.append({'No.': len(rows) + 1,
                     'Comm Op': op,
                     'Task Name': '',
                     'Baseline Calls': b_calls,
                     'Baseline Total(us)': round(t_base * 1000, 1),
                     'Baseline Avg(us)': round(t_base * 1000 / b_calls, 1) if b_calls else 0,
                     'Baseline Max(us)': round(va['max'] * 1000, 1) if va else 0,
                     'Baseline Min(us)': round(va['min'] * 1000, 1) if va else 0,
                     'Compare Calls': c_calls,
                     'Compare Total(us)': round(t_comp * 1000, 1),
                     'Compare Avg(us)': round(t_comp * 1000 / c_calls, 1) if c_calls else 0,
                     'Compare Max(us)': round(vb['max'] * 1000, 1) if vb else 0,
                     'Compare Min(us)': round(vb['min'] * 1000, 1) if vb else 0,
                     'Diff(ms)': round(t_comp - t_base, 3),
                     'is_comm': True,
                     'Diff Duration(us)': round((t_comp - t_base) * 1000, 1),
                     'Diff Ratio': round((t_comp - t_base) / t_base, 4) if t_base else 'NEW',
                     'Baseline Wait(ms)': round(va['wait'], 3) if va else 0,
                     'Compare Wait(ms)': round(vb['wait'], 3) if vb else 0,
                     'Baseline Transit(ms)': round(va['transit'], 3) if va else 0,
                     'Compare Transit(ms)': round(vb['transit'], 3) if vb else 0})
    rows.sort(key=lambda r: r['Diff(ms)'], reverse=True)
    return rows


def build_insights(overall_rows, op_rows, kernel_rows, api_rows, comm_rows):
    insights = {'overall': [], 'operator': {}, 'kernel': {}, 'api': {}, 'communication': {}}

    degraded = [r for r in overall_rows if isinstance(r['Diff Ratio'], float) and r['Diff Ratio'] > 0]
    improved = [r for r in overall_rows if isinstance(r['Diff Ratio'], float) and r['Diff Ratio'] < 0]
    def dim_insight(row):
        return {'dimension': row['Dimension'], 'diff_ms': row['Diff(ms)'],
                'diff_ratio': row['Diff Ratio']}

    insights['overall'] = {
        'degraded_max': dim_insight(degraded[0]) if degraded else None,
        'improved_max': dim_insight(improved[0]) if improved else None,
        'rows': overall_rows,
    }

    comp_ops = [r for r in op_rows if not r['is_comm']]
    top_degraded = [r for r in comp_ops if r['Diff Duration(ms)'] > 0][:10]
    total_degraded = sum(r['Diff Duration(ms)'] for r in comp_ops
                         if r['Diff Duration(ms)'] > 0)
    top10_share = (sum(r['Diff Duration(ms)'] for r in top_degraded) / total_degraded
                   if total_degraded > 0 else None)
    insights['operator'] = {
        'top_degraded': top_degraded,
        'top_improved': [r for r in comp_ops if r['Diff Duration(ms)'] < 0][:5],
        'degradation_concentration_top10': round(top10_share, 3) if top10_share is not None else None,
        'note': '劣化是否集中于少数算子' if top10_share is not None else '',
    }

    comp_kernels = [r for r in kernel_rows if not r['is_comm']]
    sig_degraded = [r for r in comp_kernels
                    if isinstance(r['Diff Total Ratio'], float) and r['Diff Total Ratio'] > 0.05
                    and r['Diff Total(us)'] > 0]
    comm_kernels = [r for r in kernel_rows if r['is_comm']]
    lb_rows = [r for r in comp_kernels
               if min(r['Baseline Calls'], r['Compare Calls']) > 10
               and r['Baseline Calls'] and r['Compare Calls']]
    load_imbalance = [r for r in lb_rows
                      if max(r['Baseline Calls'], r['Compare Calls']) /
                      min(r['Baseline Calls'], r['Compare Calls']) > 2]
    insights['kernel'] = {
        'significant_degraded_count': len(sig_degraded),
        'significant_degraded_top10': sig_degraded[:10],
        'comm_kernel_top10': comm_kernels[:10],
        'load_imbalance_kernels': load_imbalance[:10],
    }

    insights['api'] = {
        'top_degraded': [r for r in api_rows if r['Diff(ms)'] > 0][:10],
        'top_improved': [r for r in api_rows if r['Diff(ms)'] < 0][:5],
    }

    insights['communication'] = {
        'top_degraded': [r for r in comm_rows if r['Diff(ms)'] > 0][:10],
        'top_improved': [r for r in comm_rows if r['Diff(ms)'] < 0][:5],
        'wait_split_note': 'Wait 上升=到达时间差异；Transit 上升=数据量或带宽变化',
    }
    return insights


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--base-rank', type=int, default=None, help='override baseline rank')
    parser.add_argument('--compare-rank', type=int, default=None, help='override compare rank')
    parser.add_argument('--json-only', action='store_true',
                        help='仅生成 compare_analysis_result.json 中间件（跳过 xlsx 与 CSV mirrors），'
                             '供原生 compare 流程补产，避免覆盖原生 xlsx')
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    cards = find_cards(root)
    if len(cards) < 2:
        print('ERROR: need >=2 cards with step/window summary '
              '(step_trace_time.csv or analysis.db StepTraceTime)', file=sys.stderr)
        sys.exit(1)

    by_ratio = sorted(cards, key=lambda c: (c['comm_ratio'], c['trace']['Communication(Not Overlapped)']))
    min_card, max_card = by_ratio[0], by_ratio[-1]
    if args.base_rank is not None:
        cand = [c for c in cards if c['rank'] == args.base_rank]
        if not cand:
            print(f"ERROR: --base-rank {args.base_rank} not found; "
                  f"valid ranks: {[c['rank'] for c in cards]}", file=sys.stderr)
            sys.exit(1)
        min_card = cand[0]
    if args.compare_rank is not None:
        cand = [c for c in cards if c['rank'] == args.compare_rank]
        if not cand:
            print(f"ERROR: --compare-rank {args.compare_rank} not found; "
                  f"valid ranks: {[c['rank'] for c in cards]}", file=sys.stderr)
            sys.exit(1)
        max_card = cand[0]

    print(f"baseline(min comm): rank {min_card['rank']} comm_ratio={min_card['comm_ratio']:.4f}")
    print(f"compare(max comm):  rank {max_card['rank']} comm_ratio={max_card['comm_ratio']:.4f}")
    if min_card['rank'] == max_card['rank']:
        print('ERROR: baseline and compare must be different ranks', file=sys.stderr)
        sys.exit(1)
    if min_card['scope'] != max_card['scope']:
        print('ERROR: compare requires matching analysis scopes; '
              'whole-prof synthetic steps cannot be compared to training steps', file=sys.stderr)
        sys.exit(1)
    if min_card['step_ids'] != max_card['step_ids']:
        print('ERROR: compare requires identical step windows; select/export aligned ranks', file=sys.stderr)
        sys.exit(1)

    overall_rows, overall_insights = compare_overall(min_card, max_card)
    op_rows = compare_op_statistic(min_card, max_card)
    kernel_rows = compare_kernel(min_card, max_card)
    api_rows = compare_api(min_card, max_card)
    comm_rows = compare_communication(min_card, max_card)
    insights = build_insights(overall_rows, op_rows, kernel_rows, api_rows, comm_rows)

    os.makedirs(args.output, exist_ok=True)
    tag = f"{max_card['rank']}_{min_card['rank']}"

    # xlsx (msprof-compare style)；--json-only 模式跳过，保护原生 compare 产物
    if not args.json_only:
        try:
            import pandas as pd
            xlsx_path = os.path.join(args.output, f'performance_comparison_result_{tag}.xlsx')
            with pd.ExcelWriter(xlsx_path, engine='openpyxl') as w:
                # sheet 名含 minimal 可让 vendor overall_metrics 解析器返回
                # has_minimal_warning=False，避免假的 Not minimal profiling 警告
                # （注意 Excel sheet 名上限 31 字符）
                pd.DataFrame(overall_rows).to_excel(
                    w, sheet_name='OverallMetrics(minimal)', index=False)
                pd.DataFrame(op_rows).to_excel(w, sheet_name='OperatorCompareStatistic', index=False)
                pd.DataFrame(kernel_rows).to_excel(w, sheet_name='KernelCompare', index=False)
                pd.DataFrame(api_rows).to_excel(w, sheet_name='ApiCompare', index=False)
                pd.DataFrame(comm_rows).to_excel(w, sheet_name='CommunicationCompare', index=False)
            print(f'xlsx: {xlsx_path}')
        except ImportError:
            xlsx_path = None
            print('openpyxl/pandas unavailable; skip xlsx')

        # CSV mirrors
        csv_dir = os.path.join(args.output, 'csv')
        os.makedirs(csv_dir, exist_ok=True)
        for name, rows in (('overall_metrics', overall_rows), ('operator_statistic', op_rows),
                           ('kernel_compare', kernel_rows), ('api_compare', api_rows),
                           ('communication_compare', comm_rows)):
            write_csv_file(os.path.join(csv_dir, f'{name}.csv'), rows)
    else:
        print('json-only: 跳过 xlsx 与 CSV mirrors（原生 compare 产物保持不变）')

    # middleware json (prof-compare style)
    scopes = {min_card.get('scope'), max_card.get('scope')}
    middleware = {
        'warnings': ([] if all(os.path.isfile(os.path.join(c['apo'], 'kernel_details.csv')) for c in (min_card, max_card))
                     else ['kernel comparison unavailable: kernel_details.csv missing on one or both ranks'])
                    + (['整个 prof 作为一个汇总 step（prof）；按各卡采集范围比较，'
                        '标签相同不证明时窗、请求数量和负载一致；不能解释为单次迭代吞吐']
                       if scopes == {'whole_prof'} else [])
                    + (['比较口径为采集窗（capture window）：step 标识为 wN 派生标签，'
                        '不是训练 step；结论不能按迭代吞吐解释']
                       if scopes == {'capture_window'} else []),
        'unavailable_dimensions': [key for key in ('Computing', 'Free', 'Communication')
                                   if min_card['trace'].get(key) is None or max_card['trace'].get(key) is None],
        'step_ids': min_card['step_ids'],
        'step_scope': next(iter(scopes)) if len(scopes) == 1 else 'mixed',
        'synthetic_step': scopes == {'whole_prof'},
        'base_card': {'rank': min_card['rank'], 'dir': min_card['dir'],
                      'comm_ratio': round(min_card['comm_ratio'], 4),
                      'scope': min_card.get('scope', 'step'),
                      'step_source': min_card.get('step_source', 'step_trace_time.csv')},
        'compare_card': {'rank': max_card['rank'], 'dir': max_card['dir'],
                         'comm_ratio': round(max_card['comm_ratio'], 4),
                         'scope': max_card.get('scope', 'step'),
                         'step_source': max_card.get('step_source', 'step_trace_time.csv')},
        'overall_metrics': overall_rows,
        'insights': insights,
    }
    json_path = os.path.join(args.output, 'compare_analysis_result.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(middleware, f, ensure_ascii=False, indent=2, default=str)

    print(f'middleware: {json_path}')
    if overall_insights:
        print('overall dimension diffs: ' + '; '.join(
            f"{i['dimension']} {i['direction']} {i['diff_ratio']*100:+.1f}%"
            for i in overall_insights[:4]))


def write_csv_file(path, rows):
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


if __name__ == '__main__':
    main()
