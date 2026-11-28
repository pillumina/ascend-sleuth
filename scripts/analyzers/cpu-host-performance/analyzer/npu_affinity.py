# -*- coding: utf-8 -*-
"""NPU -> host PID -> thread affinity evidence and read-only binding plans."""
import re
import math
from collections import defaultdict
from .evidence import read_json
from .npu_parser import device_id, logic_map, parse_npu_info, parse_npu_mapping, parse_npu_topology
from .process_evidence import process_batch


STATE_CN = {
    'LOCAL': '已绑定亲和 CPU', 'UNCONFINED': '允许跨 NUMA / 未收敛',
    'REMOTE_ALLOWED': '绑定范围偏离亲和 CPU', 'REMOTE_OBSERVED': '观测到非亲和 CPU',
    'UNKNOWN': '证据不足', 'NO_PROCESS': '无已识别进程',
}


def cpus(text):
    text = re.sub(r'\s+', '', text or '')
    if not re.fullmatch(r'\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*', text):
        return set()
    result = set()
    for item in text.split(','):
        ends = [int(x) for x in item.split('-')]
        if len(ends) == 1:
            result.add(ends[0])
        elif 0 <= ends[1] - ends[0] < 100000:
            result.update(range(ends[0], ends[1]+1))
    return result


def cpu_list(values):
    values = sorted(set(values))
    ranges = []
    for value in values:
        if ranges and value == ranges[-1][1]+1:
            ranges[-1][1] = value
        else:
            ranges.append([value, value])
    return ','.join(str(a) if a == b else '%d-%d' % (a, b) for a, b in ranges)


def _get(snapshot, name):
    return snapshot.get('hostbound/'+name, snapshot.get(name, '')) or ''


def _topology(snapshot):
    affinity, nodes, cores = {}, defaultdict(set), {}
    for npu, row in _device_mapping(snapshot)['by_npu'].items():
        affinity[npu] = row['cpus']
    for line in _get(snapshot, 'numactl.txt').splitlines():
        match = re.match(r'node\s+(\d+)\s+cpus:\s*(.*)', line.strip())
        if match:
            nodes[int(match[1])].update(cpus(','.join(match[2].split())))
    current = None
    sysfs_nodes = defaultdict(set)
    for line in _get(snapshot, 'numa.txt').splitlines():
        match = re.match(r'==\s*/sys/devices/system/node/node(\d+)/cpulist\s*==', line.strip())
        if match:
            current = int(match[1])
        elif line.startswith('=='):
            current = None
        elif current is not None:
            sysfs_nodes[current].update(cpus(line.strip()))
            current = None
    for node, values in sysfs_nodes.items():
        if values:
            nodes[node] = values
    normalized = read_json(snapshot, 'numa_topology.json', {})
    if isinstance(normalized, dict) and isinstance(normalized.get('nodes'), list):
        for row in normalized['nodes']:
            if isinstance(row, dict) and str(row.get('node', '')).isdigit() and isinstance(row.get('cpus'), list):
                values = {int(c) for c in row['cpus'] if str(c).isdigit()}
                if values:
                    nodes[int(row['node'])] = values
    for path, text in snapshot.items():
        match = re.search(r'(?:^|/)sysfs/node/node(\d+)/cpulist$', path)
        if match and cpus(text.strip()):
            nodes[int(match[1])] = cpus(text.strip())
    lscpu_nodes = defaultdict(set)
    for line in _get(snapshot, 'lscpu_parse.txt').splitlines():
        fields = line.strip().split(',')
        if len(fields) >= 5 and all(x.isdigit() for x in fields[:4]):
            cpu, core, socket, node = map(int, fields[:4])
            if fields[4].upper() in ('Y', 'YES', '1'):
                lscpu_nodes[node].add(cpu)
                cores[cpu] = (socket, node, core)
    for node, values in lscpu_nodes.items():
        if not nodes.get(node):
            nodes[node] = values
    # A CPU mapped to two NUMA nodes is ambiguous evidence, never a binding input.
    duplicates = {c for n, values in nodes.items() for c in values
                  if sum(c in other for other in nodes.values()) > 1}
    for values in nodes.values():
        values.difference_update(duplicates)
    return affinity, dict(nodes), cores


