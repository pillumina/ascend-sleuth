"""Observed interval time series. Unknown buckets remain null."""
from .scheduling import percentile


def build_timeseries(m,events,n=120):
    start=m['t_start'];duration=m['duration'];bucket=duration/n if duration else 1
    observed=[0.0]*n;busy=[0.0]*n;cs=[0]*n;lat=[[] for _ in range(n)]
    for span in m['scheduling_intervals']:
        for b in range(max(0,int((span['start']-start)/bucket)),min(n-1,int((span['end']-start)/bucket))+1):
            dt=max(0,min(span['end'],start+(b+1)*bucket)-max(span['start'],start+b*bucket))
            observed[b]+=dt
            if span['tid']!=0: busy[b]+=dt
    for ev in events:
        if ev.etype=='sched_switch':
            b=max(0,min(n-1,int((ev.ts-start)/bucket)));cs[b]+=1
    for w in m['wait_intervals']:
        if w['kind']=='wakeup':
            b=max(0,min(n-1,int((w['end']-start)/bucket)));lat[b].append(1000*(w['end']-w['start']))
    return {'bucket_sec':bucket,'n':n,'util':[100*b/o if o else None for b,o in zip(busy,observed)],
            'cs_rate':[v/bucket if o else None for v,o in zip(cs,observed)],
            'irq_ratio':[None]*n,'softirq_ratio':[None]*n,
            'lat_p99':[percentile(v,99) for v in lat], 'lat_count':[len(v) for v in lat]}


def task_compatibility(m):
    rows=m['thread_metrics']
    observed={}
    for task in rows: observed.setdefault(task['tid'],set()).update(task['cpus'])
    ranked=lambda field: sorted([t for t in rows if t.get(field) is not None],key=lambda t:-(t[field] or 0))
    triples=lambda field:[(t['tid'],t.get('name') or '',t[field]) for t in ranked(field)[:8]]
    return {'top_runtime':triples('runtime_sec'),'top_cs':triples('switch_outs'),
            'top_wakeup':[(t.get('name') or '',t['wakeups']) for t in ranked('wakeups')[:8]],
            'top_migration':triples('migrations'),
            'task_cpus':[(t['tid'],t.get('name') or '',t['cpus'],t['runtime_sec']) for t in ranked('runtime_sec')[:8] if t['runtime_sec']>0],
            'observed_cpus_by_tid':{tid:sorted(cpus) for tid,cpus in observed.items()}}
