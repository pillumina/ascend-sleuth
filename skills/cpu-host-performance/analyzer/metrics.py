# -*- coding: utf-8 -*-
"""metrics.py — CPU Host 指标计算 + 指标中文释义表 (仅标准库)

所有指标在报告中均须附 METRIC_EXPLANATIONS 的中文解释。
"""
from collections import defaultdict

# ================================================================
# 指标/事件中文释义表 (报告引用来源)
# ================================================================
METRIC_EXPLANATIONS = {
    "cpu_util":        "CPU 利用率：非空闲时间占比。trace 中可精确得到 busy/idle，user/system 区分依赖 /proc/stat 快照（为开机以来累计值）。",
    "cpu_util_p95":    "CPU 利用率 P95：将所有核心利用率排序后取第 95 分位，反映高负载核心的普遍水平。",
    "cs_rate":         "上下文切换率 (context switches/sec)：每秒进程/线程切换次数，过高说明任务碎片化或争抢激烈。",
    "wakeup_rate":     "唤醒率 (wakeups/sec)：每秒任务被唤醒进入 runnable 的次数，反映任务碎片化程度与调度压力。",
    "sched_latency":   "调度延迟 (scheduling latency)：任务从被唤醒 (sched_wakeup) 到真正获得 CPU (sched_switch) 的等待时间，直接体现 runnable 队列拥堵程度。",
    "runnable_avg":    "平均可运行任务数 (runnable)：任意时刻处于等待 CPU 状态的平均任务数，>核心数说明调度拥挤。",
    "irq_time":        "硬中断 CPU 占用：CPU 在处理硬件中断上花费的时间占比 (irq_handler_entry~exit)。",
    "softirq_time":    "软中断 CPU 占用：CPU 在处理软中断上花费的时间占比 (softirq_entry~exit)。软中断是中断下半部延迟处理机制。",
    "irq_hotspot":     "中断热点：单个核心 IRQ/SoftIRQ 占用远高于其他核心，通常由网卡中断亲和性 (IRQ affinity) 固定在同一核导致。",
    "freq_avg":        "CPU 平均频率：trace 期间 cpu_frequency 事件的平均值，高负载下频率低说明降频/温控/调度器策略问题。",
    "idle_ratio":      "CPU 空闲占比：idle 状态时间占比，过高说明该核负载不足或任务未调度到该核。",
    "migration":       "任务迁移次数：任务在 CPU 之间搬移的次数 (sched_migrate_task 或跨核运行推断)，频繁迁移导致缓存失效、NUMA 跨访。",
    "preempt":         "抢占次数：任务未运行完就被更高优先级任务切出 (prev_state=R 的 sched_switch)。",
    "buffer_overrun":  "buffer 溢出条数：采集期间 ring buffer 溢出而丢失的事件数，>0 说明 trace 可能不完整，结论置信度应下调。",
}
# 软中断 vec 编号 -> 名称 (Linux 经典编号, 兜底用)
SOFTIRQ_VEC_NAMES = {0: "HI", 1: "TIMER", 2: "NET_TX", 3: "NET_RX", 4: "BLOCK",
                     5: "BLOCK_IOPOLL", 6: "TASKLET", 7: "SCHED", 8: "HRTIMER", 9: "RCU"}
