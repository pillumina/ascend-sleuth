"""CLI: plan -> apply -> audit -> verify -> rollback. No implicit mutations."""
import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
from .linux import LinuxHost, cpulist
from .planner import BindError, check_plan, digest, make_plan
from .transaction import apply_plan, audit_plan, load_json, restore_state, save_json
from .verify import compare_measurements


@contextmanager
def mutation_lock():
    if os.name!='posix':raise BindError('Affinity execution requires Linux')
    import fcntl
    # Stable across users/state paths; never truncate or follow an attacker supplied symlink.
    path='/tmp/cpu-host-performance.affinity.lock'
    fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:raise BindError('Another affinity experiment is running') from exc
        yield
    finally:os.close(fd)


@contextmanager
def handle_signals():
    def stop(signum,frame):raise KeyboardInterrupt('Received signal %s'%signum)
    old={s:signal.signal(s,stop) for s in (signal.SIGINT,signal.SIGTERM)}
    try:yield
    finally:
        for s,handler in old.items():signal.signal(s,handler)


def build_parser():
    parser=argparse.ArgumentParser(description='Trace-linked Ascend rank/thread CPU affinity workflow (Python 3.8+, stdlib)')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('plan',help='Read-only trace-linked live discovery and NUMA planning')
    p.add_argument('--report-data',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    target=p.add_mutually_exclusive_group(required=True)
    target.add_argument('--pid',help='Host workload root PID(s), comma-separated; include NPU descendants')
    target.add_argument('--main-pid',help='Exact NPU main PID(s), comma-separated')
    target.add_argument('--process-regex',help='Filter NPU occupant cmdline/comm; do not use a generic python match')
    target.add_argument('--worker',action='append',help='Explicit global logic NPU:hostPID, repeatable')
    p.add_argument('--topology-json',type=Path,help='Operator-verified complete global logic NPU->CPU mapping')
    p.add_argument('--allocation',choices=['locality','partition'],default='locality')
    p.add_argument('--framework-binding',choices=['unknown','disabled','absent'],default='unknown',
                   help='Record whether a competing framework CPU binder was checked')
    p=sub.add_parser('apply',help='Preflight, journal, set affinity, readback; --execute required')
    p.add_argument('--plan',required=True,type=Path);p.add_argument('--state',required=True,type=Path)
    p.add_argument('--execute',action='store_true')
    p.add_argument('--watch-seconds',type=float,default=0,help='Bounded audit; drift/new tasks stop and roll back (no PID reconnect)')
    p.add_argument('--interval',type=float,default=1)
    p=sub.add_parser('audit',help='Read-only check of planned live identities, membership, masks and topology')
    p.add_argument('--plan',required=True,type=Path)
    p=sub.add_parser('rollback',help='Restore original masks only for unchanged identities and owned state')
    p.add_argument('--state',required=True,type=Path);p.add_argument('--execute',action='store_true')
    p=sub.add_parser('verify',help='Compare business A/B samples and before/after trace evidence')
    for name in ('before','after','before-report','after-report','plan','state','output'):
        p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--min-gain',type=float,default=2)
    p.add_argument('--max-tail-regression',type=float,default=5)
    p.add_argument('--live-audit',action='store_true',help='Also check current host configuration')
    p.add_argument('--rollback-on-fail',action='store_true',help='Restore on any result except PASS; requires --execute')
    p.add_argument('--execute',action='store_true')
    return parser


def compare_traces(before,after,plan):
    issues=[]
    if digest(before)!=plan['trace_digest']:issues.append('Baseline trace report does not match plan')
    for label,report in [('before',before),('after',after)]:
        context=report.get('metrics',{}).get('npu_affinity',{}).get('host_context',{})
        if any(context.get(k)!=plan['context'].get(k) for k in ('boot_id','pid_namespace','init_pid_namespace')):
            issues.append(label+' trace belongs to another host/boot/namespace')
    from analyzer.process_evidence import process_batch
    snapshot=after.get('metrics',{}).get('snapshot',{})
    for phase in ('start','end'):
        batch=process_batch(snapshot,phase)
        processes={p['tgid']:p for p in batch.get('processes',[])}
        threads={t['tid']:t for t in batch.get('threads',[])}
        for a in plan['actions']:
            p=processes.get(a['pid'],{});t=threads.get(a['tid'],{})
            if (str(p.get('starttime'))!=a['process_starttime'] or
                str(t.get('starttime'))!=a['thread_starttime'] or t.get('tgid')!=a['pid'] or
                sorted(t.get('allowed_cpus') or [])!=a['target']):
                issues.append('after %s trace identity/affinity does not confirm TID %s'%(phase,a['tid']))
        known={a['tid'] for a in plan['actions']}
        roots={w['pid'] for w in plan['workers']}
        for tid,t in threads.items():
            pid=t.get('tgid');seen=set()
            while (plan.get('binding_scope') != 'main_process' and
                   pid in processes and pid not in seen and pid not in roots):
                seen.add(pid);pid=processes[pid].get('ppid')
            if pid in roots and tid not in known:
                issues.append('after %s trace contains unplanned task %s'%(phase,tid))
    keys=('sched','scheduler_quality','thread_metrics','migration_total','contention','npu_affinity','collection_integrity')
    # Raw measured evidence, no claimed speedup from CPU utilization alone.
    return dict(issues=issues,before={k:before.get('metrics',{}).get(k) for k in keys},
                after={k:after.get('metrics',{}).get(k) for k in keys})


def run(args):
    host=LinuxHost()
    if args.command=='plan':
        workers={}
        for value in args.worker or []:
            try:npu,pid=map(int,value.split(':'))
            except ValueError as exc:raise BindError('--worker requires global_logic_NPU:hostPID') from exc
            if pid<=0 or npu<0:raise BindError('Invalid worker NPU/PID')
            workers.setdefault(str(pid),[]).append(npu)
        workers={p:sorted(set(v)) for p,v in workers.items()}
        selection=dict(pids=cpulist(args.pid) if args.pid else [],
                       main_pids=cpulist(args.main_pid) if args.main_pid else [],workers=workers,
                       process_regex=args.process_regex,
                       topology_json=str(args.topology_json.resolve()) if args.topology_json else None)
        snap=host.snapshot(selection)
        plan=make_plan(snap,load_json(args.report_data),args.allocation)
        plan.pop('plan_id');plan['framework_binding']=args.framework_binding;plan['plan_id']=digest(plan)
        save_json(args.output,plan,exclusive=True)
        print(json.dumps(dict(plan_id=plan['plan_id'],workers=plan['workers'],pools=plan['pools'],
                              threads=len(plan['actions']),output=str(args.output)),ensure_ascii=False,indent=2))
        return 0
    if args.command=='audit':
        result=audit_plan(load_json(args.plan),host)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['status']=='OK' else 3
    if args.command=='rollback':
        state=load_json(args.state)
        if not args.execute:
            print(json.dumps(dict(mode='PREVIEW',plan_id=state.get('plan_id'),status=state.get('status'),
                                  threads=len(state.get('entries',[])),hint='Add --execute to restore'),indent=2));return 0
        with mutation_lock(),handle_signals():result=restore_state(args.state,host)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['status'] in ('RESTORED','RESTORED_WITH_SKIPS') else 4
    if args.command=='apply':
        plan=load_json(args.plan);check_plan(plan)
        if not all(math.isfinite(v) for v in (args.watch_seconds,args.interval)) or not 0<=args.watch_seconds<=86400 or args.interval<.2:
            raise BindError('Watch must be 0..86400 seconds and interval >=0.2')
        if not args.execute:
            result=audit_plan(plan,host,before=True);print(json.dumps(dict(mode='PREVIEW',**result),indent=2));return 0 if result['status']=='OK' else 3
        if plan.get('framework_binding') not in ('disabled','absent'):
            raise BindError('Competing framework CPU binder unchecked; regenerate plan with --framework-binding disabled|absent')
        with mutation_lock(),handle_signals():
            apply_plan(plan,args.state,host)
            try:
                deadline=time.monotonic()+args.watch_seconds
                while time.monotonic()<deadline:
                    time.sleep(min(args.interval,max(0,deadline-time.monotonic())))
                    result=audit_plan(plan,host)
                    if result['status']!='OK':raise BindError('Watch detected drift: '+'; '.join(result['issues']))
            except BaseException as exc:
                recovery=restore_state(args.state,host)
                raise BindError('Watch stopped (%s); rollback=%s'%(exc,recovery['status'])) from exc
        print(json.dumps(dict(status='APPLIED',plan_id=plan['plan_id'],state=str(args.state)),indent=2));return 0
    if args.command=='verify':
        if args.rollback_on_fail and not args.execute:raise BindError('--rollback-on-fail requires --execute')
        if any(not math.isfinite(v) or v<0 for v in (args.min_gain,args.max_tail_regression)):
            raise BindError('Experiment thresholds must be finite and nonnegative')
        plan=load_json(args.plan);check_plan(plan);state=load_json(args.state)
        if state.get('plan_id')!=plan['plan_id']:raise BindError('Journal does not match plan')
        before,after=load_json(args.before),load_json(args.after)
        result=compare_measurements(before,after,min_gain=args.min_gain,max_tail_regression=args.max_tail_regression)
        traces=compare_traces(load_json(args.before_report),load_json(args.after_report),plan)
        result.update(plan_id=plan['plan_id'],trace_comparison=traces,
                      affinity_evidence='journal readback; live audit not requested')
        issues=list(traces['issues'])
        if state.get('status')!='APPLIED':issues.append('Journal is not in APPLIED state')
        entries=state.get('entries',[])
        if (len(entries)!=len(plan['actions']) or any(e.get('action')!=a or e.get('phase')!='APPLIED' or
            e.get('observed')!=a['target'] for e,a in zip(entries,plan['actions']))):
            issues.append('Journal does not confirm every planned action/readback')
        if all(a['original']==a['target'] for a in plan['actions']):issues.append('Plan made no affinity changes; no binding experiment to evaluate')
        if after.get('plan_id')!=plan['plan_id']:issues.append('After business samples not associated with this plan_id')
        if args.live_audit:
            audit=audit_plan(plan,host);result['live_audit']=audit
            result['affinity_evidence']='live audit + journal readback'
            issues+=audit['issues']
        if issues:result.update(status='INCONCLUSIVE',decision='INCONCLUSIVE',reason='; '.join(issues))
        # Persist the decision even if the following recovery is interrupted.
        save_json(args.output,result,exclusive=True)
        if args.rollback_on_fail and result['status']!='PASS':
            with mutation_lock(),handle_signals():result['rollback']=restore_state(args.state,host)
            save_json(args.output,result)
        print(json.dumps({k:v for k,v in result.items() if k!='trace_comparison'},ensure_ascii=False,indent=2))
        if result.get('rollback',{}).get('status')=='RESTORE_INCOMPLETE':return 4
        return 0 if result['status']=='PASS' else 3
    raise BindError('Unknown command')


def main(argv=None):
    try:return run(build_parser().parse_args(argv))
    except (BindError,OSError,ValueError,KeyError,TypeError) as exc:
        print('ERROR: %s'%exc,file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
