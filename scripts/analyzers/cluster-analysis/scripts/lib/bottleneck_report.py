"""Render the P6a review interface from its structured evidence."""
from html import escape
import math

from lib.insight_data import stamp


KINDS = {'compute': '计算', 'communication': '通信', 'free': 'Free'}
BASES = {'compute': '同配置跨卡超额', 'communication': '最早卡等待暴露上界',
         'free': '连续空闲或候选碎片累计'}


def text(value):
    if value in (None, '', 'N/A'):
        return '—'
    return escape(str(value), quote=True)


def number(value):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result >= 0 else None


def ms(value):
    return '—' if value is None else f'{value / 1_000_000:,.3f} ms'


def pct(kind, scores):
    tenths = scores.get(kind, {}).get('tenths')
    label = f'{tenths / 10:.1f}%' if tenths is not None else '—'
    return f'<strong data-severity="{kind}">{label}</strong>'


def severity_card(locator):
    scores = locator.get('severity') or {}
    segments, legend, details = [], [], []
    for kind, name in KINDS.items():
        item = scores.get(kind) or {}
        tenths = item.get('tenths')
        if tenths:
            segments.append(f'<span data-kind="{kind}" style="--width:{tenths / 10}%">'
                            + (f'{name} {tenths / 10:.1f}%' if tenths >= 140 else '') + '</span>')
        duration, stage = item.get('duration_ns'), item.get('stage_ns')
        basis = f'{ms(duration)} / {ms(stage)} = {duration / stage:.2%}' if stage else '缺少可计分证据'
        details.append(f'<li>{name} · {BASES[kind]} <b>{basis}</b></li>')
        legend.append(f'<a href="#conclusions" data-bw-jump="{kind}" data-kind="{kind}">'
                      f'<span>{name}</span>{pct(kind, scores)}</a>')
    return ('<section class="bw-severity" aria-label="瓶颈严重度"><div class="bw-topline">'
            '<h3>瓶颈严重度</h3><span>候选影响归一化</span></div>'
            '<div class="bw-segments" aria-hidden="true">' + ''.join(segments) + '</div>'
            '<div class="bw-legend">' + ''.join(legend) + '</div>'
            '<details><summary>计算口径与证据范围</summary>'
            '<p>各类取单条候选中最大的「影响量 ÷ 对应卡 Step 的 Stage」，再归一化为 100%。'
            '通信使用最早卡 Stage；计算只计有同配置对照的超额；Free 使用被定位的区间。'
            '类别可能指向同一条因果链。百分比用于安排排查优先级，端到端可回收时间仍需验证。'
            '缺少可计分证据时会单独标注。</p><ul>' + ''.join(details) + '</ul></details></section>')


def value(e, kind):
    if kind == 'compute':
        return ((e['matching_rank_excess_ns'], '同配置跨卡超额') if e.get('matching_rank_excess_ns') is not None
                else (e.get('total_ns'), '本卡同配置累计'))
    if kind == 'communication':
        return e.get('start_skew_ns'), 'Device 起点差'
    return ((e['duration_ns'], '连续空闲') if e.get('duration_ns') is not None
            else (e.get('total_ns'), '碎片空闲累计'))


def label(finding, kind):
    e = finding.get('evidence') or {}
    return e.get('name' if kind == 'compute' else 'operator_instance') or finding.get('issue')


def pair_chart(title, rows, unit='', fixed_max=None):
    vals = [value for _, value in rows if value is not None]
    if not vals:
        return ''
    scale = fixed_max or max(vals) or 1
    parts = []
    for rank, value in rows:
        width = min(100, value / scale * 100) if value is not None else 0
        decimals = 0 if unit in ('次', 'cycles') else 2 if unit == '%' else 3
        amount = f'{value:,.{decimals}f}{" " if unit != "%" else ""}{unit}' if value is not None else '未采集'
        parts.append(f'<div class="bw-pair-row"><span>{text(rank)} 卡</span><i aria-hidden="true">'
                     f'<b style="--width:{width:.6f}%"></b></i><strong>{amount}</strong></div>')
    if len(rows) == 2 and len(vals) == 2 and unit == '%':
        delta = vals[0] - vals[1]
        difference = '<small>≈0.00 pp</small>' if abs(delta) < 0.005 else f'<small>{delta:+.2f} pp</small>'
    else:
        difference = ''
    return f'<div class="bw-pair"><div class="bw-pair-head"><b>{title}</b>{difference}</div>{"".join(parts)}</div>'


