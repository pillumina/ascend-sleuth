"""Offline machine resources from raw proc snapshots and command output."""
import json
import math
import re
import shlex
from .evidence import read_json, read_jsonl
from .process_evidence import process_batch


def _number(value):
    try:
        result = int(value)
        return result if result >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def _text(sample, name):
    value = sample.get('files', {}).get('/proc/' + name, {})
    text = value.get('text') if isinstance(value, dict) else None
    return text if isinstance(text, str) else ''


def _kv(text):
    values = {}
    for line in text.splitlines():
        fields = line.replace(':', ' ').split()
        if len(fields) > 1 and _number(fields[1]) is not None:
            values[fields[0]] = int(fields[1])
    return values


def _diskstats(text):
    disks = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 14 and all(_number(x) is not None for x in fields[3:14]):
            disks[fields[2]] = dict(read_ios=int(fields[3]), read_sectors=int(fields[5]),
                read_ms=int(fields[6]), write_ios=int(fields[7]), write_sectors=int(fields[9]),
                write_ms=int(fields[10]), in_flight=int(fields[11]), io_ms=int(fields[12]))
    return disks


def _df(text):
    rows = []
    for line in text.splitlines()[1:]:
        fields = line.split(None, 5)
        if len(fields) == 6 and all(_number(v) is not None for v in fields[1:4]):
            value = fields[4].rstrip('%')
            rows.append(dict(device=fields[0], total=int(fields[1]), used=int(fields[2]),
                             available=int(fields[3]), used_percent=_number(value), mount=fields[5]))
    return rows


def _pressure(text):
    rows = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] not in ('some', 'full'):
            continue
        row = {}
        for token in fields[1:]:
            try:
                key, value = token.split('=', 1)
                number = int(value) if key == 'total' else float(value)
                if math.isfinite(number) and number >= 0:
                    row[key] = number
            except ValueError:
                continue
        rows[fields[0]] = row
    return rows


