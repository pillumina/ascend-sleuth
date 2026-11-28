"""Pure NUMA planning. Rank labels never establish physical device ownership."""
import copy
import hashlib
import json
import re


class BindError(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
                                    allow_nan=False).encode()).hexdigest()


def role(name, tid, pid):
    for pattern, label in [('acl_thread','acl'),('release_thread','release'),
                           ('hccl|nccl','collective'),('pt_data_worker|dataloader|data_loader','dataloader'),
                           ('tokeniz','tokenizer'),('pin_memory','pin_memory'),
                           ('zmqbg|hccn|hccp','communication'),('rt_recycle','release'),
                           ('caffetaskthread','dispatch'),('monitor|plog|adx_data_dump_t|traceclientrecv|report_ras','observability'),
                           ('^dev_|npu','device'),('vllm|python3','main' if tid==pid else 'runtime')]:
        if re.search(pattern,name,re.I):return label
    return 'main' if tid==pid else 'unknown'


def pools_for(topology, allocation):
    online=set(topology['online']);mapping=topology['npu_cpus']
    if not mapping or not online:raise BindError('Missing explicit NPU affinity / online CPUs')
    groups={};pools={}
    for npu, values in sorted(mapping.items(),key=lambda x:int(x[0])):
        pool=set(values)&online
        if not pool:raise BindError('NPU %s has no online local CPUs'%npu)
        nodes={topology['cpu_node'].get(str(c)) for c in pool}
        if None in nodes or len(nodes)!=1:raise BindError('Unknown or cross-NUMA NPU pool: %s'%npu)
        groups.setdefault(tuple(sorted(pool)),[]).append(str(npu))
        pools[str(npu)]=sorted(pool)
    if allocation=='locality':return pools
    if allocation!='partition':raise BindError('Unknown allocation')
    signatures=list(groups)
    for i,sig in enumerate(signatures):
        for other in signatures[i+1:]:
            if set(sig)&set(other):raise BindError('Partially overlapping NPU pools cannot be partitioned')
    all_groups=[]
    for sig, npus in groups.items():
        units=[];seen=set()
        for cpu in sig:
            sib=set(topology['siblings'].get(str(cpu),[]))&online
            if cpu not in sib or not sib<=set(sig):raise BindError('Incomplete SMT sibling group')
            for sibling in sib:
                if set(topology['siblings'].get(str(sibling),[]))&online!=sib:
                    raise BindError('Asymmetric SMT sibling data')
            if cpu not in seen:units.append(sorted(sib));seen.update(sib)
        if len(units)<len(npus):raise BindError('Insufficient whole physical cores for all NPUs')
        for old in all_groups:
            if old&set(sig):raise BindError('SMT cores overlap across NPU pools')
        all_groups.append(set(sig))
        offset=0
        for i,npu in enumerate(npus):
            count=len(units)//len(npus)+(i<len(units)%len(npus))
            pools[npu]=sorted(c for unit in units[offset:offset+count] for c in unit)
            offset+=count
    return pools


def process_target(affinities, pool):
    """Intersect thread CPU ceilings and preserve existing local masks."""
    common = set(pool)
    local_masks = set()
    for allowed, ceiling in affinities:
        if not allowed:
            return set()
        permitted = set(ceiling) if ceiling is not None else allowed
        common &= permitted
        if allowed <= pool and allowed <= permitted:
            local_masks.add(frozenset(allowed))
    if not common or len(local_masks) > 1:
        return set()
    if not local_masks:
        return common
    existing = set(next(iter(local_masks)))
    # Keep an existing mask without shrinking other threads just to match it.
    if existing == common or (existing <= common and all(mask == existing for mask, _ in affinities)):
        return existing
    return set()


