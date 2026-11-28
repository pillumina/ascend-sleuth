"""Reconcile collector claims, packaged raw evidence and offline parsing.

Collector status is immutable provenance. Analyzer status describes the evidence
actually received; a parser or packaging bug never becomes a blind recapture.
"""
import json
import re
from collections import Counter
from .evidence import capabilities, read_json, read_manifest

from .npu_affinity import _topology
from .npu_parser import parse_npu_info, parse_npu_mapping, parse_npu_topology
from .environment_analysis import (ENV_CATEGORIES, NATIVE_DUMP_CATEGORY, NATIVE_DUMP_PATH,
                                   PREFIX, parse_environment_value, read_native_dump)


SUCCESS = {'COLLECTED', 'NO_ACTIVE_PROCESS'}
CORE = ('cpu_topology', 'npu_info', 'npu_mapping', 'npu_topology', 'processes',
        'numa_process', 'irq', 'softirq', 'proc_stat', 'schedstat', 'frequency', 'idle')
DEFAULT_COMMAND = 'sudo bash scripts/cpu_trace_collect.sh --duration 3 --buffer-size 16384 --output /tmp/cpu-host-$(date +%Y%m%d_%H%M%S)'


def evidence_path(path):
    value = str(path or '').replace('\\', '/').lstrip('./')
    parts = value.split('/')
    if 'hostbound' in parts:
        return '/'.join(parts[parts.index('hostbound'):])
    if 'cpu_trace' in parts:
        return '/'.join(parts[parts.index('cpu_trace')+1:])
    return value


def _validate(category, path, raw, m):
    """Return (success or unknown, count or unknown, reason, status override)."""
    if category == NATIVE_DUMP_CATEGORY:
        try:
            data = read_native_dump(raw)
            return True, len(data) - 1, '', None
        except (ValueError, TypeError) as exc:
            return False, 0, 'Ascend Dump 解析失败：' + str(exc), None
    if category in ENV_CATEGORIES:
        try:
            parse_environment_value(category, path, raw)
            return True, 1, '', None
        except (ValueError, TypeError) as exc:
            return False, 0, '环境证据解析失败：' + str(exc), None
    name = path.rsplit('/', 1)[-1]
    if category == 'npu_info' and name.endswith('.txt'):
        parsed = parse_npu_info(raw)
        count = parsed['parsed_count']
        if parsed['errors']:
            return False, count, '; '.join(parsed['errors']), None
        if count:
            return True, count, '', None
        if parsed['format'] in ('EMPTY', 'PROCESS_TABLE'):
            return True, 0, '', 'NO_ACTIVE_PROCESS'
        return False, 0, '原始 NPU 输出存在，但进程表未能解析；优先修复解析器。', None
    if category == 'npu_topology' and name.endswith('.txt'):
        topology = parse_npu_topology(raw)
        if topology['devices'] and not topology['errors']:
            count = sum(bool(row.get('cpu_affinity')) for row in topology['devices'])
            return True, len(topology['devices']), '' if count else '拓扑矩阵可读，但没有 CPU Affinity 列；映射保持未知。', None
        # A valid matrix with no CPU Affinity is useful hardware evidence, but
        # does not authorize any NPU->CPU mapping or binding command.
        if re.search(r'\bNPU\s*\d+', raw, re.I) and re.search(r'HCCS|PCIE|PCIe|\bX\b', raw):
            return True, 0, '拓扑矩阵可读，但未提供可信的 NPU→CPU Affinity 列；映射保持未知。', None
        return False, 0, 'NPU 拓扑原始数据无法解析。', None
    if category == 'npu_mapping' and name.endswith('.txt'):
        data = parse_npu_mapping(raw)
        return bool(data['devices']) and not data['errors'], data['parsed_count'], '; '.join(data['errors']), None
    if name in ('process_start.json', 'process_end.json'):
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get('processes'), list) or not isinstance(data.get('threads'), list):
                raise ValueError('missing process/thread arrays')
            if not data['processes'] and data.get('errors'):
                raise ValueError('acquisition errors without a stable process identity')
            if any(not isinstance(p, dict) or 'tgid' not in p for p in data['processes']):
                raise ValueError('missing process identity')
            if any(not isinstance(t, dict) or not {'tid', 'tgid'} <= set(t) for t in data['threads']):
                raise ValueError('missing thread identity')
            return True, len(data['threads']), '', None
        except (ValueError, TypeError):
            return False, 0, '进程/线程 JSON 数据契约无效。', None
    if name.endswith('.json'):
        try:
            obj = json.loads(raw)
            if not isinstance(obj, (dict, list)):
                raise ValueError('expected structured data')
            if name == 'capabilities.json':
                events = obj.get('events') if isinstance(obj, dict) else None
                if not isinstance(events, dict) or any(not isinstance(row, dict) for row in events.values()):
                    raise ValueError('invalid capability schema')
                return True, len(events), '', None
            if name in ('frequency_start.json', 'frequency_end.json'):
                if not isinstance(obj, dict) or not isinstance(obj.get('policies'), list):
                    raise ValueError('invalid frequency schema')
                if any(not isinstance(p, dict) or not p.get('id') for p in obj['policies']):
                    raise ValueError('missing policy identity')
                return True, len(obj['policies']), '', None
            return True, len(obj), '', None
        except (ValueError, TypeError):
            return False, 0, '原始 JSON 无法解析。', None
    if name.endswith('.jsonl'):
        try:
            values = [json.loads(line) for line in raw.splitlines() if line.strip()]
            return True, len(values), '', None
        except (ValueError, TypeError):
            return False, 0, '原始 JSONL 包含无效记录。', None
    if category == 'cpu_topology':
        # Validate THIS source, never let a different valid file hide its failure.
        alias = {'numactl.txt': 'numactl.txt', 'lscpu_parse.txt': 'lscpu_parse.txt',
                 'numa.txt': 'numa.txt'}.get(name)
        _, nodes, _ = _topology({'hostbound/' + (alias or 'numactl.txt'): raw})
        if nodes:
            return True, sum(len(v) for v in nodes.values()), '', None
        if alias:
            return False, 0, '该 CPU/NUMA 原始来源存在，但未解析出 CPU→NUMA 对应。', None
    if category == 'trace':
        count = m.get('parse_stats', {}).get('parsed', 0)
        return (True, count, '', None) if m.get('events_ok') else (False, count, 'trace 解析为空或包含失败行。', None)
    return None, None, '', None