def _device_mapping(snapshot):
    by_npu, errors, sources = {}, [], []
    identity_error = ''
    try:
        ids = logic_map(_get(snapshot, 'npu_smi_map.txt'))
    except ValueError as exc:
        ids, identity_error = {}, str(exc)
        errors.append(identity_error)
    for name, parser in [('npu_smi_topology.txt', parse_npu_topology), ('npu_smi_map.txt', parse_npu_mapping)]:
        text = _get(snapshot, name)
        if not text:
            continue
        sources.append('hostbound/' + name)
        parsed = parser(text)
        errors.extend(parsed['errors'])
        if not parsed['devices'] and re.search(r'CPU\s+Affinity', text, re.I):
            identity_error = '无法可靠解析标注了 CPU Affinity 的设备表'
        for row in parsed['devices']:
            npu = row['device_id'] if name == 'npu_smi_map.txt' and ids else row['npu']
            if ids and npu not in ids.values():
                identity_error = 'NPU 拓扑行与已采集的逻辑 ID 不匹配'
            item = by_npu.setdefault(npu, {'cpus': set(), 'sources': [], 'conflict': False})
            if row.get('invalid_affinity'):
                item['conflict'] = True
            values = cpus(row['cpu_affinity'])
            item['sources'].append('hostbound/%s:%d' % (name, row['source_line']))
            if values:
                if item['cpus'] and item['cpus'] != values:
                    item['conflict'] = True
                item['cpus'] = values
    for npu, item in by_npu.items():
        if item['conflict']:
            item['cpus'] = set()
            errors.append('NPU%d explicit CPU mappings conflict; no mapping selected' % npu)
    return {'by_npu': by_npu, 'logic_ids': ids, 'identity_error': identity_error, 'errors': errors, 'sources': sources,
            'status': 'AVAILABLE' if any(r['cpus'] for r in by_npu.values()) else ('PARSE_FAILED' if errors else 'UNAVAILABLE')}


def _processes(text, logic_ids=None):
    result = defaultdict(dict)
    for row in parse_npu_info(text)['processes']:
        npu, chip, pid = device_id(row, logic_ids), row['chip'], row['pid']
        proc = result[npu].setdefault(pid, {'pid': pid, 'name': row['name'], 'memory': None,
            'chip': chip, 'chips': [], 'memory_by_chip': {}, 'pid_namespace': row['pid_namespace'], 'source_lines': []})
        proc['source_lines'].append(row['source_line'])
        if chip is not None:
            proc['memory_by_chip'][chip] = row['memory']
            proc['chips'] = sorted(proc['memory_by_chip'])
        if row['memory'] is not None:
            proc['memory'] = sum(v for v in proc['memory_by_chip'].values() if v is not None) if chip is not None else row['memory']
        proc['chip'] = proc['chips'][0] if len(proc['chips']) == 1 else ','.join(map(str, proc['chips']))
    return result


