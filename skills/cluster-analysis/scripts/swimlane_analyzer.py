#!/usr/bin/env python3
"""Phase 5: swimlane operator statistics per card + cross-card comparison.

Lanes mirror MindStudio Insight's trace_view.json timeline:
  - Thread lanes: Host 侧线程（Python 进程 = cpu_op 算子 aten::/aclnn*；
    CANN 进程 = AscendCL@ API）。同名线程按进程区分，如 Python/Thread 13811。
  - Stream lanes: Device 侧流（kernel、EVENT_*/NOTIFY_* 等流上算子）。
  - Communication Group lanes: 通信域泳道（非 Plane），如 Group group_name_37
    Communication -> group_name_37，算子为 hcom_* 通信算子。
  Plane 子泳道、Overlap Analysis 总览泳道（Computing/Free/...）、AI Core Freq
  泳道不参与统计。

Data source priority: trace_view.json (streaming parse, never whole-load) >
kernel_details.csv/operator_details.csv/api_statistic.csv (degraded type-based
lanes, marked source=fallback).

Per lane: longest-duration op + full op aggregation table with
名称/持续时间(ms)/自用时间(ms)/平均/最大/最小/发生次数. 自用时间 = 持续时间 -
被包含子算子时间（栈式区间嵌套扣减；叶子节点自用=持续时间）。

Multi-card: --compare-dir aligns lanes BY NAME and produces swimlane_compare.md.
"""
import argparse
import csv
import json
import os
import re
import sys

from lib.common import iter_csv, read_csv_rows, to_f, us_ms
from lib.config import COMM_NAME_PATTERN

COLS = ['名称', '持续时间(ms)', '自用时间(ms)', '平均持续时间(ms)', '最大持续时间(ms)',
        '最小持续时间(ms)', '发生次数']
LANE_TYPE_TITLES = [
    ('thread', '线程泳道（Thread）'),
    ('stream', '流泳道（Stream）'),
    ('comm', '通信域泳道（Communication，非 Plane）'),
    ('type', '算子类型泳道（降级模式：无 trace_view.json）'),
]
THREAD_RE = re.compile(r'^Thread\s+\d+$')
STREAM_RE = re.compile(r'^Stream\s+\d+$')
GROUP_RE = re.compile(r'^Group\s+(.+)\s+Communication$')
PLANE_RE = re.compile(r'^Plane\s+\d+$')
SKIP_LANE_NAMES = {'Communication', 'Communication(Not Overlapped)', 'Computing',
                   'Free', 'Stage', 'Bubble', 'Preparing'}
COUNTED_CATS = ('', 'cpu_op')

# ---- degraded (CSV) lane defs, same as before ----
CORE_COMPUTE = {'AI_CORE', 'AI_VECTOR_CORE', 'MIX_AIC', 'MIX_AIV'}
FALLBACK_LANES = {
    'compute': '计算算子（AI Core / Vector / MIX）',
    'ai_cpu': 'AI CPU 算子',
    'comm': '通信算子',
    'host_api': 'Host CANN API',
    'pytorch_op': 'PyTorch 算子（Host 侧）',
}

# ---------------- trace_view.json streaming ----------------

def iter_trace_events(path):
    """Stream Chrome-trace events from trace_view.json without whole-loading."""
    dec = json.JSONDecoder()
    with open(path, encoding='utf-8') as f:
        head = f.read(4096)
        i = head.find('[')
        if i < 0:
            return
        f.seek(i + 1)
        buf = ''
        while True:
            buf = buf.lstrip(' \n\r\t,')
            if not buf:
                chunk = f.read(1 << 20)
                if not chunk:
                    return
                buf = chunk
                continue
            if buf[0] == ']':
                return
            try:
                obj, idx = dec.raw_decode(buf)
            except json.JSONDecodeError:
                chunk = f.read(1 << 20)
                if not chunk:
                    return
                buf += chunk
                continue
            yield obj
            buf = buf[idx:]


