"""CPUFreq policy analysis; standard tracepoint/sysfs frequencies use kHz.

scaling_cur_freq normally describes a requested P-state, not a measured clock.
A trace sample applies from its timestamp forward; no guessed initial state.
"""
import re
from .evidence import read_json, read_jsonl, cpulist, capabilities


def to_mhz(value, unit='kHz'):
    try:
        result = float(value) * {'Hz': 1e-6, 'kHz': 1e-3, 'MHz': 1.0}[unit]
        return result if 0 < result < 1e7 else None
    except (TypeError, ValueError, KeyError):
        return None


def _summary(series, end, reference, start=0.):
    # A sample applies forward only, clipped to the actual acquisition window.
    # None explicitly interrupts a state after an invalid/missing sample.
    original = sorted({float(t): v for t, v in series}.items())
    clipped = []
    for i, (ts, value) in enumerate(original):
        stop = original[i+1][0] if i+1 < len(original) else end
        if start <= ts <= end:
            clipped.append((ts, value))
        elif ts < start < stop:
            clipped.append((start, value))
    weighted = total = low = 0.0
    for i, (ts, value) in enumerate(clipped):
        stop = min(end, clipped[i+1][0]) if i+1 < len(clipped) else end
        dt = max(0.0, stop - ts)
        if value is None:
            continue
        total += dt
        weighted += value * dt
        if reference and value <= .5 * reference:
            low += dt
    vals = [v for _, v in clipped if v is not None]
    return {'average_mhz': weighted / total if total else None,
            'minimum_mhz': min(vals) if vals else None,
            'highest_mhz': max(vals) if vals else None,
            'low_frequency_ratio': 100 * low / total if reference and total else None,
            'observed_sec': total, 'observation_end': end, 'series': [[t, v] for t, v in clipped],
            'sample_count': sum(start <= t <= end and v is not None for t, v in original)}