def _pid_evidence(snapshot, pid, m):
    status_text = _get(snapshot, 'pid_%d_status_end.txt' % pid) or _get(snapshot, 'pid_%d_status.txt' % pid)
    status = dict(re.findall(r'^(\w+):[^\S\n]*(.*?)$', status_text, re.M))
    allowed = {}
    for tid, text in re.findall(r"pid\s+(\d+)'s current affinity list:\s*([\d,\-]+)", _get(snapshot, 'pid_%d_thread_affinity.txt' % pid)):
        allowed[int(tid)] = cpus(text)
    tids, psr = set(), set()
    for line in _get(snapshot, 'pid_%d_threads.txt' % pid).splitlines():
        fields = line.split()
        if len(fields) >= 3 and all(x.isdigit() for x in fields[:3]) and int(fields[0]) == pid:
            tids.add(int(fields[1]))
            psr.add(int(fields[2]))
    batches = [process_batch(snapshot, stage) for stage in ('start', 'end')]
    process_rows = [[p for p in batch.get('processes', []) if int(p.get('tgid', -1)) == pid] for batch in batches]
    current_process = (process_rows[1] or process_rows[0] or [{}])[0]
    if current_process:
        status.setdefault('Pid', str(pid))
        status.setdefault('Tgid', str(pid))
        status.setdefault('Mems_allowed_list', current_process.get('mems_allowed_list') or '')
        if current_process.get('threads'):
            status.setdefault('Threads', str(current_process['threads']))
    thread_rows = [dict(t) for t in batches[1].get('threads', []) if int(t.get('tgid', -1)) == pid]
    if not thread_rows:
        thread_rows = [dict(t) for t in batches[0].get('threads', []) if int(t.get('tgid', -1)) == pid]
    stamps = [str(rows[0].get('starttime', '')) for rows in process_rows if len(rows) == 1]
    raw_stamp = (_get(snapshot, 'pid_%d_starttime_end.txt' % pid) or _get(snapshot, 'pid_%d_starttime.txt' % pid)).strip()
    before_stamp = _get(snapshot, 'pid_%d_starttime_start.txt' % pid).strip()
    if raw_stamp:
        stamps.append(raw_stamp)
    if before_stamp:
        stamps.append(before_stamp)
    valid_stamps = [s for s in stamps if s.isdigit()]
    ambiguous = len(set(valid_stamps)) > 1 or pid in m.get('process_analysis', {}).get('unsafe_npu_pids', []) or any(t.get('identity_ambiguous') for t in m.get('process_analysis', {}).get('tasks', []) if t.get('tgid') == pid)
    stable = not ambiguous and len(valid_stamps) >= 2 and (all(process_rows) or bool(before_stamp and raw_stamp))
    thread_cpuset, thread_stamps = {}, {}
    for t in thread_rows:
        tid = int(t['tid'])
        tids.add(tid)
        if t.get('allowed_cpus') is not None:
            allowed[tid] = set(t['allowed_cpus'])
        raw_set = t.get('cpuset_cpus_effective', t.get('cpuset_cpus', ''))
        thread_cpuset[tid] = set(raw_set) if isinstance(raw_set, list) else cpus(raw_set)
        if str(t.get('starttime', '')).isdigit():
            thread_stamps[tid] = str(t['starttime'])
        if isinstance(t.get('last_cpu'), int) and t['last_cpu'] >= 0:
            psr.add(t['last_cpu'])
    trace = set()
    if not ambiguous:
        resolved = m.get('thread_metrics', [])
        seen_tids = {t['tid'] for t in resolved}
        for task in resolved:
            # TIDs can be recycled within the window. The resolved generation
            # carries its own TGID; the legacy numeric-TID union does not.
            if task.get('tgid') == pid and not task.get('identity_ambiguous'):
                process_identity = task.get('process_identity')
                expected_identity = '%d:%s' % (pid, valid_stamps[-1] if valid_stamps else 'unknown')
                if process_identity and valid_stamps and process_identity != expected_identity:
                    continue
                trace.update(task.get('cpus', []))
                trace.update((m.get('tasks') or {}).get('observed_cpus_by_identity', {}).get(task['identity'], []))
        for tid, values in (m.get('tasks') or {}).get('observed_cpus_by_tid', {}).items():
            if tid not in seen_tids and (tid == pid or tid in tids):
                trace.update(values)  # old custom metrics without identity rows
    complete = bool(tids and tids <= set(allowed))
    if status.get('Threads', '').isdigit():
        complete = complete and len(tids) == int(status['Threads'])
    complete = complete and bool(allowed) and all(allowed.values())
    starttime = valid_stamps[-1] if valid_stamps else ''
    namespaces = [p.get('namespace_pids', []) for rows in process_rows for p in rows]
    namespaces += [t.get('namespace_pids', []) for t in thread_rows if t['tid'] == pid]
    namespace_ok = not any(values and int(values[0]) != pid for values in namespaces)
    namespace_ok = namespace_ok and not any(t.get('namespace_pids') and t['namespace_pids'][0] != t['tid'] for t in thread_rows)
    namespace_ok = namespace_ok and pid not in m.get('process_analysis', {}).get('unsafe_npu_pids', [])
    for value in status.get('NSpid', '').split()[:1]:
        namespace_ok = namespace_ok and value == str(pid)
    process_cpuset = current_process.get('cpuset_cpus_effective')
    return {'status': status, 'allowed': allowed, 'tids': tids, 'psr': psr, 'trace': trace,
            'complete': complete, 'cpuset': set(process_cpuset) if isinstance(process_cpuset, list) else cpus(_get(snapshot, 'pid_%d_cpuset_effective.txt' % pid)),
            'starttime': starttime, 'thread_cpuset': thread_cpuset, 'thread_starttime': thread_stamps,
            'thread_rows': thread_rows, 'identity_status': 'AMBIGUOUS' if ambiguous else ('VERIFIED' if stable and namespace_ok else 'UNVERIFIED'),
            'namespace_ok': namespace_ok}