def classify_lane(thread_name, process_name):
    """-> (type, display_name) or None (skip lane).

    Communication 进程下除 Plane/汇总泳道外的所有泳道均视为通信域
    （Group group_name_X Communication -> group_name_X；dp:xx 等命名原样保留）。
    """
    if thread_name is None:
        return None
    if PLANE_RE.match(thread_name):
        return None
    if thread_name in SKIP_LANE_NAMES:
        return None
    if process_name == 'Communication':
        m = GROUP_RE.match(thread_name)
        return 'comm', (m.group(1) if m else thread_name)
    if THREAD_RE.match(thread_name):
        prefix = process_name if process_name else 'Thread'
        return 'thread', f'{prefix}/{thread_name}'
    if STREAM_RE.match(thread_name):
        return 'stream', thread_name
    return None


def lane_stats_from_events(events):
    """events: [(ts, dur, name)]. Stack-based nesting -> per-op stats.

    自用时间 = 持续时间 - 直接子算子时长之和（仅扣栈顶直接父级，
    避免跨代重复扣减）。
    """
    events.sort(key=lambda e: (e[0], -(e[0] + e[1])))
    stats = {}
    stack = []
    longest = None  # (dur, name)
    for ts, dur, name in events:
        if dur < 0:
            continue
        while stack and stack[-1][0] <= ts:
            stack.pop()
        if stack:
            stack[-1][1]['self'] -= dur
        e = stats.setdefault(name, {'total': 0.0, 'self': 0.0, 'count': 0,
                                    'max': 0.0, 'min': float('inf')})
        e['total'] += dur
        e['self'] += dur
        e['count'] += 1
        e['max'] = max(e['max'], dur)
        e['min'] = min(e['min'], dur)
        if longest is None or dur > longest[0]:
            longest = (dur, name)
        stack.append([ts + dur, e])
    for e in stats.values():
        if e['min'] == float('inf'):
            e['min'] = 0
        e['self'] = max(e['self'], 0.0)
    return stats, longest


def analyze_trace(tv_path):
    """Returns lanes list for trace-based analysis, or None on failure.

    Metadata (thread/process names) sits at the END of traceEvents, so events
    are collected first and lanes classified afterwards.
    """
    thread_names = {}
    proc_names = {}
    lane_events = {}   # (pid, tid) -> [(ts, dur, name)], counted cats only
    n_events = 0
    try:
        for ev in iter_trace_events(tv_path):
            ph = ev.get('ph')
            if ph == 'M':
                mname = ev.get('name')
                if mname == 'thread_name':
                    thread_names[(ev.get('pid'), ev.get('tid'))] = \
                        (ev.get('args') or {}).get('name')
                elif mname == 'process_name':
                    proc_names[ev.get('pid')] = (ev.get('args') or {}).get('name')
                continue
            if ev.get('dur') is None:
                continue
            cat = ev.get('cat') or ''
            if cat not in COUNTED_CATS:
                continue
            key = (ev.get('pid'), ev.get('tid'))
            lst = lane_events.get(key)
            if lst is None:
                lst = lane_events[key] = []
            lst.append((to_f(ev.get('ts')), to_f(ev.get('dur')), ev.get('name') or ''))
            n_events += 1
    except Exception as exc:
        print(f'WARN: trace_view.json parse failed ({exc}); fallback to CSV lanes',
              file=sys.stderr)
        return None

    if n_events == 0:
        return None
    lanes = []
    for key, evs in lane_events.items():
        if not evs:
            continue
        meta = classify_lane(thread_names.get(key), proc_names.get(key[0]))
        if meta is None:
            continue
        ltype, name = meta
        stats, longest = lane_stats_from_events(evs)
        lanes.append(build_lane(ltype, name, stats, longest))
    lanes.sort(key=lambda l: (l['type'], -l['total_us']))
    return lanes


def build_lane(ltype, name, stats, longest):
    ops = []
    total = 0.0
    count = 0
    for op_name, e in stats.items():
        total += e['total']
        count += e['count']
        ops.append({
            '名称': op_name,
            '持续时间(ms)': us_ms(e['total']),
            '自用时间(ms)': us_ms(e['self']),
            '平均持续时间(ms)': us_ms(e['total'] / e['count']) if e['count'] else 0,
            '最大持续时间(ms)': us_ms(e['max']),
            '最小持续时间(ms)': us_ms(e['min']),
            '发生次数': e['count'],
        })
    ops.sort(key=lambda r: r['持续时间(ms)'], reverse=True)
    longest_row = None
    if longest:
        e = stats.get(longest[1])
        if e:
            longest_row = {
                '名称': longest[1],
                '持续时间(ms)': us_ms(e['total']),
                '自用时间(ms)': us_ms(e['self']),
                '平均持续时间(ms)': us_ms(e['total'] / e['count']) if e['count'] else 0,
                '最大持续时间(ms)': us_ms(e['max']),
                '最小持续时间(ms)': us_ms(e['min']),
                '发生次数': e['count'],
            }
    return {'type': ltype, 'name': name, 'op_kinds': len(stats), 'calls': count,
            'total_us': round(total, 1), 'longest': longest_row, 'ops': ops}


