# -*- coding: utf-8 -*-
"""metrics.py — CPU Host 指标计算 + 指标中文释义表 (仅标准库)

所有指标在报告中均须附 METRIC_EXPLANATIONS 的中文解释。
"""
from collections import defaultdict

# ================================================================
# 指标/事件中文释义表 (报告引用来源)
# ================================================================
METRIC_EXPLANATIONS = {
    "cpu_util":        "CPU 利用率：有效观测时间内非idle调度任务时间占比。trace通过连续switch重建busy/idle，user/system 区分依赖 /proc/stat 快照（为开机以来累计值）。",
    "cpu_util_p95":    "CPU 利用率 P95：将所有核心利用率排序后取第 95 分位，反映高负载核心的普遍水平。",
    "cs_rate":         "上下文切换率 (context switches/sec)：全机每秒sched_switch次数；高值需结合等待/负载判断。",
    "wakeup_rate":     "唤醒率 (wakeups/sec)：每秒任务被唤醒进入 runnable 的次数，反映任务碎片化程度与调度压力。",
    "sched_latency":   "调度延迟 (scheduling latency)：任务从被唤醒 (sched_wakeup) 到真正获得 CPU (sched_switch) 的等待时间，直接体现 runnable 队列拥堵程度。",
    "runnable_avg":    "平均可运行任务数 (runnable)：已完成成功唤醒和R/R+切出等待区间的时间加权下界，不是全系统精确runqueue长度。",
    "irq_time":        "硬中断 CPU 占用：CPU 在处理硬件中断上花费的时间占比 (irq_handler_entry~exit)。",
    "softirq_time":    "软中断 CPU 占用：CPU 在处理软中断上花费的时间占比 (softirq_entry~exit)。软中断是中断下半部延迟处理机制。",
    "irq_hotspot":     "中断热点：单个核心 IRQ/SoftIRQ 占用远高于其他核心，通常由网卡中断亲和性 (IRQ affinity) 固定在同一核导致。",
    "freq_avg":        "CPU 平均频率：策略域已知样本持续时间加权平均；驱动报告频率不等于实测频率；低值单独不能证明降频根因。",
    "idle_ratio":      "CPU 空闲占比：idle 状态时间占比，过高说明该核负载不足或任务未调度到该核。",
    "migration":       "任务迁移次数：任务在 CPU 之间搬移的次数 (sched_migrate_task 或跨核运行推断)，频繁迁移导致缓存失效、NUMA 跨访。",
    "preempt":         "可运行态切出次数：sched_switch prev_state=R/R+；不能据此证明其他线程因果性抢占。",
    "buffer_overrun":  "buffer 溢出条数：采集期间 ring buffer 溢出而丢失的事件数，>0 说明 trace 可能不完整，结论置信度应下调。",
}
# 软中断 vec 编号 -> 名称 (Linux 经典编号, 兜底用)
SOFTIRQ_VEC_NAMES = {0: "HI", 1: "TIMER", 2: "NET_TX", 3: "NET_RX", 4: "BLOCK",
                     5: "BLOCK_IOPOLL", 6: "TASKLET", 7: "SCHED", 8: "HRTIMER", 9: "RCU"}
