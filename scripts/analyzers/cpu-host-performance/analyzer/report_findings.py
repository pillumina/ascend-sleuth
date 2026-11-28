"""Plain-language findings for the core-problems area in section one."""
from dataclasses import dataclass
from html import escape

from .diagnosis import SEVERITY_RANK, THRESHOLDS
from .npu_affinity import cpu_list


@dataclass
class Finding:
    diagnosis_types: tuple
    status: str
    title: str
    evidence: str
    action: str
    retest: str
    binding_preflight: bool = False

    def html(self, severity, severity_label):
        action = escape(self.action)
        if self.binding_preflight:
            action += ' <a href="#sec-3">查看绑核配置</a>'
        return ('<article class="card diagnosis-item"><h4><span class="diagnosis-status diagnosis-%s">%s · %s</span> %s</h4>'
                '<p>%s</p><p><b>先做什么</b> %s</p><p><b>如何复测</b> %s</p></article>'
                % (escape(severity.lower()), escape(severity_label), escape(self.status), escape(self.title),
                   escape(self.evidence), action, escape(self.retest)))


def _window_text(start, end, origin):
    return '采集开始后 %.3f–%.3f 秒' % (start - origin, end - origin)


def _waiting_finding(m, candidates):
    sched = m.get('sched', {})
    p99, count = sched.get('lat_p99'), sched.get('lat_count') or 0
    above_threshold = p99 is not None and count and p99 >= THRESHOLDS['lat_p99_warn_ms']
    wait_evidence = ('%d 次有效记录中，99%% 的唤醒等待约在 %.2f ms 以内，达到 %.0f ms 的经验关注线。'
                     % (count, p99, THRESHOLDS['lat_p99_warn_ms'])) if above_threshold else ''
    if candidates:
        matches = m.get('contention', {}).get('device_correlation', {}).get('matches', [])
        by_tid = {}
        for match in matches:
            by_tid.setdefault(match['target_tid'], []).append(match)
        aligned = []
        for row in candidates:
            for match in by_tid.get(row['target_tid'], []):
                if match['npu_id'] not in row.get('npu_ids', []):
                    continue
                window = match['window']
                if any(max(window['start'], span['start']) < min(window['end'], span['end'])
                       for span in row.get('windows', [])):
                    aligned.append((row, match))
                    break
        row, match = max(aligned, key=lambda pair: pair[0]['overlap_sec']) if aligned else (
            max(candidates, key=lambda item: item['overlap_sec']), None)
        evidence = ('业务线程 %s 等 CPU 时，线程 %s 在同一个 CPU 核（%s）上运行，累计重叠 %.1f ms。'
                    % (row['target_tid'], row['contender_tid'], cpu_list(row['cpus']), row['overlap_sec'] * 1000))
        origin = m.get('t_start', 0)
        if match:
            window = match['window']
            evidence += '%s，NPU %s 的记录也与这条线程的等待重叠。' % (
                _window_text(window['start'], window['end'], origin), match['npu_id'])
        elif row.get('windows'):
            span = max(row['windows'], key=lambda item: item['end'] - item['start'])
            evidence += '可先回看%s。' % _window_text(span['start'], span['end'], origin)
        return Finding(('SCHEDULER_LATENCY', 'SCHEDULER_CONTENTION', 'CPU_CONTENTION_CANDIDATE'),
                       '已观测到', '业务线程排队时，另一线程正在用同一颗核', wait_evidence + evidence,
                       '先确认另一线程负责什么。如果它可以单独分配，再小范围试验调整其并发或使用的 CPU 核。',
                       '用相同负载对比这条业务线程的等待时间，以及吞吐或慢请求耗时，验证调整是否有效。')
    if not above_threshold:
        return None
    evidence = wait_evidence
    series = m.get('timeseries', {})
    width = series.get('bucket_sec')
    buckets = [(i, latency, samples)
               for i, (latency, samples) in enumerate(zip(series.get('lat_p99', []), series.get('lat_count', [])))
               if latency is not None and samples]
    if width and buckets:
        index, latency, samples = max(buckets, key=lambda item: item[1])
        end = min((index + 1) * width, m.get('duration', (index + 1) * width))
        evidence += '可先回看采集开始后 %.3f–%.3f 秒（该段 %d 次记录，等待 P99 为 %.2f ms）。' % (
            index * width, end, samples, latency)
    return Finding(('SCHEDULER_LATENCY', 'SCHEDULER_CONTENTION'),
                   '已观测到', '有线程准备好后仍在等 CPU', evidence,
                   '把业务变慢的时刻与等待记录对齐，确认排队的是哪条业务线程、在哪颗核。再查同核任务和 CPU 配额。',
                   '在相同业务负载下复测这条线程的等待和业务耗时。')


