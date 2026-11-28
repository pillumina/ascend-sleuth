"""IRQ/softirq paired handler intervals over effective scheduler observation time."""
from collections import defaultdict
from .evidence import capabilities


def merge(spans):
    result=[]
    for a,b in sorted(spans):
        if result and a<=result[-1][1]:
            result[-1]=(result[-1][0],max(result[-1][1],b))
        elif b>a:
            result.append((a,b))
    return result


def intersection(a,b):
    i=j=0;total=0.0
    while i<len(a) and j<len(b):
        total+=max(0,min(a[i][1],b[j][1])-max(a[i][0],b[j][0]))
        if a[i][1]<b[j][1]: i+=1
        else: j+=1
    return total


def analyze_interrupts(m,events):
    from .metrics import SOFTIRQ_VEC_NAMES
    caps=capabilities(m['snapshot']).get('events',{})
    for kind,prefix,name_key,top_key in [('irq','irq_handler','name','top_names'),('softirq','softirq','action','top_actions')]:
        pending=defaultdict(list);spans=defaultdict(list);named=defaultdict(lambda:[0,0.0]);count=defaultdict(int)
        missed=0
        for ev in events:
            if ev.etype not in (prefix+'_entry',prefix+'_exit') or ev.cpu is None:
                continue
            ident=str(ev.fields.get('irq' if kind=='irq' else 'vec','?'))
            key=(ev.cpu,ident)
            if ev.etype.endswith('_entry'):
                name=ev.fields.get(name_key)
                if name is None:
                    name=ident if kind=='irq' else SOFTIRQ_VEC_NAMES.get(int(ident) if ident.isdigit() else -1,'vec'+ident)
                pending[key].append((ev.ts,name))
            elif pending[key]:
                lo,name=pending[key].pop()
                if ev.ts>=lo:
                    spans[ev.cpu].append((lo, ev.ts, ident, name));count[ev.cpu]+=1
                    named[name][0]+=1;named[name][1]+=ev.ts-lo
            else:
                missed+=1
        missed+=sum(len(v) for v in pending.values())
        observed=defaultdict(list)
        for span in m['scheduling_intervals']:
            observed[span['cpu']].append((span['start'],span['end']))
        enabled=all(caps.get('irq/'+prefix+'_'+part,{}).get('enabled') for part in ('entry','exit'))
        seen={prefix+'_entry',prefix+'_exit'}<=m['available']
        available=seen or enabled
        complete=available and not (missed or m.get('buffer_overrun') or not m.get('events_ok',True))
        denominator=sum(pc['observed_sec'] for pc in m['per_cpu'].values())
        total=0.0;per={}
        for c,pc in m['per_cpu'].items():
            seconds=intersection(merge((lo, hi) for lo, hi, _, _ in spans[c]),merge(observed[c]))
            total+=seconds
            ratio=100*seconds/pc['observed_sec'] if available and pc['observed_sec'] and (complete or seconds>0) else None
            per[c]=ratio
            pc[kind+'_time']=seconds if ratio is not None else None
            pc[kind+'_ratio']=ratio
            pc[kind+'_count']=count[c] if available else None
        known = [cpu for cpu, ratio in per.items() if ratio is not None]
        peak = max(known, key=per.get) if known else None
        source_spans = defaultdict(list)
        for lo, hi, ident, name in spans.get(peak, []):
            source_spans[(ident, name)].append((lo, hi))
        peak_observed = merge(observed.get(peak, []))
        sources = []
        for (ident, name), intervals in source_spans.items():
            seconds = intersection(merge(intervals), peak_observed)
            if seconds > 0:
                sources.append({'id': ident, 'name': name, 'seconds': seconds})
        sources.sort(key=lambda row: -row['seconds'])
        result={'total_count':sum(count.values()) if available else None,'total_time':total if available else None,
                'total_ratio':100*total/denominator if available and denominator and (complete or total>0) else None,
                'max_cpu_ratio':per.get(peak), 'peak_cpu':peak,
                'peak_sources':sources[:3],'observed_cpu_sec':denominator,
                'per_cpu_ratio':per,top_key:sorted([(name,n,t) for name,(n,t) in named.items()],key=lambda x:-x[2])[:10],
                'all_names' if kind=='irq' else 'all_actions':sorted([(name,n,t) for name,(n,t) in named.items()],key=lambda x:-x[2]),
                'available':available,'complete':complete,'unpaired_events':missed,
                'ratio_kind':'handler interval union / effective observed CPU time',
                'note':'配对handler区间占比，不覆盖全部硬中断入口/IPI开销；SoftIRQ区间可能含嵌套IRQ，二者不可简单相加。'}
        if kind=='softirq':
            raises=defaultdict(int)
            for ev in events:
                if ev.etype=='softirq_raise':
                    raises[str(ev.fields.get('action',ev.fields.get('vec','?')))]+=1
            result['raise_counts']=dict(raises)
        m[kind]=result
    # C-state residency has its own validated time intervals. Scheduler idle
    # ratio remains per_cpu.idle_ratio and must not overwrite that evidence.
    m.setdefault('idle', {'per_cpu_ratio': {}, 'available': False})
    m['idle']['cstate_dist'] = m.get('cstate_dist', {})
    return m
