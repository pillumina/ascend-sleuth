"""One offline timeline, independent MHz and idle residency axes."""
from html import escape
from pathlib import Path
from .core_balance import safe_json
from .npu_affinity import _topology


def chart_data(m):
    _, nodes, _ = _topology(m.get('snapshot', {}))
    c2n = {cpu: node for node, cpus in nodes.items() for cpu in cpus}
    start, end = m.get('t_start', 0.), m.get('t_end', 0.)
    output = []
    domains = m.get('frequency', {}).get('domains', [])
    for domain in domains:
        points = [list(point) for point in domain.get('series', []) if start <= point[0] <= end]
        if not points or points[0][0] > start:
            points.insert(0, [start, None])
        if points[-1][0] < end:
            # Trace transitions retain a state up to the window end. Sysfs is
            # only observed through its last sample, with no invented tail.
            points.append([end, points[-1][1] if domain.get('source', '').startswith('ftrace') else None])
        output.append({'id': 'frequency:' + str(domain['id']), 'label': str(domain['id']) + ' Frequency',
                       'kind': 'frequency', 'policy': str(domain['id']), 'cpus': domain.get('cpus', []),
                       'numas': sorted({c2n[c] for c in domain.get('cpus', []) if c in c2n}),
                       'unit': 'MHz', 'source': domain.get('source'), 'reliability': domain.get('reliability'),
                       'points': points, 'end': domain.get('observation_end', end if domain.get('source', '').startswith('ftrace') else max([p[0] for p in domain.get('series', [])] or [start]))})
    idle = m.get('idle', {})
    for row in idle.get('cpus', []):
        cpu = row['cpu']
        output.append({'id': 'idle:cpu%d' % cpu, 'label': 'CPU%d Idle Residency' % cpu,
                       'kind': 'idle', 'policy': next((str(p['id']) for p in domains if cpu in p.get('cpus', [])), None),
                       'cpus': [cpu], 'numas': [c2n[cpu]] if cpu in c2n else [],
                       'unit': '%', 'source': idle.get('source', 'ftrace:power/cpu_idle'),
                       'reliability': idle.get('reliability', 'UNKNOWN'), 'points': row.get('series', []), 'end': end})
    return {'window': [start, end], 'series': output, 'nodes': sorted(nodes),
            'policies': [str(p['id']) for p in domains], 'bucket_sec': idle.get('bucket_sec', 1.),
            'note': '共用相对秒X轴；左轴MHz，右轴Idle Residency%。频率按共享策略域仅画一条，idle按CPU画。N/A断线；首样本前不外推。'}


def render_frequency_idle(m):
    data = chart_data(m)
    script = (Path(__file__).parent / 'assets/frequency_idle.js').read_text(encoding='utf-8-sig')
    return '''<div id="frequency-idle" class="chart">
<h3>CPU Frequency / Idle Residency 联合时间线</h3>
<p class="note">%s</p>
<div class="fi-controls">
<label>NUMA <select id="fi-numa"><option value="all">全部 NUMA</option>%s</select></label>
<label>CPU <input id="fi-cpu" type="text" placeholder="全部；如 0-3,8" aria-label="CPU编号或范围"></label>
<label>策略域 <select id="fi-policy"><option value="all">全部策略域</option>%s</select></label>
<button id="fi-reset" type="button">恢复默认曲线</button></div>
<details class="fi-legend"><summary>选择曲线（默认最多两条频率、两条Idle，避免重叠）</summary><div id="fi-series"></div></details>
<p id="fi-summary" class="note"></p>
<div id="fi-plot" tabindex="0" role="img" aria-label="频率MHz左轴，Idle Residency百分比右轴，时间秒；方向键查看时间点"></div>
<div id="fi-tooltip" aria-live="polite">指向时间线查看数值、来源与可靠性；缺失值显示 N/A。</div>
<noscript><p>JavaScript 已关闭；频率与Idle全量统计见下方可展开表格。曲线数据已保留在本HTML中。</p></noscript>
<script type="application/json" id="frequency-idle-data">%s</script><script>%s</script></div>''' % (
        escape(data['note']), ''.join('<option value="%s">NUMA%s</option>' % (n, n) for n in data['nodes']),
        ''.join('<option value="%s">%s</option>' % (escape(p, quote=True), escape(p)) for p in data['policies']), safe_json(data), script)
