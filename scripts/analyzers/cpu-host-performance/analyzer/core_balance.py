"""All-core offline SVG view; data comes exclusively from computed metrics."""
import json
from html import escape
from itertools import groupby
from pathlib import Path
from .npu_affinity import _topology

GROUPS = {
    'time': 'CPU 时间占比（%）',
    'activity': '调度活动（次/秒）',
    'frequency': 'CPU Frequency（MHz）',
}

METRICS = [
    {'key':'util','label':'CPU 利用率','group':'time','unit':'%','color':'#68b8ff'},
    {'key':'idle_ratio','label':'CPU 空闲率','group':'time','unit':'%','color':'#62d6a5'},
    {'key':'irq_ratio','label':'硬中断','group':'time','unit':'%','color':'#ff956e'},
    {'key':'softirq_ratio','label':'软中断','group':'time','unit':'%','color':'#d09cff'},
    {'key':'cs_rate','label':'上下文切换','group':'activity','unit':'次/秒','color':'#68b8ff'},
    {'key':'wakeup_rate','label':'成功唤醒','group':'activity','unit':'次/秒','color':'#62d6a5'},
    {'key':'runnable_switch_out_rate','label':'可运行态切出','group':'activity','unit':'次/秒','color':'#ff956e'},
    {'key':'migration_rate','label':'迁移','group':'activity','unit':'次/秒','color':'#d09cff'},
    {'key':'freq_current','label':'当前频率','group':'frequency','unit':'MHz','color':'#62d6a5'},
    {'key':'freq_average','label':'平均频率','group':'frequency','unit':'MHz','color':'#68b8ff'},
    {'key':'freq_maximum','label':'硬件最大频率','group':'frequency','unit':'MHz','color':'#d09cff'},
]


def safe_json(data):
    return json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')


def core_data(m):
    _,nodes,_=_topology(m.get('snapshot',{}))
    c2n={c:n for n,cs in nodes.items() for c in cs}
    freq={c:p for p in m.get('frequency',{}).get('domains',[]) for c in p['cpus']}
    rows=[]
    for c,pc in sorted(m.get('per_cpu',{}).items()):
        row=dict(pc,cpu=c,numa=c2n.get(c));p=freq.get(c,{})
        row.update(freq_current=p.get('current_mhz'),freq_average=p.get('average_mhz'),freq_maximum=p.get('maximum_mhz'))
        rows.append({key:row.get(key) for key in ['cpu','numa','observed_sec']+[x['key'] for x in METRICS]})
    return {'cpus':rows,'nodes':sorted(nodes),'metrics':METRICS,'hot_threshold':90,
            'note':'全部在线/观测CPU；未采集或无法计算的指标为N/A。频率按共享policy映射，仅供每核对照，policy统计不重复计数。'}