def _memory_locality(snapshot, pid, ev, local_nodes):
    pages, kb, sources, mb = defaultdict(int), defaultdict(int), [], {}
    raw = _get(snapshot, 'pid_%d_numa_maps.txt' % pid)
    if raw:
        sources.append('hostbound/pid_%d_numa_maps.txt' % pid)
        for line in raw.splitlines():
            size = re.search(r'\bkernelpagesize_kB=(\d+)', line)
            for node, count in re.findall(r'\bN(\d+)=(\d+)', line):
                pages[int(node)] += int(count)
                if size:
                    kb[int(node)] += int(count) * int(size[1])
    if not pages:
        batch = process_batch(snapshot, 'end')
        for p in batch.get('processes', []):
            if int(p.get('tgid', -1)) == pid:
                summary = p.get('numa_maps') or {}
                if not isinstance(summary, dict):
                    continue
                for field, destination in [('node_pages', pages), ('node_kb', kb)]:
                    values = summary.get(field, {})
                    if isinstance(values, dict):
                        destination.update({int(n): v for n, v in values.items() if str(n).isdigit() and isinstance(v, (int, float)) and v >= 0})
                if pages:
                    sources.append('hostbound/process_end.json:numa_maps')
    if not pages:
        raw_stat = _get(snapshot, 'pid_%d_numastat.txt' % pid)
        header = []
        for line in raw_stat.splitlines():
            if re.search(r'Node\s+\d+', line):
                header = [int(n) for n in re.findall(r'Node\s+(\d+)', line)]
            elif header and re.match(r'^\s*Total\s+', line, re.I):
                values = line.split()[1:]
                try:
                    if len(values) >= len(header):
                        mb = dict(zip(header, [float(v) for v in values[:len(header)]]))
                        sources.append('hostbound/pid_%d_numastat.txt' % pid)
                except ValueError:
                    pass
    actual = sorted(n for n, count in (pages or mb).items() if count > 0)
    local = set(local_nodes)
    status = 'UNKNOWN' if not actual or not local else ('LOCAL' if set(actual) <= local else ('REMOTE' if set(actual).isdisjoint(local) else 'MIXED'))
    return {'allowed_nodes': sorted(cpus(ev['status'].get('Mems_allowed_list', ''))),
            'actual_pages_by_node': dict(pages), 'actual_kb_by_node': dict(kb), 'actual_nodes': actual,
            'actual_mb_by_node': mb,
            'thread_allowed_nodes': {t['tid']: sorted(cpus(t.get('mems_allowed_list', ''))) for t in ev.get('thread_rows', [])},
            'source': sources, 'status': status, 'remote_evidence': False,
            'placement_mismatch': bool(actual and local and set(actual) - local),
            'note': 'Mems_allowed 是许可范围；numa_maps 是已分配页位置，不证明远程访存流量；taskset 不迁移内存页。'}


