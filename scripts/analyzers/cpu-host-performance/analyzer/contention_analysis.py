"""Contention candidates require runnable wait AND same-CPU timeline overlap.

Candidates describe correlation; they never establish NPU performance causality.
"""
from bisect import bisect_right
from collections import defaultdict
from .evidence import read_json
from .process_evidence import process_batch


def _stats(text):
    out={}
    if not isinstance(text,str):
        return out
    for line in (text or '').splitlines():
        parts=line.split()
        if len(parts)==2:
            try: out[parts[0]]=int(parts[1])
            except ValueError: pass
    return out


def cgroup_deltas(snapshot):
    batches=[process_batch(snapshot,stage) for stage in ('start','end')]
    maps=[]
    for batch in batches:
        rows={}
        for p in batch.get('processes',[]):
            for row in p.get('cgroup_cpu',[]) if isinstance(p.get('cgroup_cpu',[]),list) else []:
                if not isinstance(row,dict) or 'path' not in row:
                    continue
                path=row['path']
                item=rows.setdefault(path,dict(row,tgids=[]))
                if p['tgid'] not in item['tgids']: item['tgids'].append(p['tgid'])
        maps.append(rows)
    result=[]
    for path in sorted(set(maps[0])|set(maps[1])):
        before=maps[0].get(path,{});after=maps[1].get(path,{})
        row=after or before
        a=_stats(before.get('cpu.stat'));b=_stats(after.get('cpu.stat'))
        delta=lambda key: b[key]-a[key] if key in a and key in b and b[key]>=a[key] else None
        quota=period=None
        try:
            if row.get('version',2)==2:
                limit,period=row.get('cpu.max','max 100000').split()
                quota=float(limit) if limit!='max' else None;period=float(period)
            else:
                quota=float(row['cpu.cfs_quota_us']);period=float(row['cpu.cfs_period_us'])
                if quota<0: quota=None
        except (KeyError,ValueError,TypeError,AttributeError): pass
        throttled=delta('throttled_usec')
        if row.get('version')==1:
            nanos=delta('throttled_time');throttled=nanos/1000 if nanos is not None else None
        result.append({'path':path,'version':row.get('version'),'tgids':row.get('tgids',[]),
                       'quota_cpus':quota/period if quota is not None and period else None,
                       'quota_status':'LIMITED' if quota is not None else ('UNLIMITED' if row.get('cpu.max','').startswith('max ') or row.get('cpu.cfs_quota_us')=='-1' else 'UNKNOWN'),
                       'nr_periods_delta':delta('nr_periods'), 'nr_throttled_delta':delta('nr_throttled'),'throttled_usec_delta':throttled,
                       'evidence':'process_start/end.json cgroup ancestor cpu.max/cpu.stat deltas',
                       'confidence':'MEDIUM' if throttled is not None else 'LOW',
                       'note':'前后快照包围trace窗口；计数为整个cgroup而非单线程；throttled时间不能视为整机饱和。'})
    return result


def overlapping_intervals(spans, starts, lo, hi):
    index=max(0,bisect_right(starts,lo)-1)
    while index<len(spans):
        span=spans[index]
        if span['start']>=hi:break
        if span['end']>lo:yield span
        index+=1