# 常见事件中文解释 (报告中"事件说明"章节使用)
EVENT_EXPLANATIONS = {
    "NET_RX":    "网络接收软中断：网卡收到数据包后，协议栈处理（IP/TCP 解析、socket 分发）在软中断中延迟执行。NET_RX集中单核是需结合Worker时间线验证的Host侧风险。",
    "NET_TX":    "网络发送软中断：网卡发送完成后的收尾处理。",
    "TIMER":     "定时器软中断：内核定时器 (tick/timer_list) 的到期处理，过高说明大量定时器密集到期。",
    "TASKLET":   "TASKLET 软中断：驱动常用的延迟执行机制，常见于网卡/NVMe 驱动。",
    "SCHED":     "调度软中断：进程调度相关延迟处理（负载均衡、调度类节流等）。",
    "RCU":       "RCU 软中断：Read-Copy-Update 宽限期回收，核心数多或 RCU pressure 大时会明显。",
    "BLOCK":     "块设备软中断：块 I/O 完成处理，存储密集场景明显。",
    "HI":        "高优先级软中断：最高优先级软中断，数量少但可抢占其他软中断。",
    "HRTIMER":   "高精度定时器软中断：hrtimer 到期处理。",
    "irq_handler_entry": "硬件中断进入事件：CPU 开始处理某条硬件中断线，irq=中断号，name=中断名（如 nvme0q3、eth0、iri/pci-MSI）。",
    "irq_handler_exit":  "硬件中断退出事件：与 entry 配对可得单次中断耗时，ret=handled 表示有实际处理。",
    "softirq_entry":     "软中断进入事件：vec=软中断编号，[action=NAME] 是软中断名。",
    "softirq_exit":      "软中断退出事件：与 entry 配对可得单次软中断耗时。",
    "softirq_raise":     "软中断触发事件：标记即将执行某类软中断（不代表已执行，仅作触发频度参考）。",
    "sched_switch":      "进程切换事件：CPU 上 prev（让出 CPU 的任务）切换到 next（获得 CPU 的任务），是计算利用率、上下文切换、运行时间的基础。",
    "sched_wakeup":      "任务唤醒事件：任务因 I/O 完成/锁释放等被唤醒进入 runnable 队列，与 sched_switch 配对可算调度延迟。",
    "sched_waking":      "任务开始唤醒事件：wakeup 的前置动作，一般与 sched_wakeup 成对。",
    "sched_wakeup_new":  "新创建任务首次唤醒事件。",
    "task_newtask":      "新建任务事件 (fork/clone)。",
    "sched_migrate_task": "任务迁移事件：任务被调度器迁往其他 CPU。",
    "cpu_idle":          "CPU 空闲状态事件：state=进入的 C-state，state=4294967295 表示退出 idle 恢复运行。",
    "cpu_frequency":     "CPU 频率变化事件：state=驱动报告的新频率，标准power/cpu_frequency为kHz；非标准导出需显式声明单位。",
    "irq_line_unknown":  "未收录中断名：按中断号展示，可在 /proc/interrupts 中查询对应设备。",
}
# 常见硬件中断名解释 (报告引用; 未收录则走 unknown)
IRQ_NAME_EXPLANATIONS = {
    "nvme":  "NVMe 存储队列中断（nvme0q*），数据加载/日志写入时产生。",
    "eth":   "网卡中断（eth*/enp*/ens*），网络通信的核心中断来源。",
    "mlnx":  "Mellanox/NVIDIA 网卡中断（mlx*），HCCL/NCCL 通信高频使用。",
    "hns":   "华为鲲鹏网卡中断（hns*），昇腾服务器常见。",
    "iri":   "PCI MSI/MSI-X 中断入口（iri/pci-MSI），具体设备需对照 /proc/interrupts。",
    "timer": "本地定时器中断。",
    "resched": "处理器间重调度中断 (IPI)，触发其他核重新调度。",
    "call_function": "处理器间函数调用中断 (IPI)。",
    "tlb":   "TLB 刷新 IPI 中断。",
    "acpi":  "ACPI 相关中断（含热事件通知）。",
}
# 常见任务名提示 (泛化, 不写死业务)
TASK_HINTS = [
    ("python", "Python 训练/推理主进程或 dataloader"),
    ("torchrun", "PyTorch 分布式启动器"),
    ("vllm", "vLLM 推理服务"),
    ("hccl", "HCCL 通信线程"),
    ("nccl", "NCCL 通信线程"),
    ("das", "昇腾 CANN/DeviceAccess 守护线程"),
    ("mindspore", "MindSpore 训练/推理进程"),
    ("ge", "图引擎 GE 线程"),
    ("tokenizer", "分词线程"),
    ("dataloader", "数据加载线程"),
    ("java", "Java 进程"),
    ("java", "Java 进程"),
    ("ffmpeg", "音视频处理进程"),
]

def _explain_irq_name(name):
    n = str(name).lower()
    for k, v in IRQ_NAME_EXPLANATIONS.items():
        if k in n:
            return v
    return EVENT_EXPLANATIONS["irq_line_unknown"]

