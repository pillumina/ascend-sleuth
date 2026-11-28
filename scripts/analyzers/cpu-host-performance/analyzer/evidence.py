"""Versioned sidecar readers. Missing/malformed evidence remains explicit."""
import json


def read_manifest(snapshot):
    raw = snapshot.get('collection_manifest.json', snapshot.get('hostbound/collection_manifest.json'))
    if raw is None:
        return {}, 'LEGACY_NOT_PROVIDED'
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict) or ('entries' in obj and not isinstance(obj['entries'], list)):
            raise ValueError('invalid manifest shape')
        if any(not isinstance(row, dict) for row in obj.get('entries', [])):
            raise ValueError('invalid entry shape')
        return obj, 'COLLECTED' if 'entries' in obj else 'LEGACY_NOT_PROVIDED'
    except (ValueError, TypeError):
        return {}, 'PARSE_FAILED'


def read_json(snapshot, name, default=None):
    raw = snapshot.get('hostbound/' + name, snapshot.get(name, ''))
    try:
        value = json.loads(raw)
        return default if isinstance(default, (dict, list)) and not isinstance(value, type(default)) else value
    except (ValueError, TypeError):
        return default


def read_jsonl(snapshot, name):
    rows, errors = [], 0
    for line in snapshot.get('hostbound/' + name, snapshot.get(name, '')).splitlines():
        try:
            rows.append(json.loads(line))
        except (ValueError, TypeError):
            errors += 1
    return rows, errors


def cpulist(text):
    if isinstance(text, list):
        return set(int(x) for x in text)
    out = set()
    for item in str(text or '').replace(',', ' ').split():
        try:
            if '-' in item:
                lo, hi = map(int, item.split('-', 1))
                if 0 <= lo <= hi < 1048576:
                    out.update(range(lo, hi + 1))
            else:
                out.add(int(item))
        except ValueError:
            pass
    return out


def capabilities(snapshot):
    value=read_json(snapshot,'capabilities.json',{}) or {}
    events=value.get('events',{})
    if not isinstance(events,dict):
        value.setdefault('errors',[]).append('capabilities.events must be an object')
        events={}
    invalid=[key for key,row in events.items() if not isinstance(row,dict)]
    events={key:row for key,row in events.items() if key not in invalid}
    if invalid:
        value.setdefault('errors',[]).append('invalid capability event rows: '+', '.join(invalid))
    value['events']=events
    text=snapshot.get('hostbound/capabilities.tsv','')
    for line in text.splitlines()[1:]:
        cols=line.split('\t')
        if len(cols)<6:
            continue
        event, exists, writable, requested, enabled, reason=cols[:6]
        row={k:v=='1' for k,v in [('exists',exists),('writable',writable),('requested',requested),('enabled',enabled)]}
        if reason not in ('ok','not_requested_minimal'):
            row['error']=reason
        events[event]=row
    return value


def optional_tools(snapshot):
    manifest=read_json(snapshot,'collection_manifest.json',{}) or {}
    declared=manifest.get('external_tools',{})
    if not isinstance(declared,dict):
        declared={}
    tools=[]
    for key,label,patterns in [('gil_tracer','GIL / gil_tracer',('gil',)),('function_monitor','function_monitor',('function_monitor',)),('msprof','msprof',('msprof',)),('host_analyzer','host_analyzer',('host_analyzer',))]:
        paths=[name for name in snapshot if any(p in name.lower() for p in patterns)]
        state='PRESENT_NOT_VALIDATED' if paths else ('NOT_RUN' if declared.get(key)=='not_run' else 'NOT_PROVIDED')
        tools.append({'name':label,'status':state,'evidence':paths,'declared':declared.get(key),
                      'note':'有文件不表示已完成时钟/内容校验；缺失不作为正常性能证据'})
    tools.append({'name':'PMU','status':'NOT_VALIDATED','evidence':[],'note':'本次工具未执行硬件计数器采集，也未提供频率估算'})
    return tools