def _legacy_entries(snapshot):
    aliases = {
        'cpu_topology': ('hostbound/numactl.txt', 'hostbound/lscpu_parse.txt', 'numa.txt'),
        'npu_info': ('hostbound/npu_smi_info.txt', 'hostbound/npu_smi_info_start.txt', 'npu_smi_info.txt'),
        'npu_mapping': ('hostbound/npu_smi_map.txt', 'npu_smi_map.txt'),
        'npu_topology': ('hostbound/npu_smi_topology.txt', 'npu_smi_topology.txt'),
        'processes': ('hostbound/process_start.json', 'hostbound/process_end.json'),
        'frequency': ('hostbound/frequency_start.json', 'cpufreq.txt'),
        'irq': ('interrupts.txt', 'hostbound/interrupts_at_end.txt'),
        'softirq': ('softirqs.txt', 'hostbound/softirqs_at_end.txt'),
        'proc_stat': ('proc_stat.txt',), 'schedstat': ('schedstat.txt',)}
    entries = []
    for category in CORE:
        paths = [path for path in aliases.get(category, ()) if path in snapshot]
        # Retain legacy per-PID evidence, without inventing a whole-system scan.
        if category == 'processes' and not paths:
            paths = [p for p in snapshot if re.search(r'pid_\d+_threads\.txt$', p)]
        if not paths:
            entries.append({'category': category, 'status': 'UNKNOWN', 'requested': None,
                            'raw_path': None, 'raw_exists': False, 'failure_reason': '旧包没有该项请求/执行记录；支持情况未知。'})
        else:
            for path in paths:
                entries.append({'category': category, 'status': 'COLLECTED', 'requested': None,
                                'raw_path': path, 'raw_exists': True, 'failure_reason': '', 'inferred': True})
    for path in sorted(p for p in snapshot if p.startswith(PREFIX)):
        group = path[len(PREFIX):].partition('/')[0]
        category = {'host': 'environment_host', 'ascend': 'environment_ascend'}.get(group)
        if group.startswith('pid_') and group.endswith('.json'):
            category = 'environment_process'
        if category:
            entries.append({'category': category, 'status': 'COLLECTED', 'requested': None,
                            'raw_path': path, 'inferred': True})
    return entries


