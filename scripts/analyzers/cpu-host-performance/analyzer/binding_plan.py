"""Build a customer configuration from the observed AI task inventory."""
import re
from collections import defaultdict
from .npu_affinity import _pid_evidence, cpus, cpu_list, _get, _topology
from .process_evidence import process_batch
from hostbind.planner import process_target
from hostbind.placement import A3_POLICY, EXPLICIT, node_order, supports_balancing
from hostbind.delivery import RUN_COMMAND, TEMPLATE, task_entry


def _role(name, process, tid, pid, direct):
    text = str(name or '').lower()
    if 'release_thread' in text:
        return '资源回收线程'
    if 'acl_thread' in text:
        return 'ACL 下发线程'
    if re.search(r'dataloader|pt_data_worker|data_loader', text):
        return '数据加载线程/进程'
    if 'tokeniz' in text:
        return '分词线程/进程'
    if 'hccl' in text or 'nccl' in text:
        return '集合通信线程'
    if re.search(r'engine_?core', text):
        return '推理引擎'
    if re.search(r'torchrun|deepspeed|accelerate', str(process.get('cmdline', '')), re.I) and tid == pid:
        return 'AI 启动器'
    if tid == pid and 'python' in (text + str(process.get('name', '')).lower()):
        return 'Python 主线程' + (' / NPU 主进程' if direct else '')
    if tid == pid and direct:
        return 'NPU 主进程'
    if 'python' in text:
        return 'Python 工作线程'
    return 'AI 工作线程（职责未确认）' if tid != pid else 'AI 关联进程'


def _legacy_threads(snapshot, pid, ev):
    rows = []
    for line in _get(snapshot, 'pid_%d_threads.txt' % pid).splitlines():
        fields = line.split()
        if len(fields) >= 6 and all(x.isdigit() for x in fields[:3]) and int(fields[0]) == pid:
            tid = int(fields[1])
            rows.append(dict(tid=tid, tgid=pid, name=' '.join(fields[5:]), last_cpu=int(fields[2]),
                             allowed_cpus=sorted(ev['allowed'].get(tid, set())), starttime=None))
    return rows


def _balance_missing(roots, nodes, online):
    by_device = defaultdict(list)
    fixed = defaultdict(set)
    blocked_devices = set()
    for root in roots.values():
        if root['source'] == A3_POLICY:
            by_device[root['npu_ids'][0]].append(root)
        elif root['reason']:
            blocked_devices.update(root['npu_ids'])
        else:
            for node, values in nodes.items():
                if values & root['pool']:
                    fixed[node].update(root['npu_ids'])
    counts = {node: len(devices) for node, devices in fixed.items()}
    for npu, owners in sorted(by_device.items()):
        if npu in blocked_devices:
            for root in owners:
                root['reason'] = '同一 NPU 的其他占卡进程身份或 CPU 范围未核实'
            continue
        candidates = {}
        for node, values in nodes.items():
            targets = []
            for root in owners:
                ev = root['evidence']
                available = values & online
                for tid in ev['tids']:
                    available &= ev['allowed'][tid] & ev['thread_cpuset'][tid]
                if ev['cpuset']:
                    available &= ev['cpuset']
                if not available:
                    break
                targets.append(available)
            if len(targets) == len(owners):
                candidates[node] = targets
        if not candidates:
            for root in owners:
                root['reason'] = 'A3 均衡策略找不到所有占卡进程均可用的 NUMA；需核验在线 CPU、线程掩码和 cpuset'
            continue
        node = node_order(candidates, counts)[0]
        counts[node] = counts.get(node, 0) + 1
        for root, target in zip(owners, candidates[node]):
            root['pool'] = target


