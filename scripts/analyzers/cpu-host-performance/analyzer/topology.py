"""Report view of actual CPU/NUMA topology, capacity and distance evidence."""
import re
from .evidence import read_json, cpulist
from .npu_affinity import _topology


def analyze_topology(m):
    snapshot = m.get('snapshot', {})
    _, nodes, cores = _topology(snapshot)
    data = read_json(snapshot, 'numa_topology.json', {})
    if not isinstance(data, dict):
        data = {}
    rows = data.get('nodes', [])
    if not isinstance(rows, list):
        rows = []
    normalized = {r['node']: r for r in rows if isinstance(r, dict) and isinstance(r.get('node'), int)}
    # Memory-only NUMA nodes are real nodes even with a readable empty cpulist.
    # CPU locality is unchanged; node inventory/capacity must still retain them.
    for node in normalized:
        nodes.setdefault(node, set())
    for path in snapshot:
        match = re.search(r'/sysfs/node/node(\d+)/', path)
        if match:
            nodes.setdefault(int(match[1]), set())
    order = data.get('distance_node_order', [])
    if not isinstance(order, list) or any(not isinstance(n, int) for n in order):
        order = []
    online = cpulist(snapshot.get('cpu_online.txt', snapshot.get('hostbound/cpu_online.txt', '')))
    if not online and isinstance(data.get('online_cpus'), list):
        online = cpulist(data['online_cpus'])
    if not online:
        online = set(m.get('per_cpu', {})) | {c for values in nodes.values() for c in values}
    text = snapshot.get('hostbound/numactl.txt', snapshot.get('numactl.txt', ''))
    capacities = {}
    for node, field, value, unit in re.findall(r'node\s+(\d+)\s+(size|free):\s*([\d.]+)\s*([KMGTP]?B)', text, re.I):
        factor = {'B': 1/1024., 'KB': 1, 'MB': 1024, 'GB': 1024**2, 'TB': 1024**3, 'PB': 1024**4}[unit.upper()]
        capacities.setdefault(int(node), {})[field] = float(value) * factor
    old_distances = {}
    in_distance = False
    legacy_order = []
    for line in text.splitlines():
        if 'node distances:' in line:
            in_distance = True
        elif in_distance and re.fullmatch(r'\s*node\s+[\d\s]+', line):
            legacy_order = [int(n) for n in re.findall(r'\d+', line)]
        elif in_distance:
            match = re.fullmatch(r'\s*(\d+):\s*([\d\s]+)', line)
            if match:
                values = [int(v) for v in match[2].split()]
                if len(values) == len(legacy_order):
                    old_distances[int(match[1])] = dict(zip(legacy_order, values))
    output = []
    for node, cpus in sorted(nodes.items()):
        row = normalized.get(node, {})
        memory = row.get('memory_kb', {})
        if not isinstance(memory, dict):
            memory = {}
        raw_mem = snapshot.get('hostbound/sysfs/node/node%d/meminfo' % node, '')
        memory.update({k: int(v) for k, v in re.findall(r'Node\s+\d+\s+(\w+):\s*(\d+)\s+kB', raw_mem)})
        distance = row.get('distance', [])
        if not isinstance(distance, list):
            distance = []
        raw_dist = snapshot.get('hostbound/sysfs/node/node%d/distance' % node)
        if raw_dist and re.fullmatch(r'[\d\s]+', raw_dist):
            distance = [int(n) for n in raw_dist.split()]
        distance_map = dict(zip(order, distance)) if len(order) == len(distance) and order else old_distances.get(node, {})
        output.append({'node': node, 'cpus': sorted(cpus),
                       'total_kb': memory.get('MemTotal', capacities.get(node, {}).get('size')),
                       'free_kb': memory.get('MemFree', capacities.get(node, {}).get('free')),
                       'available_kb': memory.get('MemAvailable'), 'memory_kb': memory,
                       'distance_by_node': distance_map, 'distance': distance,
                       'errors': row.get('errors', {})})
    c2n = {c: n for n, values in nodes.items() for c in values}
    return {'status': 'COLLECTED' if nodes else 'UNKNOWN', 'cpu_count': len(online) if online else None,
            'numa_count': len(nodes) if nodes else None, 'online_cpus': sorted(online),
            'cpu_to_numa': c2n, 'cores': [{'cpu': c, 'socket': core[0], 'numa': core[1], 'core': core[2]} for c, core in sorted(cores.items())],
            'nodes': output, 'unmapped_cpus': sorted(online-set(c2n)),
            'distance_node_order': order or legacy_order,
            'sources': [p for p in snapshot if p.endswith(('numa_topology.json', 'numactl.txt', 'lscpu_parse.txt', 'numa.txt')) or '/sysfs/node/' in p],
            'note': 'CPU 所属 NUMA、Mems_allowed 许可范围及实际页分布分别记录；distance 为系统报告的相对距离，不是访存延迟测量。MemFree 不等于 MemAvailable。'}
