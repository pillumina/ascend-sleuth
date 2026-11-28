"""Conservative scheduler reconstruction. All scheduler IDs are TIDs.

Only matching consecutive switches produce runtime. Wakeup latency and runnable
switch-out waits are separate distributions. Boundaries and lost pairs are counted.
"""
from collections import defaultdict
from .evidence import cpulist


def percentile(values, p):
    if not values:
        return None
    vals=sorted(values)
    k=(len(vals)-1)*p/100.0
    lo=int(k); hi=min(lo+1,len(vals)-1)
    return vals[lo]*(hi-k)+vals[hi]*(k-lo) if hi!=lo else vals[lo]


def analyze_scheduling(m, events):
    duration=m['duration']; start=m['t_start']; end=m['t_end']
    by_tid=defaultdict(list)
    for t in m['process_analysis']['tasks']:
        by_tid[t['tid']].append(t)
    rows={}; intervals=[]; waits=[]; cur={}; pending={}; last_cpu={}; exits={}
    quality={'mismatched_switches':0,'unpaired_wakeups':0,'duplicate_wakeups':0,
             'exit_censored_waits':0,'boundary_censored_waits':0,'waking_ignored':0,
             'identity_ambiguous_events':0,'wait_cpu_unknown':0,'exit_without_switch':0,
             'preempt_switches':0,'preempt_switches_unresolved':0}
    def identity(tid,ts):
        if tid<=0:
            return None
        choices=[t for t in by_tid[tid] if t['start_ts']<=ts<=t['end_ts'] and not t['identity_ambiguous']]
        # At an exact fork/exit boundary prefer the newly starting identity.
        if len(choices)>1:
            choices=[t for t in choices if t['end_ts']>ts]
        t=choices[0] if len(choices)==1 else None
        key=t['identity'] if t else '%d:unresolved:%.9f'%(tid,ts)
        if key not in rows:
            rows[key]=dict(t or {'identity':key,'tid':tid,'tgid':None,'name':None,'npu_ids':[],
                                 'role':'UNKNOWN','allowed_cpus':None,'identity_ambiguous':True,'evidence':['TGID/identity unavailable']})
            rows[key].update({'runtime_sec':0.0,'switch_outs':0,'context_switches':0,'wakeups':0,
                              'duplicate_wakeups':0,'runnable_switch_out':0,'explicit_migrations':0,
                              'observed_migrations':0,'runqueue_wait_sec':0.0,'cpus':set(),
                              '_lat':[],'_seen':False,'sched_stat_wait_ns':0})
        if not t:
            quality['identity_ambiguous_events']+=1
        return key
    def interval(cpu, task, stop):
        tid,key,lo=task
        if stop <= lo:
            return
        intervals.append({'cpu':cpu,'start':lo,'end':stop,'tid':tid,'identity':key})
        if key:
            rows[key]['runtime_sec']+=stop-lo
            rows[key]['cpus'].add(cpu)
    cs=defaultdict(int); wake_count=defaultdict(int); runnable_count=defaultdict(int); migrations=defaultdict(int)
    for ev in events:
        et=ev.etype; f=ev.fields; cpu=ev.cpu; ts=ev.ts
        if et=='sched_switch' and cpu is not None:
            prev=int(f.get('prev_pid',-1)); nxt=int(f.get('next_pid',-1))
            if prev<0 or nxt<0:
                quality['mismatched_switches']+=1
                continue
            cs[cpu]+=1
            prevkey=cur[cpu][1] if cpu in cur and cur[cpu][0]==prev else identity(prev,ts)
            nextkey=identity(nxt,ts)
            if cpu in cur:
                task=cur.pop(cpu)
                if task[0]==prev and (not prevkey or task[1]==prevkey):
                    interval(cpu,task,ts)
                else:
                    quality['mismatched_switches']+=1
                    # Unknown switches may have invalidated local runnable state.
                    for k in [k for k,w in pending.items() if w['cpu']==cpu]:
                        quality['unpaired_wakeups']+=pending.pop(k)['kind']=='wakeup'
            if prevkey:
                row=rows[prevkey];row['_seen']=True
                row['switch_outs']+=1;row['context_switches']+=1
                if str(f.get('prev_state','')) in ('R','R+'):
                    row['runnable_switch_out']+=1;runnable_count[cpu]+=1
                    pending.setdefault(prevkey,{'start':ts,'kind':'runnable','cpu':cpu,'moves':[(ts,cpu)]})
            if nextkey:
                row=rows[nextkey];row['_seen']=True;row['context_switches']+=1
                if prev > 0 and str(f.get('prev_state', '')) == 'R+':
                    quality['preempt_switches'] += 1
                    outgoing = rows.get(prevkey, {})
                    previous_tgid = outgoing.get('tgid')
                    next_tgid = row.get('tgid')
                    if not previous_tgid or not next_tgid or outgoing.get('end_ts', ts) < ts:
                        quality['preempt_switches_unresolved'] += 1
                    elif previous_tgid != next_tgid:
                        row['cross_process_preemptions'] = row.get('cross_process_preemptions', 0) + 1
                        row.setdefault('preempted_tgids', set()).add(previous_tgid)
                if nextkey in pending:
                    w=pending.pop(nextkey);dt=ts-w['start']
                    if dt>=0:
                        row['runqueue_wait_sec']+=dt
                        if w['kind']=='wakeup':
                            row['_lat'].append(dt*1000)
                        moves=w['moves']
                        cpu_known=w['cpu']==cpu
                        if not cpu_known:
                            quality['wait_cpu_unknown']+=1
                        waits.append({'identity':nextkey,'tid':nxt,'start':w['start'],'end':ts,'kind':w['kind'],
                                      'cpu_segments':[(lo, moves[i+1][0] if i+1<len(moves) else ts,c) for i,(lo,c) in enumerate(moves)] if cpu_known else [],
                                      'cpu_known':cpu_known})
                lc=last_cpu.get(nextkey)
                if lc is not None and lc!=cpu:
                    row['observed_migrations']+=1
                last_cpu[nextkey]=cpu
                row['cpus'].add(cpu)
            cur[cpu]=(nxt,nextkey,ts)
        elif et in ('sched_wakeup','sched_wakeup_new'):
            if str(f.get('success','1'))=='0':
                continue
            tid=int(f.get('pid',-1)); key=identity(tid,ts)
            if not key:
                continue
            target=int(f.get('target_cpu',cpu if cpu is not None else -1))
            if target>=0:
                wake_count[target]+=1
            rows[key]['wakeups']+=1
            if key in pending or any(x[1]==key for x in cur.values()):
                rows[key]['duplicate_wakeups']+=1;quality['duplicate_wakeups']+=1
                continue
            pending[key]={'start':ts,'kind':'wakeup','cpu':target,'moves':[(ts,target)]}
        elif et=='sched_waking':
            quality['waking_ignored']+=1
        elif et=='sched_process_exit':
            tid=int(f.get('pid',ev.pid));exits[tid]=ts
            for key in [k for k in pending if rows[k]['tid']==tid]:
                w=pending.pop(key)
                quality['unpaired_wakeups']+=w['kind']=='wakeup'
                quality['exit_censored_waits']+=1
        elif et=='sched_migrate_task':
            key=identity(int(f.get('pid',-1)),ts)
            if key:
                rows[key]['explicit_migrations']+=1
                origin=int(f.get('orig_cpu',cpu if cpu is not None else -1))
                if origin>=0:
                    migrations[origin]+=1
                dest=int(f.get('dest_cpu',-1))
                if key in pending:
                    pending[key]['cpu']=dest
                    pending[key]['moves'].append((ts,dest))
        elif et=='sched_stat_wait':
            key=identity(int(f.get('pid',-1)),ts)
            if key:
                rows[key]['sched_stat_wait_ns']+=int(f.get('delay',0))
    for cpu,task in cur.items():
        # No future switch observed: end of known capture window is right-censored.
        stop=exits.get(task[0],end)
        if stop<end:
            quality['exit_without_switch']+=1
        interval(cpu,task,max(task[2],min(end,stop)))
    quality['boundary_censored_waits']=len(pending)
    quality['unpaired_wakeups']+=sum(w['kind']=='wakeup' for w in pending.values())
    quality['loss_statistics_known']=m.get('buffer_overrun_known',False)
    quality['complete']=m.get('buffer_overrun_known',False) and not (m.get('buffer_overrun') or not m.get('events_ok',True) or quality['mismatched_switches'] or quality['unpaired_wakeups'] or quality['identity_ambiguous_events'] or quality['exit_without_switch'])
    quality['note']='runtime 为 sched_switch 区间（含线程上下文内IRQ）；缺失/边界等待不进入延迟分位数；同一TID重复唤醒保留最早成功wakeup，不使用sched_waking。'
    cpus=cpulist(m.get('snapshot',{}).get('cpu_online.txt',''))
    cpus |= cpulist(m.get('snapshot',{}).get('hostbound/cpu_online.txt',''))
    cpus |= {e.cpu for e in events if e.cpu is not None}
    selected=cpulist(m.get('snapshot',{}).get('hostbound/collection_cpus.txt',''))
    if not selected:
        selected=cpulist(m.get('metadata',{}).get('cpu_list_input',''))
    observation=defaultdict(float);busy=defaultdict(float)
    for span in intervals:
        c=span['cpu'];dt=span['end']-span['start']
        observation[c]+=dt
        if span['tid']>0:
            busy[c]+=dt
    per={}
    for cpu in sorted(cpus):
        obs=observation[cpu]
        per[cpu]={'observed_sec':obs, 'observation_scope':'selected' if not selected or cpu in selected else 'not_collected',
                  'util':100*busy[cpu]/obs if obs else None,'idle_ratio':100*(obs-busy[cpu])/obs if obs else None,
                  'util_known':bool(obs), 'cs':cs[cpu],'cs_rate':cs[cpu]/obs if obs else None,
                  'wakeups':wake_count[cpu],'wakeup_rate':wake_count[cpu]/obs if obs and bool(m['available'] & {'sched_wakeup','sched_wakeup_new'}) else None,
                  'preempt':runnable_count[cpu],'runnable_switch_out_rate':runnable_count[cpu]/obs if obs else None,
                  'migration_rate':migrations[cpu]/obs if obs and 'sched_migrate_task' in m['available'] else None}
    # Reuse the same validated transitions as the Frequency/Idle report, so
    # missing events and unsigned exit sentinels have one interpretation.
    from .idle_analysis import analyze_idle
    m['idle'] = analyze_idle(dict(m, per_cpu=per), events)
    cstates=defaultdict(float)
    for row in m['idle']['cpus']:
        cpu = row['cpu']
        for state in row['states']:
            cstates[str(state['state'])] += state['residency_sec']
        if cs[cpu] != 0:
            continue
        if cpu not in per:
            per[cpu] = {'observation_scope': 'selected', 'cs': 0, 'cs_rate': None,
                        'wakeups': 0, 'wakeup_rate': None, 'preempt': 0,
                        'runnable_switch_out_rate': None, 'migration_rate': None,
                        'observed_sec': 0., 'util': None, 'idle_ratio': None, 'util_known': False}
        for part in row['intervals']:
            if part['idle'] is None:
                continue
            dt = part['end']-part['start']
            intervals.append({'cpu': cpu, 'start': part['start'], 'end': part['end'],
                              'tid': 0 if part['idle'] else -1, 'identity': None})
            observation[cpu] += dt
            if not part['idle']:
                busy[cpu] += dt
    # Recompute idle-only CPU observations after fallback intervals have been added.
    for cpu,pc in per.items():
        if cs[cpu]==0 and observation[cpu]>0:
            pc.update(observed_sec=observation[cpu],util=100*busy[cpu]/observation[cpu],idle_ratio=100*(observation[cpu]-busy[cpu])/observation[cpu],util_known=True)
        if 'sched_switch' not in m['available']:pc['cs_rate']=pc['runnable_switch_out_rate']=None
    m['cstate_dist']=dict(cstates)
    total_runtime=sum(t['runtime_sec'] for t in rows.values())
    # Discovered tasks with no scheduling evidence are missing, not measured zero.
    for task in m['process_analysis']['tasks']:
        if task['identity'] not in rows:
            rows[task['identity']]=dict(task,runtime_sec=None,context_switches=None,switch_outs=None,wakeups=None,
                                      duplicate_wakeups=0,runnable_switch_out=None,explicit_migrations=None,observed_migrations=None,
                                      runqueue_wait_sec=None,cpus=set(),_lat=[],_seen=False,sched_stat_wait_ns=None)
    lat=[];top_lat=[]
    for key,t in rows.items():
        t['cpus']=sorted(t['cpus'])
        if 'preempted_tgids' in t:
            t['preempted_tgids'] = sorted(t['preempted_tgids'])
        t['migrations']=t['explicit_migrations'] if t['explicit_migrations'] is not None and 'sched_migrate_task' in m['available'] else t['observed_migrations']
        t['migration_source']='sched_migrate_task' if 'sched_migrate_task' in m['available'] else 'observed CPU changes (lower bound)'
        t['cpu_utilization']=100*t['runtime_sec']/duration if t['runtime_sec'] is not None and duration else None
        t['runtime_share']=100*t['runtime_sec']/total_runtime if t['runtime_sec'] is not None and total_runtime else None
        vals=t.pop('_lat');lat.extend(vals)
        t['wait_samples']=len(vals)
        for p in (50,95,99):
            t['wait_p%d_ms'%p]=percentile(vals,p)
        t['data_quality']='OBSERVED_PARTIAL' if not quality['complete'] or t.get('identity_ambiguous') else 'OBSERVED'
        if vals:
            top_lat.append((t['tid'],t.get('name') or '',max(vals)/1000,sum(vals)/len(vals)/1000,len(vals)))
        t.pop('_seen')
    observed_total=sum(observation.values())
    sch={'cs_total':sum(cs.values()) if 'sched_switch' in m['available'] else None, 'cs_rate':sum(cs.values())/duration if duration and cs else None,
         'wakeup_total':sum(wake_count.values()) if bool(m['available'] & {'sched_wakeup','sched_wakeup_new'}) else None,'wakeup_rate':sum(wake_count.values())/duration if duration and bool(m['available'] & {'sched_wakeup','sched_wakeup_new'}) else None,
         'lat_count':len(lat),'lat_avg':sum(lat)/len(lat) if lat else None,'lat_max':max(lat) if lat else None,
         'runnable_avg':sum(w['end']-w['start'] for w in waits)/duration if waits and duration else None,
         'runnable_note':'已完成等待区间的时间加权下界，不是全系统精确runqueue长度',
         'top_lat_tasks':sorted(top_lat,key=lambda x:-x[2])[:8], 'lat_note':None if lat else '无完整成功 wakeup→switch 配对样本',
         'pairing':quality, 'observed_cpu_sec':observed_total}
    for p in (50,95,99):
        sch['lat_p%d'%p]=percentile(lat,p)
    m.update({'per_cpu':per,'cpu_list':sorted(per),'n_cpus':len(per),'sched':sch,'scheduler_quality':quality,
              'thread_metrics':list(rows.values()),'scheduling_intervals':intervals,'wait_intervals':waits,
              'migration_total':sum(t['migrations'] or 0 for t in rows.values())})
    return m