def build_binding_plan(m):
    snapshot = m.get('snapshot', {})
    data = m.get('npu_affinity', {})
    context = data.get('host_context', {})
    _, nodes, _ = _topology(snapshot)
    online = cpus(_get(snapshot, 'cpu_online.txt'))
    batches = [process_batch(snapshot, phase) for phase in ('start', 'end')]
    before, after = [{p['tgid']: p for p in batch.get('processes', [])} for batch in batches]
    processes = dict(before)
    processes.update(after)
    raw_threads = defaultdict(list)
    for row in batches[1].get('threads', []) or batches[0].get('threads', []):
        if isinstance(row.get('tgid'), int) and row['tgid'] > 0:
            raw_threads[row['tgid']].append(dict(row))
    by_pid = defaultdict(list)
    for row in data.get('rows', []):
        if row.get('pid'):
            by_pid[row['pid']].append(row)

    roots = {}
    for pid, rows in by_pid.items():
        ev = _pid_evidence(snapshot, pid, m)
        mapped = [cpus(r.get('affinity', '')) for r in rows]
        pool = set().union(*mapped) if all(mapped) else set()
        known = set().union(*nodes.values()) if nodes else set()
        reason = ''
        if not pool or not pool <= known:
            reason = '缺少明确的 NPU→CPU/NUMA 映射'
        elif len({tuple(sorted(values)) for values in mapped}) > 1:
            reason = '同进程使用不同 NPU CPU 池；缺少 TID/rank 分工，不能替所有线程选择并集'
        elif sum(bool(pool & values) for values in nodes.values()) != 1:
            reason = 'NPU 亲和 CPU 跨 NUMA 节点'
        elif not online:
            reason = '缺少在线 CPU 范围'
        if (ev['identity_status'] == 'AMBIGUOUS' or not ev['namespace_ok'] or
            ev['status'].get('Pid') != str(pid) or ev['status'].get('Tgid') != str(pid) or
            not str(ev['starttime']).isdigit()):
            reason = 'NPU 主进程 %d 的身份或命名空间未通过核验' % pid
        pool &= online
        if len(rows) == 1 and rows[0].get('target') and not rows[0].get('blockers'):
            pool = cpus(rows[0]['target'])
        source = EXPLICIT if all(mapped) else None
        if any(r.get('ownership_error') for r in rows):
            reason = next(r['ownership_error'] for r in rows if r.get('ownership_error'))
        elif any(r.get('mapping_status') == 'CONFLICT' for r in rows):
            reason = 'NPU 显式亲和数据冲突或无效，不能使用策略覆盖'
        elif not all(mapped) and supports_balancing(m.get('product_identity', {})):
            if len(rows) != 1 or len(rows[0].get('chips', [])) > 1:
                reason = '同一 PID 涉及多个设备，缺少可核验的共同池或 TID/rank 分工'
            elif (ev['identity_status'] != 'VERIFIED' or not ev['complete'] or pid not in ev['tids']
                  or not all(ev['thread_cpuset'].get(t) and ev['thread_starttime'].get(t) for t in ev['tids'])):
                reason = 'A3 策略需要稳定占卡 PID、完整 TID 身份及逐线程有效 cpuset'
            else:
                source, reason = A3_POLICY, ''
        roots[pid] = dict(pool=pool, evidence=ev, reason=reason, source=source,
                          npu_ids=sorted({r['npu'] for r in rows}))
        if pid not in processes:
            processes[pid] = dict(tgid=pid, name=rows[0].get('name'), ppid=int(ev['status'].get('PPid', '0')) if str(ev['status'].get('PPid', '0')).isdigit() else None)
        if not raw_threads[pid]:
            raw_threads[pid] = _legacy_threads(snapshot, pid, ev)
        if not raw_threads[pid]:
            raw_threads[pid] = [dict(tid=pid, tgid=pid, name=processes[pid].get('name'),
                                    allowed_cpus=sorted(ev['allowed'].get(pid, set())), starttime=None)]

    _balance_missing(roots, nodes, online)

    # Relate descendants and AI ancestors through observed, stable parent links.
    associations = defaultdict(set)
    ancestors = set()
    for root in roots:
        associations[root].add(root)
        current, seen = root, set()
        while current in before and current in after and current not in seen:
            seen.add(current)
            old, new = before[current], after[current]
            if old.get('starttime') != new.get('starttime') or old.get('ppid') != new.get('ppid'):
                break
            current = int(new.get('ppid') or 0)
            if current <= 1:
                break
            p = processes.get(current, {})
            if re.search(r'python|torchrun|vllm|sglang|mindie|engine|deepspeed|accelerate',
                         str(p.get('name', '')) + ' ' + str(p.get('cmdline', '')), re.I):
                associations[current].add(root)
                ancestors.add(current)
    for pid in processes:
        current, seen = pid, set()
        while current in processes and current not in seen:
            seen.add(current)
            if current in roots:
                associations[pid].add(current)
                break
            old, new = before.get(current), after.get(current)
            if not old or not new or old.get('starttime') != new.get('starttime') or old.get('ppid') != new.get('ppid'):
                break
            current = int(new.get('ppid') or 0)

    # Explicit workload roots can at least reproduce their observed configuration.
    explicit = cpus(str(m.get('metadata', {}).get('hostbound_pid', '')))
    for task in m.get('process_analysis', {}).get('tasks', []):
        pid = task.get('tgid')
        if pid and task.get('related') and (pid in explicit or task.get('role') != 'SYSTEM_PROCESS'):
            associations.setdefault(pid, set())

    inventory, actions = [], []
    for pid, root_ids in sorted(associations.items()):
        p = processes.get(pid, {})
        ev = roots[pid]['evidence'] if pid in roots else _pid_evidence(snapshot, pid, m)
        desired = set().union(*(roots[root]['pool'] for root in root_ids)) if root_ids else set()
        root_reasons = [roots[root]['reason'] for root in root_ids if roots[root]['reason']]
        root_reason = '; '.join(dict.fromkeys(root_reasons))
        problem = root_reason
        if not root_ids and pid not in explicit:
            problem = '未建立稳定的 NPU 主进程关系，不能继承其 CPU 方案'
        if context.get('execution_context') != 'host':
            problem = '未确认采集宿主机命名空间'
        elif not context.get('boot_id'):
            problem = '缺少宿主机 boot_id'
        elif (context.get('pid_namespace') and context.get('init_pid_namespace') and
              context['pid_namespace'] != context['init_pid_namespace']):
            problem = '采集端 PID 命名空间与 init 不一致'
        elif ev['identity_status'] == 'AMBIGUOUS' or not ev['namespace_ok']:
            problem = 'PID/TID 身份变化或命名空间对应关系不明确'
        elif ev['status'].get('Pid') != str(pid) or ev['status'].get('Tgid') != str(pid):
            problem = '宿主机 PID/TGID 对应关系不一致'
        elif not ev['starttime'] or not str(ev['starttime']).isdigit():
            problem = '缺少用于现场核对进程身份的 starttime'
        tids = raw_threads.get(pid, [])
        if not tids:
            tids = [dict(tid=pid, tgid=pid, name=p.get('name'), allowed_cpus=[], starttime=None)]
        masks = [set(t.get('allowed_cpus') or ev['allowed'].get(t['tid'], set())) for t in tids]
        if not problem and pid not in roots:
            problem = '关联进程或辅助任务，仅展示'
        if not problem and (not ev['complete'] or {t['tid'] for t in tids} != set(ev['tids'])):
            problem = '主进程线程清单不完整'
        target = set()
        if not problem:
            affinities = [
                (mask, t['cpuset_cpus_effective'] if t.get('cpuset_cpus_effective') is not None
                 else ev['thread_cpuset'].get(t['tid']) or None)
                for t, mask in zip(tids, masks)
            ]
            target = process_target(affinities, desired)
            if not target:
                problem = '没有可统一使用的本地 CPU 掩码，或现有本地线程掩码不同、需保留'
        source = roots[pid]['source'] if pid in roots else None
        if target:
            actions.append(dict(pid=pid, tid=pid, target=cpu_list(target), scope='process',
                                placement_source=source, npu_ids=roots[pid]['npu_ids'],
                                process_starttime=ev['starttime'], thread_starttime=ev['starttime']))
        npu_ids = sorted({npu for root in root_ids for npu in roots[root]['npu_ids']})
        for t, allowed in sorted(zip(tids, masks), key=lambda pair: (pair[0]['tid'] != pid, pair[0]['tid'])):
            tid = t['tid']
            thread_birth = t.get('starttime') or (ev['starttime'] if tid == pid else None)
            inventory.append(dict(pid=pid, tid=tid, ppid=p.get('ppid'), name=t.get('name') or p.get('name') or '',
                process_starttime=ev['starttime'], thread_starttime=thread_birth,
                rank=(p.get('rank_env') or {}).get('RANK'),
                local_rank=(p.get('rank_env') or {}).get('LOCAL_RANK'),
                rank_note='环境标签；子进程可能继承，不用于推断全局 NPU ID',
                role=_role(t.get('name'), p, tid, pid, pid in roots),
                object_type='NPU 主进程' if tid == pid and pid in roots else ('AI 线程' if tid != pid else ('AI 启动/父进程' if pid in ancestors else ('AI 子进程' if root_ids else 'AI 关联进程'))),
                npu_ids=npu_ids, placement_source=source, current_cpu=cpu_list(allowed), target_cpu=cpu_list(target),
                numa=sorted(n for n, values in nodes.items() if values & target),
                status=('BLOCKED' if pid in roots else 'OBSERVED') if problem else 'RUNTIME_CHECK_REQUIRED',
                reason=problem or ('A3 缺少硬件 CPU Affinity；按占卡任务在可用 NUMA 间均衡放置'
                                   if source == A3_POLICY else '依据显式 NPU CPU Affinity')))
    design = {'custom_bind': [task_entry(a['pid'], a['target'], all_threads=True) for a in actions]}
    return dict(tasks=inventory, actions=actions, design=design,
                commands=RUN_COMMAND if actions else '', script=TEMPLATE.read_bytes().decode('utf-8'),
                note='配置按占卡主 PID 覆盖其当前线程组；关联进程在清单中单列。')
