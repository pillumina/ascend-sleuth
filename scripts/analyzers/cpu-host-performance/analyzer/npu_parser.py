"""Conservative, shared readers for version-dependent npu-smi text (stdlib).

Device/logic/physical chip numbers never imply host CPU or NUMA locality.
Only an explicitly labelled CPU Affinity column produces a CPU mapping.
The callers retain the complete raw text; source_line is one based.
"""
import re


def _integer(value):
    match = re.fullmatch(r'\s*(?:NPU\s*)?(\d+)\s*', value, re.I)
    return int(match.group(1)) if match else None


def _cpulist(value):
    value = re.sub(r'\s+', '', value)
    if not re.fullmatch(r'\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*', value):
        return ''
    for part in value.split(','):
        ends = [int(x) for x in part.split('-')]
        if ends[-1] < ends[0] or ends[-1] > 1048575:
            return ''
    return value


def _cells(line):
    if '|' in line:
        return [c.strip() for c in line.strip().strip('|').split('|')]
    return re.split(r'\s{2,}|\t+', line.strip())


def _header(cells):
    names = []
    for cell in cells:
        text = re.sub(r'[^a-z0-9]', '', cell.lower())
        if text in ('npuid', 'npu', 'cardid', 'card'):
            names.append('npu')
        elif text in ('npuchip', 'npuidchipid'):
            names.append('npu_chip')
        elif text in ('chipid', 'chip'):
            names.append('chip')
        elif text in ('processid', 'pid', 'hostpid'):
            names.append('pid')
        elif text in ('processname', 'name'):
            names.append('name')
        elif text.startswith('processmemory') or text in ('memorymb', 'memorymib'):
            names.append('memory')
        elif text in ('cpuaffinity', 'hostcpuaffinity', 'cpulist', 'hostcpulist'):
            names.append('cpu_affinity')
        elif text in ('numaid', 'numanode', 'numanodeid', 'numaaffinity'):
            names.append('numa_id')
        elif text in ('chiplogicid', 'logicid', 'deviceid'):
            names.append('device_id')
        elif text in ('chipphyid', 'physicalid', 'chipphysicalid'):
            names.append('physical_id')
        else:
            names.append('')
    return names


def parse_npu_info(text):
    processes, devices, errors = [], set(), []
    header, previous = None, {}
    recognized = False
    for number, line in enumerate((text or '').splitlines(), 1):
        cells = _cells(line)
        names = _header(cells)
        if 'pid' in names and ('npu' in names or 'npu_chip' in names):
            header = names
            recognized = True
            continue
        values = {}
        if header and len(cells) == len(header):
            values = {name: cell for name, cell in zip(header, cells) if name}
            if 'npu_chip' in values:
                pair = re.fullmatch(r'\s*(\d+)\s+(\d+)\s*', values['npu_chip'])
                if pair:
                    values.update(npu=pair[1], chip=pair[2])
            for name in ('npu', 'chip'):
                if not values.get(name) and name in previous:
                    values[name] = previous[name]
        # Common combined-column format, also supported in headerless old archives.
        if not values.get('pid') or _integer(values.get('pid', '')) is None:
            match = re.match(r'^\s*\|?\s*(\d+)\s+(\d+)\s*\|\s*(\d+)\s*\|\s*([^|]+)\|\s*(\d+(?:\.\d+)?)\s*(?:M[Bb]|MiB)?\s*\|?', line)
            if match:
                values = dict(zip(('npu', 'chip', 'pid', 'name', 'memory'), match.groups()))
        npu = _integer(values.get('npu', ''))
        pid = _integer(values.get('pid', ''))
        if npu is not None:
            devices.add(npu)
        if npu is None or pid is None or pid <= 0:
            if npu is not None and header and not re.search(r'no\s+(?:running|active)\s+process', line, re.I):
                errors.append('Line %d: invalid PID in process table' % number)
            continue
        previous = {key: values[key] for key in ('npu', 'chip') if values.get(key)}
        memory_match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:MB|MiB)?\s*', values.get('memory', ''), re.I)
        processes.append({'npu': npu, 'chip': _integer(values.get('chip', '')),
                          'pid': pid, 'name': values.get('name', '').strip(),
                          'memory': int(float(memory_match[1])) if memory_match else None,
                          'pid_namespace': 'host' if re.search(r'host\s*pid', text or '', re.I) else 'unknown',
                          'source_line': number})
    empty = bool(re.search(r'no\s+(?:running|active)\s+process|no\s+process(?:es)?\s+(?:found|running)', text or '', re.I))
    if not processes and not recognized and not empty and (text or '').strip():
        errors.append('Unrecognized npu-smi process table; no PID ownership inferred')
    if not processes and recognized and not empty and not errors:
        errors.append('Process table has no valid records and no explicit no-active-process marker')
    return {'processes': processes, 'devices': sorted(devices), 'errors': errors,
            'format': 'PROCESS_TABLE' if processes or recognized else ('EMPTY' if empty else 'UNKNOWN'),
            'parsed_count': len(processes)}


