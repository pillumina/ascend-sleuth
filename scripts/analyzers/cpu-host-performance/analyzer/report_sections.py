"""Shared report sections for frequency, discovery, and evidence-backed contention."""
from html import escape
from .environment_analysis import toolkit_version_location
from .report_explanation import fmt
from .npu_affinity import _topology, cpu_list
from .report_tables import disclose_table, limit_markdown_tables
from .frequency_idle_chart import render_frequency_idle
from .resource_chart import render_resource_overview


def _text(value):
    if value is None:return '缺失 / 不可用'
    if isinstance(value,list):return ', '.join(str(x) for x in value) or '—'
    return str(value)


def table(headers,rows,html=False,title="完整明细",force=False):
    rows=list(rows)
    if html:
        markup = '<div class="core-table-scroll"><table><thead><tr>'+''.join('<th>%s</th>'%escape(x) for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>%s</td>'%escape(_text(x)) for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'
        return disclose_table(markup,title,len(rows),force)
    def clean(x):return _text(x).replace('|','\\|').replace('\n',' ')
    return limit_markdown_tables('| '+' | '.join(headers)+' |\n|'+'|'.join('---' for _ in headers)+'|\n'+'\n'.join('| '+' | '.join(clean(x) for x in row)+' |' for row in rows))+'\n'


def paragraph(text,html):
    return '<p>%s</p>'%escape(text) if html else text+'\n\n'


def heading(text,html):
    return '<h3>%s</h3>'%escape(text) if html else '### '+text+'\n\n'


_ENV_LABELS = {
    'os_release': '操作系统', 'kernel': '内核与架构', 'thp': '透明大页（THP）',
    'numa_balancing': '自动 NUMA 平衡', 'swappiness': 'vm.swappiness',
    'overcommit_memory': 'vm.overcommit_memory', 'clocksource': '内核时钟源',
    'driver': 'Ascend 驱动', 'toolkit': 'CANN Toolkit', 'runtime': 'CANN Runtime',
    'compiler': 'CANN Compiler', 'hccl': 'HCCL', 'opp': 'OPP', 'atb': 'ATB', 'mindie': 'MindIE',
    'exe': '可执行文件', 'environment': '启动变量', 'limits': '进程资源限额', 'libraries': '已加载共享库',
}


def environment_section(data):
    if data.get('status', 'UNKNOWN') == 'UNKNOWN':
        return paragraph('此采集包没有环境快照。操作系统、软件版本和目标进程环境显示为 N/A。', True)

    out = [paragraph('以下为采集时读取的环境信息，供同负载对照与排查。'
                     '组件版本来自宿主机安装目录，目标进程以其已加载库为依据。', True)]
    native = data.get('native_dump')
    if native:
        if native['capture_status'] == 'COLLECTED':
            out.append(paragraph('原生 Ascend Dump · Schema %s · %s' % (
                native.get('schema_version') or '未知', native.get('status') or '采集状态未知'), True))
            coverage = native.get('collection', {})
            if coverage:
                out.append(table(['原生采集范围', '状态', '说明'],
                                 [(name, info.get('status'), info.get('reason') or '—')
                                  for name, info in sorted(coverage.items())],
                                 True, 'Ascend Dump 采集覆盖', force=True))
        else:
            out.append(paragraph('原生 Ascend Dump · %s · %s' % (
                native['capture_status'], native.get('reason') or '—'), True))
    for key, title in (('host', '宿主机系统与内核'), ('ascend', 'Ascend 组件版本')):
        out.append(heading(title, True))
        rows = data.get(key, [])
        if not rows:
            out.append(paragraph('此采集包缺少这类证据。', True))
            continue
        out.append(table(['项目', '采集值', '来源', '状态', '采集时间', '缺失原因'],
                         [('asc-devkit 子包' if toolkit_version_location(row)[0] == 'asc-devkit'
                           else _ENV_LABELS.get(row['id'], row['id']), row['value'], row['source'],
                           row['status'], row.get('collected_at'), row.get('reason') or '—') for row in rows], True))

    out.append(heading('业务进程启动环境与已加载库', True))
    if not data.get('targets'):
        reason = ('本次未请求业务进程详情。' if data.get('target_scope') == 'NOT_REQUESTED'
                  else '此采集包缺少业务进程环境记录。')
        out.append(paragraph(reason, True))
    targets = data.get('targets', [])
    for target in targets[:100]:
        pid, starttime = target['pid'], target.get('starttime')
        identity = 'PID %s' % pid
        if target.get('role'):
            identity = '%s · %s' % (target['role'], identity)
        if starttime is not None:
            identity += ' · starttime %s' % starttime
        out.append(heading(identity, True))
        out.append(paragraph(' / '.join(str(value) for value in (
            target['status'], target.get('collected_at'), target.get('reason')) if value), True))
        rows = []
        for field in ('exe', 'environment', 'limits', 'libraries'):
            item = target.get(field)
            if not item:
                continue
            value = item['value']
            if field == 'environment':
                summary = '%d 项白名单启动变量' % len(value) if value is not None else None
            elif field in ('limits', 'libraries'):
                summary = '%d 条记录' % len(value) if value is not None else None
            else:
                summary = value
            rows.append((_ENV_LABELS[field], summary, item['source'], item['status'], item['reason'] or '—'))
        if rows:
            out.append(table(['项目', '采集结果', '来源', '状态', '缺失原因'], rows, True))
        variables = target.get('environment', {}).get('value') or {}
        if variables:
            out.append(table(['启动变量', '值'], sorted(variables.items()), True, '白名单启动变量'))
        limits = target.get('limits', {}).get('value') or {}
        if limits:
            out.append(table(['资源限额', '软限制', '硬限制', '单位'],
                             [(name, row['soft'], row['hard'], row['unit'] or '—')
                              for name, row in limits.items()], True, '进程资源限额', force=True))
        libraries = target.get('libraries', {}).get('value') or []
        if libraries:
            out.append(table(['已加载共享库路径'], [(path,) for path in libraries],
                             True, '已加载共享库', force=True))
    if len(targets) > 100:
        out.append(paragraph('仅展示前 100 / %d 个目标，完整记录见 report_data.json。' % len(targets), True))
    return ''.join(out)


def frequency_section(m,html=False):
    f=m.get('frequency',{});out=[heading('CPU Frequency Analysis',html)]
    out.append(paragraph('频率状态：%s；事件状态：%s；动态样本数：%s。%s'%(f.get('status','UNKNOWN'),f.get('event_status','UNKNOWN'),f.get('sample_count',0),'；'.join(f.get('reasons',[]))),html))
    rows=[]
    for p in f.get('domains',[]):
        rows.append([p['id'],cpu_list(p['cpus']),fmt(p['current_mhz'],' MHz'),fmt(p['average_mhz'],' MHz'),fmt(p['minimum_mhz'],' MHz'),fmt(p['highest_mhz'],' MHz'),fmt(p['maximum_mhz'],' MHz'),fmt(p['low_frequency_ratio'],'%'),p.get('governor'),p['source']+' / '+p['reliability'],p['sample_count'],str(p.get('errors',{}))])
    if rows:
        out.append(table(['策略域','相关CPU','当前','时间加权平均','窗口最低','窗口最高','硬件最大参考','低频时间占比','Governor','来源 / 可靠性','样本数','接口读取限制'],rows,html,title='全部CPU Frequency策略域',force=html))
    else:out.append(paragraph('没有可用策略域数据；频率缺失时不显示0 MHz。',html))
    out.append(paragraph(f.get('note',''),html))
    out.append(paragraph('低频占比仅在cpuinfo_max_freq可靠参考存在时计算（≤其50%，经验筛选）；首个样本前不外推。窗口无频率转换不表示降频。当前值来自结束快照，平均值仅覆盖已观测样本持续区间。',html))
    idle=m.get('idle',{})
    out.append(heading('CPU Idle Residency',html))
    out.append(paragraph('Idle状态：%s；来源：%s；可靠性：%s。%s'%(idle.get('status','NO_EVENTS'),idle.get('source','ftrace:power/cpu_idle'),idle.get('reliability','UNKNOWN'),'；'.join(idle.get('reasons',[]))),html))
    out.append(paragraph(idle.get('note','没有可用cpu_idle事件；缺失值为N/A。swapper近似空闲率另见第5节。'),html))
    if html: out.append(render_frequency_idle(m))
    out.append(table(['CPU','整窗Idle Residency','已知Idle秒','有效覆盖','整窗Idle下界','各C-state持续秒'],[
        [p['cpu'],fmt(p.get('residency_percent'),'%'),fmt(p.get('idle_sec'),' s'),fmt(p.get('coverage_percent'),'%'),fmt(p.get('idle_lower_bound_percent'),'%'),'; '.join('state%s: %.6f s'%(x['state'],x['residency_sec']) for x in p.get('states',[])) or 'N/A'] for p in idle.get('cpus',[])],html,title='全部CPU Idle Residency',force=html))
    pmu=f.get('pmu',{})
    out.append(paragraph('PMU：%s；%s'%(pmu.get('status','NOT_VALIDATED'),pmu.get('reason','未验证')),html))
    return ''.join(out) if html else '\n'.join(out)


def thread_section(m,html=False):
    a=m.get('process_analysis',{});ct=m.get('contention',{});rows=m.get('thread_metrics',[])
    out=[heading('Process / Thread Discovery',html)]
    out.append(paragraph('已发现进程 %d，任务身份 %d，关联TGID %s。%s'%(len(a.get('processes',[])),len(a.get('tasks',[])),a.get('related_tgids',[]),a.get('note','')),html))
    if a.get('errors'):out.append(paragraph('快照读取失败/退出竞争 %d 项；错误保留在report_data.json。'%len(a['errors']),html))
    summary=a.get('system_summary',{})
    if summary: out.append(paragraph('系统进程 %s / 线程 %s；AI线程 %s；同核竞争线程 %s；非关联 %s；未知 %s；角色置信度 %s。'%(summary.get('total_processes'),summary.get('total_threads'),summary.get('ai_threads'),summary.get('competitor_threads'),summary.get('unrelated_threads'),summary.get('unknown_threads'),summary.get('confidence_counts')),html))
    by_id={t['identity']:t for t in rows}
    for key,label,fallback in [('ai_workers','AI Worker Top 10',ct.get('workers',[])),('ai_competitors','AI竞争线程 Top 10',[]),('system_top','系统线程 CPU Runtime Top 10',[])]:
        ids=ct.get(key,fallback)
        chosen=[by_id[x] for x in ids if x in by_id]
        if key=='system_top' and not chosen: chosen=sorted(rows,key=lambda t:-(t.get('runtime_sec') or 0))
        out.append(heading(label,html))
        out.append(table(['进程','TGID','TID','类别','角色/置信度','NPU','Runtime','Runqueue Wait','Wait P99','CPU','关系证据'],[
            [t.get('process_name') or t.get('name'),t.get('tgid'),t['tid'],t.get('category','UNKNOWN'),str(t.get('role'))+' / '+str(t.get('confidence')),t.get('npu_ids'),fmt(t.get('runtime_sec'),' s'),fmt(t.get('runqueue_wait_sec'),' s'),fmt(t.get('wait_p99_ms'),' ms'),t.get('cpus'),'; '.join(t.get('relation_evidence',[]))] for t in chosen[:10]],html))
    out.append(paragraph('AI Worker需要NPU PID/TGID、后代关系或运行证据支持；竞争线程需同核可运行等待时间重叠。仅线程名称/相同Affinity不足以确认角色或竞争因果。',html))
    mapping=[]
    for t in rows:
        mapping.append([t.get('process_name'),t.get('tgid'),t['tid'],t.get('ppid'),t['identity'],t.get('category','UNKNOWN'),t.get('role'),t.get('npu_ids',[]),cpu_list(t.get('allowed_cpus') or []) if t.get('allowed_cpus') is not None else None,t.get('last_cpu'),t.get('mems_allowed_list'),t.get('task_group'),t.get('confidence'),fmt(t.get('runtime_sec'),' s'),fmt(t.get('runtime_share'),'%'),fmt(t.get('cpu_utilization'),'%'),fmt(t.get('runqueue_wait_sec'),' s'),fmt(t.get('wait_p50_ms'),' ms'),fmt(t.get('wait_p95_ms'),' ms'),fmt(t.get('wait_p99_ms'),' ms'),t.get('wait_samples'),t.get('context_switches'),t.get('wakeups'),t.get('runnable_switch_out'),t.get('migrations'),t.get('cpus'),t.get('data_quality'),'; '.join(t.get('relation_evidence',[])),'; '.join(t.get('evidence',[]))])
    out.append(table(['进程','TGID','TID','PPID','任务身份/starttime','类别','角色','NPU关联','Affinity快照','PSR快照','Mems_allowed','Task Group','角色置信度','CPU Runtime','Runtime份额','线程利用率','Runqueue Wait','Wait P50','Wait P95','Wait P99','唤醒样本','上下文切换','成功唤醒','Runnable切出','Migration','观测CPU','数据质量','关系证据','采样证据'],mapping,html,title='全部进程/线程映射',force=html))
    out.append(heading('CPU Contention Analysis',html))
    out.append(paragraph(ct.get('note',''),html))
    by_id={t['identity']:t for t in rows}
    for name,label in [('runtime','Top CPU Runtime Threads'),('wait','Top Runqueue Wait Threads'),('runnable','Top Runnable Switch-out Threads'),('migration','Top CPU Migration Threads')]:
        out.append(heading(label,html));rank=[]
        for key in ct.get('rankings',{}).get(name,[]):
            t=by_id[key]
            rank.append([t.get('process_name') or t.get('name'),t.get('tgid'),t['tid'],t.get('npu_ids',[]),fmt(t['runtime_sec'],' s'),fmt(t.get('runtime_share'),'%'),fmt(t.get('cpu_utilization'),'%'),fmt(t.get('runqueue_wait_sec'),' s'),fmt(t.get('wait_p50_ms'),' ms'),fmt(t.get('wait_p95_ms'),' ms'),fmt(t.get('wait_p99_ms'),' ms'),t['wait_samples'],t.get('context_switches'),t.get('wakeups'),t.get('runnable_switch_out'),t.get('migrations'),t['cpus'],t.get('data_quality')])
        headers=['Process','TGID','TID','NPU','CPU Runtime','Runtime份额','线程利用率','Runqueue Wait','Wait P50','Wait P95','Wait P99','唤醒样本','上下文切换','成功唤醒','Runnable切出','Migration','观测CPU','数据质量']
        if html and len(rank)>10: out.append(table(headers,rank[:5],html))
        out.append(table(headers,rank,html,title=label+' 全部记录',force=html and len(rank)>10))
    out.append(paragraph('Runtime份额以全体任务已观测runtime为分母，线程利用率以采集窗口为分母；Runtime含任务上下文内IRQ，不等同纯用户态CPU。Runqueue Wait为已完成成功唤醒+R/R+切出的等待区间下界，Wait P99仅含成功唤醒；未配对等待不填零。',html))
    _,nodes,_=_topology(m.get('snapshot',{}));c2n={c:n for n,cs in nodes.items() for c in cs}
    out.append(heading('NPU Worker CPU 竞争情况与证据链',html));chains=[]
    for key in ct.get('workers',[]):
        t=by_id[key];candidates=[c for c in ct.get('candidates',[]) if c['target_identity']==key]
        observed_nodes=sorted({c2n[c] for c in t['cpus'] if c in c2n})
        chains.append([t.get('npu_ids'),t.get('tgid'),t['tid'],t.get('role'),cpu_list(t['cpus']),observed_nodes,fmt(t.get('wait_p99_ms'),' ms'),'; '.join('TID%d %.3fms CPU%s'%(c['contender_tid'],c['overlap_sec']*1000,c['cpus']) for c in candidates) or '未观测到候选；不代表绝无竞争'])
    out.append(table(['NPU','Worker/关联TGID','TID','角色','观测CPU','NUMA','Wait P99','候选与重叠'],chains,html))
    candidates=ct.get('candidates',[])
    out.append(table(['目标TID/TGID','候选TID/TGID','CPU','NUMA','重叠ms','时间窗证据','置信度','因果'],[
        ['%s/%s'%(c['target_tid'],c['target_tgid']),'%s/%s'%(c['contender_tid'],c['contender_tgid']),c['cpus'],sorted({c2n[x] for x in c['cpus'] if x in c2n}),fmt(c['overlap_sec']*1000),str(c['windows'])+'； '+'; '.join(c['evidence']),c['confidence'],c['causality']] for c in candidates],html))
    out.append(heading('热点CPU与关联线程',html))
    out.append(table(['CPU','NUMA','利用率','TID'],[[r['cpu'],c2n.get(r['cpu']),fmt(r['util'],'%'),sorted(set(r['threads']))] for r in ct.get('hot_cores',[])],html))
    out.append(heading('CPU Affinity 重叠（配置相关性）',html))
    out.append(paragraph('Affinity比较范围：'+str(ct.get('affinity_scope',{})),html))
    out.append(table(['TID A','TID B','重叠CPU','因果'],[[r['a_tid'],r['b_tid'],cpu_list(r['cpus']),r['causality']] for r in ct.get('affinity_overlaps',[])],html))
    out.append(heading('cgroup CPU quota / throttling',html))
    cg=ct.get('cgroups',[])
    if not cg:out.append(paragraph('缺少可配对cgroup快照；不能排除容器配额限制。',html))
    out.append(table(['cgroup/祖先','TGID','Quota核数','nr_throttled增量','throttled_usec增量','来源与限制'],[[r['path'],r['tgids'],('无限制（核验祖先）' if r.get('quota_status')=='UNLIMITED' else fmt(r['quota_cpus'])),r['nr_throttled_delta'],r['throttled_usec_delta'],r['evidence']+'; '+r['note']] for r in cg],html))
    out.append(paragraph('Device时间关联：%s；匹配 %s。未提供或未对齐时，只能报告Host侧风险，不能确认NPU性能根因。'%(ct.get('device_correlation',{}).get('status'),ct.get('device_correlation',{}).get('matches')),html))
    out.append(paragraph('优化与验证：先核验目标/候选线程职责、有效cpuset、IRQ Affinity和cgroup限额；比较同负载下的Worker等待分位数、重叠窗口与NPU吞吐/请求延迟。调整并发或配额等方案须经用户确认，保存原配置，复采同一窗口验证收益与副作用。',html))
    return ''.join(out) if html else '\n'.join(out)


def core_table(m,html=False):
    _,nodes,_=_topology(m.get('snapshot',{}));c2n={c:n for n,cs in nodes.items() for c in cs}
    return table(['CPU','NUMA','观测秒','利用率','空闲率','切换/秒','唤醒/秒','R切出/秒','迁移/秒','硬中断','软中断'],[
        [c,c2n.get(c),fmt(p.get('observed_sec'),' s'),fmt(p.get('util'),'%'),fmt(p.get('idle_ratio'),'%'),fmt(p.get('cs_rate')),fmt(p.get('wakeup_rate')),fmt(p.get('runnable_switch_out_rate')),fmt(p.get('migration_rate')),fmt(p.get('irq_ratio'),'%'),fmt(p.get('softirq_ratio'),'%')] for c,p in sorted(m.get('per_cpu',{}).items())],html,title='全部CPU核心明细',force=html)


def coverage_section(m,html=False):
    return heading('可选工具证据覆盖（缺失不等于正常）',html)+table(['工具','状态','证据文件','限制'],[[r['name'],r['status'],r['evidence'],r['note']] for r in m.get('optional_tools',[])],html)


def topology_section(m,html=False):
    topology=m.get('topology',{})
    nodes=topology.get('nodes',[])
    count=topology.get('cpu_count',len(m.get('per_cpu',{})))
    out=[paragraph('CPU 总数 %s；NUMA 节点 %s；距离矩阵列顺序 %s。'%(count,topology.get('numa_count',topology.get('node_count',len(nodes))),topology.get('distance_node_order',[])),html)]
    if not nodes:
        _,mapped,_=_topology(m.get('snapshot',{}))
        nodes=[{'node':node,'cpus':cpus} for node,cpus in sorted(mapped.items())]
    def gib(value):
        return fmt(value/1048576.,' GiB') if isinstance(value,(int,float)) else 'N/A'
    rows=[]
    for node in nodes:
        memory=node.get('memory_kb',{})
        rows.append([node.get('node'),cpu_list(node.get('cpus',[])),gib(node.get('total_kb',memory.get('MemTotal'))),gib(node.get('free_kb',memory.get('MemFree'))),node.get('distance_by_node') or node.get('distance'),node.get('errors',{})])
    out.append(table(['NUMA','CPU列表','内存容量','内存空闲','节点距离','读取限制'],rows,html,title='全部NUMA拓扑与容量',force=html))
    out.append(paragraph('CPU许可范围、PSR/trace运行位置、Mems_allowed许可内存节点、numa_maps/numastat实际页分布分别核验。节点距离是拓扑成本提示，实际页不在本地不能单独证明跨节点访问导致性能损失；相关任务证据见2.3节。',html))
    return ''.join(out) if html else '\n'.join(out)


def resource_section(m, html=False):
    return render_resource_overview(m, html)


def interrupt_tables(m,kind,html=False):
    from .metrics import EVENT_EXPLANATIONS, _explain_irq_name
    data=m.get(kind,{})
    key='names' if kind=='irq' else 'actions'
    label='硬中断来源' if kind=='irq' else '软中断类型'
    values=data.get('all_'+key,data.get('top_'+key,[]))
    rows=[[name,count,fmt(seconds*1000,' ms'),_explain_irq_name(name) if kind=='irq' else EVENT_EXPLANATIONS.get(name,'参考内核文档')] for name,count,seconds in values]
    headers=['中断源' if kind=='irq' else '软中断类型','次数','累计耗时','说明']
    if not rows: return ''
    out=[]
    if len(rows)>5:
        out.append(paragraph('按累计耗时排列的 Top 5；完整来源与次数保留在展开表格。',html))
        out.append(table(headers,rows[:5],html))
    out.append(table(headers,rows,html,title='全部'+label,force=html and len(rows)>5))
    return ''.join(out) if html else '\n'.join(out)