# ---------------- degraded CSV lanes ----------------

def lane_of_kernel(name, core):
    if COMM_NAME_PATTERN.search(name) or core == 'COMMUNICATION':
        return 'comm'
    if core in CORE_COMPUTE:
        return 'compute'
    if core == 'AI_CPU':
        return 'ai_cpu'
    return None


def analyze_csv(card_dir):
    apo = os.path.join(card_dir, 'ASCEND_PROFILER_OUTPUT')
    lanes = {k: {} for k in FALLBACK_LANES}
    longest = {k: None for k in FALLBACK_LANES}

    for r in iter_csv(os.path.join(apo, 'kernel_details.csv')):
        name = r.get('Name', '')
        lane = lane_of_kernel(name, r.get('Accelerator Core', ''))
        if lane is None:
            continue
        dur = to_f(r.get('Duration(us)'))
        e = lanes[lane].setdefault(name, {'total': 0.0, 'self': 0.0, 'count': 0,
                                          'max': 0.0, 'min': float('inf')})
        e['total'] += dur
        e['self'] += dur
        e['count'] += 1
        e['max'] = max(e['max'], dur)
        e['min'] = min(e['min'], dur)
        if longest[lane] is None or dur > longest[lane][0]:
            longest[lane] = (dur, name)

    for r in read_csv_rows(os.path.join(apo, 'api_statistic.csv')):
        api = r.get('API Name', '')
        if not api:
            continue
        t = to_f(r.get('Time(us)'))
        cnt = int(to_f(r.get('Count')))
        e = lanes['host_api'].setdefault(api, {'total': 0.0, 'self': 0.0, 'count': 0,
                                               'max': 0.0, 'min': float('inf')})
        e['total'] += t
        e['self'] += t
        e['count'] += cnt
        e['max'] = max(e['max'], to_f(r.get('Max(us)')) or t / max(cnt, 1))
        e['min'] = min(e['min'], to_f(r.get('Min(us)')) if to_f(r.get('Min(us)'))
                       else t / max(cnt, 1))
        avg = t / max(cnt, 1)
        if longest['host_api'] is None or avg > longest['host_api'][0]:
            longest['host_api'] = (avg, api)

    for r in read_csv_rows(os.path.join(apo, 'operator_details.csv')):
        name = r.get('Name', '')
        if not name:
            continue
        total = to_f(r.get('Device Total Duration(us)')) or \
            to_f(r.get('Host Total Duration(us)'))
        self_us = to_f(r.get('Device Self Duration(us)')) or \
            to_f(r.get('Host Self Duration(us)'))
        if total <= 0:
            continue
        e = lanes['pytorch_op'].setdefault(name, {'total': 0.0, 'self': 0.0, 'count': 0,
                                                  'max': 0.0, 'min': float('inf')})
        e['total'] += total
        e['self'] += self_us
        e['count'] += 1
        e['max'] = max(e['max'], total)
        e['min'] = min(e['min'], total)
        if longest['pytorch_op'] is None or total > longest['pytorch_op'][0]:
            longest['pytorch_op'] = (total, name)

    out = []
    for key, title in FALLBACK_LANES.items():
        if not lanes[key]:
            continue
        out.append(build_lane('type', title, lanes[key], longest[key]))
    return out


# ---------------- output ----------------