def _explain_task(comm):
    c = str(comm).lower()
    for k, v in TASK_HINTS:
        if k in c:
            return v
    return ""

def _pct(sorted_vals, p):
    """p in [0,100]; 线性插值分位数"""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k); c = min(f + 1, len(sorted_vals) - 1)
    d = k - f
    return sorted_vals[f] * (1 - d) + sorted_vals[c] * d

# ================================================================
# 主计算
# ================================================================
def _pop_any_pending(pending, cpu):
    """兜底: exit 事件缺少 irq/vec 编号时, 弹出该 cpu 上最早的一条 pending 配对。"""
    cands = [(k, v) for k, v in pending.items() if k[0] == cpu]
    if not cands:
        return None
    k, v = min(cands, key=lambda kv: kv[1][0])
    del pending[k]
    return v


WAKE_MAX_AGE_S = 30.0   # 唤醒等待老化阈值 (秒): 超时未运行的唤醒记录视为陈旧


def compute_metrics(td):
    """Orchestrate evidence modules; v1 fields stay available in explicit units."""
    from .npu_affinity import analyze_npu_affinity
    from .evidence import read_json, optional_tools
    from .process_analysis import analyze_processes, resolve_task
    from .product_identity import detect_product
    from .scheduling import analyze_scheduling
    from .interrupt_analysis import analyze_interrupts
    from .frequency_analysis import analyze_frequency, legacy_frequency
    from .contention_analysis import analyze_contention
    from .ai_rankings import summarize_ai_rankings
    from .timeline import build_timeseries, task_compatibility
    from .collection_integrity import analyze_collection_integrity
    from .environment_analysis import analyze_environment
    from .topology import analyze_topology
    events=sorted(td.events,key=lambda e:e.ts)
    lo=events[0].ts if events else 0.0
    hi=events[-1].ts if events else lo
    # Window markers are emitted only while tracing is enabled.
    markers={str(e.fields.get('message', '')):e.ts for e in events if e.etype=='tracing_mark_write'}
    lo=markers.get('CPU_HOST_WINDOW_START',lo)
    hi=markers.get('CPU_HOST_WINDOW_END',hi)
    events=[e for e in events if lo<=e.ts<=hi]
    ps=td.parse_stats or {}
    total=int(ps.get('total',0) or 0);parsed=int(ps.get('parsed',0) or 0)
    over=0
    try: over=int(td.snapshot.get('trace_overrun.txt','0').strip() or 0)
    except ValueError: pass
    m={'schema_version':2,'available':{e.etype for e in events}, 'warnings':list(td.warnings),
       'parse_stats':ps,'format_name':td.format_name,'snapshot':td.snapshot,'metadata':td.metadata,
       't_start':lo,'t_end':hi,'duration':max(hi-lo,1e-9), 'buffer_overrun':over,
       'buffer_overrun_known':td.snapshot.get('trace_overrun.txt','').strip().isdigit(),
       'events_ok':bool(events) and (total==0 or parsed==total) and not td.snapshot.get('hostbound/export_errors.txt','').strip(),
       'proc_stat':_parse_proc_stat(td.snapshot.get('proc_stat.txt','')),
       'governor':_parse_governor(td.snapshot.get('cpufreq.txt',''))}
    try: m['n_cpus_report']=int(td.metadata.get('nproc',0)) or None
    except ValueError: m['n_cpus_report']=None
    if td.snapshot.get('hostbound/helper_error.txt','').strip():m['warnings'].append('增强采集降级：'+td.snapshot['hostbound/helper_error.txt'].strip())
    if over: m['warnings'].append('trace buffer丢失/溢出 %d 条：时间线与分位数仅表示已观测样本'%over)
    if not m['events_ok']: m['warnings'].append('事件流缺失或解析失败，数据不完整')
    m['optional_tools']=optional_tools(td.snapshot)
    m['product_identity']=detect_product(td.snapshot)
    m['process_analysis']=analyze_processes(m,events)
    analyze_scheduling(m,events)
    analyze_interrupts(m,events)
    m['frequency']=analyze_frequency(m,events)
    m['freq']=legacy_frequency(m['frequency'])
    if not m['governor']: m['governor']=','.join(sorted({p['governor'] for p in m['frequency']['domains'] if p.get('governor')})) or None
    m['contention']=analyze_contention(m)
    m['ai_rankings']=summarize_ai_rankings(m)
    m['tasks']=task_compatibility(m)
    m['tasks']['observed_cpus_by_identity']={}
    for ev in events:
        if ev.etype=='sched_switch' and ev.cpu is not None:
            tid=int(ev.fields.get('next_pid',-1))
            if tid>0:
                values=m['tasks']['observed_cpus_by_tid'].setdefault(tid,[])
                if ev.cpu not in values: values.append(ev.cpu)
                identity=resolve_task(m['process_analysis'],tid,ev.ts)
                if identity:
                    scoped=m['tasks']['observed_cpus_by_identity'].setdefault(identity['identity'],[])
                    if ev.cpu not in scoped: scoped.append(ev.cpu)
    m['timeseries']=build_timeseries(m,events)
    m['npu_affinity']=analyze_npu_affinity(m)
    from .binding_plan import build_binding_plan
    m['binding_plan']=build_binding_plan(m)
    m['topology']=analyze_topology(m)
    from .resource_analysis import analyze_resources
    m['resources']=analyze_resources(m)
    m['collection_integrity']=analyze_collection_integrity(m, getattr(td, 'source_files', {}))
    m['environment']=analyze_environment(td.snapshot, m['collection_integrity'])
    m['source_files']=getattr(td, 'source_files', {})
    m['npu_affinity']['collection_integrity']=m['collection_integrity']
    return m