def _quota_finding(m, worker_pids):
    throttled = [row for row in m.get('contention', {}).get('cgroups', [])
                 if (row.get('nr_throttled_delta') or 0) > 0 and worker_pids.intersection(row.get('tgids', []))]
    if not throttled:
        return None
    row = max(throttled, key=lambda item: item['nr_throttled_delta'])
    return Finding(('CGROUP_CPU_THROTTLING',), '已观测到', '业务任务组触发了 CPU 配额限制',
                   '%s 在采集期间新增 %s 次限流。即使机器还有空闲核，这组任务也可能需要等配额刷新。'
                   % (row['path'], row['nr_throttled_delta']),
                   '请运维核对任务组及上级的 CPU 配额。确认限流与业务变慢同步后，按容量预算试调对应配额。',
                   '用相同负载比较限流次数、线程等待时间和业务耗时。')


def _interrupt_finding(m):
    hotspots = {}
    sources = set()
    limited = False
    for kind, label in [('irq', '硬中断'), ('softirq', '软中断')]:
        data = m.get(kind, {})
        cpu, ratio = data.get('peak_cpu'), data.get('max_cpu_ratio')
        if cpu is None or ratio is None or ratio < THRESHOLDS[kind + '_ratio_warn']:
            continue
        source = next(iter(data.get('peak_sources', [])), {})
        name = source.get('name') or ''
        irq_id = '，IRQ %s' % source['id'] if kind == 'irq' and str(source.get('id')).isdigit() else ''
        origin = '（该核主要来源 %s%s）' % (name, irq_id) if name else ''
        hotspots.setdefault(cpu, []).append('%s占 %.1f%%%s' % (label, ratio, origin))
        if name in ('NET_RX', 'NET_TX') or name.lower().startswith(('hns', 'eth')):
            sources.add('网卡')
        if name == 'BLOCK' or name.lower().startswith('nvme'):
            sources.add('磁盘')
        limited |= not data.get('complete') or not m.get('buffer_overrun_known')
    if not hotspots:
        return None
    evidence = '；'.join('CPU %s 的观测时间中，%s' % (cpu, '，'.join(items))
                        for cpu, items in hotspots.items()) + '。'
    if limited:
        evidence += '这些比例来自可用的中断记录。'
    queue = '和'.join(sorted(sources)) + '队列' if sources else '中断来源与队列'
    return Finding(('IRQ_HOTSPOT', 'SOFTIRQ_HOTSPOT'), '待验证', '部分 CPU 核花了较多时间处理中断', evidence,
                   '先查%s，并核对业务线程是否在同一核、同一时段排队。确认重叠后，再小范围试验分开队列和业务线程。' % queue,
                   '用相同负载比较该核的中断耗时、业务线程等待和吞吐。')


def _frequency_finding(m):
    per_cpu = m.get('per_cpu', {})
    candidates = [(row, cpu) for row in m.get('frequency', {}).get('domains', [])
                  if row.get('low_frequency_ratio') is not None
                  and row['low_frequency_ratio'] >= THRESHOLDS['low_freq_ratio']
                  for cpu in row['cpus'] if (per_cpu.get(cpu, {}).get('util') or 0) >= 50]
    if not candidates:
        return None
    domain, cpu = max(candidates, key=lambda item: item[0]['low_frequency_ratio'])
    return Finding(('CPU_FREQUENCY_LOW',), '待验证', '忙核所在的 CPU 组报告过低频',
                   'CPU %s 的利用率为 %.1f%%。它所在的频率组（%s）有 %.1f%% 的有效观测时间报告频率在参考上限的一半或以下。'
                   % (cpu, per_cpu[cpu]['util'], domain['id'], domain['low_frequency_ratio']),
                   '先确认低频是否发生在业务忙段。若同时出现，请运维检查频率上限、温度和功耗，再决定是否试调频率策略。',
                   '用相同负载对比忙段频率、任务等待和业务吞吐。')


def _numa_finding(m):
    rows = [row for row in m.get('npu_affinity', {}).get('rows', []) if row.get('pid')]
    remote = next((row for row in rows if row.get('state') == 'REMOTE_OBSERVED'), None)
    pages = next((row for row in rows if row.get('memory_locality', {}).get('placement_mismatch')), None)
    allowed = next((row for row in rows if row.get('state') in ('REMOTE_ALLOWED', 'UNCONFINED')), None)
    row = remote or pages or allowed
    if not row:
        return None
    prefix = 'NPU %s 的任务（PID %s）' % (row['npu'], row['pid'])
    if row is remote:
        evidence = '%s 在采集期间跑到了 NPU 推荐 CPU 范围之外。' % prefix
    elif row is pages:
        return Finding(('NUMA_RISK',), '待验证', '部分任务内存页分布在 NPU 就近节点之外',
                       '%s 的部分内存页位于 NPU 就近节点之外，实际访问代价需要核验。' % prefix,
                       '请运维核对该进程的内存页位置、实际远端访问与线程运行位置，再评估内存分配策略。',
                       '用相同负载比较远端访问、线程等待和业务耗时。')
    else:
        evidence = '%s 的许可范围（%s）超出了 NPU 推荐 CPU 范围（%s）。' % (
            prefix, row['allowed'], row['affinity'])
        if row.get('numa_locality') == 'LOCAL_OBSERVED':
            evidence += '采集期间仍观测到它在 NPU 就近节点运行。'
    ready = any(item.get('pid') == row['pid'] for item in m.get('binding_plan', {}).get('actions', []))
    action = ('先核对实际运行位置和业务等待。若需要试验，按第 3 节对应进程的配置和操作说明小范围验证。'
              if ready else '先核对第 3 节列出的进程身份、允许使用的 CPU 和 NPU 就近范围，再判断是否具备绑核试验条件。')
    return Finding(('NUMA_RISK',), '待验证', '业务任务的 CPU 运行范围需要核对', evidence, action,
                   '若开展绑核试验，用相同负载比较任务等待时间与业务吞吐。', binding_preflight=ready)