def md_table(cols, rows, max_rows=None):
    lines = ['| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
    shown = rows[:max_rows] if max_rows else rows
    for r in shown:
        lines.append('| ' + ' | '.join(str(r.get(c, '')) for c in cols) + ' |')
    if max_rows and len(rows) > max_rows:
        lines.append(f'| … 共 {len(rows)} 行，完整数据见 json |' + ' |' * (len(cols) - 1))
    return '\n'.join(lines)


def write_card_md(result, out_dir):
    rank = result['rank']
    lanes = result['lanes']
    total_all = sum(l['total_us'] for l in lanes)
    lines = [f'# 泳道算子统计 — Rank {rank}', '',
             f'- 数据目录：`{result["dir"]}`',
             f'- 数据源：{result["source"]}',
             f'- 泳道总数：{len(lanes)}（Thread / Stream / 通信域，跳过 Plane 与总览泳道）',
             f'- 全泳道总耗时：{us_ms(total_all)} ms', '',
             '## 泳道总览', '',
             '| 类型 | 泳道 | 算子种类 | 总次数 | 总持续时间(ms) | 占比 |',
             '|---|---|---|---|---|---|']
    for l in lanes:
        share = l['total_us'] / total_all * 100 if total_all else 0
        lines.append(f"| {l['type']} | {l['name']} | {l['op_kinds']} | {l['calls']} | "
                     f"{us_ms(l['total_us'])} | {share:.1f}% |")

    for ltype, title in LANE_TYPE_TITLES:
        group = [l for l in lanes if l['type'] == ltype]
        if not group:
            continue
        lines += ['', f'## {title}', '']
        for l in group:
            lines += [f'### {l["name"]}', '', '持续时间最长的算子：', '']
            if l['longest']:
                lines.append(md_table(COLS, [l['longest']]))
            lines += ['', f'全部算子（共 {l["op_kinds"]} 种，按持续时间降序 Top 30）：', '']
            lines.append(md_table(COLS, l['ops'], max_rows=30))
            lines.append('')
    lines.append('')

    md_path = os.path.join(out_dir, f'swimlane_rank{rank}.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    data = {'rank': rank, 'dir': result['dir'], 'source': result['source'],
            'total_us': round(total_all, 1), 'lanes': lanes}
    json_path = os.path.join(out_dir, f'swimlane_rank{rank}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return md_path, json_path


def write_compare_md(swimlane_dir):
    files = sorted(f for f in os.listdir(swimlane_dir)
                   if f.startswith('swimlane_rank') and f.endswith('.json'))
    if len(files) < 2:
        return None
    cards = []
    for fn in files:
        with open(os.path.join(swimlane_dir, fn), encoding='utf-8') as f:
            cards.append(json.load(f))
    ranks = [c['rank'] for c in cards]

    lines = ['# 跨卡泳道算子比对（按泳道名对齐）', '',
             f'- 参与比对：rank {", ".join(str(r) for r in ranks)}',
             '- 泳道口径：Thread / Stream / 通信域（非 Plane），与单卡泳道统计一致', '']

    # 1. lane-level overview aligned by name
    lane_map = {}
    for c in cards:
        for l in c.get('lanes', []):
            lane_map.setdefault((l['type'], l['name']), {})[c['rank']] = l
    lines += ['## 1. 泳道级总览比对', '',
              '| 类型 | 泳道 | ' + ' | '.join(f'rank{r} 总时长(ms)' for r in ranks) +
              ' | 差异 |', '|---|---|' + '---|' * (len(ranks) + 1)]
    for (ltype, name), per_rank in sorted(lane_map.items()):
        vals = [per_rank[r]['total_us'] / 1000 if r in per_rank else None for r in ranks]
        present = [v for v in vals if v is not None]
        cells = [f'{v:.1f}' if v is not None else '—' for v in vals]
        if len(present) >= 2 and min(present) > 0:
            diff = f'{(max(present) - min(present)) / min(present) * 100:+.1f}%'
        else:
            diff = '独有' if len(present) == 1 else 'N/A'
        lines.append(f'| {ltype} | {name} | ' + ' | '.join(cells) + f' | {diff} |')
    lines.append('')

    # 2. biggest per-op diffs across all lanes
    merged = []
    for (ltype, name), per_rank in lane_map.items():
        ops = {}
        for r in ranks:
            for row in (per_rank.get(r) or {}).get('ops', []):
                ops.setdefault(row['名称'], {})[r] = row
        for op, per in ops.items():
            totals = [per.get(r, {}).get('持续时间(ms)', 0) for r in ranks]
            if max(totals) == 0:
                continue
            spread = max(totals) - min(totals)
            if spread <= 0:
                continue
            merged.append({
                '类型': ltype, '泳道': name, '名称': op,
                **{f'rank{r} 持续时间(ms)': per.get(r, {}).get('持续时间(ms)', 0)
                   for r in ranks},
                **{f'rank{r} 次数': per.get(r, {}).get('发生次数', 0) for r in ranks},
                '差异(ms)': round(spread, 3),
                '差异率': (f'{spread / min(t for t in totals if t > 0) * 100:.1f}%'
                          if any(t > 0 for t in totals) else 'N/A'),
            })
    merged.sort(key=lambda x: x['差异(ms)'], reverse=True)
    if merged:
        cols = ['类型', '泳道', '名称'] + [f'rank{r} 持续时间(ms)' for r in ranks] + \
               [f'rank{r} 次数' for r in ranks] + ['差异(ms)', '差异率']
        lines += ['## 2. 差异最大的算子 Top 30（跨全部泳道）', '',
                  md_table(cols, merged, max_rows=30), '']
    else:
        lines += ['## 2. 差异最大的算子', '', '各泳道算子完全一致，无差异。', '']

    # 3. longest op side by side for common lanes
    lines += ['## 3. 各泳道"持续时间最长算子"并排比对', '',
              '| 类型 | 泳道 | ' + ' | '.join(f'rank{r} 最长算子' for r in ranks) + ' |',
              '|---|---|' + '---|' * len(ranks)]
    for (ltype, name), per_rank in sorted(lane_map.items()):
        cells = []
        for r in ranks:
            lg = (per_rank.get(r) or {}).get('longest')
            cells.append(f"{lg['名称']}（{lg['最大持续时间(ms)']}ms × {lg['发生次数']}）"
                         if lg else '—')
        lines.append(f'| {ltype} | {name} | ' + ' | '.join(cells) + ' |')
    lines.append('')

    path = os.path.join(swimlane_dir, 'swimlane_compare.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--card', help='single card dir')
    parser.add_argument('--rank', help='rank id')
    parser.add_argument('--output', help='output dir for per-card results')
    parser.add_argument('--compare-dir', help='dir containing swimlane_rank*.json; '
                                              'build swimlane_compare.md')
    args = parser.parse_args()

    if args.compare_dir:
        path = write_compare_md(args.compare_dir)
        print(f'compare md: {path}' if path else 'need >=2 swimlane json files')
        return

    if not (args.card and args.output and args.rank is not None):
        print('ERROR: --card/--rank/--output required (or --compare-dir)', file=sys.stderr)
        sys.exit(1)

    card = os.path.abspath(args.card)
    apo = os.path.join(card, 'ASCEND_PROFILER_OUTPUT')
    if not os.path.isdir(apo):
        print(f'ERROR: ASCEND_PROFILER_OUTPUT not found: {card}', file=sys.stderr)
        sys.exit(1)

    tv_path = os.path.join(apo, 'trace_view.json')
    lanes = None
    source = 'fallback (csv)'
    if os.path.isfile(tv_path) and os.path.getsize(tv_path) > 0:
        lanes = analyze_trace(tv_path)
        if lanes:
            source = f'trace_view.json ({os.path.getsize(tv_path)/1e6:.0f}MB, 流式解析)'
    if lanes is None:
        lanes = analyze_csv(card)
        if not lanes:
            print(f'ERROR: no usable data (trace_view.json and csv both empty): {card}',
                  file=sys.stderr)
            sys.exit(1)

    result = {'rank': args.rank, 'dir': card, 'source': source, 'lanes': lanes}
    os.makedirs(args.output, exist_ok=True)
    md_path, json_path = write_card_md(result, args.output)
    print(f'swimlane md: {md_path}')
    print(f'swimlane json: {json_path}')
    print(f'source: {source}')
    for ltype, title in LANE_TYPE_TITLES:
        group = [l for l in lanes if l['type'] == ltype]
        if group:
            print(f'  {ltype}: {len(group)} lanes, '
                  f'{us_ms(sum(l["total_us"] for l in group))}ms total')


if __name__ == '__main__':
    main()
