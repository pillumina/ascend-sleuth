"""Task identity and relation evidence; a scheduler PID is a Linux TID.

Unknown TGIDs stay null. A fork tracepoint alone cannot distinguish clone threads.
"""
import re
from .evidence import read_json, cpulist
from .npu_affinity import _processes
from .process_evidence import process_batch

FRAMEWORK = r'\b(?:torchrun|deepspeed|accelerate|vllm|sglang|mindspore|tensorflow|tritonserver|mindie|megatron)\b|mindie[_-](?:service|server|worker)|torch\.distributed|pytorch|ascend.*(?:worker|infer|train)'
ROLE_HINTS = [('DATA_LOADER',r'dataloader|pt_data_worker'), ('TOKENIZER',r'tokenizer'),
              ('HCCL_THREAD',r'hccl'), ('ACL_THREAD',r'acl_thread|release_thread'),
              ('OMP_THREAD',r'libgomp|\bomp\b|openmp'), ('ENGINE_CORE',r'enginecore|engine_core'),
              ('API_SERVER',r'api_server|vllm.*serve')]


def classify(task, process, direct, related):
    text = ' '.join([str(task.get('name') or ''), str(process.get('name') or ''), str(process.get('cmdline') or '')]).lower()
    evidence = []
    if direct:
        evidence.append('npu-smi PID→TGID direct relation')
    if related:
        evidence.append('root/ancestor/descendant/cgroup relation')
    framework = bool(re.search(FRAMEWORK, text))
    if related or framework:
        for role, pattern in ROLE_HINTS:
            if re.search(pattern, text):
                return role, 'MEDIUM', evidence + (['framework cmdline + thread/process role evidence'] if framework else []) + ['role hint from comm/cmdline (not causal proof)']
        if direct:
            return 'NPU_WORKER', 'HIGH', evidence
        if 'python' in text and task['tid'] == task.get('tgid'):
            return 'PYTHON_MAIN', 'MEDIUM', evidence + ['process leader and python cmdline']
    if process.get('kernel_thread'):
        return 'SYSTEM_PROCESS', 'HIGH', ['proc/stat: PF_KTHREAD']
    if re.search(r'^(?:sshd|systemd|cron|bash|sh|rsyslogd|journald|nginx)(?:\s|$)', str(task.get('name') or ''), re.I):
        return 'SYSTEM_PROCESS', 'MEDIUM', ['system service name + observed task; no verified AI relationship']
    return 'UNKNOWN', 'LOW', evidence or ['no verified workload relationship']