def _action(row):
    state = row['status']
    reason = row.get('failure_reason') or state
    advice = {
        'NOT_INCLUDED': '先取回已生成原始文件并修复打包路径，再离线分析；不要求重复采集。',
        'PARSE_FAILED': '原始数据已在包内，先修复解析器或数据契约并离线重跑。',
        'COMMAND_NOT_FOUND': '先在目标环境核对所需工具/驱动，检查可用 proc/sysfs 降级；重复执行相同命令不能解决。',
        'PERMISSION_DENIED': '核对具体接口权限与宿主机/容器边界；解决权限后才对缺少部分进行采集。',
        'UNSUPPORTED': '接口或硬件不支持；使用可用降级来源，重复采集不能补出该能力。',
        'NOT_REQUESTED': '本次明确未请求该常规数据；如需该维度，可在业务窗口使用默认完整入口采集。',
        'UNKNOWN': '旧包没有执行记录，先检查原始目录、依赖和权限，不能由缺失推断未请求。',
        'EXECUTION_FAILED': '先核对返回码与错误原文，解决失败条件后再决定是否采集。',
    }
    recollect = state == 'NOT_REQUESTED' and row.get('category') in CORE + ('trace',)
    return {'category': row.get('category'), 'status': state, 'reason': reason,
            'action': advice.get(state, '保留原始失败信息，核对现场条件。'),
            'recollect': recollect, 'command': DEFAULT_COMMAND if recollect else '',
            'requirements': row.get('command') or '参见该项原始命令和错误信息'}


def _collection_gaps(snapshot, entries, actions):
    gaps = []
    for row in entries:
        if row['status'] not in SUCCESS | {'NOT_REQUESTED'} and row.get('requested') is not False:
            gaps.append({'category': row['category'], 'item': row['raw_path'],
                         'status': row['status'], 'reason': row.get('failure_reason')})
    for action in actions:
        if action['category'] == 'manifest' or action['status'] == 'LOST_EVENTS':
            gaps.append({'category': action['category'], 'item': None,
                         'status': action['status'], 'reason': action['reason']})
    for event, capability in capabilities(snapshot)['events'].items():
        if capability.get('requested') is True and capability.get('enabled') is False:
            if capability.get('exists') is False:
                status = 'UNSUPPORTED'
            elif capability.get('writable') is False:
                status = 'PERMISSION_DENIED'
            else:
                status = 'EXECUTION_FAILED'
            gaps.append({'category': 'ftrace 事件', 'item': event, 'status': status,
                         'reason': capability.get('error') or '未能启用已请求的事件。'})
    for phase in ('start', 'end'):
        name = 'resource_%s.json' % phase
        files = read_json(snapshot, name, {}).get('files')
        if isinstance(files, dict):
            for path, row in files.items():
                if isinstance(row, dict) and row.get('status') == 'UNAVAILABLE':
                    gaps.append({'category': name, 'item': path, 'status': 'UNAVAILABLE',
                                 'reason': '接口缺失或不可读。'})
        process_name = 'process_%s.json' % phase
        errors = read_json(snapshot, process_name, {}).get('errors')
        if isinstance(errors, list) and errors:
            gaps.append({'category': '进程/线程快照', 'item': process_name, 'status': 'PARTIAL',
                         'reason': '记录了 %d 条任务读取错误。明细见原始快照。' % len(errors)})
    return gaps