def communication_chart(e):
    starts = sorted((e.get('arrival_ns_by_rank') or {}).items(), key=lambda row: row[1])
    if not starts:
        return ''
    origin, limit = starts[0][1], max(1, starts[-1][1] - starts[0][1])
    dots = []
    for i, (rank, start) in enumerate(starts):
        highlight = ' bw-extreme' if i in (0, len(starts) - 1) else ''
        dots.append(f'<i class="bw-dot{highlight}" title="{text(rank)} 卡 · +{ms(start - origin)}" '
                    f'style="--x:{(start - origin) / limit * 100:.8f}%;--y:{12 + i % 7 * 12}%"></i>')
    end = ms(e.get('end_spread_ns'))
    return ('<figure class="bw-plot"><figcaption><b>各卡 Device 起点</b>'
            '<span>相对最早到达 · 同一通信实例</span></figcaption><div class="bw-arrival" aria-hidden="true">'
            + ''.join(dots) + f'</div><div class="bw-axis"><span>{text(starts[0][0])} 卡 · 0 ms</span>'
            f'<span>{text(starts[-1][0])} 卡 · +{ms(limit if len(starts) > 1 else 0)}</span></div>'
            f'<p>结束跨度 <b>{end}</b> · 共对齐 {len(starts)} 张卡</p></figure>')