def analyze_frequency(m, events):
    snap = m.get('snapshot', {})
    raw_start = read_json(snap, 'frequency_start.json', {})
    raw_finish = read_json(snap, 'frequency_end.json', {})
    samples, malformed = read_jsonl(snap, 'frequency_samples.jsonl')
    shape_errors = []
    def policies(blob, label):
        if not isinstance(blob, dict) or not isinstance(blob.get('policies', []), list):
            shape_errors.append(label + ': policies应为列表')
            return []
        valid = []
        for item in blob.get('policies', []):
            try:
                if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']:
                    raise ValueError('缺少策略域ID')
                cpus = sorted(cpulist(item.get('cpus', item.get('related_cpus'))))
                if any(c < 0 for c in cpus):
                    raise ValueError('CPU编号无效')
                valid.append(dict(item, cpus=cpus))
            except (TypeError, ValueError):
                shape_errors.append(label + ': 策略域记录/CPU列表无效')
        return valid
    begin_policies, end_policies = policies(raw_start, 'frequency_start'), policies(raw_finish, 'frequency_end')
    try:
        cap = capabilities(snap).get('events', {}).get('power/cpu_frequency', {})
        if not isinstance(cap, dict): cap = {}
    except (AttributeError, TypeError):
        cap = {}
    domains, aliases, cpu_sets = {}, {}, {}
    def register(p):
        key = p['id']
        group = tuple(p.get('cpus', []))
        canonical = cpu_sets.get(group, key) if group else aliases.get(key, key)
        aliases[key] = canonical
        if group: cpu_sets[group] = canonical
        domains.setdefault(canonical, dict(p, id=canonical))
        return canonical
    for p in begin_policies + end_policies: register(p)
    finish = {aliases.get(p['id'], p['id']): p for p in end_policies}
    trace_clock = str(snap.get('hostbound/trace_clock.txt', m.get('metadata', {}).get('trace_clock', ''))).strip()
    sample_clocks = {str(row.get('clock', 'monotonic')) for row in samples if isinstance(row, dict)}
    clock_matches = ((trace_clock in ('mono', 'monotonic') and sample_clocks <= {'monotonic'}) or
                     (trace_clock == 'boot' and sample_clocks == {'boottime'}))
    alignment = 'MONOTONIC' if clock_matches else ('INCOMPATIBLE' if trace_clock else 'UNVERIFIED')
    # Older collector archives: static fields only; never invent dynamic samples.
    if not domains:
        for path, field, value in re.findall(r'(/sys/devices/system/cpu/cpu\d+/cpufreq)/(\w+):\s*(\S+)', snap.get('cpufreq.txt', '')):
            c = int(re.search(r'/cpu(\d+)/', path).group(1))
            p = domains.setdefault('cpu%d' % c, {'id': 'cpu%d' % c, 'cpus': [c], 'unit': 'kHz'})
            p[field] = value
    cpu_domain = {c: key for key, p in domains.items() for c in cpulist(p.get('cpus', p.get('related_cpus')))}
    trace = {}
    trace_errors = []
    trace_event_count=0; invalid_trace_samples=0
    for ev in events:
        if ev.etype != 'cpu_frequency':
            continue
        trace_event_count+=1
        try:
            c = int(ev.fields.get('cpu_id'))  # emitting CPU may differ from the affected CPU
        except (TypeError, ValueError):
            invalid_trace_samples+=1
            trace_errors.append({'timestamp':ev.ts,'cpu_id':ev.fields.get('cpu_id'),
                                 'state':ev.fields.get('state'),'policy':None,'reason':'cpu_id无效'})
            continue
        key = cpu_domain.get(c, 'cpu%d' % c)
        domains.setdefault(key, {'id': key, 'cpus': [c], 'unit': 'kHz'})
        value = to_mhz(ev.fields.get('state'), ev.fields.get('unit', m.get('metadata', {}).get('frequency_trace_unit', 'kHz')))
        if value is not None:
            trace.setdefault(key, []).append((ev.ts, value))
        else:
            trace.setdefault(key, []).append((ev.ts, None))
            invalid_trace_samples+=1
            trace_errors.append({'timestamp':ev.ts,'cpu_id':c,'state':ev.fields.get('state'),
                                 'unit':ev.fields.get('unit',m.get('metadata',{}).get('frequency_trace_unit','kHz')),
                                 'policy':key,'reason':'频率值或单位无效'})
    sysfs = {}
    for index, row in enumerate(samples):
        for p in policies(row, 'frequency_samples[%d]' % index):
            key = aliases.get(p['id']) or register(p)
            field = 'cpuinfo_cur_freq' if to_mhz(p.get('cpuinfo_cur_freq'), p.get('unit', 'kHz')) else 'scaling_cur_freq'
            value = to_mhz(p.get(field), p.get('unit', 'kHz'))
            ts = row.get('ts')
            if not isinstance(ts, (float, int)) or not (-1e18 < ts < 1e18):
                shape_errors.append('frequency_samples[%d]: 单调时间戳无效' % index)
                continue
            sysfs.setdefault(key, []).append((ts, value))
    loss = bool(m.get('buffer_overrun') or not m.get('events_ok', True) or malformed or invalid_trace_samples or shape_errors)
    valid_trace = any(v is not None for points in trace.values() for _,v in points)
    if valid_trace:
        event_status = 'TRACE_AVAILABLE'
    elif invalid_trace_samples:
        event_status = 'COLLECTION_FAILED'
    elif cap.get('enabled') and loss:
        event_status = 'COLLECTION_FAILED'
    elif cap.get('enabled'):
        event_status = 'NO_TRANSITION'
    elif cap.get('exists') is False:
        event_status = 'UNSUPPORTED'
    elif cap.get('requested') is False or str(m.get('metadata', {}).get('minimal_mode', '')) == '1':
        event_status = 'NOT_REQUESTED'
    elif cap.get('requested') and not cap.get('enabled'):
        event_status = 'COLLECTION_FAILED'
    else:
        event_status = 'UNKNOWN'
    result = []
    for key, p in sorted(domains.items()):
        endp = finish.get(key, p)
        unit = endp.get('unit', 'kHz')
        reference = to_mhz(endp.get('cpuinfo_max_freq'), unit)
        series = trace.get(key, [])
        usable_trace = any(value is not None for _,value in series)
        source = 'ftrace:power/cpu_frequency' if usable_trace else 'sysfs'
        if not usable_trace:
            series = sysfs.get(key, []) if alignment != 'INCOMPATIBLE' else []
        end = m.get('t_end', 0.) if usable_trace else min(m.get('t_end', 0.), max([t for t, _ in series] or [m.get('t_start', 0.)]))
        summary = _summary(series, end, reference, m.get('t_start', 0.))
        current = to_mhz(endp.get('cpuinfo_cur_freq'), unit) or to_mhz(endp.get('scaling_cur_freq'), unit)
        summary.update({'id': key, 'cpus': sorted(cpulist(p.get('cpus', p.get('related_cpus')))),
                        'current_mhz': current, 'maximum_mhz': reference,
                        'scaling_min_mhz': to_mhz(endp.get('scaling_min_freq'), unit),
                        'scaling_max_mhz': to_mhz(endp.get('scaling_max_freq'), unit),
                        'governor': endp.get('scaling_governor'), 'source': source,
                        'static_start': p, 'static_end': endp, 'errors':endp.get('errors',{}),
                        'reliability': 'PARTIAL' if loss else ('CLOCK_UNVERIFIED' if source == 'sysfs' and alignment == 'UNVERIFIED' else 'REQUESTED_OR_DRIVER_REPORTED'),
                        'clock_alignment': 'TRACE_CLOCK' if usable_trace else alignment, 'raw_sysfs_samples': sysfs.get(key, []),
                        'raw_trace_errors': [error for error in trace_errors if error['policy']==key],
                        'reference': 'cpuinfo_max_freq; low <= 50% (经验阈值)' if reference else None})
        result.append(summary)
    dynamic = any(p['sample_count'] >= 2 and p['observed_sec'] > 0 for p in result if p['source'] == 'sysfs')
    static = any(any(to_mhz(p.get(k)) is not None for k in ('scaling_cur_freq', 'cpuinfo_cur_freq', 'cpuinfo_max_freq', 'scaling_max_freq')) for p in domains.values())
    status = 'TRACE_AVAILABLE' if valid_trace else ('SYSFS_AVAILABLE' if dynamic else ('STATIC_ONLY' if static or sysfs else event_status))
    if status in ('UNKNOWN', 'NOT_REQUESTED'):
        status = 'UNSUPPORTED' if cap.get('exists') is False else 'COLLECTION_FAILED'
    reasons = [cap['error']] if cap.get('error') else []
    reasons.extend(shape_errors)
    if invalid_trace_samples: reasons.append('%d条频率trace事件无效；原值与原因保留在raw_trace_errors，存在有效sysfs时按策略域降级。' % invalid_trace_samples)
    if malformed: reasons.append('frequency_samples含%d行无效JSON' % malformed)
    if sysfs and alignment == 'UNVERIFIED': reasons.append('旧包未记录trace_clock；sysfs单调时钟与trace对齐未经核验。')
    if sysfs and alignment == 'INCOMPATIBLE': reasons.append('trace_clock=%s与sysfs样本时钟%s不同域；不叠加时间线、不计算采集窗口平均；原始样本仍保留。' % (trace_clock, ','.join(sorted(map(str, sample_clocks)))))
    if event_status == 'NO_TRANSITION':
        reasons.append('事件已启用，窗口无频率转换；不代表降频或频率不可用。')
    if event_status == 'NOT_REQUESTED':
        reasons.append('精简/配置模式未请求频率事件。')
    if loss:
        reasons.append('事件丢失/解析不完整；不能断言采集窗口没有转换。')
    if not cap and not valid_trace:
        reasons.append('旧采集包未记录频率事件能力，支持情况未知。')
    return {'status': status, 'event_status': event_status, 'capability': cap, 'domains': result,
            'sample_count': sum(p['sample_count'] for p in result), 'trace_event_count':trace_event_count, 'invalid_trace_samples':invalid_trace_samples, 'raw_trace_errors':trace_errors, 'reasons': reasons,
            'window': [m.get('t_start'), m.get('t_end')], 'clock_alignment': alignment, 'invalid_sidecar_records': len(shape_errors)+malformed,
            'note': 'ftrace/scaling_cur_freq 表示驱动报告或请求频率；cpuinfo_cur_freq 为硬件反馈（如实现）。均不等同于已验证的PMU实测频率。',
            'pmu': {'status': 'NOT_VALIDATED', 'reason': '未运行 perf；cycles/ref-cycles 需验证事件语义、参考频率、同域权限和 multiplexing，ARM64 不保证存在 ref-cycles。'}}


def legacy_frequency(frequency):
    """Compatibility view in explicit MHz; policy aggregates remain unique above."""
    per = {}
    for p in frequency['domains']:
        if p['average_mhz'] is None:
            continue
        for c in p['cpus']:
            per[c] = {'min': p['minimum_mhz'], 'avg': p['average_mhz'], 'max': p['highest_mhz'],
                      'low_ratio': p['low_frequency_ratio'], 'unit': 'MHz', 'policy': p['id']}
    return {'per_cpu': per, 'available': bool(per), 'unit': 'MHz'}