def analyze_contention(m):
    rows={t['identity']:t for t in m['thread_metrics']}
    per_cpu=defaultdict(list)
    for s in m['scheduling_intervals']:
        per_cpu[s['cpu']].append(s)
    starts={c:[s['start'] for s in spans] for c,spans in per_cpu.items()}
    candidates={}
    for w in m['wait_intervals']:
        target=rows[w['identity']]
        for lo,hi,cpu in w['cpu_segments']:
            if cpu<0 or hi<=lo:
                continue
            spans=per_cpu[cpu]
            for s in overlapping_intervals(spans,starts[cpu],lo,hi):
                dt=min(hi,s['end'])-max(lo,s['start'])
                if dt<=0 or s['tid']<=0 or s['identity']==w['identity']: continue
                contender=rows[s['identity']]
                allowed=target.get('allowed_cpus')
                if allowed is not None and cpu not in allowed:
                    continue  # stale affinity or timeline mismatch; no strong association
                key=(w['identity'],s['identity'])
                out=candidates.setdefault(key,{'target_identity':w['identity'],'target_tid':w['tid'],'target_tgid':target.get('tgid'),
                                              'npu_ids':target.get('npu_ids',[]),'contender_identity':s['identity'],
                                              'contender_tid':s['tid'],'contender_tgid':contender.get('tgid'),
                                              'overlap_sec':0.0,'cpus':set(),'windows':[],
                                              'confidence':'MEDIUM' if m['scheduler_quality']['complete'] else 'LOW',
                                              'causality':'UNPROVEN','evidence':['runnable wait + same CPU running interval',
                                                'affinity snapshot corroborates scope' if allowed is not None else 'affinity unavailable; target_cpu is scheduling evidence']})
                out['overlap_sec']+=dt;out['cpus'].add(cpu)
                out['windows'].append({'start':max(lo,s['start']),'end':min(hi,s['end']),'cpu':cpu,'wait_kind':w['kind']})
    values=sorted(candidates.values(),key=lambda x:-x['overlap_sec'])
    for c in values: c['cpus']=sorted(c['cpus'])
    ai_workers = {t['identity'] for t in rows.values() if t.get('npu_ids') or t.get('category') == 'AI_WORKLOAD'}
    ai_competitors = {c['contender_identity'] for c in values if c['target_identity'] in ai_workers}
    process_tasks = {t['identity']: t for t in m.get('process_analysis', {}).get('tasks', [])}
    for key in ai_competitors:
        row = rows[key]
        row['competes_with_ai'] = True
        row.setdefault('evidence', []).append('Runnable AI wait overlaps this task running on the same CPU; causality unproven')
        if row.get('category') != 'AI_WORKLOAD':
            row['category'] = 'COMPETITOR'
        if key in process_tasks:
            process_tasks[key]['competes_with_ai'] = True
            process_tasks[key]['category'] = row['category']
    if 'system_summary' in m.get('process_analysis', {}):
        tasks = m['process_analysis']['tasks']
        m['process_analysis']['system_summary'].update({
            'ai_threads': sum(t.get('category') == 'AI_WORKLOAD' for t in tasks),
            'competitor_threads': sum(t.get('category') == 'COMPETITOR' for t in tasks),
            'unrelated_threads': sum(t.get('category') == 'UNRELATED' for t in tasks),
            'unknown_threads': sum(t.get('category') == 'UNKNOWN' for t in tasks)})
    # Report affinity intersections only for workload threads seen by scheduler; no quadratic all-system scan.
    active=[t for t in rows.values() if t.get('related') and t.get('runtime_sec') is not None and t.get('allowed_cpus')]
    affinity_total=len(active)
    active=sorted(active,key=lambda t:-(t.get('runqueue_wait_sec') or 0))[:512]
    overlaps=[]
    for i,a in enumerate(active):
        for b in active[i+1:]:
            common=set(a['allowed_cpus'])&set(b['allowed_cpus'])
            if common:
                overlaps.append({'a_tid':a['tid'],'b_tid':b['tid'],'cpus':sorted(common),'causality':'UNPROVEN'})
    ranks={}
    for name,field in [('runtime','runtime_sec'),('wait','runqueue_wait_sec'),('runnable','runnable_switch_out'),('migration','migrations')]:
        ranks[name]=[t['identity'] for t in sorted(rows.values(),key=lambda t:-(t.get(field) or 0)) if t.get(field) is not None][:20]
    device=read_json(m['snapshot'],'device_windows.json',{}) or {}
    correlations=[]
    if isinstance(device,dict) and device.get('clock')=='mono' and m.get('metadata',{}).get('trace_clock')=='mono':
        for c in values:
            for window in device.get('windows',[]) if isinstance(device.get('windows'),list) else []:
                if not isinstance(window,dict) or not all(isinstance(window.get(k),(int,float)) for k in ('start','end')):
                    continue
                if window.get('npu_id') in c['npu_ids'] and any(max(window['start'],w['start'])<min(window['end'],w['end']) for w in c['windows']):
                    correlations.append({'target_tid':c['target_tid'],'npu_id':window['npu_id'],'window':window,'causality':'UNPROVEN'})
    return {'candidates':values,'rankings':ranks, 'ai_workers': sorted(ai_workers, key=lambda key: -(rows[key].get('runqueue_wait_sec') or 0)),
            'ai_competitors': sorted(ai_competitors, key=lambda key: -(rows[key].get('runtime_sec') or 0)),
            'system_top': ranks['runtime'], 'display_limits': {'system_top':20,'candidate_preview_windows':3,'all_threads':'collapsed; full JSON retained'},
            'affinity_overlaps':overlaps,'affinity_scope':{'active_workload_threads':affinity_total,'compared_threads':len(active),'truncated':affinity_total>len(active),'reason':'按已观测等待排序，最多512个活跃关联线程做成对Affinity比较；全线程Affinity仍保留在thread_metrics'},'cgroups':cgroup_deltas(m['snapshot']),
            'workers':[t['identity'] for t in rows.values() if t.get('npu_ids')],
            'hot_cores':[{'cpu':c,'util':pc['util'],'threads':[s['tid'] for s in per_cpu[c] if s['tid']>0]} for c,pc in m['per_cpu'].items() if (pc.get('util') or 0)>=90],
            'device_correlation':{'status':'ALIGNED' if correlations else ('NOT_PROVIDED' if not device else 'NO_PROVEN_OVERLAP_OR_CLOCK_ALIGNMENT'), 'matches':correlations},
            'note':'高CPU占用、共享Affinity或R/R+切出均不单独构成竞争根因；候选是相关性，NPU性能因果需同域Device时间线与受控复测。'}
