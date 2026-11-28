"""Six customer-facing explanations, shared by HTML and Markdown section 2."""
from html import escape


def fmt(value, unit='', digits=2):
    return ('%.*f%s' % (digits,value,unit)) if isinstance(value,(int,float)) else '缺失 / 不可用'


def explanations(m,diag):
    stats=diag.get('stats',{});sch=m.get('sched',{});quality=m.get('scheduler_quality',{})
    pcs=list(m.get('per_cpu',{}).values());known=sum(p.get('util') is not None for p in pcs)
    obs=sum(p.get('observed_sec',0) for p in pcs)
    coverage='%d/%d CPU 有有效观测；总观测 %.3f CPU·秒；%s' % (known,len(pcs),obs,'事件完整性存在限制' if not quality.get('complete') else '连续事件已核验，窗口边界保守处理')
    avg=stats.get('avg_util');mx=stats.get('max_util');cs=sch.get('cs_rate');lat=sch.get('lat_p99')
    def item(name,value,what,why,current,conclusion,trust):
        return {'name':name,'当前值':value,'指标是什么':what,'为什么需要关注':why,'当前值说明':current,'诊断结论':conclusion,'数据可信度':trust}
    records=[]
    records.append(item('CPU 平均利用率',fmt(avg,'%'),
        '采集窗口中有效CPU忙碌时间之和 / 有效CPU总观测时间 × 100%；busy由连续sched_switch中非idle任务区间计算，包含任务上下文内IRQ时间。',
        '反映所观测CPU整体算力需求。平均利用率低，不代表不存在局部核心饱和。',
        '当前缺少有效观测。' if avg is None else ('整体利用率较高（经验关注值≥70%）。' if avg>=70 else '所观测CPU整体仍有余量；需结合单核热点、配额与线程等待判断。'),
        '不能仅凭均值排除CPU瓶颈；未观测核心不参与分母。'+('已出现单核≥90%的热点。' if mx is not None and mx>=90 else ''),coverage))
    records.append(item('单核最高利用率',fmt(mx,'%'),
        '逐CPU计算 busy / 该CPU有效观测时间 × 100%，再取有效CPU中的最大值。',
        '关键串行线程即使只占一核，也可能限制整机性能；需要对照CPU Affinity、线程绑核和IRQ热点。',
        '无可用核心数据。' if mx is None else ('至少一个观测核心接近饱和（经验值≥90%），整机均值较低也不能忽略。' if mx>=90 else '观测窗口内单核未达到90%的经验关注线；更短突发仍需时间线验证。'),
        '热点是直接观测事实，是否拖慢Worker需查看该核关联线程和可运行等待。',coverage))
    n=sum(p.get('observed_sec',0)>0 for p in pcs)
    records.append(item('上下文切换率',fmt(cs,' 次/秒',0),
        'CPU从一个调度任务切换到另一个任务。为共享CPU、阻塞唤醒和优先级调度而切换；当前为全机每秒观测sched_switch次数 / 采集窗口秒数，不是单核每秒。',
        '过于频繁可能增加调度、缓存和TLB开销；并发线程多且等待升高时可能有竞争，I/O密集或正常并行也会频繁切换。',
        '缺少sched_switch数据。' if cs is None else '当前全机观测 %.0f 次/秒；参考 %.0f×%d 有效CPU = %.0f 次/秒，仅为经验筛选线。'%(cs,2000,n,2000*n),
        '不能单凭切换次数高认定性能问题，必须结合等待、CPU时间线与业务基线。',coverage))
    records.append(item('调度延迟 P99',fmt(lat,' ms'),
        '同一任务身份的成功sched_wakeup/sched_wakeup_new到首次sched_switch(next_tid)获得CPU的时间；P99是这些已配对样本的99分位（线性插值）。不使用sched_waking起点，重复唤醒保留最早有效记录。',
        '高等待可能让NPU Worker无法及时准备数据或提交任务；它不等于推理请求P99，也不等于模型计算耗时。',
        '无完整配对，当前值缺失。' if lat is None else ('等待尾部偏高（经验关注≥5 ms，严重≥20 ms）；请核对对应Worker。' if lat>=5 else '已观测等待尾部低于5 ms经验线；不代表请求尾延迟健康。'),
        '这是已配对唤醒样本分布；可运行态R/R+切出后的等待另列Runqueue Wait，不混入本指标。',
        '样本量 %d；未配对唤醒 %d；重复唤醒 %d；边界未完成等待 %d；switch不连续 %d；buffer丢失 %s；%s。' % (sch.get('lat_count',0),quality.get('unpaired_wakeups',0),quality.get('duplicate_wakeups',0),quality.get('boundary_censored_waits',0),quality.get('mismatched_switches',0),(m.get('buffer_overrun',0) if m.get('buffer_overrun_known') else '未知（无统计）'),'仅部分观测，不能还原缺失样本' if not quality.get('complete') else '未发现配对不连续，样本仍受采集边界约束')))
    for kind,name,threshold,why in [('irq','硬中断总占比',15,
            '网卡、NVMe等硬件通知CPU处理完成或接收事件。集中在Worker所在核心时可能挤占其CPU时间；先对照/proc/interrupts与/proc/irq/*/smp_affinity_list，只读核验IRQ Affinity。'),
            ('softirq','软中断总占比',20,
             'SoftIRQ延后处理内核工作：NET_RX网络接收、NET_TX发送完成、TIMER定时器、RCU延迟回收、BLOCK块I/O完成。网络通信和存储I/O可增加软中断，集中到Worker所在CPU时可能影响执行节奏。')]:
        irq=m.get(kind,{})
        value=irq.get('total_ratio');peak=irq.get('max_cpu_ratio')
        records.append(item(name,fmt(value,'%'),
            '全机观测占比 = 所有有效CPU内可配对%s handler区间的并集时间之和 / 所有有效CPU总观测时间 × 100%%。单核最高占比单独计算，不用一个采集窗口作全机分母。'%('硬中断' if kind=='irq' else '软中断'),
            why,
            '全机观测 %s；单核最高 %s。%s'%(fmt(value,'%'),fmt(peak,'%'),'缺少事件或完整配对时不可当作0%。' if value is None else ('热点达到单核经验线≥%d%%。'%threshold if peak is not None and peak>=threshold else '全机均值需与单核分布对照。')),
            '单核热点与整机总量含义不同；同核重叠是相关性，不能据此断言NPU性能因果。handler事件不覆盖全部入口/IPI开销，SoftIRQ墙钟区间可能含嵌套IRQ。',
            '%s；未配对事件 %d；分母 %.3f CPU·秒；%s。'%(('可用' if irq.get('available') else '事件缺失/未启用'),irq.get('unpaired_events',0),irq.get('observed_cpu_sec',0),'完整性有限，下界' if not irq.get('complete') else '配对事件完整（不代表内核全部中断开销）')))
    return records