def analyze_npu_affinity(m):
    snapshot = m.get('snapshot', {})
    mapping = _device_mapping(snapshot)
    affinity, nodes, cores = _topology(snapshot)
    parsed_info = parse_npu_info(_get(snapshot, 'npu_smi_info.txt'))
    info = _get(snapshot, 'npu_smi_info.txt')
    ownership_error = mapping['identity_error'] or '; '.join(parsed_info['errors'])
    changed_owners = set()
    try:
        processes = _processes(info, mapping['logic_ids'])
        start_info = _get(snapshot, 'npu_smi_info_start.txt')
        if start_info.strip():
            previous = _processes(start_info, mapping['logic_ids'])
            for device in previous.keys() | processes.keys():
                changed_owners.update(previous.get(device, {}).keys() ^ processes.get(device, {}).keys())
    except ValueError as exc:
        ownership_error = str(exc)
        processes = _processes(info)
    online = cpus(_get(snapshot, 'cpu_online.txt'))
    context = dict(re.findall(r'^([a-z_]+)=(.*)$', _get(snapshot, 'host_context.txt'), re.M))
    rows, notes = [], []
    inventory_ids = mapping['logic_ids'].values() if mapping['logic_ids'] else parsed_info['devices']
    for npu in sorted(set(affinity) | set(processes) | set(inventory_ids)):
        pool = affinity.get(npu, set())
        local_nodes = sorted(n for n, values in nodes.items() if pool & values)
        procs = sorted(processes.get(npu, {}).values(), key=lambda p: (-(p['memory'] or 0), p['pid']))
        for i, proc in enumerate(procs or [{'pid': None, 'name': '—', 'memory': None, 'chip': None}]):
            pid = proc['pid']
            owner_issue = ownership_error or ('采集前后 PID 的 NPU 归属发生变化' if pid in changed_owners else '')
            ev = _pid_evidence(snapshot, pid, m) if pid else {}
            permitted = set().union(*ev.get('allowed', {}).values()) if ev else set()
            observed = ev.get('trace', set()) | ev.get('psr', set())
            observed_numa = sorted(n for n, values in nodes.items() if values & observed)
            known = set().union(*nodes.values()) if nodes else set()
            locality = ('LOCAL_OBSERVED' if set(observed_numa) <= set(local_nodes) else 'REMOTE_OBSERVED') if observed and not observed - known and local_nodes else 'UNKNOWN'
            if not pid:
                state = 'NO_PROCESS'
            elif not pool or not ev['complete'] or len(local_nodes) != 1 or ev['identity_status'] == 'AMBIGUOUS':
                state = 'UNKNOWN'
            elif observed - pool:
                state = 'REMOTE_OBSERVED'
            elif permitted and permitted <= pool:
                state = 'LOCAL'
            elif permitted.isdisjoint(pool):
                state = 'REMOTE_ALLOWED'
            else:
                state = 'UNCONFINED'
            blockers = []
            candidate = pool & online & nodes.get(local_nodes[0], set()) if len(local_nodes) == 1 else set()
            if pid:
                if owner_issue:
                    blockers.append(owner_issue)
                    candidate = set()
                if context.get('execution_context') != 'host':
                    blockers.append('未确认在物理机/宿主机采集')
                if not ev['complete']:
                    blockers.append('全量 TID/线程 affinity 快照不完整')
                if ev['status'].get('Tgid') != str(pid) or ev['status'].get('Pid') != str(pid) or not ev['namespace_ok']:
                    blockers.append('宿主机 PID/TGID 或 PID namespace 对应关系未核验')
                if ev['identity_status'] != 'VERIFIED':
                    blockers.append('进程采集前后身份未核验或 PID 已复用')
                if not ev['starttime'] or not context.get('boot_id'):
                    blockers.append('缺少进程 starttime 或主机 boot_id')
                if ev['cpuset']:
                    candidate &= ev['cpuset']
                else:
                    candidate = set()
                for tid in ev['tids']:
                    if not ev['thread_cpuset'].get(tid) or not ev['thread_starttime'].get(tid):
                        blockers.append('TID%d 缺少有效 cpuset 或 starttime' % tid)
                        candidate = set()
                    else:
                        candidate &= ev['thread_cpuset'][tid]
                if not candidate:
                    blockers.append('亲和 NUMA/在线 CPU/全 TID 有效 cpuset 交集不可用')
            sources = mapping['by_npu'].get(npu, {}).get('sources', []) + ['hostbound/npu_smi_info.txt', 'process_start/end.json', 'pid_*_status/thread_affinity/threads/cpuset_effective.txt', 'ftrace']
            row = dict(proc, npu=npu, role='主进程（显存占用最高）' if i == 0 and pid else '其他占卡进程',
                       numa=local_nodes, affinity=cpu_list(pool), allowed=cpu_list(permitted),
                       observed=cpu_list(observed), trace=cpu_list(ev.get('trace', set())),
                       observed_numa=observed_numa, numa_locality=locality,
                       allowed_numa=sorted(n for n, values in nodes.items() if values & permitted),
                       psr=cpu_list(ev.get('psr', set())), state=state, target='', blockers=blockers,
                       threads=len(ev.get('tids', [])), evidence=ev, sources=sources,
                       identity_status=ev.get('identity_status', 'UNAVAILABLE'),
                       mapping_status=('CONFLICT' if mapping['by_npu'].get(npu, {}).get('conflict') else
                                       ('AVAILABLE' if pool else 'UNKNOWN')), ownership_error=owner_issue,
                       current_cpu=cpu_list(permitted), current_numa=observed_numa,
                       recommended_cpu='', recommended_numa=[], recommendation_status='INSUFFICIENT_EVIDENCE',
                       reasons=[], risks=['调整 affinity 会改变调度资源；需同负载灰度验证，收益尚未测量。',
                                          'taskset 只约束目标线程，不排除其他进程或 IRQ 使用这些 CPU。'],
                       expected_improvement='待验证：减少范围外运行或已观测同核等待；不估算未经测量的吞吐收益。',
                       verification=['读回主进程各线程 affinity 并核验有效 cpuset', '同负载复采比较 runnable wait P99、吞吐/时延和 Device 空泡'],
                       rollback='由现场执行器保存原 affinity 并据日志恢复。',
                       thread_rows=ev.get('thread_rows', []), _candidate=candidate,
                       memory_locality=_memory_locality(snapshot, pid, ev, local_nodes) if pid else {})
            rows.append(row)
    pid_rows = defaultdict(list)
    for row in rows:
        if row['pid']:
            pid_rows[row['pid']].append(row)
    for group in pid_rows.values():
        if len(group) > 1:
            for row in group:
                row['blockers'].append('同一 PID 使用多张 NPU；缺少 TID/rank 到卡的分工证据')
                row['_candidate'] = set()
    active = [r for r in rows if r['pid'] and r['_candidate']]
    # Connected overlapping CPU pools are allocation domains; arbitrary partial overlaps are not guessed.
    remaining = list(active)
    while remaining:
        group = [remaining.pop(0)]
        changed = True
        while changed:
            changed = False
            for row in list(remaining):
                if any(row['_candidate'] & other['_candidate'] for other in group):
                    group.append(row); remaining.remove(row); changed = True
        pool = group[0]['_candidate']
        preserved = []
        for row in group:
            allowed = row['evidence']['allowed']
            if allowed and all(values and values <= row['_candidate'] for values in allowed.values()):
                row['target'] = row['allowed']
                row['recommendation_status'] = 'PRESERVE'
                row['reasons'].append('全 TID 当前许可范围已在实测亲和范围及各自 cpuset 内，保留各线程原掩码。')
                preserved.append(row)
        pending = [r for r in group if r not in preserved]
        if not pending:
            continue
        if any(r['_candidate'] != pool for r in group):
            for row in pending:
                row['blockers'].append('工作进程可用 CPU 部分重叠，缺少可核验的分配策略')
            continue
        weights = []
        for row in pending:
            tasks = [t for t in m.get('thread_metrics', []) if t.get('tgid') == row['pid'] and not t.get('identity_ambiguous')]
            weights.append(sum((t.get('runtime_sec') or 0) + (t.get('runqueue_wait_sec') or 0) for t in tasks))
        group_pids = {r['pid'] for r in group}
        occupants = [r for r in rows if r['pid'] and cpus(r['affinity']) & pool]
        unknown_peer = any(r['pid'] not in group_pids for r in occupants)
        if unknown_peer or (len(group) > 1 and (not all(w > 0 for w in weights) or not m.get('scheduler_quality', {}).get('complete'))):
            mapped = cpus(group[0]['affinity'])
            valid_pool = (all(cpus(r['affinity']) == mapped for r in occupants) and
                          all(mapped <= nodes.get(r['numa'][0], set()) for r in group) and
                          pool == mapped & online)
            if valid_pool:
                for row in pending:
                    row['target'] = cpu_list(pool)
                    row['allocation_mode'] = 'SHARED_LOCALITY'
                    row['recommendation_status'] = 'PROPOSED_SHARED'
                    row['reasons'].append('调度证据不足以细分互斥核组；按已核验拓扑、身份及全 TID cpuset 约束到完整在线本地亲和池，组内共享，不按卡数均分。')
                continue
            for row in pending:
                row['blockers'].append('共享池负载证据不完整，且无法核验共同的完整在线本地亲和池')
            continue
        units = defaultdict(set)
        for cpu in pool:
            if cpu in cores:
                units[cores[cpu]].add(cpu)
        # Do not split online SMT siblings, including siblings excluded by cpuset.
        all_units = defaultdict(set)
        for cpu, key in cores.items():
            if cpu in online:
                all_units[key].add(cpu)
        available = [values for key, values in sorted(units.items(), key=lambda item: min(item[1])) if values == all_units[key]]
        occupied = set().union(*(cpus(r['allowed']) for r in preserved)) if preserved else set()
        available = [u for u in available if not u & occupied]
        if len(available) < len(pending):
            for row in pending:
                row['blockers'].append('缺少完整且互斥的在线物理核心/SMT 同胞组')
            continue
        counts = [1] * len(pending)
        extra = len(available) - len(pending)
        total = sum(weights)
        fractions = [extra * w / total if total else extra / len(pending) for w in weights]
        for i, value in enumerate(fractions):
            counts[i] += int(math.floor(value))
        left = len(available) - sum(counts)
        for i in sorted(range(len(pending)), key=lambda i: (-(fractions[i] % 1), pending[i]['pid']))[:left]:
            counts[i] += 1
        offset = 0
        for row, count in zip(pending, counts):
            target = set().union(*available[offset:offset + count]); offset += count
            row['target'] = cpu_list(target)
            row['recommendation_status'] = 'PROPOSED' if not row['blockers'] else 'BLOCKED'
            row['allocation_mode'] = 'EXCLUSIVE_CORE_GROUPS'
            row['reasons'].append('仅使用显式 NPU CPU 映射与全 TID cpuset 交集；完整 SMT 核心组互斥。')
            if len(group) > 1:
                row['reasons'].append('按已观测进程 runtime + runnable wait 权重分配核心组；分配需业务灰度验证。')
    # Pools that look disjoint at logical CPU level may still share one physical core.
    owners = defaultdict(list)
    for row in rows:
        if row.get('allocation_mode') == 'SHARED_LOCALITY':
            continue
        for key in {cores[c] for c in cpus(row['target']) if c in cores}:
            owners[key].append(row)
    for owners_rows in owners.values():
        if len({r['pid'] for r in owners_rows}) > 1:
            for row in owners_rows:
                row['blockers'].append('不同工作进程目标涉及同一物理核心的 SMT 同胞')
    actions = []
    for row in rows:
        row.pop('_candidate', None)
        row['blockers'] = list(dict.fromkeys(row['blockers']))
        row['recommended_cpu'] = row['target']
        row['recommended_numa'] = sorted(n for n, values in nodes.items() if values & cpus(row['target']))
        if row['blockers']:
            row['recommendation_status'] = 'BLOCKED' if row['target'] else 'INSUFFICIENT_EVIDENCE'
        if row['target'] and not row['blockers'] and row['recommendation_status'] != 'PRESERVE':
            actions.append(row)
        if not row['reasons']:
            row['reasons'] = ['当前证据不足以提出安全的具体 CPU 掩码。']
    notes.append('显式硬件亲和用于判断本地性。缺少该字段的 A3 设备可在绑核计划中按可用 NUMA 均衡放置。完整运行/等待证据支持互斥核心组；调度证据不足时仅在拓扑、身份和 cpuset 均已核验后给共享本地亲和池方案，不承诺隔离或性能收益。')
    _, child_evidence = _child_binding_actions(rows, m, online) if context.get('execution_context') == 'host' else ([], [])
    return {'rows': rows, 'notes': notes, 'host_context': context,
            'children': child_evidence,
            'candidate_bindings': _binding_candidates(actions),
            'mapping': {k: v for k, v in mapping.items() if k not in ('by_npu','logic_ids')},
            'process_parser': {k: v for k, v in parsed_info.items() if k != 'processes'},
            'coverage': '显式 NPU CPU 映射/宿主机进程身份/全线程 affinity 与 cpuset/实际 NUMA 页分布/运行与等待证据'}

