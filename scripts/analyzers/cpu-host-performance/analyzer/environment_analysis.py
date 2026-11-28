"""Normalize environment sidecars independently of scheduling and binding evidence."""
import json
import re
from pathlib import PurePosixPath


NATIVE_DUMP_CATEGORY = 'environment_dump'
ENV_CATEGORIES = ('environment_host', 'environment_ascend', 'environment_process', NATIVE_DUMP_CATEGORY)
TARGET_FIELDS = ('exe', 'environment', 'limits', 'libraries')
PREFIX = 'hostbound/environment/'
NATIVE_DUMP_PATH = PREFIX + 'msprechecker_dumped.json'
PID_PATH = re.compile(r'hostbound/environment/pid_([1-9][0-9]*)\.json')
VERSION_KEY = re.compile(r'version(?:_dir)?|ascend-cann-atb version|ascend-mindie(?: version)?', re.I)
LIMIT = re.compile(r'(Max .+?)\s{2,}(\S+)\s+(\S+)(?:\s+(\S+))?\s*$')


def _object(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    return value if isinstance(value, str) else None


def is_native_dump(data):
    obj = _object(data)
    return ('traceEvents' not in obj and 'systemTraceEvents' not in obj and
            _object(obj.get('_meta')).get('tool') in ('msprechecker_dump.py', 'msprechecker'))


def read_native_dump(raw):
    data = json.loads(raw)
    if not is_native_dump(data):
        raise ValueError('缺少 msprechecker 原生 Dump 标识。')
    return data


def _assignments(raw):
    return dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)


def _target_field(field, raw):
    if field == 'environment':
        return _assignments(raw)
    if field == 'libraries':
        return sorted(set(raw.splitlines()))
    if field == 'limits':
        values = {}
        for line in raw.splitlines():
            match = LIMIT.fullmatch(line)
            if match:
                name, soft, hard, unit = match.groups()
                values[name] = {'soft': soft, 'hard': hard, 'unit': unit}
        if not values:
            raise ValueError('未解析到进程资源限额。')
        return values
    return raw.strip()


def parse_environment_value(category, path, raw):
    """Parse only supported sidecar shapes. Unrecognized versions remain unknown."""
    if category == 'environment_process':
        match = PID_PATH.fullmatch(path)
        data = json.loads(raw)
        if (not match or not isinstance(data, dict) or data.get('pid') != int(match[1])
                or not re.fullmatch(r'[0-9]+', str(data.get('starttime', '')))):
            raise ValueError('目标 PID 或 starttime 无效。')
        result = {'pid': data['pid'], 'starttime': int(data['starttime'])}
        for field in TARGET_FIELDS:
            item = data.get(field)
            if not isinstance(item, dict) or item.get('status') not in (
                    'COLLECTED', 'UNSUPPORTED', 'PERMISSION_DENIED', 'EXECUTION_FAILED'):
                raise ValueError('目标进程快照字段无效：' + field)
            status = item['status']
            value = None
            reason = item.get('reason')
            if status == 'COLLECTED':
                if not isinstance(item.get('text'), str):
                    raise ValueError('目标进程快照缺少文本：' + field)
                try:
                    value = _target_field(field, item['text'])
                except ValueError as exc:
                    status, reason = 'PARSE_FAILED', str(exc)
            result[field] = {'status': status, 'source': item.get('source'),
                             'reason': reason, 'value': value}
        return result

    name = PurePosixPath(path).stem
    value = raw.strip()
    if category == 'environment_ascend':
        versions = []
        for line in raw.splitlines():
            key, sep, text = line.partition('=' if '=' in line else ':')
            if sep and VERSION_KEY.fullmatch(key.strip()) and text.strip():
                versions.append(text.strip().strip('"\''))
        value = ' / '.join(dict.fromkeys(versions))
    elif name == 'os_release':
        fields = _assignments(raw)
        value = next((fields[key].strip('"\'') for key in ('PRETTY_NAME', 'NAME', 'ID')
                      if fields.get(key)), '')
    elif name == 'thp':
        match = re.search(r'\[([^\]]+)\]', value)
        value = match[1] if match else value
    if not value:
        raise ValueError('未解析到可用的环境字段。')
    return value


