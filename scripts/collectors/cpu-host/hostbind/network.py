"""Interrupt frequency evidence; counts are never treated as CPU duration."""
import math
import re
from pathlib import Path


def parse_interrupts(text):
    lines=text.splitlines()
    if not lines:raise ValueError('Empty interrupts snapshot')
    cpus=re.findall(r'CPU(\d+)',lines[0])
    if not cpus or len(cpus)!=len(set(cpus)):raise ValueError('Invalid CPU header')
    rows={}
    for line in lines[1:]:
        if ':' not in line:continue
        ident,body=line.split(':',1);ident=ident.strip();parts=body.split()
        if ident in ('ERR','MIS') and len(parts)==1 and parts[0].isdigit():continue
        if len(parts)<len(cpus) or not all(v.isdigit() for v in parts[:len(cpus)]):
            raise ValueError('Malformed per-CPU counter row: '+ident)
        if ident in rows:raise ValueError('Duplicate IRQ identifier')
        rows[ident]=dict(counts=dict(zip(cpus,map(int,parts[:len(cpus)]))),name=' '.join(parts[len(cpus):]))
    return cpus,rows


def interrupt_delta(before,after,seconds):
    result=dict(interval_seconds=seconds,rows=[],movable_candidates=[],issues=[],
                note='Frequency only; excludes IPI/timer from candidate list, not from diagnosis. Candidates require device ownership and affinity support checks.')
    try:
        if isinstance(seconds,bool) or not math.isfinite(seconds) or seconds<=0:
            raise ValueError('Positive interval required')
        cpus,a=parse_interrupts(before);end_cpus,b=parse_interrupts(after)
        if cpus!=end_cpus:raise ValueError('CPU header changed; recollect stable online topology')
        for ident in sorted(set(a)|set(b)):
            if ident not in a or ident not in b:
                result['issues'].append('IRQ appeared/disappeared: '+ident);continue
            if a[ident]['name']!=b[ident]['name']:
                result['issues'].append('IRQ identity changed: '+ident);continue
            delta={c:b[ident]['counts'][c]-a[ident]['counts'][c] for c in cpus}
            if any(v<0 for v in delta.values()):
                result['issues'].append('Counter reset: '+ident);continue
            name=a[ident]['name']
            movable=ident.isdigit() and not re.search(r'arch_timer|\bIPI\b|local.timer',name,re.I)
            row=dict(id=ident,name=name,delta=sum(delta.values()),rate_per_sec=sum(delta.values())/seconds,
                     per_cpu={c:v/seconds for c,v in delta.items()},device_candidate=movable)
            result['rows'].append(row)
        result['rows'].sort(key=lambda r:(-r['rate_per_sec'],r['id']))
        result['movable_candidates']=[r for r in result['rows'] if r['device_candidate'] and r['delta']>0]
    except (ValueError,TypeError) as exc:result['issues'].append(str(exc))
    return result


def capture_inventory(proc=Path('/proc'),sys=Path('/sys')):
    """Read physical/virtual NIC relationships; errors remain explicit evidence gaps."""
    errors=[]
    def read(path):
        try:return path.read_text().strip()
        except OSError as exc:
            errors.append(dict(path=str(path),error=str(exc)));return None
    nics=[]
    for nic in sorted((sys/'class/net').glob('*')):
        device=nic/'device'
        numa=read(device/'numa_node') if device.exists() else None
        try:numa=int(numa) if numa is not None else None
        except ValueError:numa=None
        irq_ids=[p.name for p in (device/'msi_irqs').glob('*') if p.name.isdigit()]
        msi_irqs=sorted(irq_ids,key=int)
        # Legacy INTx may expose only device/irq. Shared lines need separate review.
        if not irq_ids and (device/'irq').exists():
            legacy=read(device/'irq')
            if legacy and legacy.isdigit() and int(legacy)>0:irq_ids=[legacy]
        irq_info={}
        for irq in sorted(irq_ids,key=int):
            irq_info[irq]={key:read(proc/'irq'/irq/key) for key in
                ('smp_affinity_list','effective_affinity_list','smp_affinity','effective_affinity')}
        queues={}
        for queue in sorted((nic/'queues').glob('*')):
            queues[queue.name]={key:read(queue/key) for key in
                ('rps_cpus','rps_flow_cnt','xps_cpus','xps_rxqs') if (queue/key).exists()}
        nics.append(dict(name=nic.name,ifindex=read(nic/'ifindex'),
            pci_device=str(device.resolve()) if device.exists() else None,
            numa_node=numa,local_cpulist=read(device/'local_cpulist') if device.exists() else None,
            lower_devices=[p.name[6:] for p in sorted(nic.glob('lower_*'))],
            master=str((nic/'master').resolve()) if (nic/'master').exists() else None,
            irqs=irq_info,msi_irqs=msi_irqs,queues=queues))
    pci_irq_devices=[]
    nic_paths={nic['pci_device'] for nic in nics if nic['pci_device']}
    for device in sorted((sys/'bus/pci/devices').glob('*')):
        path=str(device.resolve())
        if path in nic_paths:continue
        ids=sorted((entry.name for entry in (device/'msi_irqs').glob('*') if entry.name.isdigit()),key=int)
        if not ids:continue
        node=read(device/'numa_node')
        pci_irq_devices.append(dict(bdf=device.name,pci_device=path,numa_node=int(node) if node and node.isdecimal() else None,
            local_cpulist=read(device/'local_cpulist'),msi_irqs=ids,irqs={irq:{key:read(proc/'irq'/irq/key) for key in
            ('smp_affinity_list','effective_affinity_list')} for irq in ids}))
    return dict(nics=nics,pci_irq_devices=pci_irq_devices,errors=errors)