def analyze_processes(m, events):
    snap = m.get('snapshot', {})
    before = process_batch(snap, 'start')
    after = process_batch(snap, 'end')
    procs = {int(p['tgid']): dict(p) for batch in (before, after) for p in batch.get('processes', [])}
    process_generations = {}
    for batch in (before, after):
        for p in batch['processes']:
            if str(p.get('starttime', '')).isdigit():
                process_generations.setdefault(p['tgid'], set()).add(str(p['starttime']))
    reused_processes = {pid for pid, stamps in process_generations.items() if len(stamps) > 1}
    errors = before.get('errors', []) + after.get('errors', [])
    npu = {}
    parsed_npu = _processes(snap.get('hostbound/npu_smi_info_start.txt','')+'\n'+snap.get('hostbound/npu_smi_info.txt', snap.get('npu_smi_info.txt','')))
    npu_rows = [dict(p, npu=n) for n, group in parsed_npu.items() for p in group.values()]
    for p in npu_rows:
        npu.setdefault(p['pid'], set()).add(p['npu'])
    # A device PID may be a namespace PID. Never remap a colliding number by name.
    context = snap.get('hostbound/host_context.txt', snap.get('host_context.txt', ''))
    namespace_ambiguous = set()
    explicit_host = bool(re.search(r'^execution_context=host\s*$', context, re.M))
    explicit_container = bool(re.search(r'^execution_context=container\s*$', context, re.M))
    if explicit_container:
        namespace_ambiguous.update(npu)
        errors.append('NPU PID namespace cannot be matched to local TGIDs in explicit container context; no host ownership inferred')
    if not explicit_host:
        for pid in npu:
            aliases = [p['tgid'] for p in procs.values() if pid in (p.get('namespace_pids') or [])[1:]]
            if aliases:
                namespace_ambiguous.add(pid)
                errors.append('NPU PID%d namespace is ambiguous (namespace aliases %s); no host PID inferred' % (pid, aliases))
    unsafe = namespace_ambiguous | reused_processes
    for pid in unsafe:
        npu.pop(pid, None)
    roots = cpulist(m.get('metadata', {}).get('hostbound_pid', '')) - {0,1}
    roots -= unsafe
    before_process_ids = {p['tgid'] for p in before['processes'] if str(p.get('starttime', '')).isdigit()}
    after_process_ids = {p['tgid'] for p in after['processes'] if str(p.get('starttime', '')).isdigit()}
    verified_processes = before_process_ids & after_process_ids - unsafe
    related = set(npu) | roots
    # Walk ancestors, but never traverse all descendants of init/systemd.
    for pid in list(related):
        seen = set()
        while pid in procs and pid not in seen:
            seen.add(pid)
            pid = int(procs[pid].get('ppid', 0))
            if pid <= 1:
                break
            related.add(pid)
    def group_key(process):
        raw=process.get('cgroup') or ''
        paths=[]
        for line in raw.splitlines():
            fields=line.split(':',2)
            path=fields[2] if len(fields)==3 else line
            if path and path not in ('/', '/system.slice', '/user.slice', '/init.scope', '/kubepods.slice'):
                paths.append((fields[1] if len(fields)==3 else '',path))
        return tuple(paths) or None
    descend=set(npu)|roots|{p for p in related if re.search(r'torchrun|vllm|deepspeed|accelerate|enginecore',str(procs.get(p,{}).get('cmdline','')),re.I)}
    groups={group_key(procs[p]) for p in set(npu)|roots if p in procs}-{None}
    changed=True
    while changed:
        changed=False
        for pid,p in procs.items():
            if pid in descend: continue
            hints = ' '.join(str(p.get(k) or '') for k in ('name', 'cmdline'))
            same_group = group_key(p) in groups and bool(re.search(FRAMEWORK, hints, re.I))
            if pid not in unsafe and (int(p.get('ppid',0)) in descend or same_group):
                descend.add(pid);related.add(pid);changed=True
    tasks = []
    by_key = {}
    for label, batch in [('start', before), ('end', after)]:
        batch_procs={p['tgid']:p for p in batch.get('processes',[])}
        for row in batch.get('threads', []):
            t = dict(row)
            tid = int(t['tid'])
            p = batch_procs.get(t.get('tgid'),procs.get(t.get('tgid'),{}))
            key = '%d:%s:%s' % (tid, t.get('starttime', 'unknown'), p.get('starttime', 'unknown'))
            if key in by_key:
                by_key[key]['snapshots'].append(label)
                by_key[key]['end_snapshot'] = t
                continue
            t.update({'identity': key, 'process_name': p.get('name'), 'cmdline': p.get('cmdline'),
                      'ppid': p.get('ppid'), 'cgroup': p.get('cgroup'), 'process_identity': '%s:%s'%(t.get('tgid'),p.get('starttime','unknown')), 'identity_ambiguous': False,
                      'start_ts': m['t_start'], 'end_ts': m['t_end'], 'snapshots': [label],
                      'evidence': ['proc/%s/task/%s/stat+status:%s' % (t.get('tgid'),tid,label)]})
            tasks.append(t)
            by_key[key] = t
    # Legacy archives: explicit ps -T columns provide TID/TGID; comm never does.
    if not tasks:
        for path, text in snap.items():
            mm = re.search(r'pid_(\d+)_threads.txt$', path)
            if not mm:
                continue
            for line in text.splitlines():
                vals = line.split()
                if len(vals) >= 6 and vals[0].isdigit() and vals[1].isdigit():
                    tid, tgid = int(vals[1]), int(vals[0])
                    tasks.append({'tid':tid,'tgid':tgid,'identity':'%d:legacy'%tid,'name':' '.join(vals[5:]),
                                  'process_name':None,'starttime':None,'start_ts':m['t_start'],'end_ts':m['t_end'],
                                  'snapshots':['legacy'],'identity_ambiguous':False,'evidence':[path], 'allowed_cpus':None})
    active = {}
    for t in tasks:
        if 'start' in t['snapshots'] or 'legacy' in t['snapshots']:
            active[t['tid']] = t
    def unknown(tid, ts, name='', source='trace', parent=None):
        t = {'tid':tid, 'tgid':None, 'identity':'%d:trace:%.9f' % (tid,ts), 'name':name,
             'starttime':None,'start_ts':ts,'end_ts':m['t_end'],'snapshots':[],
             'identity_ambiguous':False,'allowed_cpus':None,'evidence':[source], 'parent_tid':parent}
        tasks.append(t)
        return t
    for ev in events:
        f = ev.fields
        if ev.etype in ('sched_process_fork', 'task_newtask'):
            tid = int(f.get('child_pid', f.get('pid', -1)))
            parent = int(f.get('parent_pid', ev.pid))
            if tid <= 0:
                continue
            current=active.get(tid)
            # Both tracepoints describe one birth, not two generations.
            same_birth=current and (('sched_process_fork' in current['evidence'] and ev.etype=='task_newtask') or ('task_newtask' in current['evidence'] and ev.etype=='sched_process_fork'))
            candidates=[t for t in tasks if t['tid']==tid and 'end' in t['snapshots'] and 'start' not in t['snapshots']]
            if same_birth:
                t=current
            else:
                t=candidates[0] if len(candidates)==1 else unknown(tid,ev.ts,f.get('child_comm',f.get('comm','')),ev.etype,parent)
                if current is not None and current is not t: current['end_ts']=ev.ts
                t['start_ts']=ev.ts
            t['evidence'].append(ev.etype)
            t['parent_tid']=parent
            active[tid]=t
            if ev.etype=='task_newtask':
                try:
                    # Linux task_newtask prints clone_flags using %lx, including bare hex.
                    flags=int(str(f.get('clone_flags','0')),16)
                except ValueError:
                    flags=0
                if flags&0x10000 and parent in active:
                    t['tgid']=active[parent].get('tgid')
                elif 'clone_flags' in f and not flags&0x10000:
                    t['tgid']=tid
        elif ev.etype == 'sched_process_exit':
            tid = int(f.get('pid',ev.pid))
            t = active.pop(tid, None)
            if t:
                t['end_ts'] = ev.ts
                t['evidence'].append('sched_process_exit')
        elif ev.etype == 'sched_process_exec':
            tid = int(f.get('pid',ev.pid))
            if tid in active:
                active[tid]['exec_filename'] = f.get('filename')
                active[tid]['evidence'].append('sched_process_exec')
    generations={}
    for t in tasks:generations.setdefault(t['tid'],[]).append(t)
    for group in generations.values():
        if len(group)<2:continue
        for t in group:
            if any(other is not t and max(t['start_ts'],other['start_ts'])<min(t['end_ts'],other['end_ts']) for other in group):
                t['identity_ambiguous']=True
                t['evidence'].append('PID reuse: generation boundary not observed')
    # Trace-only tasks are retained as competitors, with unknown process attribution.
    known = set(t['tid'] for t in tasks)
    for ev in events:
        pairs = []
        if ev.etype == 'sched_switch':
            pairs = [(ev.fields.get(k+'_pid',-1),ev.fields.get(k+'_comm','')) for k in ('prev','next')]
        elif ev.etype in ('sched_wakeup','sched_wakeup_new','sched_migrate_task'):
            pairs = [(ev.fields.get('pid',-1),ev.fields.get('comm',''))]
        for pid, name in pairs:
            tid = int(pid)
            if tid > 0 and tid not in known:
                unknown(tid,m['t_start'],name,'trace only: TGID unknown')
                known.add(tid)
    for t in tasks:
        tgid = t.get('tgid')
        t['process_name']=t.get('process_name') or procs.get(tgid,{}).get('name')
        t['ppid']=t.get('ppid',procs.get(tgid,{}).get('ppid'))
        t['related'] = tgid in related
        ids = set(npu.get(tgid, set()))
        parent = tgid
        seen = set()
        while parent in procs and parent not in seen:
            seen.add(parent)
            parent = int(procs[parent].get('ppid',0))
            ids.update(npu.get(parent,set()))
        if tgid in reused_processes:
            t['identity_ambiguous'] = True
            t['evidence'].append('Process TGID reused across process snapshots')
        if t.get('identity_ambiguous') or tgid in namespace_ambiguous:
            ids=set();t['related']=False
            t['evidence'].append('NPU ownership not attributed across ambiguous PID generations')
        t['npu_ids'] = sorted(ids)
        t['npu_relation'] = 'direct' if tgid in npu else ('ancestor association' if ids else 'unknown')
        verified_ownership = bool(ids and explicit_host and tgid in verified_processes)
        t['ownership_status'] = 'VERIFIED' if verified_ownership else ('UNVERIFIED' if ids else 'UNKNOWN')
        if ids and not verified_ownership:
            t['npu_relation'] = 'unverified numeric PID/ancestor match'
        t['task_group'] = 'WORKLOAD' if t['related'] else 'UNASSIGNED'
        role, confidence, evidence = classify(t, procs.get(tgid, {}), tgid in npu and not t.get('identity_ambiguous'), t['related'])
        t.update({'role':role,'confidence':confidence})
        if ids and not verified_ownership:
            t['confidence'] = 'LOW'
            evidence.append('NPU PID namespace or process generation unverified; ownership requires host-context and stable identity confirmation')
        t['evidence'].extend(evidence)
        t['category'] = 'AI_WORKLOAD' if t['related'] or role not in ('UNKNOWN', 'SYSTEM_PROCESS') else ('UNRELATED' if role == 'SYSTEM_PROCESS' else 'UNKNOWN')
        if t.get('identity_ambiguous') or tgid in namespace_ambiguous:
            t['category'] = 'UNKNOWN'
            t['confidence'] = 'LOW'
        t['relation_evidence'] = [e for e in t['evidence'] if any(k in e for k in ('relation', 'framework', 'NPU', 'namespace', 'root'))]
    summary = {'total_processes': len(procs), 'total_threads': len(tasks),
               'ai_threads': sum(t['category']=='AI_WORKLOAD' for t in tasks), 'competitor_threads': 0,
               'unrelated_threads': sum(t['category']=='UNRELATED' for t in tasks),
               'unknown_threads': sum(t['category']=='UNKNOWN' for t in tasks),
               'confidence_counts': {level: sum(t['confidence']==level for t in tasks) for level in ('HIGH','MEDIUM','LOW')}}
    return {'tasks':tasks,'processes':list(procs.values()),'related_tgids':sorted(related), 'npu_processes':npu_rows,
            'snapshots_available':bool(before['processes'] or after['processes'] or before['threads'] or after['threads']), 'errors':errors,
            'system_summary': summary, 'unsafe_npu_pids': sorted(unsafe),
            'note':'短生命周期任务无 /proc 或 clone_flags 证据时 TGID 保持未知；名称只用于角色提示。'}


def resolve_task(analysis, tid, ts):
    candidates = [t for t in analysis['tasks'] if t['tid']==tid and t['start_ts'] <= ts <= t['end_ts'] and not t['identity_ambiguous']]
    return candidates[0] if len(candidates)==1 else None