def _native_field(value, source, data=None):
    data = data or {}
    state = data.get('collection_status')
    status = {'failed': 'EXECUTION_FAILED', 'unavailable': 'UNAVAILABLE',
              'skipped': 'NOT_REQUESTED'}.get(state if isinstance(state, str) else '')
    return {'value': value, 'source': source, 'reason': _text(data.get('reason')) or _text(data.get('error')),
            'status': status or ('COLLECTED' if value is not None else 'UNKNOWN')}


def _native_environment(data):
    """Build a report view while retaining the original JSON as separate evidence."""
    meta = data['_meta']
    time = _text(meta.get('timestamp'))
    system = _object(data.get('system'))
    hardware = _object(data.get('hardware'))
    os_release = _object(system.get('os_release'))
    os_name = next((os_release[key].strip('"\'') for key in ('PRETTY_NAME', 'NAME', 'ID')
                    if isinstance(os_release.get(key), str) and os_release[key]), None)
    kernel = ' '.join(system[key] for key in ('system', 'release', 'machine')
                      if isinstance(system.get(key), str))
    params = _object(hardware.get('kernel_params'))
    host = []
    for key, value, source in (
            ('os_release', os_name, 'system.os_release'),
            ('kernel', kernel or None, 'system.system/release/machine'),
            ('thp', system.get('transparent_hugepage'), 'system.transparent_hugepage'),
            ('numa_balancing', params.get('kernel.numa_balancing'), 'hardware.kernel_params.kernel.numa_balancing'),
            ('swappiness', params.get('vm.swappiness'), 'hardware.kernel_params.vm.swappiness'),
            ('overcommit_memory', system.get('overcommit_memory'), 'system.overcommit_memory'),
            ('clocksource', _object(hardware.get('clock')).get('clocksource'), 'hardware.clock.clocksource')):
        if isinstance(value, (str, int)):
            host.append(dict(_native_field(value, source), id=key, collected_at=time))

    ascend = []
    for key, value in _object(data.get('ascend')).items():
        component = _object(value)
        if component and key != 'custom_opp':
            version = component.get('version')
            ascend.append(dict(_native_field(version if isinstance(version, str) else None,
                                             _text(component.get('source')) or 'ascend.' + key, component),
                               id=key, collected_at=time))

    targets = []
    for role, value in _object(_object(data.get('workload')).get('targets')).items():
        target = _object(value)
        pid = target.get('pid')
        if type(pid) is not int or pid <= 0:
            continue
        path = 'workload.targets.' + role
        starttime = target.get('start_time_ticks')
        row = dict(_native_field(None, path, target), role=role, pid=pid,
                   starttime=starttime if type(starttime) is int else None, collected_at=time)
        row.pop('value')
        if target.get('collection_status') in ('failed', 'unavailable'):
            targets.append(row)
            continue
        identity = _object(target.get('identity'))
        env = _object(target.get('environment'))
        libraries = _object(target.get('libraries'))
        limits = target.get('process_limits')
        variables = env.get('values')
        paths = libraries.get('paths')
        row['exe'] = _native_field(_text(identity.get('exe')), path + '.identity.exe', identity)
        row['environment'] = _native_field(
            {name: value for name, value in variables.items() if isinstance(value, str)}
            if isinstance(variables, dict) else None, path + '.environment.values', env)
        row['libraries'] = _native_field(
            [item for item in paths if isinstance(item, str)]
            if isinstance(paths, list) else None, path + '.libraries.paths', libraries)
        row['limits'] = _native_field(None, path + '.process_limits', _object(limits))
        if isinstance(limits, str):
            try:
                row['limits'] = _native_field(_target_field('limits', limits), path + '.process_limits')
            except ValueError as exc:
                row['limits'].update(status='PARSE_FAILED', reason=str(exc))
        row['status'] = 'COLLECTED' if all(row[field]['status'] == 'COLLECTED'
                                           for field in TARGET_FIELDS) else 'PARTIAL'
        targets.append(row)

    coverage = {}
    for name, info in _object(meta.get('collection')).items():
        if not isinstance(info, dict):
            continue
        reason = _text(info.get('reason'))
        errors = info.get('errors')
        failures = info.get('command_failures')
        if not reason and isinstance(errors, list):
            reason = next((error for error in errors if isinstance(error, str) and error), None)
        if not reason and isinstance(failures, list):
            failure = next((item for item in failures if isinstance(item, dict)), {})
            command = failure.get('command')
            if isinstance(command, list) and command and isinstance(command[0], str):
                reason = '%s 执行失败，返回码 %s' % (command[0], failure.get('returncode'))
        coverage[name] = {'status': _text(info.get('status')), 'reason': reason}
    scope = ('REQUESTED' if targets else 'NOT_REQUESTED'
             if coverage.get('workload', {}).get('status') == 'skipped' else 'UNKNOWN')
    return {'host': host, 'ascend': ascend, 'targets': targets, 'target_scope': scope}, coverage