def _mapping(text, topology=False):
    devices, errors, header = [], [], None
    affinity_labelled = False
    tail_columns = []
    for number, line in enumerate((text or '').splitlines(), 1):
        cells = _cells(line)
        names = _header(cells)
        if ('npu' in names or 'npu_chip' in names) and any(n in names for n in ('chip', 'device_id', 'cpu_affinity', 'numa_id')):
            header = names
            affinity_labelled = 'cpu_affinity' in names
            tail = re.search(r'(CPU\s+Affinity(?:\s+NUMA\s+(?:Affinity|ID|Node))?)\s*\|?\s*$', line, re.I)
            tail_columns = ['cpu_affinity'] + (['numa_id'] if tail and re.search(r'NUMA', tail[1], re.I) else []) if tail else []
            continue
        if topology and re.search(r'\b(?:host\s+)?CPU\s+Affinity\b', line, re.I):
            affinity_labelled = True
            tail = re.search(r'(CPU\s+Affinity(?:\s+NUMA\s+(?:Affinity|ID|Node))?)\s*\|?\s*$', line, re.I)
            tail_columns = ['cpu_affinity'] + (['numa_id'] if tail and re.search(r'NUMA', tail[1], re.I) else []) if tail else []
            # Space-delimited topology matrices have variable width; affinity is the last named column.
            header = None
            continue
        values = {}
        if header and len(cells) == len(header):
            values = {name: cell for name, cell in zip(header, cells) if name}
            if 'npu_chip' in values:
                pair = re.fullmatch(r'(\d+)\s+(\d+)', values['npu_chip'])
                if pair:
                    values.update(npu=pair[1], chip=pair[2])
        elif topology:
            match = re.match(r'^\s*NPU\s*(\d+)\s+(.+?)\s*$', line, re.I)
            if not match and re.search(r'\b(?:X|HCCS|SYS|PHB|PIX|PXB|NODE|SOC|SIO)\b', line, re.I):
                match = re.match(r'^\s*\|?\s*(\d+)\s+(.+?)\s*\|?$', line)
            if match:
                values['npu'] = match[1]
                # The column title must explicitly identify CPU affinity.
                if affinity_labelled and tail_columns:
                    tokens = match[2].split()
                    if len(tokens) >= len(tail_columns):
                        values.update(zip(tail_columns, tokens[-len(tail_columns):]))
        npu = _integer(values.get('npu', ''))
        if npu is None:
            continue
        affinity = _cpulist(values.get('cpu_affinity', '')) if affinity_labelled else ''
        raw_affinity = values.get('cpu_affinity', '').strip()
        unavailable = raw_affinity.upper() in ('', '-', '--', 'N/A', 'NA', 'NONE', 'UNKNOWN', 'NOT SUPPORTED')
        devices.append({'npu': npu, 'chip': _integer(values.get('chip', '')),
                        'device_id': _integer(values.get('device_id', '')),
                        'physical_id': _integer(values.get('physical_id', '')),
                        'cpu_affinity': affinity, 'invalid_affinity': not affinity and not unavailable,
                        'numa_id': _integer(values.get('numa_id', '')),
                        'source_line': number})
        if values.get('cpu_affinity') and not affinity:
            errors.append('Line %d: CPU affinity is unavailable or not a numeric cpulist' % number)
    if not devices and (text or '').strip():
        errors.append('Unrecognized npu-smi mapping/topology table')
    return {'devices': devices, 'errors': errors, 'parsed_count': len(devices)}


def parse_npu_mapping(text):
    return _mapping(text)


def parse_npu_topology(text):
    return _mapping(text, topology=True)


def logic_map(raw_map):
    """Map observed (physical card, chip) pairs into the labelled logic ID space."""
    if not re.search(r'Chip\s+Logic\s+ID', raw_map, re.I):
        return {}
    rows = parse_npu_mapping(raw_map)['devices']
    if not rows and re.search(r'^\s*NPU\s+ID\s+Chip\s+ID\s+Chip\s+Logic\s+ID(?:\s|$)', raw_map, re.I | re.M):
        rows = [dict(npu=int(m[1]), chip=int(m[2]), device_id=int(m[3])) for line in raw_map.splitlines()
                for m in [re.match(r'^\s*(\d+)\s+(\d+)\s+(\d+)(?:\s|$)', line)] if m]
    result = {}
    for row in rows:
        pair, logic = (row['npu'], row['chip']), row['device_id']
        if None in pair or logic is None or (pair in result and result[pair] != logic):
            raise ValueError('Incomplete/conflicting NPU card/chip to logic ID map')
        result[pair] = logic
    if not result or len(set(result.values())) != len(result):
        raise ValueError('Missing or non-unique NPU logic IDs')
    return result


def device_id(row, ids):
    if not ids:
        return row['npu']
    pair = (row['npu'], row['chip'])
    if pair[1] is None:
        candidates = [key for key in ids if key[0] == pair[0]]
        if len(candidates) == 1:
            pair = candidates[0]
    if pair not in ids:
        raise ValueError('Unresolved physical NPU card/chip in logic ID map')
    return ids[pair]