def _binding_candidates(actions):
    """Return observed process targets that preserve existing narrow masks."""
    targets = {}
    for row in actions:
        target = cpus(row['target'])
        masks = row.get('evidence', {}).get('allowed', {}).values()
        if not any(mask and mask < target for mask in masks):
            targets[row['pid']] = row['target']
    return [{'pid': pid, 'target': target} for pid, target in targets.items()]


def _child_binding_actions(rows, m, online):
    """Expand stable descendants; a child's own NPU mapping takes precedence."""
    snapshot = m.get('snapshot', {})
    batches = [process_batch(snapshot, phase) for phase in ('start', 'end')]
    before, after = [{p['tgid']: p for p in batch.get('processes', [])} for batch in batches]
    roots = {r['pid']: r for r in rows if r['pid']}
    actions, evidence = [], []
    for pid, process in sorted(after.items()):
        if pid in roots:
            continue
        ancestry, current, seen = [], pid, set()
        while current in before and current in after and current not in seen:
            seen.add(current)
            old, new = before[current], after[current]
            if old.get('starttime') != new.get('starttime') or old.get('ppid') != new.get('ppid'):
                break
            ancestry.append(current)
            current = new.get('ppid')
            if current in roots:
                parent = roots[current]
                if parent['blockers'] or not parent['target']:
                    break
                ev = _pid_evidence(snapshot, pid, m)
                target = cpus(parent['target'])
                blockers = []
                if ev['identity_status'] != 'VERIFIED' or not ev['complete']:
                    blockers.append('子进程身份或全线程快照不完整')
                if not target <= online or not target <= ev['cpuset']:
                    blockers.append('子进程有效 cpuset 不允许父进程建议分区')
                for tid in ev['tids']:
                    if not ev['thread_starttime'].get(tid) or not target <= ev['thread_cpuset'].get(tid, set()):
                        blockers.append('子进程 TID 的身份或有效 cpuset 不足')
                row = dict(pid=pid, parent_pid=current, ancestry=ancestry,
                           target=parent['target'], evidence=ev, blockers=blockers)
                evidence.append({k: v for k, v in row.items() if k != 'evidence'})
                if not blockers and not all(values and values <= target for values in ev['allowed'].values()):
                    actions.append(row)
                break
    return actions, evidence
