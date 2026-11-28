"""Supplementary Linux read-only NIC/IRQ evidence (requires complete skill folder)."""
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hostbind.network import capture_inventory, interrupt_delta


def raw_snapshot():
    errors=[];raw={}
    start=time.monotonic()
    for path in ('/proc/interrupts','/proc/softirqs','/proc/stat','/proc/net/dev',
                 '/proc/net/softnet_stat','/proc/sys/kernel/random/boot_id',
                 '/sys/devices/system/cpu/online','/proc/sys/net/core/rps_sock_flow_entries'):
        try:raw[path]=Path(path).read_text()
        except OSError as exc:errors.append(dict(path=path,error=str(exc)))
    end=time.monotonic()
    return dict(monotonic=start,read_span_seconds=end-start,raw=raw,errors=errors)


def command(args):
    if not shutil.which(args[0]):return dict(status='COMMAND_NOT_FOUND',argv=args)
    try:
        p=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                         timeout=3,text=True,errors='replace')
        return dict(status='COLLECTED' if p.returncode==0 else 'COMMAND_FAILED',argv=args,
                    returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)
    except (OSError,subprocess.TimeoutExpired) as exc:
        return dict(status='FAILED',argv=args,error=str(exc))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interval',type=float,default=5,help='Seconds between counter snapshots (0.1..60)')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not sys.platform.startswith('linux'):
        parser.error('Collection requires the Linux host; offline planning also works on Windows')
    if not math.isfinite(args.interval) or not .1<=args.interval<=60:parser.error('interval must be 0.1..60')
    if args.output.exists():parser.error('Output exists; use a new capture path')
    inventory_before=capture_inventory()
    before=raw_snapshot();time.sleep(args.interval);after=raw_snapshot()
    inventory_after=capture_inventory()
    raw1,raw2=before['raw'],after['raw']
    delta=interrupt_delta(raw1.get('/proc/interrupts',''),raw2.get('/proc/interrupts',''),
                          after['monotonic']-before['monotonic'])
    for key in ('/proc/sys/kernel/random/boot_id','/sys/devices/system/cpu/online'):
        if not raw1.get(key) or raw1.get(key)!=raw2.get(key):
            delta['issues'].append('Identity/online evidence missing or changed: '+key)
            delta['movable_candidates']=[]
    if inventory_before['nics']!=inventory_after['nics']:
        delta['issues'].append('NIC/IRQ/queue topology or affinity changed during capture')
        delta['movable_candidates']=[]
    commands={'irqbalance':command(['systemctl','is-active','irqbalance'])}
    for nic in inventory_after['nics']:
        if nic['pci_device']:
            commands[nic['name']]={flag:command(['ethtool',flag,nic['name']])
                                  for flag in ('-i','-l','-x','-c','-S')}
    result=dict(schema_version=1,kind='network_evidence',before=before,after=after,
                inventory_before=inventory_before,inventory_after=inventory_after,
                interrupt_delta=delta,commands_after_window=commands,
                note='Read-only. Use repeated representative windows and ftrace durations for CPU sizing. No packet rate or IRQ count to CPU-core conversion.')
    try:
        with args.output.open('x',encoding='utf-8') as handle:json.dump(result,handle,ensure_ascii=False,indent=2)
    except OSError as exc:print(str(exc),file=sys.stderr);return 2
    print(str(args.output))
    return 0


if __name__=='__main__':sys.exit(main())