def _coverage_gap(m):
    integrity = m.get('collection_integrity', {})
    ftrace = integrity.get('ftrace', {})
    loss = ftrace.get('loss_status')
    actions = integrity.get('actions', [])
    if loss == 'LOST_EVENTS':
        return '采集记录丢失了 %s 条事件，等待时间和时间重叠可能受影响。请核对溢出的 CPU 和缓冲区大小，再补采变慢时段。' % format(
            ftrace.get('lost_events') or 0, ',')
    if not ftrace.get('events_present') or not ftrace.get('parse_success'):
        return '调度事件缺失或解析不完整。先检查原始采集包和解析结果，再判断是否需要补采。'
    if loss != 'NO_REPORTED_LOSS':
        return '无法确认采集时有没有丢事件。先核对原始包里的丢失统计，已有观察可用于初步定位。'
    if m.get('sched', {}).get('lat_p99') is None or not m.get('sched', {}).get('lat_count'):
        return '缺少可用的线程等待样本。若业务仍慢，请在变慢时段核对是否同时采到了线程唤醒和开始运行的记录。'
    if not m.get('scheduler_quality', {}).get('complete'):
        return '只有部分等待记录能成功配对。先核对采集是否覆盖慢段，再用同负载记录复查。'
    if any(item.get('category') in ('npu_info', 'npu_topology', 'cpu_topology', 'processes') for item in actions):
        return '进程身份或 CPU/NPU 对应关系仍待核对。请核对原始采集包中的进程和拓扑记录，再判断绑核建议是否适用。'
    return ''


def diagnosis_overview(m, diag, severity_labels, primary_resource=False):
    """Sort condensed findings by the same severity used by the diagnosis engine."""
    contention = m.get('contention', {})
    worker_ids = set(contention.get('ai_workers', []))
    worker_pids = {row['tgid'] for row in m.get('thread_metrics', [])
                   if row['identity'] in worker_ids and row.get('tgid')}
    worker_pids.update(row['pid'] for row in m.get('npu_affinity', {}).get('rows', []) if row.get('pid'))
    candidates = [row for row in contention.get('candidates', [])
                  if row.get('target_identity') in worker_ids and row.get('overlap_sec', 0) > 0]
    findings = [item for item in (_waiting_finding(m, candidates), _quota_finding(m, worker_pids),
                                  _interrupt_finding(m), _frequency_finding(m), _numa_finding(m)) if item]
    primary = diag.get('primary')
    primary_type = primary['type'] if primary else None
    important_primary = primary and primary['severity'] in ('CRITICAL', 'WARNING')
    if important_primary and not any(primary_type in item.diagnosis_types for item in findings):
        evidence = primary.get('evidence') or []
        fact = ('本次采集发现资源压力，具体项目和当前用量见第 4 节。' if primary_resource else
                '本次观测的%s为 %s。' % (evidence[0]['metric'], evidence[0]['value']) if evidence else
                '先对照第 2 节的观测数据核实影响范围。')
        action = ('按第 4 节定位紧张的资源，确认与业务慢段重叠后，再试调对应容量或任务限额。'
                  if primary_resource else '按第 2 节的证据定位受影响的任务，对照业务慢段核查后再调整。')
        findings.append(Finding((primary_type,), '待验证', primary['title'], fact, action,
                                '用相同负载比较该指标和业务吞吐或慢请求耗时。'))

    severity_by_type = {}
    for entry in diag.get('findings', []):
        level = entry['severity']
        previous = severity_by_type.get(entry['type'], 'INFO')
        if SEVERITY_RANK[level] >= SEVERITY_RANK[previous]:
            severity_by_type[entry['type']] = level
    ranked = [(max((severity_by_type.get(kind, 'INFO') for kind in item.diagnosis_types),
                   key=SEVERITY_RANK.__getitem__), item) for item in findings]
    ranked.sort(key=lambda pair: (SEVERITY_RANK[pair[0]], primary_type in pair[1].diagnosis_types),
                reverse=True)

    heading = '核心问题：' + primary['title'] if important_primary else '核心问题'
    gap = _coverage_gap(m)
    parts = ['<section id="core-problems"><h3>%s</h3>' % escape(heading)]
    if ranked:
        parts.append('<p>按严重程度从高到低排列。每次只试调一项，便于判断效果。</p>')
        parts.extend(item.html(level, severity_labels[level]) for level, item in ranked)
    elif not gap:
        parts.append('<p>本次可判断的指标未见明显异常，暂无优先调整项。</p>')
    if gap:
        parts.append('<p class="card"><b>数据不足</b> %s</p>' % escape(gap))
    parts.append('</section>')
    return ''.join(parts)