def analyze_resources(m):
    snapshot = m.get('snapshot', {})
    start = read_json(snapshot, 'resource_start.json', {})
    end = read_json(snapshot, 'resource_end.json', {})
    samples, bad_lines = read_jsonl(snapshot, 'resource_samples.jsonl')
    valid = [s for s in [start] + samples + [end] if isinstance(s, dict) and
             isinstance(s.get('files'), dict) and isinstance(s.get('ts'), (int, float)) and
             not isinstance(s['ts'], bool) and math.isfinite(s['ts'])]
    # Snapshots bracket the collection command; disclose their actual window.
    valid.sort(key=lambda row: row['ts'])
    first, last = (valid[0], valid[-1]) if valid else ({}, {})
    dt = last.get('ts', 0) - first.get('ts', 0)
    clocks = [s.get('clock') for s in valid]
    same_clock = bool(clocks) and all(isinstance(c, str) and c in ('boottime', 'monotonic') for c in clocks) and len(set(clocks)) == 1
    elapsed = dt if dt > 0 and same_clock else None
    limitations = []
    if not valid:
        limitations.append('旧包未提供资源快照；缺失不表示资源充足。')
    if valid and elapsed is None:
        limitations.append('缺少同一时钟下的不同时间点，累计计数仅作静态展示，不计算速率。')
    if bad_lines:
        limitations.append('资源轮询包含 %d 行无效 JSON。' % bad_lines)

    def delta(a, b):
        return b - a if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b >= a else None

    def rate(a, b, multiplier=1):
        value = delta(a, b)
        return value * multiplier / elapsed if value is not None and elapsed else None

    def raw(name):
        return snapshot.get('hostbound/resources/' + name, '')

    risks = []
    def risk(kind, title, evidence, state='POTENTIAL'):
        risks.append(dict(type=kind, title=title, evidence=evidence, evidence_state=state,
                          note='资源风险候选，需与业务时延、吞吐及 Device 时间线关联，尚未确认劣化根因。'))

    before_cpu = next((line.split()[1:9] for line in _text(first, 'stat').splitlines() if line.startswith('cpu ')), [])
    after_cpu = next((line.split()[1:9] for line in _text(last, 'stat').splitlines() if line.startswith('cpu ')), [])
    cpu = dict(logical_cpus=m.get('topology', {}).get('cpu_count') or m.get('n_cpus_report'),
               busy_percent=None, iowait_percent=None, load1=None)
    if elapsed and len(before_cpu) == len(after_cpu) == 8:
        changes = [delta(_number(a), _number(b)) for a, b in zip(before_cpu, after_cpu)]
        if None not in changes and sum(changes) > 0:
            total = sum(changes)
            cpu.update(busy_percent=100.0 * (total - changes[3] - changes[4]) / total,
                       iowait_percent=100.0 * changes[4] / total)
    try:
        cpu['load1'] = float(_text(last, 'loadavg').split()[0])
    except (ValueError, IndexError):
        pass

    mem = _kv(_text(last, 'meminfo')) or _kv(snapshot.get('meminfo.txt', ''))
    memory = {key: mem.get(field) for key, field in [('total_kb', 'MemTotal'), ('available_kb', 'MemAvailable'),
              ('free_kb', 'MemFree'), ('swap_total_kb', 'SwapTotal'), ('swap_free_kb', 'SwapFree'),
              ('dirty_kb', 'Dirty'), ('writeback_kb', 'Writeback')]}
    memory['available_percent'] = (100.0 * memory['available_kb'] / memory['total_kb']
        if memory.get('total_kb') and memory.get('available_kb') is not None else None)
    memory_samples = [_kv(_text(s, 'meminfo')) for s in valid]
    available_samples = [100.0 * x['MemAvailable'] / x['MemTotal'] for x in memory_samples if x.get('MemTotal') and 'MemAvailable' in x]
    memory['minimum_available_percent'] = min(available_samples) if available_samples else memory['available_percent']
    previous_vm, current_vm = _kv(_text(first, 'vmstat')), _kv(_text(last, 'vmstat'))
    vm = {key + '_delta': delta(previous_vm.get(key), current_vm.get(key)) for key in
          ('pswpin', 'pswpout', 'pgmajfault', 'pgscan_direct', 'oom_kill')}

    pressure = {}
    for resource in ('cpu', 'memory', 'io'):
        old, new = _pressure(_text(first, 'pressure/' + resource)), _pressure(_text(last, 'pressure/' + resource))
        for kind, row in new.items():
            value = rate(old.get(kind, {}).get('total'), row.get('total'), 1e-4)
            row['stall_percent'] = value if value is not None and value <= 100.1 else None
        pressure[resource] = new
    if memory['minimum_available_percent'] is not None and memory['minimum_available_percent'] < 10:
        stressed = (pressure['memory'].get('some', {}).get('stall_percent') or 0) > 1 or any((vm.get(k) or 0) > 0 for k in ('pswpin_delta', 'pswpout_delta', 'oom_kill_delta'))
        risk('MEMORY_PRESSURE', '可用内存偏低' + ('且伴随内存压力' if stressed else ''),
             '窗口最低 MemAvailable %.2f%%，结束值 %s%%；PSI %s；交换/OOM增量 %s' % (memory['minimum_available_percent'], memory['available_percent'], pressure['memory'], vm), 'OBSERVED_CANDIDATE' if stressed else 'POTENTIAL')
    if not any(r['type'] == 'MEMORY_PRESSURE' for r in risks):
        if (vm.get('oom_kill_delta') or 0) > 0:
            risk('MEMORY_PRESSURE', '资源窗口发生 OOM kill', str(vm), 'OBSERVED_CANDIDATE')
        elif (pressure['memory'].get('some', {}).get('stall_percent') or 0) > 1:
            risk('MEMORY_PRESSURE', '资源窗口存在内存等待', str(pressure['memory']), 'OBSERVED_CANDIDATE')
    if (pressure['cpu'].get('some', {}).get('stall_percent') or 0) >= 5:
        risk('CPU_RESOURCE_PRESSURE', '资源窗口存在 CPU 等待', str(pressure['cpu']), 'OBSERVED_CANDIDATE')
    elif cpu['busy_percent'] is not None and cpu['busy_percent'] >= 90:
        risk('CPU_RESOURCE_PRESSURE', '资源快照显示 CPU 高负载', str(cpu))

    filesystems = _df(raw('df_blocks_end.txt') or raw('df_blocks.txt'))
    inodes = {(r['device'], r['mount']): r for r in _df(raw('df_inodes_end.txt') or raw('df_inodes.txt'))}
    for row in filesystems:
        inode = inodes.get((row['device'], row['mount']), {})
        row['inode_used_percent'] = inode.get('used_percent')
        row['total_kb'], row['available_kb'] = row.pop('total'), row.pop('available')
        if any(v is not None and v >= 95 for v in (row['used_percent'], row['inode_used_percent'])):
            risk('DISK_CAPACITY', '文件系统空间或 inode 接近耗尽：' + row['mount'], str(row))

    inventory = []
    for line in raw('lsblk.txt').splitlines():
        try:
            item = dict(token.split('=', 1) for token in shlex.split(line) if '=' in token)
            if item.get('NAME'):
                inventory.append(dict(name=item['NAME'], size_bytes=_number(item.get('SIZE')),
                    type=item.get('TYPE'), rotational=item.get('ROTA'), mount=item.get('MOUNTPOINT')))
        except ValueError:
            limitations.append('lsblk 一行无法解析，原文保留。')
    inventory_map = {row['name']: row for row in inventory}
    disks = []
    old_disks = _diskstats(_text(first, 'diskstats'))
    for name, current in _diskstats(_text(last, 'diskstats')).items():
        old = old_disks.get(name, {})
        read_ios, write_ios = delta(old.get('read_ios'), current['read_ios']), delta(old.get('write_ios'), current['write_ios'])
        ios = read_ios + write_ios if read_ios is not None and write_ios is not None else None
        read_ms, write_ms = delta(old.get('read_ms'), current['read_ms']), delta(old.get('write_ms'), current['write_ms'])
        ms = read_ms + write_ms if read_ms is not None and write_ms is not None else None
        row = dict(inventory_map.get(name, {}), name=name, read_bytes_per_sec=rate(old.get('read_sectors'), current['read_sectors'], 512),
            write_bytes_per_sec=rate(old.get('write_sectors'), current['write_sectors'], 512),
            iops=ios / elapsed if ios is not None and elapsed else None,
            await_ms=ms / ios if ms is not None and ios else None,
            busy_percent=rate(old.get('io_ms'), current['io_ms'], .1), in_flight=current['in_flight'])
        disks.append(row)
    observed_names = {row['name'] for row in disks}
    for item in inventory:
        if item['name'] not in observed_names:
            disks.append(dict(item, read_bytes_per_sec=None, write_bytes_per_sec=None,
                              iops=None, await_ms=None, busy_percent=None, in_flight=None))
    if (pressure['io'].get('some', {}).get('stall_percent') or 0) >= 5:
        risk('IO_PRESSURE', '资源窗口存在 I/O 等待压力', str(pressure['io']), 'OBSERVED_CANDIDATE')

    # Retain per-cgroup limits: host free memory does not imply a job has room.
    workload_pids = set(m.get('process_analysis', {}).get('related_tgids', []))
    workload_pids.update(row['pid'] for row in m.get('npu_affinity', {}).get('rows', []) if row.get('pid'))
    phase_groups = []
    for phase in ('start', 'end'):
        groups = {}
        for process in process_batch(snapshot, phase).get('processes', []):
            if process.get('tgid') not in workload_pids:
                continue
            for row in process.get('cgroup_cpu', []):
                if isinstance(row, dict) and row.get('path'):
                    groups[row['path']] = row
        phase_groups.append(groups)
    cgroups = []
    for path, group in sorted(phase_groups[1].items()):
        current = _number(group.get('memory.current', group.get('memory.usage_in_bytes')))
        maximum = _number(group.get('memory.max', group.get('memory.limit_in_bytes')))
        pids_current, pids_max = _number(group.get('pids.current')), _number(group.get('pids.max'))
        old_events = _kv(phase_groups[0].get(path, {}).get('memory.events', ''))
        new_events = _kv(group.get('memory.events', ''))
        if current is None and maximum is None and pids_current is None and not new_events:
            continue
        row = dict(path=path, memory_current_bytes=current, memory_max_bytes=maximum,
                   pids_current=pids_current, pids_max=pids_max,
                   oom_kill_delta=delta(old_events.get('oom_kill'), new_events.get('oom_kill')))
        cgroups.append(row)
        if ((current is not None and maximum and current >= maximum * .95) or
            (pids_current is not None and pids_max and pids_current >= pids_max * .95) or (row['oom_kill_delta'] or 0) > 0):
            risk('CGROUP_RESOURCE_LIMIT', '任务所在 cgroup 接近资源限额或发生 OOM', str(row))

    missing = sorted({name for sample in valid for name, row in sample['files'].items()
                      if not isinstance(row, dict) or not isinstance(row.get('text'), str)})
    if missing:
        limitations.append('部分资源接口缺失或不可读：' + ', '.join(missing))
    has_raw_data = any(isinstance(row, dict) and isinstance(row.get('text'), str) for sample in valid for row in sample['files'].values())
    return dict(available=bool(has_raw_data or mem or filesystems or inventory), window_sec=elapsed,
        window=[first.get('ts'), last.get('ts')], clock=last.get('clock'), sample_count=len(valid),
        cpu=cpu, memory=memory, vm=vm, pressure=pressure, disks=disks, filesystems=filesystems,
        storage_inventory=inventory, cgroups=cgroups, risks=risks, limitations=limitations,
        note='资源窗口使用快照自身时间，不等同于 ftrace 窗口。磁盘逐设备展示，不累加分区与整盘；busy% 不单独代表并行设备饱和。')
