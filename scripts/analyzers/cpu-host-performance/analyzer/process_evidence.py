"""Shape checked process sidecars; malformed data is not identity evidence."""
from .evidence import read_json


def process_batch(snapshot, stage):
    value = read_json(snapshot, 'process_' + stage + '.json', {})
    if not isinstance(value, dict):
        value = {}
    result = dict(value)
    errors = list(value.get('errors', [])) if isinstance(value.get('errors', []), list) else []
    for field, identifier in [('processes', 'tgid'), ('threads', 'tid')]:
        rows = value.get(field, [])
        if not isinstance(rows, list):
            rows = []
            errors.append('process_%s.json:%s must be a list' % (stage, field))
        valid = []
        for row in rows:
            if not isinstance(row, dict):
                errors.append('process_%s.json:%s row is not an object' % (stage, field))
                continue
            try:
                item = dict(row)
                item[identifier] = int(item[identifier])
                if item[identifier] <= 0:
                    raise ValueError()
                if item.get('tgid') is not None:
                    item['tgid'] = int(item['tgid'])
                if field == 'processes':
                    item['ppid'] = int(item.get('ppid') or 0)
                if item.get('allowed_cpus') is not None:
                    if not isinstance(item['allowed_cpus'], list):
                        raise ValueError()
                    item['allowed_cpus'] = [int(c) for c in item['allowed_cpus'] if int(c) >= 0]
                for key in ('namespace_pids', 'cpuset_cpus_effective', 'cpuset_mems_effective'):
                    if item.get(key) is None:
                        continue
                    if not isinstance(item[key], list):
                        errors.append('process_%s.json:%s %s is not a numeric list' % (stage, field, key))
                        item[key] = []
                        continue
                    try:
                        item[key] = [int(v) for v in item[key] if int(v) >= 0]
                    except (ValueError, TypeError, OverflowError):
                        errors.append('process_%s.json:%s %s contains a nonnumeric value' % (stage, field, key))
                        item[key] = []
                if item.get('cgroup') is not None and not isinstance(item['cgroup'], str):
                    errors.append('process_%s.json:%s cgroup is not text' % (stage, field))
                    item['cgroup'] = ''
                if 'rank_env' in item:
                    env=item['rank_env'] if isinstance(item['rank_env'],dict) else {}
                    keys=('RANK','LOCAL_RANK','WORLD_SIZE','LOCAL_WORLD_SIZE','GROUP_RANK',
                          'ASCEND_RT_VISIBLE_DEVICES','ASCEND_VISIBLE_DEVICES','CUDA_VISIBLE_DEVICES')
                    item['rank_env']={k:v for k,v in env.items() if k in keys and isinstance(v,str) and len(v)<=256}
            except (ValueError, TypeError, KeyError, OverflowError):
                errors.append('process_%s.json:%s row lacks valid numeric identity/CPU fields' % (stage, field))
                continue
            valid.append(item)
        result[field] = valid
    result['errors'] = errors
    return result
