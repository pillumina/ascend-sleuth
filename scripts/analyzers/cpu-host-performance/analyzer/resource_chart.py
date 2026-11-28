from html import escape

from .report_explanation import fmt


def _percent(value):
    return fmt(value, '%', digits=1) if value is not None else '—'


def _ratio(used, limit):
    return 100 * used / limit if used is not None and limit else None


def _highest(rows, value):
    known = [(value(row), row) for row in rows if value(row) is not None]
    return max(known, key=lambda pair: pair[0]) if known else (None, {})


def _rows(resources, cpu_quotas):
    """Show baseline indicators, the tightest capacities and active limits."""
    rows = []

    def add(label, value, detail='', warn=False, risk=False):
        status = ('紧张' if risk else '留意' if warn else
                  '缺数据' if value is None else '正常')
        rows.append((label, value, detail, status))

    def psi(kind):
        return resources.get('pressure', {}).get(kind, {}).get('some', {}).get('stall_percent')

    cpu = resources.get('cpu', {})
    busy, cpu_stall = cpu.get('busy_percent'), psi('cpu')
    add('CPU · 平均忙碌', busy, 'CPU 等待 %s' % _percent(cpu_stall),
        warn=(busy or 0) >= 90, risk=(cpu_stall or 0) >= 5)

    memory = resources.get('memory', {})
    free = memory.get('minimum_available_percent')
    memory_stall = psi('memory')
    vm = resources.get('vm', {})
    oom = (vm.get('oom_kill_delta') or 0) > 0
    swapping = any((vm.get(key) or 0) > 0 for key in ('pswpin_delta', 'pswpout_delta'))
    detail = ('发生 OOM' if oom else '发生换页' if swapping else
              '内存等待 %s' % _percent(memory_stall))
    add('内存 · 峰值占用', 100 - free if free is not None else None, detail,
        warn=swapping or (free is not None and free < 10),
        risk=oom or (memory_stall or 0) > 1 or (swapping and free is not None and free < 10))

    io_stall = psi('io')
    disks = [row for row in resources.get('disks', [])
             if row.get('type') != 'part' and not row['name'].startswith(('loop', 'ram', 'zram'))]
    disk_busy, disk = _highest(disks, lambda row: row.get('busy_percent'))
    if disk_busy is not None:
        add('磁盘 I/O · 最忙设备', disk_busy,
            '%s · I/O 等待 %s' % (disk['name'], _percent(io_stall)),
            warn=disk_busy >= 90, risk=(io_stall or 0) >= 5)
    else:
        add('磁盘 I/O · 等待', io_stall, risk=(io_stall or 0) >= 5)

    for label, key in [('磁盘空间 · 最满挂载点', 'used_percent'),
                       ('inode · 最满挂载点', 'inode_used_percent')]:
        usage, fs = _highest(resources.get('filesystems', []), lambda row: row.get(key))
        add(label, usage, fs.get('mount', ''), risk=(usage or 0) >= 95)

    groups = resources.get('cgroups', [])
    for label, used, limit in [('任务内存限额', 'memory_current_bytes', 'memory_max_bytes'),
                               ('任务 PID 限额', 'pids_current', 'pids_max')]:
        limited = [row for row in groups if row.get(limit)]
        pct, group = _highest(limited, lambda row: _ratio(row.get(used), row.get(limit)))
        if limited or (label == '任务内存限额' and any((row.get('oom_kill_delta') or 0) > 0 for row in groups)):
            oom = label == '任务内存限额' and any((row.get('oom_kill_delta') or 0) > 0 for row in groups)
            add(label, pct, '发生 OOM' if oom else group.get('path', ''), risk=oom or (pct or 0) >= 95)

    if cpu_quotas:
        def throttle(row):
            return _ratio(row.get('nr_throttled_delta'), row.get('nr_periods_delta'))
        pct, group = _highest(cpu_quotas, throttle)
        throttled = any((row.get('nr_throttled_delta') or 0) > 0 for row in cpu_quotas)
        add('任务 CPU 配额 · 限流周期', pct, group.get('path', ''), risk=throttled)
    return rows


def render_resource_overview(m, html):
    resources = m.get('resources', {})
    task_pids = set(m.get('process_analysis', {}).get('related_tgids', []))
    task_pids.update(row['pid'] for row in m.get('npu_affinity', {}).get('rows', []) if row.get('pid'))
    quotas = [row for row in m.get('contention', {}).get('cgroups', [])
              if task_pids.intersection(row.get('tgids', [])) and row.get('quota_status') == 'LIMITED']
    rows = _rows(resources, quotas)
    window = resources.get('window_sec')
    caption = (('资源窗口 %.1f 秒。' % window if window is not None else '资源窗口不可用。') +
               '条长表示占用或等待比例，颜色与状态标出可能限制性能的资源。')
    if not html:
        return caption + '\n\n' + '\n'.join('%s · %s · %s %s' %
            (label, status, _percent(value), detail) for label, value, detail, status in rows)

    height = 38 + 46 * len(rows)
    colors = {'正常': '#4adea1', '留意': '#fbbf55', '紧张': '#ff8588', '缺数据': '#a1adbd'}
    parts = [
        '<figure style="margin:0;max-width:960px;overflow-x:auto">',
        '<svg class="resource-overview" xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 960 %d" role="img" aria-label="主机资源占用与压力概览" '
        'style="display:block;width:100%%;min-width:680px;font:16px system-ui,sans-serif">' % height,
        '<rect width="960" height="%d" rx="12" fill="#15222f"/>' % height,
        '<g fill="#a1adbd" font-size="13"><text x="235" y="25">0%</text>'
        '<text x="392" y="25" text-anchor="middle">50%</text>'
        '<text x="549" y="25" text-anchor="end">100%</text>'
        '<text x="630" y="25">状态</text><text x="725" y="25">关注项</text></g>'
    ]
    for i, (label, value, detail, status) in enumerate(rows):
        y = 42 + 46 * i
        color = colors[status]
        parts.append('<g><title>%s</title>' % escape(' · '.join(filter(None, (label, _percent(value), status, detail)))))
        parts.append('<text x="20" y="%d" fill="#e0e8f0">%s</text>' % (y + 18, escape(label)))
        parts.append('<rect x="235" y="%d" width="314" height="16" rx="4" fill="#2b3d4f"/>' % (y + 4))
        if value is not None and value > 0:
            parts.append('<rect x="235" y="%d" width="%.2f" height="16" rx="4" fill="%s"/>' %
                         (y + 4, 3.14 * min(value, 100), color))
        short_detail = detail if len(detail) <= 25 else detail[:24] + '…'
        parts.append('<text x="565" y="%d" fill="#e0e8f0">%s</text>'
                     '<text x="630" y="%d" fill="%s" font-weight="600">%s</text>'
                     '<text x="725" y="%d" fill="#c8d4e0" font-size="13">%s</text></g>' %
                     (y + 18, escape(_percent(value)), y + 18, color, status, y + 18, escape(short_detail)))
    parts.append('</svg><figcaption class="note">%s</figcaption></figure>' % escape(caption))
    return ''.join(parts)
