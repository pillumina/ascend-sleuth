"""Write-ahead affinity journal with identity and ownership checked restoration."""
import copy
import datetime
from itertools import groupby
import json
import os
from pathlib import Path
import tempfile
from .planner import BindError, check_plan


def save_json(path, data, exclusive=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if exclusive:
        fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        os.close(fd)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',dir=str(path.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,str(path))
        if os.name=='posix':
            dfd=os.open(str(path.parent),os.O_RDONLY)
            try:os.fsync(dfd)
            finally:os.close(dfd)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def load_json(path):
    with open(path,encoding='utf-8-sig') as stream:return json.load(stream)


def identity(backend, action, selection):
    if hasattr(backend,'identity'):
        return backend.identity(action['pid'],action['tid'])
    snap=backend.snapshot(selection)
    for p in snap['processes']:
        if p['pid']==action['pid']:
            for t in p['threads']:
                if t['tid']==action['tid']:
                    return dict(pid=p['pid'],tid=t['tid'],process_starttime=str(p['starttime']),
                        thread_starttime=str(t['starttime']),ppid=p['ppid'],ceiling=t.get('ceiling'))
    raise ProcessLookupError('Target exited')


def same_identity(expected, actual):
    return all(str(expected[k])==str(actual[k]) for k in
               ('pid','tid','process_starttime','thread_starttime','ppid'))


def check_context(expected, actual):
    if any(not expected.get(k) or expected[k]!=actual.get(k) for k in
           ('boot_id','pid_namespace','init_pid_namespace')) or actual.get('execution_context')!='host':
        raise BindError('Wrong host/boot/PID namespace; refusing affinity operation')


def audit_plan(plan, backend, before=False):
    check_plan(plan)
    try:
        snap=backend.snapshot(plan['selection']);check_context(plan['context'],snap['context'])
        issues=[]
        if snap['topology']!=plan['topology']:issues.append('CPU/NPU/NUMA/SMT topology changed')
        scope = plan.get('binding_scope')
        actual={t['tid']:(p,t) for p in snap['processes'] if scope != 'main_process' or p.get('npus')
                for t in p['threads']}
        if set(actual)!={a['tid'] for a in plan['actions']}:issues.append('process/thread membership changed; replan required')
        planned_workers={w['pid']:w for w in plan['workers']}
        for p in snap['processes']:
            if p['pid'] in planned_workers:
                w=planned_workers[p['pid']]
                if p['npus']!=w['npus'] or p.get('env',{}).get('LOCAL_RANK')!=w['local_rank'] or p.get('env',{}).get('RANK')!=w['rank']:
                    issues.append('Rank/device ownership changed for PID %s'%p['pid'])
        for a in plan['actions']:
            if a['tid'] not in actual:continue
            p,t=actual[a['tid']]
            ident=dict(pid=p['pid'],tid=t['tid'],process_starttime=p['starttime'],
                       thread_starttime=t['starttime'],ppid=p['ppid'])
            if not same_identity(a,ident):issues.append('PID/TID identity changed: %s'%a['tid'])
            if t.get('ceiling')!=a['ceiling']:issues.append('cpuset changed: %s'%a['tid'])
            if set(t['affinity'])!=set(a['original'] if before else a['target']):
                issues.append('affinity drift: %s'%a['tid'])
        return dict(status='DRIFT' if issues else 'OK',issues=issues)
    except (OSError,BindError,KeyError,ValueError) as exc:
        return dict(status='DRIFT',issues=[str(exc)])


def restore_state(path, backend, journal=None):
    data=copy.deepcopy(journal) if journal is not None else load_json(path)
    if data.get('schema_version')!=1 or not isinstance(data.get('entries'),list):raise BindError('Invalid journal')
    if hasattr(backend,'context'):context=backend.context()
    else:context=backend.snapshot(data['selection'])['context']
    check_context(data['context'],context)
    outcomes=[];persist_errors=[]
    def checkpoint():
        try:save_json(path,data)
        except OSError as exc:persist_errors.append(str(exc))
    for entry in reversed(data['entries']):
        a=entry['action'];tid=a['tid']
        try:
            ident=identity(backend,a,data['selection'])
            if not same_identity(a,ident):
                outcomes.append(dict(tid=tid,status='REUSED',reason='identity changed; left untouched'));continue
            current=backend.get_affinity(tid);original=set(a['original'])
            if current==original:
                outcomes.append(dict(tid=tid,status='RESTORED'));continue
            owned=set(entry.get('observed',a['target']))
            if (entry['phase'] not in ('WRITING','APPLIED','WRITE_FAILED') or current!=owned or
                not owned or not owned<=set(a['target']) or
                (entry['phase']=='WRITE_FAILED' and not entry.get('write_succeeded'))):
                outcomes.append(dict(tid=tid,status='CONFLICT',reason='affinity changed outside this journal'));continue
            ceiling=ident.get('ceiling')
            if ceiling is not None and not original<=set(ceiling):
                outcomes.append(dict(tid=tid,status='FAILED',reason='original mask no longer allowed by cpuset'));continue
            backend.set_affinity(tid,original)
            if backend.get_affinity(tid)!=original:raise BindError('restore readback mismatch')
            if not same_identity(a,identity(backend,a,data['selection'])):raise BindError('identity changed during restore')
            outcomes.append(dict(tid=tid,status='RESTORED'))
        except ProcessLookupError:
            outcomes.append(dict(tid=tid,status='EXITED',reason='target no longer exists'))
        except (OSError,BindError,KeyError,ValueError) as exc:
            outcomes.append(dict(tid=tid,status='FAILED',reason=str(exc)))
        data['restore_results']=outcomes;checkpoint()
    # Threads/children born after planning can inherit a changed mask. Their exact
    # pre-experiment state is unknown: do not guess, and do not claim full rollback.
    try:
        if hasattr(backend,'members'):
            members=backend.members([e['action'] for e in data['entries']],
                                    main_only=data.get('binding_scope')=='main_process')
        else:
            snap=backend.snapshot(data['selection'])
            roots={e['action']['pid'] for e in data['entries']}
            members=[(p['pid'],t['tid'],str(t['starttime'])) for p in snap['processes']
                     if data.get('binding_scope')!='main_process' or p['pid'] in roots for t in p['threads']]
        known={(e['action']['pid'],e['action']['tid'],str(e['action']['thread_starttime'])) for e in data['entries']}
        for pid,tid,birth in members:
            if (pid,tid,birth) not in known:
                outcomes.append(dict(tid=tid,status='UNTRACKED',reason='new task may have inherited affinity; fresh discovery required'))
    except (OSError,BindError) as exc:
        outcomes.append(dict(tid=None,status='UNTRACKED',reason='cannot check new tasks: '+str(exc)))
    bad=bool(persist_errors) or any(r['status'] in ('FAILED','CONFLICT','UNTRACKED') for r in outcomes)
    skipped=any(r['status'] in ('EXITED','REUSED') for r in outcomes)
    data.update(status='RESTORE_INCOMPLETE' if bad else ('RESTORED_WITH_SKIPS' if skipped else 'RESTORED'),
                restore_results=outcomes)
    checkpoint()
    if persist_errors:data['status']='RESTORE_INCOMPLETE'
    return dict(status=data['status'],results=outcomes,journal_errors=persist_errors)


def apply_plan(plan, state_path, backend):
    check_plan(plan)
    if plan.get('binding_scope') != 'main_process':
        raise BindError('Regenerate this plan for main-process taskset -apc execution')
    if Path(state_path).exists():raise BindError('Journal already exists; never overwrite a rollback record')
    audit=audit_plan(plan,backend,before=True)
    if audit['status']!='OK':raise BindError('Preflight failed: '+'; '.join(audit['issues']))
    data=dict(schema_version=1,plan_id=plan['plan_id'],context=plan['context'],selection=plan['selection'],
              binding_scope=plan['binding_scope'],
              created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),status='PREPARED',
              entries=[dict(action=copy.deepcopy(a),phase='PREPARED') for a in plan['actions']])
    save_json(state_path,data,exclusive=True)
    try:
        entries = sorted(data['entries'], key=lambda entry: entry['action']['pid'])
        for pid, group in groupby(entries, key=lambda entry: entry['action']['pid']):
            batch = list(group)
            actions = [entry['action'] for entry in batch]
            target = set(actions[0]['target'])
            if (not target or pid not in {a['tid'] for a in actions} or
                    any(a['root_pid'] != pid or set(a['target']) != target for a in actions)):
                raise BindError('Invalid main-process action for PID %s' % pid)

            for entry in batch:
                entry['phase'] = 'WRITING'
            save_json(state_path, data)
            try:
                for a in actions:
                    ident = identity(backend, a, plan['selection'])
                    if (not same_identity(a, ident) or ident.get('ceiling') != a['ceiling'] or
                            backend.get_affinity(a['tid']) != set(a['original'])):
                        raise BindError('Task changed after journal sync: %s' % a['tid'])
                if hasattr(backend, 'members'):
                    planned = {(pid, a['tid'], a['thread_starttime']) for a in actions}
                    if set(backend.members(actions, main_only=True)) != planned:
                        raise BindError('Main-process thread membership changed: %s' % pid)
            except BaseException:
                for entry in batch:
                    entry['phase'] = 'PREPARED'
                raise

            if any(a['original'] != a['target'] for a in actions):
                # A failed taskset can already have updated some threads.
                # WRITING records allow rollback of masks equal to the planned target.
                backend.set_process_affinity(pid, target)
            for entry, a in zip(batch, actions):
                if not same_identity(a, identity(backend, a, plan['selection'])):
                    raise BindError('Identity changed during write: %s' % a['tid'])
                observed = sorted(backend.get_affinity(a['tid']))
                entry.update(observed=observed, write_succeeded=True)
                if observed != a['target']:
                    raise BindError('Affinity readback mismatch: %s' % a['tid'])
                entry['phase'] = 'APPLIED'
            save_json(state_path, data)
        final=audit_plan(plan,backend)
        if final['status']!='OK':raise BindError('Post-apply audit failed: '+'; '.join(final['issues']))
        data['status']='APPLIED';save_json(state_path,data)
        return data
    except BaseException as exc:
        data['status']='APPLY_FAILED';data['error']=str(exc)
        try:save_json(state_path,data)
        except OSError:pass  # Restoring known changed masks takes priority over an unavailable disk.
        try:recovery=restore_state(state_path,backend,journal=data)
        except BaseException as restore_exc:
            raise BindError('Apply failed (%s); rollback also failed (%s); journal: %s'%(exc,restore_exc,state_path)) from exc
        raise BindError('Apply failed (%s); rollback=%s; journal: %s'%(exc,recovery['status'],state_path)) from exc
