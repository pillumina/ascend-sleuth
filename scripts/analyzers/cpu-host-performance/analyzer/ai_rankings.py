"""Aggregate observed AI task runtime and scheduler preemptions by name."""


def summarize_ai_rankings(metrics):
    quality = metrics['scheduler_quality']
    workers = set(metrics['contention']['ai_workers'])
    tasks = metrics['thread_metrics']
    ai_tgids = {task['tgid'] for task in tasks if task['identity'] in workers and task.get('tgid')}
    rankings = {'processes': {}, 'threads': {}}
    for task in tasks:
        tgid = task.get('tgid')
        if task.get('identity_ambiguous') or (task['identity'] not in workers and tgid not in ai_tgids):
            continue
        runtime = task.get('runtime_sec') or 0.0
        preemptions = task.get('cross_process_preemptions', 0)
        if not runtime and not preemptions:
            continue
        for kind, name, identity in (
            ('processes', task.get('process_name'), tgid),
            ('threads', task.get('name'), task['identity']),
        ):
            if not name or not identity:
                continue
            group = rankings[kind].setdefault(name, {
                'name': name, 'runtime_sec': 0.0, 'cross_process_preemptions': 0,
                'instances': set(), 'tgids': set(), 'tids': set(), 'preempted_tgids': set(),
            })
            group['runtime_sec'] += runtime
            group['cross_process_preemptions'] += preemptions
            group['instances'].add(identity)
            group['tids'].add(task['tid'])
            if tgid:
                group['tgids'].add(tgid)
            group['preempted_tgids'].update(task.get('preempted_tgids', []))

    result = {'duration_sec': metrics['duration'], 'complete': quality['complete'],
              'preempt_switches': quality['preempt_switches'],
              'preempt_switches_unresolved': quality['preempt_switches_unresolved']}
    for kind, groups in rankings.items():
        for group in groups.values():
            group['instance_count'] = len(group.pop('instances'))
            for key in ('tgids', 'tids', 'preempted_tgids'):
                group[key] = sorted(group[key])
        result[kind] = sorted(groups.values(), key=lambda group: group['name'])
    return result