def make_plan(snapshot, report, allocation='locality'):
    context=snapshot['context'];metrics=report.get('metrics',{})
    old=metrics.get('npu_affinity',{}).get('host_context',{})
    for key in ('boot_id','pid_namespace','init_pid_namespace'):
        if not context.get(key) or old.get(key)!=context[key]:
            raise BindError('Trace/live host identity mismatch: '+key)
    if context.get('execution_context')!='host' or context['pid_namespace']!=context['init_pid_namespace']:
        raise BindError('Host PID namespace required')
    pools=pools_for(snapshot['topology'],allocation)
    processes={p['pid']:p for p in snapshot['processes']}
    roots={pid:p for pid,p in processes.items() if p.get('npus')}
    if not roots:raise BindError('No verified NPU worker was selected')
    births={a['pid']:str(a['process_starttime']) for a in metrics.get('binding_plan',{}).get('actions',[])
            if a.get('process_starttime') is not None}
    generations={pid:{birth} for pid,birth in births.items()}
    # Include evidence even when the old conservative plan could not propose an action.
    for row in metrics.get('binding_plan',{}).get('tasks',[]):
        if row.get('process_starttime'):
            births[row['pid']]=str(row['process_starttime'])
            generations.setdefault(row['pid'],set()).add(births[row['pid']])
    for phase in ('start','end'):
        for path,raw in metrics.get('snapshot',{}).items():
            if path.rsplit('/',1)[-1]=='process_%s.json'%phase:
                try:batch=json.loads(raw) if isinstance(raw,str) else raw
                except (ValueError,TypeError):continue
                for p in batch.get('processes',[]):
                    if p.get('starttime') is not None:
                        pid=int(p['tgid']);births[pid]=str(p['starttime'])
                        generations.setdefault(pid,set()).add(births[pid])
    actions=[];workers=[]
    for pid,p in sorted(roots.items()):
        if len(generations.get(pid,set()))>1:raise BindError('Worker PID reused within trace: %s'%pid)
        if births.get(pid)!=str(p['starttime']):raise BindError('Worker absent from trace or PID reused: %s'%pid)
        signatures={tuple(pools.get(str(n),[])) for n in p['npus']}
        if len(signatures)!=1 or not next(iter(signatures)):
            raise BindError('PID %s uses distinct/unknown NPU pools; TID-device mapping required'%pid)
        env=p.get('env',{})
        workers.append(dict(pid=pid,npus=p['npus'],local_rank=env.get('LOCAL_RANK'),
                            rank=env.get('RANK'),rank_source='proc_environ' if env.get('LOCAL_RANK') else 'unknown'))
    for pid, p in sorted(roots.items()):
        pool = set(pools[str(p['npus'][0])])
        threads = sorted(p['threads'], key=lambda t: t['tid'])
        if not threads or pid not in {t['tid'] for t in threads}:
            raise BindError('Main PID %s has an incomplete thread list' % pid)
        affinities = []
        for t in threads:
            allowed = set(t['affinity'])
            if not allowed or not str(t['starttime']).isdigit():
                raise BindError('Invalid thread identity/affinity')
            affinities.append((allowed, t.get('ceiling')))
        target = process_target(affinities, pool)
        if not target:
            raise BindError('PID %s has no common safe mask that preserves existing local affinity' % pid)
        for t in threads:
            actions.append(dict(pid=pid, tid=t['tid'], process_starttime=str(p['starttime']),
                thread_starttime=str(t['starttime']), ppid=p['ppid'], root_pid=pid,
                role=role(t['name'],t['tid'],pid), name=t['name'],
                original=sorted(t['affinity']), target=sorted(target), ceiling=t.get('ceiling')))
    if not actions:raise BindError('No live threads')
    plan=dict(schema_version=1,binding_scope='main_process',context=copy.deepcopy(context),topology=copy.deepcopy(snapshot['topology']),
              selection=copy.deepcopy(snapshot['selection']),allocation=allocation,pools=pools,
              workers=workers,actions=actions,trace_digest=digest(report),
              baseline_host_status=report.get('diagnosis',{}).get('host_status'),
              warnings=['Thread roles are name hints, not proof of bottlenecks.',
                        'CPU affinity does not migrate memory or isolate CPUs from other jobs.',
                        'Multiple PIDs on one NPU share that NPU pool; no per-PID isolation claimed.'])
    plan['plan_id']=digest(plan)
    return plan


def check_plan(plan):
    value=dict(plan);expected=value.pop('plan_id',None)
    if plan.get('schema_version')!=1 or not expected or digest(value)!=expected:
        raise BindError('Invalid or edited plan; generate a fresh plan')