def explanations_html(m,diag):
    out=['<p class="note">以下阈值为工具经验筛选值，不是Linux或Ascend官方性能标准；建议用同业务、同窗口基线复核。</p>']
    for r in explanations(m,diag):
        out.append('<article class="card metric-explanation"><h3>%s：%s</h3>'%(escape(r['name']),escape(r['当前值'])))
        for key,value in r.items():
            if key not in ('name','当前值'):out.append('<p><b>%s：</b>%s</p>'%(escape(key),escape(value)))
        out.append('</article>')
    return ''.join(out)


def explanations_md(m,diag):
    out=['> 以下阈值为工具经验筛选值，不是Linux或Ascend官方标准；应与同业务基线对照。','']
    for r in explanations(m,diag):
        out.append('#### %s：%s\n'%(r['name'],r['当前值']))
        for key,value in r.items():
            if key not in ('name','当前值'):out.append('**%s：** %s\n'%(key,value))
    return '\n'.join(out)


def collection_actions_html(integrity):
    """Actionable existing-file/collection guidance, driven by verified states."""
    actions = (integrity or {}).get('actions', [])
    if not actions:
        return '<p class="note">采集执行清单未提供；仅据现有文件判断，无法确认缺失项是否曾请求或成功采集。</p>'
    out = ['<h3>数据补证与处理路径</h3>']
    for item in actions:
        out.append('<div class="card collection-action"><p><b>%s · %s</b>：%s</p><p>%s</p>' % (
            escape(str(item.get('category', '证据'))), escape(str(item.get('status', 'UNKNOWN'))),
            escape(str(item.get('reason', '未记录原因'))), escape(str(item.get('action', '核验现有原始证据')))))
        if item.get('recollect') and item.get('command'):
            command = item['command']
            if isinstance(command, list):
                import shlex
                command = ' '.join(shlex.quote(str(x)) for x in command)
            out.append('<pre><code>%s</code></pre>' % escape(str(command)))
        out.append('</div>')
    return ''.join(out)


def collection_integrity_html(integrity):
    from .report_sections import table
    data = integrity or {}
    gaps = data.get('gaps', [])
    if not gaps:
        return ''
    return ('<h3>采集缺项与原因</h3>'
            '<p>共 %d 项缺失、不完整或状态未知。完整状态见 report_data.json。</p>' % len(gaps)
            + table(['类别', '项目或原始路径', '状态', '原因'], [
                [row['category'], row.get('item') or '—', row['status'], row.get('reason') or '未记录']
                for row in gaps], True, title='查看采集缺项'))


def collection_actions_md(integrity):
    out=['### 数据补证与处理路径', '']
    actions=(integrity or {}).get('actions',[])
    if not actions:
        return '采集执行清单未提供；无法确认缺失项是否曾请求或成功采集。'
    for item in actions:
        out.append('- **%s · %s**：%s %s' % (item.get('category','证据'),item.get('status','UNKNOWN'),item.get('reason','未记录原因'),item.get('action','核验现有原始证据')))
        if item.get('recollect') and item.get('command'):
            command=item['command']
            if isinstance(command,list):
                import shlex
                command=' '.join(shlex.quote(str(x)) for x in command)
            out += ['', '```bash',str(command),'```','']
    return '\n'.join(out)