def static_chart(rows, group, metrics):
    """Keep all metric groups readable in print and with JavaScript disabled."""
    legend = []
    values = []
    for metric in metrics:
        known = [row[metric['key']] for row in rows if row[metric['key']] is not None]
        values.extend(known)
        stats = f"均值 {sum(known)/len(known):.2f} · 最小 {min(known):.2f} · 最大 {max(known):.2f}" if known else 'N/A'
        legend.append(f'<span style="color:{metric["color"]}">{metric["label"]} · {stats}</span>')
    summary = '<p class="core-stats">' + ''.join(legend) + '</p>'
    if not values:
        message = '该组缺少可用数据（N/A）' if rows else 'CPU 数据为空'
        return summary + f'<p class="core-summary">{message}</p>'

    left, top, width, height = 65, 24, 980, 220
    right, bottom = left + width, top + height
    step = width / len(rows)
    ymax = 100 if group == 'time' else max(1, max(values)) * 1.15
    unit = metrics[0]['unit']
    out = [f'<div class="core-chart-scroll"><svg viewBox="0 0 1080 295" role="img" aria-label="{GROUPS[group]} · 全部 CPU">']
    for i in range(5):
        v = ymax * i / 4
        y = bottom - height * i / 4
        out.append(f'<line x1="{left}" x2="{right}" y1="{y:g}" y2="{y:g}" stroke="#354151"/>'
                   f'<text x="4" y="{y+4:g}" fill="#9eaec2" font-size="11">{v:g}</text>')
    out.append(f'<text x="8" y="15" fill="#a6b4c7" font-size="12">{unit}</text>')
    for metric in metrics:
        color = metric['color']
        key = metric['key']
        points = ((left + (i + .5) * step, row[key]) for i, row in enumerate(rows))
        for has_data, run in groupby(points, key=lambda point: point[1] is not None):
            if not has_data:
                continue
            coords = [(x, bottom - height * v / ymax) for x, v in run]
            if len(coords) == 1:
                x, y = coords[0]
                out.append(f'<circle cx="{x:g}" cy="{y:g}" r="2.2" fill="{color}"/>')
            else:
                points_attr = ' '.join(f'{x:g},{y:g}' for x, y in coords)
                out.append(f'<polyline points="{points_attr}" fill="none" stroke="{color}" stroke-width="1.7"/>')
        known = [(i, row[key]) for i, row in enumerate(rows) if row[key] is not None]
        if known:
            avg = sum(v for _, v in known) / len(known)
            y = bottom - height * avg / ymax
            out.append(f'<line x1="{left}" x2="{right}" y1="{y:g}" y2="{y:g}" '
                       f'stroke="{color}" stroke-dasharray="4 5" opacity=".7"/>')
        if key == 'util':
            for i, v in known:
                row = rows[i]
                x, y = left + (i + .5) * step, bottom - height * v / ymax
                hot = v >= 90
                marker = '#ff956e' if hot else color
                out.append(f'<circle cx="{x:g}" cy="{y:g}" r="{3 if hot else 1.5}" fill="{marker}">'
                           f'<title>CPU {row["cpu"]} / NUMA {escape(str(row["numa"]))} / {v:.2f}%</title></circle>')
    for i, row in enumerate(rows):
        if i % max(1, len(rows) // 16) == 0 or i == len(rows) - 1:
            x = left + (i + .5) * step
            out.append(f'<text x="{x:g}" y="265" fill="#a6b4c7" font-size="11" text-anchor="middle">{row["cpu"]}</text>')
    out.append('<text x="550" y="285" fill="#a6b4c7" font-size="12" text-anchor="middle">CPU 编号</text></svg></div>')
    return summary + ''.join(out)


def render_core_balance(m):
    data = core_data(m)
    script = (Path(__file__).parent / 'assets/core_balance.js').read_text(encoding='utf-8-sig')
    numa_options = ''.join(f'<option value="{n}">NUMA{n}</option>' for n in data['nodes'])
    panels = []
    for group, title in GROUPS.items():
        metrics = [metric for metric in data['metrics'] if metric['group'] == group]
        panels.append(f"""
<section class="core-panel" data-core-group="{group}" aria-labelledby="core-title-{group}">
<h3 id="core-title-{group}">{title}</h3>
<div class="core-static">{static_chart(data['cpus'], group, metrics)}</div>
<div class="core-dynamic" hidden>
<div class="core-metrics" role="group" aria-label="{title} · 指标显隐"></div>
<p class="core-stats"></p>
<div class="core-chart-scroll"></div>
<div class="core-tooltip" aria-live="polite"></div>
</div>
</section>""")
    return """<div id="core-balance" class="chart">
<style>
#core-balance svg{display:block;width:100%;min-width:560px}
.core-controls{gap:12px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.core-controls:not([hidden]){display:flex}
.core-controls label{font-size:12px;color:var(--muted)}.core-controls select,.core-controls input,.metric-toggle{background:#182333;color:#dce3ea;border:1px solid #40516a;border-radius:5px;padding:6px}
.core-controls input{width:80px}.metric-toggle{cursor:pointer;margin:3px}.metric-toggle[aria-pressed="false"]{opacity:.45}
.core-panel + .core-panel{border-top:1px solid var(--border);margin-top:16px;padding-top:8px}
.core-tooltip{white-space:pre-wrap;font:12px/1.7 Consolas,monospace;margin-top:8px;overflow-wrap:anywhere}
.core-stats{display:flex;flex-wrap:wrap;gap:4px 18px;font-size:12px;line-height:1.6}
.core-summary{font-size:12px;color:var(--muted)}.core-chart-scroll,.core-table-scroll{overflow:auto}
@media print{
  #core-balance{break-inside:auto;overflow:visible}
  .core-panel{break-inside:avoid}
  .core-controls,.core-dynamic{display:none!important}
  .core-static{display:block!important}
}
</style>
<div class="core-controls" hidden>
<label>图形 <select id="core-style"><option value="line">折线图</option><option value="bar">柱状图</option></select></label>
<label>NUMA <select id="core-numa"><option value="all">全部 NUMA</option>""" + numa_options + """</select></label>
<label>CPU 起始 <input id="core-min" type="number" min="0" placeholder="全部"></label><label>CPU 结束 <input id="core-max" type="number" min="0" placeholder="全部"></label>
<button type="button" id="core-reset" class="metric-toggle">全部核心</button></div>
<p class="core-summary" id="core-summary">""" + escape(data['note']) + """</p>
""" + ''.join(panels) + """
<noscript><p>静态图展示全部 CPU，启用 JavaScript 可使用交互筛选。</p></noscript>
<script type="application/json" id="core-data">""" + safe_json(data) + """</script>
<script>""" + script + """</script></div>"""
