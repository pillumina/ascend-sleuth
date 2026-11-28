"""Bounded power/cpu_idle intervals and fixed-window idle residency (stdlib only).

The state number identifies a C-state, never an idle percentage. An initial
unknown interval, a malformed transition, or loss remains unknown, not zero.
"""
import math
from collections import defaultdict
from .evidence import capabilities


def analyze_idle(m, events):
    start, end = m.get('t_start', 0.), m.get('t_end', 0.)
    window = max(0., end - start)
    grouped = defaultdict(list)
    invalid = 0
    unknown = 'UNKNOWN'
    for event in events:
        if event.etype != 'cpu_idle':
            continue
        cpu = None
        try:
            cpu = int(event.fields.get('cpu_id', event.cpu))
            state = int(str(event.fields.get('state')), 0)
            if cpu < 0 or state < -1:
                raise ValueError('invalid idle state or CPU')
            if start <= event.ts <= end:
                grouped[cpu].append((event.ts, state))
        except (TypeError, ValueError):
            invalid += 1
            if cpu is not None and cpu >= 0 and start <= event.ts <= end:
                grouped[cpu].append((event.ts, unknown))
    cpus = sorted(set(m.get('per_cpu', {})) | set(grouped))
    loss = bool(m.get('buffer_overrun') or not m.get('events_ok', True))
    bucket = max(1., window / 600.)
    count = max(1, int(math.ceil(window / bucket)))
    result, unmatched = [], invalid
    for cpu in cpus:
        intervals = []
        previous = None
        cpu_unmatched = 0
        for timestamp, raw in sorted(grouped[cpu], key=lambda row: row[0]):
            state = None if raw in (-1, 4294967295, 18446744073709551615) else raw
            if previous is not None:
                t0, old = previous
                # Two entries or two exits imply a missing transition. Preserve
                # the gap instead of attributing the whole interval to a state.
                valid = old != unknown and (state == unknown or (old is None) != (state is None))
                if not valid:
                    cpu_unmatched += 1
                if timestamp > t0:
                    intervals.append({'start': t0, 'end': timestamp,
                                      'idle': old is not None if valid else None,
                                      'state': old if valid else None})
            previous = (timestamp, state)
        if previous is not None and previous[0] < end:
            intervals.append({'start': previous[0], 'end': end,
                              'idle': None if previous[1] == unknown else previous[1] is not None,
                              'state': None if previous[1] == unknown else previous[1],
                              'boundary_censored': True})
        unmatched += cpu_unmatched
        durations = defaultdict(float)
        idle_sec = known = 0.
        for part in intervals:
            dt = max(0., min(end, part['end']) - max(start, part['start']))
            if part['idle'] is not None:
                known += dt
                if part['idle']:
                    idle_sec += dt
                    durations[part['state']] += dt
        observed_bins, asleep_bins = [0.]*count, [0.]*count
        for part in intervals:
            if part['idle'] is None:
                continue
            first = max(0, int((max(start,part['start'])-start)//bucket))
            last = min(count, int(math.ceil((min(end,part['end'])-start)/bucket)))
            for index in range(first,last):
                lo,hi=start+index*bucket,min(end,start+(index+1)*bucket)
                overlap=max(0.,min(hi,part['end'])-max(lo,part['start']))
                observed_bins[index] += overlap
                if part['idle']: asleep_bins[index] += overlap
        series = []
        for index in range(count):
            lo, hi = start + index * bucket, min(end, start + (index + 1) * bucket)
            observed,asleep=observed_bins[index],asleep_bins[index]
            value = 100. * asleep / (hi-lo) if hi > lo and observed >= hi-lo-1e-9 and not loss else None
            series.append([lo, value])
        ratio = 100. * idle_sec / window if window and known >= window-1e-9 and not loss and not invalid else None
        result.append({'cpu': cpu, 'residency_percent': ratio, 'idle_sec': idle_sec,
                       'known_sec': known, 'coverage_percent': 100.*known/window if window else 0.,
                       'idle_lower_bound_percent': 100.*idle_sec/window if window and known else None,
                       'states': [{'state': state, 'residency_sec': duration,
                                   'window_percent': 100.*duration/window if window else None}
                                  for state, duration in sorted(durations.items())],
                       'series': series, 'intervals': intervals, 'unpaired_events': cpu_unmatched})
    cap = capabilities(m.get('snapshot', {})).get('events', {}).get('power/cpu_idle', {})
    available = any(grouped.values())
    status = 'TRACE_AVAILABLE' if available else ('UNSUPPORTED' if cap.get('exists') is False else 'NO_EVENTS')
    reasons = []
    if not available:
        reasons.append('没有可用 power/cpu_idle 事件；sched_switch 空闲率另见核心负载，不能冒充 C-state residency。')
    if loss or unmatched:
        reasons.append('丢失/无效/未配对事件使区间不完整；未知区间为 N/A，不填零。')
    return {'available': available, 'status': status, 'source': 'ftrace:power/cpu_idle',
            'reliability': 'PARTIAL' if loss or unmatched else 'BOUNDED_TRACE_INTERVALS',
            'window': [start, end], 'bucket_sec': bucket, 'cpus': result,
            'per_cpu_ratio': {p['cpu']: p['residency_percent'] for p in result},
            'unpaired_events': unmatched, 'reasons': reasons,
            'note': 'Idle Residency = 已配对/边界限定 idle 持续时间 / 对应时间窗 × 100%；C-state编号不是比例。初始状态未知；最后状态仅延续至采集边界。整窗有未知区间则整窗比例为N/A，另列已知idle时间下界。'}