# 常见事件中文解释 (报告中"事件说明"章节使用)
EVENT_EXPLANATIONS = {
    "NET_RX":    "网络接收软中断：网卡收到数据包后，协议栈处理（IP/TCP 解析、socket 分发）在软中断中延迟执行。NET_RX 软中断打满单核是分布式训练/推理通信中最常见的 IRQ 热点根因。",
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
    "cpu_frequency":     "CPU 频率变化事件：state=新频率（单位通常 kHz，x86 平台）或 Hz（ARM 部分平台）。",
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
    """输入 parser.TraceData -> Metrics dict (全中文注释字段)"""
    events = sorted(td.events, key=lambda e: (e.ts if e.ts is not None else 0))
    m = {
        "available": set(), "warnings": list(td.warnings),
        "parse_stats": td.parse_stats, "format_name": td.format_name,
        "snapshot": td.snapshot, "metadata": td.metadata,
        "per_cpu": {}, "sched": {}, "irq": {}, "softirq": {},
        "freq": {}, "idle": {}, "tasks": {}, "timeseries": [],
        "proc_stat": {}, "duration": 0.0, "t_start": 0.0, "t_end": 0.0,
        "n_cpus": 0, "cpu_list": [],
    }
    for ev in events:
        m["available"].add(ev.etype)
    if not events:
        m["events_ok"] = False
        m["warnings"].append("无任何可分析事件")
        return m

    m["t_start"] = events[0].ts
    m["t_end"] = events[-1].ts
    m["duration"] = max(m["t_end"] - m["t_start"], 1e-9)
    dur = m["duration"]

    # 事件流健康度: 解析成功率 (供诊断报告区分 "确实无问题" 与 "数据不可信")
    _ps = td.parse_stats or {}
    _tot = int(_ps.get("total", 0) or 0)
    _okn = int(_ps.get("parsed", 0) or 0)
    m["events_ok"] = _tot == 0 or _okn * 2 >= _tot   # 成功率 >= 50% 视为可用
    if not m["events_ok"]:
        m["warnings"].append("事件流不完整 (成功解析 %d/%d 行), 分析结论可信度低" % (_okn, _tot))

    cpus = sorted({ev.cpu for ev in events if ev.cpu is not None})
    m["cpu_list"] = cpus
    m["n_cpus"] = len(cpus)
    # metadata 中记录的核数优先 (覆盖未采到事件的核)
    try:
        m["n_cpus_report"] = int(m["metadata"].get("nproc", 0)) or None
    except Exception:
        m["n_cpus_report"] = None

    has_idle_ev = "cpu_idle" in m["available"]
    # ---------- per-cpu 累计容器 ----------
    idle   = defaultdict(float)   # idle 时间
    cs     = defaultdict(int)     # sched_switch 次数
    wake   = defaultdict(int)     # wakeup 类事件次数
    irq_t  = defaultdict(float); irq_c = defaultdict(int)
    soft_t = defaultdict(float); soft_c = defaultdict(int)
    irq_pending = {}   # cpu -> (ts, irq_name)
    soft_pending = {}  # cpu -> (ts, action)
    # idle 配对: cpu -> True/False (是否处于 idle)
    in_idle = {} if has_idle_ev else None
    # swapper 近似 idle: cpu -> idle_start_ts or None
    idle_start = {}
    # freq
    freq_vals = defaultdict(list)
    # sched latency
    pending_wake = {}          # pid -> 最早 wakeup ts
    lat_all = []               # [(pid, comm, ts, lat)]
    runnable_weighted = 0.0    # 时间加权 runnable 数
    prev_ts = m["t_start"]
    preempt = defaultdict(int) # cpu -> 抢占次数 (prev_state=R)
    # task 运行时间: cpu -> (pid, comm, start_ts)
    cur_task = {}
    task_runtime = defaultdict(float)
    task_cs = defaultdict(int)      # prev_pid -> 切出次数
    task_wake = defaultdict(int)    # (comm) -> 唤醒次数
    task_migr = defaultdict(int)    # pid -> 迁移次数
    last_cpu_of = {}                # pid -> 最近运行 cpu
    task_comm = {}                  # pid -> 最近使用的 comm (task_name_of 查询表)
    task_cpus = defaultdict(set)    # (pid, comm) -> 运行过的 cpu 集合 (绑核/NUMA 分析用)
    migrate_ev = defaultdict(int)   # sched_migrate_task 显式事件
    cstate_dist = defaultdict(float)  # (cstate) -> 累计时长
    # softirq / irq 名称分布
    irq_name_time = defaultdict(float); irq_name_cnt = defaultdict(int)
    soft_name_time = defaultdict(float); soft_name_cnt = defaultdict(int)
    soft_raise_cnt = defaultdict(int)

    for ev in events:
        dt = ev.ts - prev_ts
        cpu = ev.cpu
        # 老化清理: 唤醒后超过阈值仍未运行的记录视为陈旧 (进程退出/PID 复用/丢事件),
        # 否则会一直计入 runnable 加权, 高估平均可运行队列长度
        if pending_wake:
            _cut = ev.ts - WAKE_MAX_AGE_S
            for _p in [p for p, w in pending_wake.items() if w < _cut]:
                del pending_wake[_p]
        runnable_weighted += len(pending_wake) * max(dt, 0)
        prev_ts = ev.ts
        et = ev.etype
        f = ev.fields

        if et == "sched_switch":
            if cpu is not None:
                cs[cpu] += 1
            prev_pid = int(f.get("prev_pid", -1) or -1)
            next_pid = int(f.get("next_pid", -1) or -1)
            prev_comm = f.get("prev_comm", "")
            next_comm = f.get("next_comm", "")
            # ---- idle 近似 (无 cpu_idle 事件时) ----
            if not has_idle_ev and cpu is not None:
                if prev_pid == 0 and prev_comm.startswith("swapper"):
                    idle_start[cpu] = ev.ts  # 进入 idle
                if idle_start.get(cpu) is not None and next_pid != 0:
                    idle[cpu] += ev.ts - idle_start[cpu]
                    idle_start[cpu] = None
            # ---- task runtime ----
            cur = cur_task.get(cpu)
            if cur is not None and cur[0] == prev_pid:
                if prev_pid > 0:
                    task_runtime[(prev_pid, prev_comm)] += ev.ts - cur[2]
                cur_task[cpu] = None
            if next_pid != 0:
                cur_task[cpu] = (next_pid, next_comm, ev.ts)
                # migration 近似
                lc = last_cpu_of.get(next_pid)
                if lc is not None and cpu is not None and lc != cpu:
                    task_migr[next_pid] += 1
                if next_comm:
                    task_comm[next_pid] = next_comm
                if cpu is not None:
                    last_cpu_of[next_pid] = cpu
                    task_cpus[(next_pid, next_comm)].add(cpu)
            if prev_pid > 0:
                if cpu is not None:
                    task_cs[(prev_pid, prev_comm)] += 1
                if f.get("prev_state", "") in ("R", "R+"):
                    preempt[cpu] += 1
            # ---- 调度延迟 ----
            if next_pid > 0 and next_pid in pending_wake:
                lat = ev.ts - pending_wake.pop(next_pid)
                if lat >= 0:
                    lat_all.append((next_pid, next_comm, ev.ts, lat))

        elif et in ("sched_wakeup", "sched_waking", "sched_wakeup_new"):
            if cpu is not None:
                wake[cpu] += 1
            pid = int(f.get("pid", -1) or -1)
            comm = f.get("comm", "")
            if pid > 0:
                if pid not in pending_wake:
                    pending_wake[pid] = ev.ts
                else:
                    pending_wake[pid] = min(pending_wake[pid], ev.ts)
                task_wake[comm] += 1

        elif et == "cpu_idle":
            if cpu is None:
                continue
            if f.get("idle_exit"):
                if in_idle.get(cpu):
                    idle[cpu] += ev.ts - in_idle[cpu]
                    in_idle[cpu] = None
            else:
                if not in_idle.get(cpu):
                    in_idle[cpu] = ev.ts
                    cstate_dist[str(f.get("state", "?"))] += 0.0  # 状态记录(时长另算)

        elif et == "cpu_frequency":
            try:
                freq_vals[cpu if cpu is not None else -1].append(float(f.get("state", 0) or 0))
            except Exception:
                pass

        elif et == "irq_handler_entry":
            key = (cpu, str(f.get("irq", "?")))
            irq_pending[key] = (ev.ts, f.get("name", f.get("irq", "?")))

        elif et == "irq_handler_exit":
            key = (cpu, str(f.get("irq", "?")))
            p = irq_pending.pop(key, None)
            if p is None:
                p = _pop_any_pending(irq_pending, cpu)
            if p is not None:
                d = ev.ts - p[0]
                if d >= 0:
                    irq_t[cpu] += d
                    irq_c[cpu] += 1
                    irq_name_time[p[1]] += d
                    irq_name_cnt[p[1]] += 1

        elif et == "softirq_entry":
            act = f.get("action") or SOFTIRQ_VEC_NAMES.get(
                _to_int(f.get("vec")), "vec%s" % f.get("vec", "?"))
            soft_pending[(cpu, str(f.get("vec", "?")))] = (ev.ts, act)

        elif et == "softirq_exit":
            key = (cpu, str(f.get("vec", "?")))
            p = soft_pending.pop(key, None)
            if p is None:
                p = _pop_any_pending(soft_pending, cpu)
            if p is not None:
                d = ev.ts - p[0]
                if d >= 0:
                    soft_t[cpu] += d
                    soft_c[cpu] += 1
                    soft_name_time[p[1]] += d
                    soft_name_cnt[p[1]] += 1

        elif et == "softirq_raise":
            act = f.get("action") or SOFTIRQ_VEC_NAMES.get(
                _to_int(f.get("vec")), "vec%s" % f.get("vec", "?"))
            soft_raise_cnt[act] += 1

        elif et == "sched_migrate_task":
            pid = _to_int(f.get("pid"))
            if pid > 0:
                migrate_ev[pid] += 1

    # 收尾: 未配对的 idle 区间
    if has_idle_ev:
        for cpu, st in in_idle.items():
            if st is not None:
                idle[cpu] += m["t_end"] - st
    else:
        for cpu, st in idle_start.items():
            if st is not None:
                idle[cpu] += m["t_end"] - st
    for cpu, cur in cur_task.items():
        if cur is not None and cur[0] > 0:
            task_runtime[(cur[0], cur[1])] += m["t_end"] - cur[2]

    all_cpus = cpus if cpus else (list(range(m["n_cpus_report"] or 0)))
    # ---------- per_cpu 汇总 ----------
    for c in all_cpus:
        # idle 证据判定:
        #   a) 该核出现 cpu_idle 记录 (已累计或未配对挂起);
        #   b) swapper 近似模式进入过 idle (idle_start 挂起或已累计);
        #   c) 该核有 sched_switch —— 有切换而无 idle 记录, 说明观测期内从未 idle, busy=dur 成立。
        # 三者皆无 (静默核, 如 per-cpu buffer 为空) => 无法判定, 记 UNKNOWN (None), 不再按 100% 计。
        idle_known = bool(idle.get(c)) \
            or idle_start.get(c) is not None \
            or (in_idle is not None and in_idle.get(c) is not None) \
            or cs.get(c, 0) > 0
        pc = {
            "cs": cs.get(c, 0), "cs_rate": cs.get(c, 0) / dur if dur else 0.0,
            "wakeups": wake.get(c, 0), "wakeup_rate": wake.get(c, 0) / dur if dur else 0.0,
            "irq_time": irq_t.get(c, 0.0),
            "irq_ratio": 100.0 * irq_t.get(c, 0.0) / dur if dur else 0.0,
            "irq_count": irq_c.get(c, 0),
            "softirq_time": soft_t.get(c, 0.0),
            "softirq_ratio": 100.0 * soft_t.get(c, 0.0) / dur if dur else 0.0,
            "softirq_count": soft_c.get(c, 0),
            "preempt": preempt.get(c, 0),
        }
        if idle_known:
            busy = max(dur - idle.get(c, 0.0), 0.0)
            pc["util"] = 100.0 * busy / dur if dur else 0.0
            pc["idle_ratio"] = 100.0 * idle.get(c, 0.0) / dur if dur else 0.0
            pc["util_known"] = True
        else:
            pc["util"] = None
            pc["idle_ratio"] = None
            pc["util_known"] = False
        m["per_cpu"][c] = pc
    # migration per-cpu 近似: 用 last_cpu_of 无法回溯; 用 sched_migrate_task 数量计入整体
    m["migration_total"] = sum(task_migr.values()) + sum(migrate_ev.values())

    # ---------- sched ----------
    lats = sorted(l for _pid, _c, _ts, l in lat_all)
    lat_by_task = defaultdict(list)
    for pid, comm, _ts, l in lat_all:
        lat_by_task[(pid, comm)].append(l)
    top_lat = sorted(((pid, comm, max(v), sum(v) / len(v), len(v))
                      for (pid, comm), v in lat_by_task.items()),
                     key=lambda x: -x[2])[:8]
    m["sched"] = {
        "cs_total": sum(cs.values()), "cs_rate": sum(cs.values()) / dur if dur else 0.0,
        "wakeup_total": sum(wake.values()),
        "wakeup_rate": (sum(wake.values())) / dur if dur else 0.0,
        "lat_count": len(lats),
        "lat_avg": sum(lats) / len(lats) * 1000 if lats else None,   # ms
        "lat_p50": _pct(lats, 50) * 1000 if lats else None,
        "lat_p95": _pct(lats, 95) * 1000 if lats else None,
        "lat_p99": _pct(lats, 99) * 1000 if lats else None,
        "lat_max": lats[-1] * 1000 if lats else None,
        "runnable_avg": runnable_weighted / dur if dur else None,
        "top_lat_tasks": top_lat,
        "lat_note": None if lat_all else "trace 中缺少 wakeup 与 switch 可配对事件，无法计算调度延迟",
    }
    # ---------- irq / softirq ----------
    m["irq"] = {
        "total_count": sum(irq_c.values()),
        "total_time": sum(irq_t.values()),
        "total_ratio": 100.0 * sum(irq_t.values()) / dur if dur else 0.0,
        "per_cpu_ratio": {c: m["per_cpu"][c]["irq_ratio"] for c in all_cpus},
        "top_names": sorted(((n, cnt, t) for n, cnt in irq_name_cnt.items()
                             for t in [irq_name_time[n]]),
                            key=lambda x: -x[2])[:10],
    }
    m["softirq"] = {
        "total_count": sum(soft_c.values()),
        "total_time": sum(soft_t.values()),
        "total_ratio": 100.0 * sum(soft_t.values()) / dur if dur else 0.0,
        "per_cpu_ratio": {c: m["per_cpu"][c]["softirq_ratio"] for c in all_cpus},
        "top_actions": sorted(((n, cnt, t) for n, cnt in soft_name_cnt.items()
                               for t in [soft_name_time[n]]),
                              key=lambda x: -x[2])[:10],
        "raise_counts": dict(soft_raise_cnt),
    }
    # ---------- freq ----------
    freq_per = {}
    for c, vals in freq_vals.items():
        if not vals:
            continue
        mx = max(vals)
        freq_per[c] = {
            "min": min(vals), "avg": sum(vals) / len(vals), "max": mx,
            "low_ratio": 100.0 * sum(1 for v in vals if mx and v <= 0.5 * mx) / len(vals),
        }
    m["freq"] = {"per_cpu": freq_per, "available": bool(freq_vals)}
    # ---------- idle ----------
    m["idle"] = {
        "per_cpu_ratio": {c: m["per_cpu"][c]["idle_ratio"] for c in all_cpus},
        "cstate_dist": dict(cstate_dist),
        "available": has_idle_ev,
    }
    # ---------- tasks ----------
    def _top(d, k=8):
        return sorted(((p, c, v) for (p, c), v in d.items()), key=lambda x: -x[2])[:k]
    m["tasks"] = {
        "top_runtime": sorted(((p, c, v) for (p, c), v in task_runtime.items()),
                              key=lambda x: -x[2])[:8],
        "top_cs": _top(task_cs), "top_wakeup": sorted(
            ((c, n) for c, n in task_wake.items()), key=lambda x: -x[1])[:8],
        "top_migration": sorted(((p, task_name_of(p, task_comm), v) for p, v in
                                 list(task_migr.items()) + list(migrate_ev.items())),
                                key=lambda x: -x[2])[:8],
        # 绑核/NUMA 分析: 任务 -> 运行过的 cpu 集合 (按累计运行时间排序取前 8)
        "task_cpus": sorted(((p, c, sorted(cp), task_runtime.get((p, c), 0.0))
                             for (p, c), cp in task_cpus.items()
                             if task_runtime.get((p, c), 0.0) > 0),
                            key=lambda x: -x[3])[:8],
    }
    # ---------- 时间序列 (120 桶) ----------
    n_bucket = 120
    bucket = max(dur / n_bucket, 0.001)
    ts_util = [0.0] * n_bucket      # busy 秒
    ts_busy_known = [0.0] * n_bucket
    ts_cs = [0] * n_bucket
    ts_irq = [0.0] * n_bucket
    ts_soft = [0.0] * n_bucket
    ts_lat = [[] for _ in range(n_bucket)]
    for ev in events:
        b = int((ev.ts - m["t_start"]) / bucket)
        if b < 0 or b >= n_bucket:
            b = min(max(b, 0), n_bucket - 1)
        cpu = ev.cpu
        if ev.etype == "sched_switch":
            ts_cs[b] += 1
        elif ev.etype == "irq_handler_exit":
            ts_irq[b] += 0.0  # 时间在配对处累计, 此处仅占位
    # 精确重扫: idle/irq/soft/lat 按区间落桶
    in_idl = {} if has_idle_ev else None
    idl_st = {}
    irq_p2 = {}; soft_p2 = {}
    pw2 = {}
    for ev in events:
        b = int((ev.ts - m["t_start"]) / bucket)
        b = min(max(b, 0), n_bucket - 1)
        cpu = ev.cpu
        et = ev.etype
        f = ev.fields
        # 老化清理: 与主循环口径一致, 避免陈旧唤醒在落桶时产生超长"延迟"样本
        if pw2:
            _cut = ev.ts - WAKE_MAX_AGE_S
            for _p in [p for p, w in pw2.items() if w < _cut]:
                del pw2[_p]
        if has_idle_ev and et == "cpu_idle":
            if f.get("idle_exit"):
                if in_idl.get(cpu) is not None:
                    _add_range(ts_util, ts_busy_known, m, in_idl.pop(cpu), ev.ts, bucket, n_bucket)
            else:
                in_idl[cpu] = ev.ts
        elif not has_idle_ev and et == "sched_switch":
            prev_pid = int(f.get("prev_pid", -1) or -1)
            next_pid = int(f.get("next_pid", -1) or -1)
            if prev_pid == 0 and str(f.get("prev_comm", "")).startswith("swapper"):
                idl_st[cpu] = ev.ts
            if idl_st.get(cpu) is not None and next_pid != 0:
                _add_range(ts_util, ts_busy_known, m, idl_st.pop(cpu), ev.ts, bucket, n_bucket)
        elif et == "irq_handler_exit":
            p = irq_p2.pop(cpu, None)
            if p is not None:
                _add_range(ts_irq, ts_busy_known, m, p, ev.ts, bucket, n_bucket)
        elif et == "irq_handler_entry":
            irq_p2[cpu] = ev.ts
        elif et == "softirq_exit":
            p = soft_p2.pop(cpu, None)
            if p is not None:
                _add_range(ts_soft, ts_busy_known, m, p, ev.ts, bucket, n_bucket)
        elif et == "softirq_entry":
            soft_p2[cpu] = ev.ts
        elif et in ("sched_wakeup", "sched_waking", "sched_wakeup_new"):
            pid = _to_int(f.get("pid"))
            if pid > 0:
                pw2[pid] = min(pw2.get(pid, ev.ts), ev.ts)
        elif et == "sched_switch":
            npid = _to_int(f.get("next_pid"))
            if npid > 0 and npid in pw2:
                lat = ev.ts - pw2.pop(npid)
                if lat >= 0:
                    ts_lat[b].append(lat)
    m["timeseries"] = {
        "bucket_sec": bucket, "n": n_bucket,
        "util": [100.0 * (ts_util[i] / (ts_busy_known[i] or bucket * len(all_cpus) or 1))
                 if ts_busy_known[i] > 0 else None for i in range(n_bucket)],
        "cs_rate": [c / bucket for c in ts_cs],
        "irq_ratio": [100.0 * ts_irq[i] / (bucket * max(len(all_cpus), 1)) for i in range(n_bucket)],
        "softirq_ratio": [100.0 * ts_soft[i] / (bucket * max(len(all_cpus), 1)) for i in range(n_bucket)],
        "lat_p99": [_pct(sorted(v), 99) * 1000 if v else None for v in ts_lat],
    }
    # ---------- proc/stat 快照 (开机以来累计) ----------
    if "proc_stat.txt" in td.snapshot:
        m["proc_stat"] = _parse_proc_stat(td.snapshot["proc_stat.txt"])
    # ---------- buffer overrun ----------
    over = 0
    src = td.snapshot.get("trace_overrun.txt", "")
    if src and src.strip() and src.strip() not in ("N/A (文件不存在)",):
        try:
            over = int(src.strip().splitlines()[0].strip() or 0)
        except Exception:
            over = 0
    m["buffer_overrun"] = over
    if over:
        m["warnings"].append("采集期间 ring buffer 溢出 %d 条事件，trace 可能不完整，结论置信度请酌情下调" % over)
    # 元数据补充
    m["governor"] = _parse_governor(td.snapshot.get("cpufreq.txt", ""))
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
    return "%s (pid %s)" % (c, pid)

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

def freq_to_mhz(v):
    """启发式频率单位转换 -> MHz"""
    try:
        v = float(v)
    except Exception:
        return 0.0
    if v >= 1e7:      # Hz (如 2800000000)
        return v / 1e6
    if v >= 1e3:      # kHz (如 2800000)
        return v / 1e3
    return v