def toolkit_version_location(row):
    """Identify the package and installation root from the captured source path."""
    if row.get('id') != 'toolkit' or not isinstance(row.get('source'), str):
        return None, None
    path = PurePosixPath(row['source'])
    if path.name == 'version.info' and path.parent.name in ('asc-devkit', 'toolkit'):
        package = path.parent.name
        root = path.parent.parent
        if root.parts[-2:] == ('share', 'info'):
            root = root.parent.parent
    elif path.name == 'ascend_toolkit_install.info' and path.parent.name in ('aarch64-linux', 'x86_64-linux'):
        package, root = 'toolkit', path.parent.parent
    else:
        return None, None
    return package, root if root.is_absolute() and '..' not in root.parts else None


def _merge_component_versions(bash_rows, native_rows):
    """Keep each parsed version with the source that actually provided it."""
    components = {row['id']: row for row in bash_rows}
    for native in native_rows:
        key = native['id']
        existing = components.get(key)
        if existing is None:
            components[key] = native
            continue
        if existing['reason'] == 'ambiguous_cann_installation':
            continue
        if native['status'] != 'COLLECTED' or not (native['value'] or '').strip():
            continue
        if existing['status'] == 'COLLECTED' and existing['value']:
            package, root = toolkit_version_location(existing)
            if package != 'asc-devkit' or root is None or toolkit_version_location(native) != ('toolkit', root):
                continue
        components[key] = native
    return list(components.values())


def analyze_environment(snapshot, integrity):
    rows = [row for row in integrity.get('entries', []) if row.get('category') in ENV_CATEGORIES]
    result = {'status': 'UNKNOWN', 'host': [], 'ascend': [], 'targets': [], 'target_scope': 'UNKNOWN'}
    native = None
    for entry in rows:
        category = entry['category']
        path = entry.get('raw_path') or ''
        status = entry['status']
        if category == NATIVE_DUMP_CATEGORY:
            native = entry
            continue
        value = None
        if status == 'COLLECTED' and path in snapshot:
            value = parse_environment_value(category, path, snapshot[path])
        row = {'status': status, 'source': entry.get('source') or entry.get('command') or path,
               'raw_path': path or None, 'reason': entry.get('failure_reason'),
               'collected_at': entry.get('ended_at')}
        if category != 'environment_process':
            result['host' if category == 'environment_host' else 'ascend'].append(
                dict(row, id=PurePosixPath(path).stem, value=value))
            continue
        if status == 'NOT_REQUESTED':
            result['target_scope'] = 'NOT_REQUESTED'
            continue
        match = PID_PATH.fullmatch(path)
        if match:
            result['target_scope'] = 'REQUESTED'
            row['pid'] = int(match[1])
            if value:
                row.update(value)
                if any(value[field]['status'] != 'COLLECTED' for field in TARGET_FIELDS):
                    row['status'] = 'PARTIAL'
            result['targets'].append(row)
    if rows:
        result['status'] = 'AVAILABLE' if any(row['status'] in ('COLLECTED', 'PARTIAL')
                                             for key in ('host', 'ascend', 'targets')
                                             for row in result[key]) else 'UNAVAILABLE'
    if native:
        path = native.get('raw_path')
        result['native_dump'] = {'path': path, 'capture_status': native['status'],
                                 'reason': native.get('failure_reason')}
        if native['status'] == 'COLLECTED' and path in snapshot:
            data = read_native_dump(snapshot[path])
            meta = data['_meta']
            view, coverage = _native_environment(data)
            result['native_dump'].update(schema_version=_text(meta.get('schema_version')), status=_text(meta.get('status')),
                                         timestamp=_text(meta.get('timestamp')), collection=coverage)
            if any(view[key] for key in ('host', 'ascend', 'targets')):
                if result['status'] == 'AVAILABLE':
                    result['bash_snapshot'] = {key: result[key] for key in view}
                view['ascend'] = _merge_component_versions(result['ascend'], view['ascend'])
                result.update(view, status='AVAILABLE')
    return result