def analyze_collection_integrity(m, source_files=None):
    snapshot = m.get('snapshot', {})
    manifest, manifest_status = read_manifest(snapshot)
    inputs = manifest.get('entries', []) if manifest_status == 'COLLECTED' else _legacy_entries(snapshot)
    if NATIVE_DUMP_PATH in snapshot and not any(row.get('category') == NATIVE_DUMP_CATEGORY for row in inputs):
        inputs = inputs + [{'category': NATIVE_DUMP_CATEGORY, 'status': 'COLLECTED',
                            'raw_path': NATIVE_DUMP_PATH, 'requested': None, 'inferred': True}]
    entries = []
    for claim in inputs:
        row = dict(claim)
        row.setdefault('category', 'unknown')
        row['collector_status'] = row.get('status', 'UNKNOWN')
        row.setdefault('status', 'UNKNOWN')
        path = evidence_path(row.get('raw_path'))
        row['raw_path'] = path or None
        item = (source_files or {}).get(path)
        raw = snapshot.get(path)
        if raw is None and path and '/' not in path:
            raw = snapshot.get(path.rsplit('/', 1)[-1])
        exists = raw is not None or item is not None
        row['raw_exists'] = exists
        row['empty'] = not raw.strip() if raw is not None else (item.get('empty') if item else None)
        row.setdefault('parse_success', None)
        row.setdefault('parsed_count', None)
        row.setdefault('failure_reason', '')
        if row['collector_status'] in SUCCESS | {'PARSE_FAILED'} and path:
            if not exists:
                row.update(status='NOT_INCLUDED', parse_success=None, parsed_count=None,
                           failure_reason='Manifest 声明生成了该文件，但输入包/目录没有此路径：'+path)
            elif item and item.get('error'):
                row.update(status='PERMISSION_DENIED' if item.get('permission_denied') else 'READ_FAILED',
                           parse_success=False, failure_reason=item['error'])
            elif row['empty']:
                row.update(status='PARSE_FAILED', parse_success=False, parsed_count=0,
                           failure_reason='原始文件已提供但为空，不能视作成功解析。')
            elif row['category'] == 'trace':
                # The loader deliberately avoids copying large trace text into
                # snapshot; its actual semantic result is already in metrics.
                export_error = snapshot.get('hostbound/export_errors.txt', '').strip()
                if export_error:
                    row.update(status='EXECUTION_FAILED', parse_success=False,
                               parsed_count=m.get('parse_stats', {}).get('parsed'),
                               failure_reason='trace 导出不完整：'+export_error)
                else:
                    success = bool(m.get('events_ok'))
                    row.update(status='COLLECTED' if success else 'PARSE_FAILED', parse_success=success,
                               parsed_count=m.get('parse_stats', {}).get('parsed'),
                               failure_reason='' if success else 'trace 解析为空或包含失败记录；先检查原始文本/解析器。')
            elif raw is not None:
                success, count, reason, override = _validate(row['category'], path, raw, m)
                if success is not None:
                    row.update(parse_success=success, parsed_count=count)
                    row['status'] = override or ('COLLECTED' if success else 'PARSE_FAILED')
                    row['failure_reason'] = reason
        entries.append(row)
    actions = [_action(row) for row in entries if row['status'] not in SUCCESS]
    if manifest_status == 'PARSE_FAILED':
        actions.insert(0, {'category': 'manifest', 'status': 'PARSE_FAILED', 'reason': 'collection_manifest.json 无法解析。',
                          'action': '修复 Manifest JSON 并重新离线分析已有原始数据。', 'recollect': False, 'command': ''})
    ftrace = {'events_present': bool(m.get('available')), 'parse_success': bool(m.get('events_ok')),
              'event_types': sorted(m.get('available', [])), 'parse_stats': m.get('parse_stats', {}),
              'loss_status': 'LOST_EVENTS' if m.get('buffer_overrun') else ('NO_REPORTED_LOSS' if m.get('buffer_overrun_known') else 'UNKNOWN'),
              'lost_events': m.get('buffer_overrun') if m.get('buffer_overrun_known') else None,
              'status': 'COLLECTED' if m.get('events_ok') else 'UNAVAILABLE_OR_PARSE_FAILED'}
    if m.get('buffer_overrun'):
        actions.append({'category': 'trace', 'status': 'LOST_EVENTS', 'reason': '实测 trace buffer 丢失/溢出 %d 条。' % m['buffer_overrun'],
                        'action': '先核对丢失所在 CPU、导出错误和内存预算；需要完整调度时间线时，以 16384 KiB/CPU 重采并核对丢失计数。',
                        'recollect': True, 'command': DEFAULT_COMMAND,
                        'requirements': 'root、私有 trace instance；增大 --buffer-size 前检查内存预算。'})
    hb = [r for r in entries if r.get('category') not in ('trace', 'external_tools', 'manifest') + ENV_CATEGORIES]
    categories = {r['category'] for r in hb}
    return {'manifest_status': manifest_status, 'schema_version': manifest.get('schema_version'),
            'entries': entries, 'ftrace': ftrace,
            'hostbound': {'complete': bool(hb) and set(CORE) <= categories and all(r['status'] in SUCCESS for r in hb),
                          'status_counts': dict(Counter(r['status'] for r in hb)),
                          'missing_categories': sorted(set(CORE)-categories),
                          'note': 'HostBound/NPU/NUMA 完整性与 ftrace 调度完整性分别核验。COLLECTED 的 parse_success=null 表示仅保留原始数据，尚未做语义解析。'},
            'actions': actions, 'gaps': _collection_gaps(snapshot, entries, actions),
            'note': 'collector_status 保留现场声明；status 为包内证据对账结果。未知值为 null，缺失工具、无活动进程、解析失败和未打包分别呈现。'}