def _to_int(v):
    try:
        return int(str(v))
    except Exception:
        return -1

def task_name_of(pid, task_comm=None):
    """查 task_comm 表 (pid -> comm) 返回任务名; 无记录时回退 pid:xxx。"""
    if task_comm:
        c = (task_comm.get(pid) or "").strip()
        if c and not c.startswith("pid:"):
            return c
    return "pid:%d" % pid

def _pid_disp(comm, pid):
    """任务显示名: comm 缺失或为 pid 回退形式 (pid:xxx) 时, 不重复追加 (pid xxx)。"""
    c = (comm or "").strip()
    if not c or c == "pid:%d" % pid or c.startswith("pid:"):
        return "pid:%s" % pid
    return "%s (TID %s)" % (c, pid)

def _add_range(arr, known, m, t0, t1, bucket, n):
    """把 [t0,t1) 区间按桶累加 (秒)"""
    if t1 < t0:
        return
    b0 = min(max(int((t0 - m["t_start"]) / bucket), 0), n - 1)
    b1 = min(max(int((t1 - m["t_start"]) / bucket), 0), n - 1)
    for b in range(b0, b1 + 1):
        lo = m["t_start"] + b * bucket
        hi = lo + bucket
        seg = min(t1, hi) - max(t0, lo)
        if seg > 0:
            arr[b] += seg
            known[b] += seg

def _parse_proc_stat(text):
    """首行 cpu 聚合: 开机以来累计占比"""
    for line in text.splitlines():
        if line.startswith("cpu "):
            parts = line.split()
            keys = ("user", "nice", "system", "idle", "iowait",
                    "irq", "softirq", "steal", "guest", "gnice")
            vals = {}
            for i, k in enumerate(keys):
                try:
                    vals[k] = float(parts[i + 1]) if len(parts) > i + 1 else 0.0
                except Exception:
                    vals[k] = 0.0
            total = sum(vals.values())
            if total <= 0:
                return {}
            return {k: 100.0 * v / total for k, v in vals.items()}
    return {}

def _parse_governor(cpufreq_text):
    gov = set()
    for line in (cpufreq_text or "").splitlines():
        if "scaling_governor" in line:
            try:
                gov.add(line.split(":", 1)[1].strip())
            except Exception:
                pass
    return ",".join(sorted(gov)) if gov else None

def freq_to_mhz(value, unit="kHz"):
    """Compatibility entry: standard interfaces are kHz; alternate units explicit."""
    from .frequency_analysis import to_mhz
    return to_mhz(value,unit)