def free_timeline(e):
    timeline = e.get('timeline') or {}
    if not timeline:
        return '<p class="bw-muted">缺少完整 Step 的 Free 区间证据。</p>'
    start, end = timeline['start_ns'], timeline['end_ns']
    duration = end - start
    if duration <= 0:
        return ''
    gaps, chosen = timeline['free_intervals_ns'], timeline['selected_intervals_ns']
    width = 600

    def coverage(intervals, highlight=False):
        # Each bin stores the exact covered fraction, including subpixel gaps.
        bins = [0] * width
        for a, b in intervals:
            lo, hi = (max(a, start) - start) * width, (min(b, end) - start) * width
            for i in range(max(0, lo // duration), min(width, (hi + duration - 1) // duration)):
                bins[i] += min(hi, (i + 1) * duration) - max(lo, i * duration)
        paths = {1: [], 2: [], 3: [], 4: []}
        for i, fraction in enumerate(bins):
            if fraction:
                paths[min(4, (fraction * 4 + duration - 1) // duration)].append(f'M{i} 0h1v20h-1z')
        kind = 'candidate' if highlight else 'idle'
        return ''.join(f'<path class="bw-{kind}-{level}" d="{"".join(path)}"/>' for level, path in paths.items() if path)

    arrows, frame = '', ''
    focus_ranges = sorted(chosen, key=lambda pair: pair[1] - pair[0], reverse=True)[:3]
    if chosen and e.get('relative_start_ns') is not None and e.get('relative_end_ns') is not None:
        a, b = max(start, e['relative_start_ns']), min(end, e['relative_end_ns'])
        if b > a:
            x, w = (a - start) / duration * 100, (b - a) / duration * 100
            frame = f'<i class="bw-free-frame" style="--x:{x:.8f}%;--width:{w:.8f}%"></i>'
            focus_ranges = [(a, b)]
    for a, b in focus_ranges:
        x = (max(start, a) + min(end, b) - 2 * start) / (2 * duration) * 100
        arrows += f'<i class="bw-free-pin" title="{text(stamp(a))} ～ {text(stamp(b))}" style="--x:{x:.8f}%"></i>'
    total = sum(b - a for a, b in gaps)
    examples = '、'.join(f'{stamp(a)}～{stamp(b)}' for a, b in focus_ranges)
    return ('<figure class="bw-plot"><figcaption><b>整步 Device Free 分布</b>'
            f'<span>{text(e.get("rank"))} 卡 · {"整段 prof" if e.get("step") == "prof" else "Step " + text(e.get("step"))}'
            f' · {ms(duration)}</span></figcaption><div class="bw-free-track" aria-hidden="true">'
            f'<svg viewBox="0 0 {width} 20" preserveAspectRatio="none">{coverage(gaps)}{coverage(chosen, True)}</svg>'
            + frame + arrows + f'</div><div class="bw-axis"><span>起点 {stamp(start)}</span><span>终点 {stamp(end)}</span></div>'
            '<div class="bw-free-key"><span>青色深浅表示该位置的 Free 密度</span>'
            '<span>橙色标出候选，箭头指向选中区间或代表段</span></div>'
            f'<p>整步 Free <b>{ms(total)}（{total / duration:.2%}）</b> · {len(gaps):,} 段'
            f' · {text(timeline.get("source"))}</p>'
            + (f'<p class="bw-examples">箭头定位 {text(examples)}</p>' if examples else '') + '</figure>')


def compute_chart(e, origin):
    instances = e.get('instances') or []
    if not instances:
        return ''
    def rank_time(field):
        return [(i.get('rank'), v / 1_000_000 if (v := number(i.get(field))) is not None else None)
                for i in instances]
    names = ['形状', '数据类型', '格式']
    metadata = []
    for side, side_name in [('inputs', '输入'), ('outputs', '输出')]:
        for index, name in enumerate(names):
            values = [(i.get(side) or [None] * 3)[index] for i in instances]
            metadata.append((side_name + name, values))
    metadata.append(('执行核', [i.get('core') for i in instances]))
    for param in ('modelId', 'operatorType', 'taskType', 'streamId', 'taskId', 'connectionId', 'blockDim', 'mixBlockDim'):
        metadata.append((param, [(i.get('params') or {}).get(param) for i in instances]))
    for field, heading in [('start_ns','开始'), ('start_ns','开始（原始时间戳）'), ('end_ns','结束（原始时间戳）'),
                           ('duration_ns','持续时间')]:
        values = []
        for i in instances:
            raw = i.get(field)
            values.append(None if raw is None else
                          stamp(raw-origin) if heading == '开始' and isinstance(origin, int) else
                          stamp(raw) if field == 'duration_ns' else f'{raw} ns')
        metadata.append((heading, values))
    pmus = [i.get('pmu') or {} for i in instances]
    ratios = {'vec_ratio':'向量', 'mac_ratio':'矩阵', 'scalar_ratio':'标量', 'mte1_ratio':'MTE1',
              'mte2_ratio':'MTE2 搬入', 'mte3_ratio':'MTE3 搬出', 'fixpipe_ratio':'Fixpipe',
              'icache_miss_rate':'I-Cache Miss'}
    pmu_charts, other_charts = [], [pair_chart('代表实例耗时', rank_time('duration_ns'), 'ms')]
    for core in ('aic', 'aiv'):
        for name, label in ratios.items():
            values = [number(p.get(f'{core}_{name}')) for p in pmus]
            if any(v is not None and v > 0 for v in values):
                pmu_charts.append(pair_chart(core.upper() + ' ' + label,
                                            [(i.get('rank'), v * 100 if v is not None else None)
                                             for i, v in zip(instances, values)], '%', 100))
        cycles = [(i.get('rank'), number(p.get(f'{core}_total_cycles'))) for i, p in zip(instances, pmus)]
        if any(v for _, v in cycles):
            other_charts.append(pair_chart(core.upper() + ' 周期数', cycles, 'cycles'))
    other_charts.append(pair_chart('同配置执行次数', [(i.get('rank'), number(i.get('count'))) for i in instances], '次'))

    def table(rows):
        head = ''.join(f'<th scope="col">{text(i.get("rank"))} 卡</th>' for i in instances)
        body = []
        for name, vals in rows:
            differs = len(vals) == 2 and all(v not in (None, '', 'N/A') for v in vals) and str(vals[0]) != str(vals[1])
            cells = ''.join(f'<td class="{"bw-diff" if differs else ""}">{text(v)}</td>' for v in vals)
            body.append(f'<tr><th scope="row">{text(name)}</th>{cells}</tr>')
        return ('<div class="bw-table-wrap"><table class="bw-table"><thead><tr><th scope="col">字段</th>'
                + head + '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>')

    raw_rows = []
    for field in sorted(set().union(*(p.keys() for p in pmus))):
        values = []
        for i, pmu in zip(instances, pmus):
            raw = pmu.get(field)
            unit = (i.get('pmu_time_units') or {}).get(field)
            values.append(f'{raw} {unit}' if raw is not None and unit else raw)
        raw_rows.append((field, values))
    sources = '、'.join(f'{text(i.get("rank"))} 卡 {text(i.get("pmu_source"))}' for i in instances)
    pmu = (('<div class="bw-pair-grid">' + ''.join(pmu_charts) + '</div>') if pmu_charts
           else '<p>未采集到有值的流水占用率。</p>')
    return ('<figure class="bw-plot"><figcaption><b>同配置跨卡对照</b>'
            '<span>每卡选取该配置的最长实例作细节对照</span></figcaption>'
            + pair_chart('累计耗时', rank_time('total_ns'), 'ms')
            + ('<p>缺少同配置对照卡，当前仅展示本卡热点。</p>' if len(instances) == 1 else '')
            + '</figure><details class="bw-compute-detail"><summary>展开算子对照 · PMU、输入输出与任务参数</summary>'
            '<div class="bw-detail-body"><h4>耗时、周期与次数</h4><div class="bw-pair-grid">'
            + ''.join(other_charts) + '</div><h4>PMU 流水占用率</h4>' + pmu
            + f'<p class="bw-muted">各流水可重叠。图中比率使用共同 0–100% 刻度。首选实例级 DB 数据，CSV 补缺。{sources}</p>'
            '<h4>输入输出与任务参数</h4>' + table(metadata)
            + ('<details><summary>查看全部已采集原始 PMU 字段</summary>' + table(raw_rows) + '</details>' if raw_rows else '')
            + '</div></details>')


def workbench(locator):
    scores = locator.get('severity') or {}
    counts = {kind: len((locator.get(kind) or [])[:3]) for kind in KINDS}
    ordered = sorted(KINDS, key=lambda kind: (scores.get(kind, {}).get('tenths') or 0, counts[kind]), reverse=True)
    first = next((k for k in ordered if counts[k]), None)
    first_index = (scores.get(first, {}).get('candidate_index') or 0)
    summary = text(locator.get('summary') or '定位证据不足')
    lead = ('<div class="bw-workbench"><header class="bw-heading"><div><h3>瓶颈定位与解决</h3>'
            f'<p>{summary}</p></div><span>{sum(counts.values())} 条候选</span></header>')
    index, panels = [], []
    origin = (locator.get('coverage') or {}).get('origin_ns')
    for kind in ordered:
        selected_label = '最高候选' if scores.get(kind, {}).get('candidate_index') is not None else '无可计分证据'
        buttons = []
        for i, finding in enumerate((locator.get(kind) or [])[:3]):
            evidence = finding.get('evidence') or {}
            label_text = text(label(finding, kind))
            amount, metric = value(evidence, kind)
            rank = evidence.get('rank', evidence.get('latest_observed_rank'))
            step = evidence.get('step')
            where = f'{"整段 prof" if step == "prof" else "Step " + text(step)} · {text(rank)} 卡' if rank is not None else ''
            active = kind == first and i == first_index
            best = i == scores.get(kind, {}).get('candidate_index')
            key = f'bw-{kind}-{i}'
            buttons.append(f'<button type="button" data-bw-case="{key}" data-bw-best="{str(best).lower()}" '
                           f'aria-controls="{key}" aria-pressed="{str(active).lower()}">'
                           f'<b>{label_text}</b><span>{where}<strong>{ms(amount) if amount is not None else ""}</strong></span></button>')
            chart = (communication_chart(evidence) if kind == 'communication' else
                     free_timeline(evidence) if kind == 'free' else compute_chart(evidence, origin))
            diagnostic = label_text if kind != 'free' else text(finding.get('issue'))
            panels.append(f'<section class="bw-panel" data-kind="{kind}" id="{key}" data-bw-panel{" hidden" if not active else ""}>'
                          '<div class="bw-panel-head"><div>'
                          f'<div class="bw-context">{KINDS[kind]} <span>{where}</span></div><h4 tabindex="-1">{diagnostic}</h4>'
                          + (f'<p>{text(finding.get("issue"))}</p>' if diagnostic != text(finding.get('issue')) else '')
                          + '</div>'
                          + (f'<div class="bw-metric"><strong>{ms(amount)}</strong><span>{metric}</span></div>' if amount is not None else '')
                          + '</div>' + chart + '<div class="bw-next"><h5>证据与下一步</h5>'
                          f'<p>{text(finding.get("cause"))}</p><p class="bw-muted">{text(finding.get("impact"))}</p></div>'
                          '<details class="bw-source"><summary>展开 Insight 精确定位</summary>'
                          f'<p>{text(finding.get("location"))}</p></details></section>')
        index.append(f'<div class="bw-group" data-kind="{kind}"><div class="bw-group-head">'
                     f'<h5>{KINDS[kind]}</h5>{pct(kind, scores)}</div><p>{selected_label} · {counts[kind]} 条</p>'
                     + (''.join(buttons) if buttons else f'<small>{text(locator.get(kind + "_reason") or "当前证据不足。")}</small>')
                     + '</div>')
    limits = ''.join(f'<li>{text(limit)}</li>' for limit in locator.get('limitations') or [])
    return (lead + '<div class="bw-layout"><aside class="bw-index" aria-label="候选索引"><h4>候选索引</h4>'
            '<p class="bw-muted">严重度占比 · 见概览口径</p>' + ''.join(index) + '</aside>'
            '<div class="bw-panels" aria-live="polite">' + (''.join(panels) or '<p>缺少可定位的卡级证据。</p>')
            + '</div></div>' + (f'<details class="bw-source"><summary>采集范围与时间口径</summary><ul>{limits}</ul></details>' if limits else '') + '</div>')
