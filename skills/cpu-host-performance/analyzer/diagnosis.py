# -*- coding: utf-8 -*-
"""diagnosis.py — CPU Host 问题诊断引擎 (组合判断 + 置信度体系)

诊断类型 (13 类):
CPU_SATURATION / CPU_IMBALANCE / SCHEDULER_CONTENTION / SCHEDULER_LATENCY /
IRQ_HOTSPOT / SOFTIRQ_HOTSPOT / CPU_FREQUENCY_LOW / CPU_IDLE_EXCESSIVE /
TASK_AFFINITY_PROBLEM / TASK_MIGRATION_HIGH / NUMA_RISK / HOST_NOT_BOTTLENECK /
INSUFFICIENT_EVIDENCE
"""
import re

from .metrics import METRIC_EXPLANATIONS, freq_to_mhz

# 经验阈值 (报告中展示, 单位见说明)
THRESHOLDS = {
    "util_critical": 90.0,      # 单核利用率 % 超过则视为饱和
    "util_imbalance_gap": 40.0, # 最高核与均值差 % 超过视为不均衡
    "cs_rate_high": 2000.0,     # 单核上下文切换基线 /s; 全机判定 = 基线 × 核数
    "wakeup_rate_high": 1000.0, # 单核唤醒 /s
    "lat_p99_warn_ms": 5.0,     # 调度延迟 P99 ms
    "lat_p99_crit_ms": 20.0,
    "irq_ratio_warn": 15.0,     # 单核硬中断 CPU 占比 %
    "softirq_ratio_warn": 20.0, # 单核软中断 CPU 占比 %
    "hotspot_mult": 2.0,        # 热点判定: 超过中位数倍数
    "idle_high": 70.0,          # 全机空闲 %
    "low_freq_ratio": 50.0,     # 低频样本占比 %
    "migration_rate_high": 50.0,# 全机迁移 /s
}


def _parse_cpulist(s):
    """展开 "0-31,64" 形式的 cpulist 为 cpu 编号集合。"""
    cpus = set()
    for part in (s or "").replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                cpus.update(range(int(a), int(b) + 1))
            except ValueError:
                pass
        else:
            try:
                cpus.add(int(part))
            except ValueError:
                pass
    return cpus


def _numa_node_cpus(snapshot):
    """从 numa.txt 快照解析 NUMA 节点 -> cpu 集合; 无拓扑时返回 {}。"""
    txt = (snapshot or {}).get("numa.txt", "") or ""
    nodes, cur = {}, None
    for line in txt.splitlines():
        s = line.strip()
        mm = re.match(r"^==\s*/sys/devices/system/node/node(\d+)/cpulist\s*==\s*$", s)
        if mm:
            cur = int(mm.group(1))
            nodes[cur] = ""
            continue
        if cur is not None:
            if s.startswith("=="):
                cur = None
            elif s and not nodes[cur]:
                nodes[cur] = s
    return {n: _parse_cpulist(v) for n, v in nodes.items() if v}


DIAG_EXPLANATIONS = {
    "CPU_SATURATION":        "CPU 饱和：整体 CPU 已接近打满，算力不足",
    "CPU_IMBALANCE":         "CPU 负载不均衡：少数核心打满而大量核心空闲，常见于绑核不当或中断亲和性集中",
    "SCHEDULER_CONTENTION":  "调度争抢：runnable 任务堆积，任务间激烈抢占 CPU",
    "SCHEDULER_LATENCY":     "调度延迟过大：任务被唤醒后长时间得不到 CPU",
    "IRQ_HOTSPOT":           "硬中断热点：硬件中断集中消耗个别核心 CPU",
    "SOFTIRQ_HOTSPOT":       "软中断热点：软中断（如 NET_RX 网络收包）集中消耗个别核心 CPU",
    "CPU_FREQUENCY_LOW":     "CPU 频率异常：高负载下 CPU 长期低频运行",
    "CPU_IDLE_EXCESSIVE":    "CPU 过度空闲：核心大量闲置，负载未被合理分布",
    "TASK_AFFINITY_PROBLEM": "任务绑核问题：任务集中在少数核心运行",
    "TASK_MIGRATION_HIGH":   "任务迁移频繁：任务在核间频繁搬移，破坏缓存局部性",
    "NUMA_RISK":             "NUMA 风险：存在跨 NUMA 节点访问的可能性",
    "HOST_NOT_BOTTLENECK":   "Host CPU 不是主瓶颈：CPU 负载健康，性能问题应从其他方向（NPU/IO/框架）排查",
    "INSUFFICIENT_EVIDENCE": "证据不足：当前数据无法支持可靠结论",
}

def _med(vals):
    s = sorted(vals)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0

def _f(m, path, default=None):
    """安全取嵌套字段"""
    cur = m
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur if cur is not None else default

def diagnose(m):
    """输入 metrics dict -> 诊断 dict {host_status, primary, findings, snapshot_issues}"""
    findings = []
    per_cpu = m.get("per_cpu", {})
    cpus = sorted(per_cpu.keys())
    dur = m.get("duration") or 0.0
    av = m.get("available", set())
    T = THRESHOLDS

    # 无 idle 证据 (util_known=False) 的核不参与统计, 避免 UNKNOWN(None) 混入数值运算
    known_cpus = [c for c in cpus if per_cpu[c].get("util_known", True)]
    utils = [per_cpu[c]["util"] for c in known_cpus]
    avg_util = sum(utils) / len(utils) if utils else None
    max_cpu = max(utils) if utils else None
    min_cpu = min(utils) if utils else None
    med_util = _med(utils) if utils else None

    def add(dtype, severity, confidence, title, evidence, impact, root, rec):
        findings.append({
            "type": dtype, "severity": severity, "confidence": confidence,
            "title": title, "evidence": evidence, "impact": impact,
            "possible_root_cause": root, "recommendation": rec,
            "explanation": DIAG_EXPLANATIONS.get(dtype, ""),
        })

    def cpu_label(c):
        return "CPU %s" % c

    # ============ 1. CPU_SATURATION / SCHEDULER_CONTENTION ============
    if avg_util is not None and avg_util >= T["util_critical"]:
        ev = [{"metric": "全机平均 CPU 利用率", "value": "%.1f%%" % avg_util,
               "threshold": "≥%.0f%% 判定饱和" % T["util_critical"]}]
        sev = "CRITICAL" if avg_util >= 95 else "WARNING"
        conf = "HIGH"
        if len(cpus) < max(2, m.get("n_cpus_report") or 2) * 0.5:
            conf = "MEDIUM"
        if _f(m, ["sched", "lat_p99"]) is not None and m["sched"]["lat_p99"] >= T["lat_p99_warn_ms"]:
            add("SCHEDULER_CONTENTION", sev, conf,
                "CPU 饱和且伴随调度争抢",
                ev + [{"metric": "调度延迟 P99", "value": "%.2f ms" % m["sched"]["lat_p99"],
                       "threshold": "≥%.0f ms 视为偏高" % T["lat_p99_warn_ms"]},
                      {"metric": "平均 runnable 任务数", "value": "%.1f" % (m["sched"]["runnable_avg"] or 0),
                       "threshold": "接近核心数说明排队"}],
                "任务无法及时获得 CPU，训练/推理线程提交变慢，NPU 可能因等待 Host 侧数据而利用率下降",
                "CPU 算力不足或任务并行度过高，runnable 队列堆积",
                ["降低 Host 侧并发/线程数，或更换更高规格 CPU",
                 "检查是否存在异常进程消耗 CPU (见 Top Task)",
                 "使用 taskset/numactl 将关键线程绑定到空闲核心"])
        else:
            add("CPU_SATURATION", sev, conf, "CPU 整体饱和",
                ev, "Host 算力不足，任务排队等待，可能拖慢 NPU 供数",
                "整机 CPU 计算需求超过供给",
                ["识别并优化 Top CPU 任务 (见 Task 分析)",
                 "提高 Host 并行度配置或升级 CPU",
                 "排查业务是否存在无意义忙等/自旋"])
    # ============ 2. CPU_IMBALANCE ============
    elif avg_util is not None and cpus and max_cpu is not None and \
            (max_cpu - med_util) >= T["util_imbalance_gap"] and max_cpu >= T["util_critical"]:
        hot = [c for c in known_cpus if per_cpu[c]["util"] >= T["util_critical"]]
        cold = [c for c in known_cpus if per_cpu[c]["util"] <= 30.0]
        top_c = max(known_cpus, key=lambda c: per_cpu[c]["util"])
        ev = [{"metric": "最高核利用率 (%s)" % cpu_label(top_c), "value": "%.1f%%" % per_cpu[top_c]["util"],
               "threshold": "≥%.0f%%" % T["util_critical"]},
              {"metric": "核心利用率中位数", "value": "%.1f%%" % med_util, "threshold": "差值≥%.0f%% 判定不均衡" % T["util_imbalance_gap"]},
              {"metric": "空闲核数量 (利用率≤30%)", "value": "%d 个" % len(cold), "threshold": "-"}]
        sev = "WARNING"
        conf = "HIGH" if len(cpus) >= 4 else "MEDIUM"
        root = "任务绑核过于集中、负载均衡失效或中断亲和性固定于个别核"
        soft_ratio = per_cpu[top_c]["softirq_ratio"]
        if soft_ratio >= T["softirq_ratio_warn"]:
            root = "软中断集中在该核 (疑为 IRQ affinity 将网卡中断固定到单核)"
        add("CPU_IMBALANCE", sev, conf, "CPU 负载严重不均衡",
            ev, "部分核心打满成为瓶颈，同时大量算力闲置，吞吐受限",
            root,
            ["检查 IRQ affinity: cat /proc/interrupts，将高频中断分散 (echo 掩码 > /proc/irq/N/smp_affinity)",
             "检查业务线程绑核配置 (taskset/numactl)，把任务分散到空闲核",
             "开启 RPS/XPS 或 RSS 多队列分散网络软中断"])
    # ============ 3. IRQ_HOTSPOT / SOFTIRQ_HOTSPOT ============
    irq_ratios = [per_cpu[c]["irq_ratio"] for c in cpus] if cpus else []
    if irq_ratios:
        med_irq = _med(irq_ratios)
        top_irq_c = max(cpus, key=lambda c: per_cpu[c]["irq_ratio"])
        v = per_cpu[top_irq_c]["irq_ratio"]
        if v >= T["irq_ratio_warn"] and v >= med_irq * T["hotspot_mult"]:
            top_names = ", ".join("%s(%d 次)" % (n, cnt) for n, cnt, _t in m["irq"]["top_names"][:3]) or "见下表"
            add("IRQ_HOTSPOT", "WARNING" if v < 30 else "CRITICAL",
                "HIGH" if m["irq"]["total_count"] > 100 else "MEDIUM",
                "硬中断集中于 %s" % cpu_label(top_irq_c),
                [{"metric": "%s 硬中断 CPU 占比" % cpu_label(top_irq_c), "value": "%.1f%%" % v,
                  "threshold": "≥%.0f%% 且≥中位数 %.1f 倍" % (T["irq_ratio_warn"], T["hotspot_mult"])},
                 {"metric": "Top 中断源", "value": top_names, "threshold": "-"}],
                "中断处理与计算线程争抢 CPU，增加调度延迟，可能造成 NPU 供数不稳",
                "该核承载了大量设备中断 (存储/网络/IPI)，未做中断亲和性分散",
                ["cat /proc/interrupts 定位中断源设备",
                 "用 irqbalance 或手工修改 /proc/irq/*/smp_affinity 分散中断",
                 "避免将业务关键线程绑定到中断密集核"])
    soft_ratios = [per_cpu[c]["softirq_ratio"] for c in cpus] if cpus else []
    if soft_ratios:
        med_soft = _med(soft_ratios)
        top_soft_c = max(cpus, key=lambda c: per_cpu[c]["softirq_ratio"])
        v = per_cpu[top_soft_c]["softirq_ratio"]
        if v >= T["softirq_ratio_warn"] and v >= med_soft * T["hotspot_mult"]:
            top_act = ", ".join("%s(%.0fms)" % (n, t * 1000) for n, cnt, t in m["softirq"]["top_actions"][:3]) or "见下表"
            is_net = "NET_RX" in top_act or "NET_TX" in top_act
            root = "该核集中处理了软中断" + ("，且以网络收包 (NET_RX) 为主：网卡队列中断亲和性固定于单核，通信/收包量大时极易打满" if is_net else "")
            rec = ["检查 /proc/softirqs 与 /proc/interrupts 中网络中断分布",
                   "开启/调大网卡多队列 (RSS) 并用 ethtool -X 均衡队列",
                   "用 irqbalance 或 smp_affinity 将 NET_RX 分散到多核",
                   "评估业务通信量是否异常 (如 all-reduce 风暴)"] if is_net else \
                  ["cat /proc/softirqs 定位软中断类型",
                   "检查对应子系统 (块设备/定时器/RCU) 的压力",
                   "将软中断负载分散到更多核心"]
            add("SOFTIRQ_HOTSPOT", "CRITICAL" if v >= 40 else "WARNING",
                "HIGH" if m["softirq"]["total_count"] > 100 else "MEDIUM",
                "软中断集中于 %s" % cpu_label(top_soft_c),
                [{"metric": "%s 软中断 CPU 占比" % cpu_label(top_soft_c), "value": "%.1f%%" % v,
                  "threshold": "≥%.0f%% 且≥中位数 %.1f 倍" % (T["softirq_ratio_warn"], T["hotspot_mult"])},
                 {"metric": "Top 软中断类型", "value": top_act, "threshold": "-"}],
                "软中断处理挤占计算线程运行时间，调度延迟上升，训练/推理吞吐下降",
                root, rec)
    # ============ 4. SCHEDULER_LATENCY ============
    lat_p99 = _f(m, ["sched", "lat_p99"])
    if lat_p99 is not None:
        if lat_p99 >= T["lat_p99_crit_ms"]:
            sev, txt = "CRITICAL", "严重"
        elif lat_p99 >= T["lat_p99_warn_ms"]:
            sev, txt = "WARNING", "偏高"
        else:
            sev = None
        if sev:
            top_lat = m["sched"]["top_lat_tasks"][:3]
            tl = "; ".join("%s (最大 %.1fms)" % (c or ("pid%s" % p), mx * 1000)
                           for p, c, mx, _a, _n in top_lat)
            add("SCHEDULER_LATENCY", sev,
                "HIGH" if m["sched"]["lat_count"] > 200 else "MEDIUM",
                "调度延迟%s" % txt,
                [{"metric": "调度延迟 P99", "value": "%.2f ms" % lat_p99,
                  "threshold": "≥%.0fms 警告 / ≥%.0fms 严重" % (T["lat_p99_warn_ms"], T["lat_p99_crit_ms"])},
                 {"metric": "调度延迟平均值", "value": "%.3f ms" % (m["sched"]["lat_avg"] or 0), "threshold": "-"},
                 {"metric": "受影响最大的任务", "value": tl or "-", "threshold": "-"}],
                "关键线程被唤醒后需等待较久才能运行，通信/数据准备节奏被打断，NPU 等待 Host",
                "CPU 竞争 (饱和/中断/优先级) 导致 runnable 排队",
                ["结合 CPU 利用率与中断热点结论处理根源负载",
                 "提高关键线程优先级 (nice/chrt) 或绑核隔离 (isolcpus/cpuset)",
                 "减少 Host 线程数，避免过度并发"])
    # ============ 5. CPU_FREQUENCY_LOW ============
    freq_per = _f(m, ["freq", "per_cpu"], {}) or {}
    if freq_per:
        low_cpus = [c for c, fv in freq_per.items()
                    if fv["max"] and fv["low_ratio"] >= T["low_freq_ratio"]]
        # 优先观察高负载核 (无 idle 证据的核不参与)
        hot_low = [c for c in low_cpus
                   if isinstance(per_cpu.get(c, {}).get("util"), (int, float))
                   and per_cpu[c]["util"] >= 50]
        if hot_low or (low_cpus and len(low_cpus) >= max(1, len(freq_per) // 2)):
            cs = hot_low or low_cpus
            cc = cs[0]
            fv = freq_per[cc]
            add("CPU_FREQUENCY_LOW", "WARNING",
                "MEDIUM",
                "CPU 高负载下运行于低频" if hot_low else "大量核心长期低频",
                [{"metric": "CPU %s 平均频率" % cc, "value": "%.0f MHz (最高 %.0f MHz)" % (freq_to_mhz(fv["avg"]), freq_to_mhz(fv["max"])),
                  "threshold": "低频(≤最高50%%)样本占比≥%.0f%%" % T["low_freq_ratio"]},
                 {"metric": "涉及核心数", "value": "%d 个" % len(cs), "threshold": "-"},
                 {"metric": "governor", "value": m.get("governor") or "快照未提供", "threshold": "建议 performance"}],
                "同负载需要更多周期，实际算力下降，任务变慢",
                "governor 为 powersave/ondemand、温控降频或平台频率限制",
                ["检查 governor: cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor",
                 "建议设置 performance: cpupower frequency-set -g performance",
                 "排查温度/功耗墙 (需结合平台监控)，本分析不判定硬件故障"])
    # ============ 6. TASK_MIGRATION_HIGH ============
    mig = m.get("migration_total", 0)
    if mig and dur:
        rate = mig / dur
        if rate >= T["migration_rate_high"]:
            top_mig = "; ".join("%s (%d 次)" % (c or ("pid%s" % p), n) for p, c, n in m["tasks"]["top_migration"][:3])
            add("TASK_MIGRATION_HIGH", "WARNING", "MEDIUM", "任务迁移频繁",
                [{"metric": "迁移速率", "value": "%.1f 次/秒" % rate,
                  "threshold": "≥%.0f 次/秒 视为频繁 (近似统计)" % T["migration_rate_high"]},
                 {"metric": "迁移最多的任务", "value": top_mig or "-", "threshold": "-"}],
                "跨核迁移导致 L1/L2 缓存与 TLB 失效，可能跨 NUMA 访存，性能抖动",
                "负载均衡器频繁搬移任务或任务未绑核",
                ["将关键线程固定核心 (taskset -c / numactl --physcpubind)",
                 "调小内核调度域负载均衡激进度 (如 sched_migration_cost_ns 调大)"])
    # ============ 6b. TASK_AFFINITY_PROBLEM / NUMA_RISK ============
    idle_cpus = [c for c in known_cpus if per_cpu[c]["util"] <= 30.0]
    # 任务绑核风险: 任务仅在极少数核心运行 + 这些核心饱和 + 存在空闲核 (仅报风险)
    if idle_cpus:
        hot_util = {c: per_cpu[c]["util"] for c in known_cpus
                    if per_cpu[c]["util"] >= T["util_critical"]}
        max_span = max(2, len(cpus) // 8)
        for p, comm, t_cpus, t_rt in m.get("tasks", {}).get("task_cpus", []):
            if not t_cpus or len(t_cpus) > max_span:
                continue
            if not all(c in hot_util for c in t_cpus):
                continue
            aff_keys = [k for k in (m.get("snapshot", {}) or {})
                        if k.endswith("pid_%d_affinity.txt" % p)]
            add("TASK_AFFINITY_PROBLEM", "WARNING", "MEDIUM",
                "任务绑核风险: %s 只在 %d 个核心上运行" % (comm or ("pid%s" % p), len(t_cpus)),
                [{"metric": "任务 (pid)", "value": "%s (pid %s), 观测内运行 %.1f 秒" % (comm or "?", p, t_rt),
                  "threshold": "-"},
                 {"metric": "运行过的核心", "value": ",".join(str(c) for c in t_cpus), "threshold": "-"},
                 {"metric": "这些核心的利用率", "value": ", ".join("cpu%s=%.0f%%" % (c, hot_util[c]) for c in t_cpus),
                  "threshold": "≥%.0f%% 视为饱和" % T["util_critical"]},
                 {"metric": "空闲核心", "value": "%d 个 (cpu %s)" % (len(idle_cpus), ",".join(str(c) for c in idle_cpus[:8])),
                  "threshold": "-"}]
                + ([{"metric": "affinity 快照", "value": aff_keys[0], "threshold": "-"}] if aff_keys else []),
                "任务被限制在饱和核心上运行而其他核心空闲, 算力未被充分利用",
                "taskset/cgroup cpuset 限制或调度配置导致任务无法迁移到空闲核",
                ["查看绑核配置: taskset -pc %s; cat /proc/%s/status | grep Cpus_allowed_list" % (p, p),
                 "将关键线程绑定/迁移到空闲核心 (taskset -c / numactl --physcpubind), 执行前保存当前 affinity",
                 "如为有意绑核 (如 cache 亲和), 确认该核饱和是否为业务预期"])
            break  # 只报最显著 (运行时间最长) 的一个, 避免噪音
    # NUMA 风险: 多节点拓扑 + 任务跨节点运行或迁移频繁 (仅报风险, 不可称根因)
    node_cpus = _numa_node_cpus(m.get("snapshot", {}))
    if len(node_cpus) >= 2 and dur:
        cpu2node = {}
        for nd, nd_cpus in node_cpus.items():
            for c in nd_cpus:
                cpu2node.setdefault(c, nd)
        cross_tasks = []
        for p, comm, t_cpus, _t_rt in m.get("tasks", {}).get("task_cpus", []):
            ns = sorted({cpu2node.get(c) for c in t_cpus if c in cpu2node} - {None})
            if len(ns) >= 2:
                cross_tasks.append("%s (节点 %s)" % (comm or ("pid%s" % p), "/".join(str(x) for x in ns)))
        mig_rate = (m.get("migration_total", 0) or 0) / dur
        if cross_tasks or mig_rate >= T["migration_rate_high"]:
            add("NUMA_RISK", "WARNING", "LOW", "NUMA 风险: 存在跨 NUMA 节点访问的可能性",
                [{"metric": "NUMA 节点拓扑", "value": "%d 个节点: %s" % (
                    len(node_cpus),
                    "; ".join("node%d(%d核)" % (nd, len(nd_cpus)) for nd, nd_cpus in sorted(node_cpus.items()))),
                  "threshold": "-"},
                 {"metric": "跨节点运行的任务", "value": "; ".join(cross_tasks[:3]) or "-", "threshold": "-"},
                 {"metric": "迁移速率", "value": "%.1f 次/秒" % mig_rate,
                  "threshold": "≥%.0f 次/秒 视为频繁" % T["migration_rate_high"]}],
                "跨节点访存延迟高, 任务/内存在节点间漂移可能带来性能抖动",
                "未绑核或内存策略未指定节点, 由调度器/内存分配器自行分布",
                ["结合 numactl -H 与 numastat 快照确认内存分布 (本报告仅有拓扑与迁移旁证)",
                 "对关键线程做节点内绑定 (numactl --cpunodebind/--membind), 执行前保存现状",
                 "此结论为风险提示, 不应直接认定跨 NUMA 为根因"])
    # ============ 7. CPU_IDLE_EXCESSIVE / HOST_NOT_BOTTLENECK ============
    if avg_util is not None and avg_util <= (100 - T["idle_high"]) / 100 * 100:
        pass  # 条件等价改写, 见下方清晰分支
    if avg_util is not None and (100 - avg_util) >= T["idle_high"]:
        imbalance = any(f["type"] in ("CPU_IMBALANCE", "IRQ_HOTSPOT", "SOFTIRQ_HOTSPOT") for f in findings)
        if not imbalance:
            add("HOST_NOT_BOTTLENECK", "OK", "HIGH", "Host CPU 负载健康，不是当前瓶颈",
                [{"metric": "全机平均 CPU 利用率", "value": "%.1f%%" % avg_util, "threshold": "空闲≥%.0f%%" % T["idle_high"]},
                 {"metric": "最高核利用率", "value": "%.1f%%" % (max_cpu or 0), "threshold": "-"}],
                "CPU 侧无拥塞，若业务性能仍差，瓶颈大概率在 NPU/IO/框架/算法侧",
                "计算负载低于算力供给",
                ["从 NPU 利用率、数据管道 (dataloader)、算子耗时等方向继续排查",
                 "如需深入可用本 Skill 附带的 Prof/集群分析工具链"])
        else:
            add("CPU_IDLE_EXCESSIVE", "WARNING", "MEDIUM", "多数核心空闲但存在热点核",
                [{"metric": "全机平均利用率", "value": "%.1f%%" % avg_util, "threshold": "-"},
                 {"metric": "热点核", "value": "见上方不均衡/中断结论", "threshold": "-"}],
                "整体算力富余但热点核成为局部瓶颈",
                "负载/中断分布不均",
                ["按上方 CPU_IMBALANCE / IRQ 热点建议重新分布负载"])
    # ============ 8. 数据覆盖不足 ============
    limited = []
    if "cpu_idle" not in av:
        limited.append("缺少 cpu_idle 事件，利用率基于 swapper 切换近似估算")
    if not ({"sched_wakeup", "sched_waking", "sched_wakeup_new"} & av):
        limited.append("缺少 wakeup 事件，无法计算调度延迟")
    if not {"irq_handler_entry", "irq_handler_exit"} <= av:
        limited.append("缺少 IRQ 事件，无法分析硬中断")
    if not {"softirq_entry", "softirq_exit"} <= av:
        limited.append("缺少 SoftIRQ 事件，无法分析软中断")
    if "cpu_frequency" not in av:
        limited.append("缺少 cpu_frequency 事件，无法分析频率")
    if limited:
        if len(limited) >= 3:
            add("INSUFFICIENT_EVIDENCE", "INFO", "HIGH", "本次采集数据维度有限",
                [{"metric": "缺失维度", "value": "；".join(limited), "threshold": "-"},
                 {"metric": "采集模式", "value": "精简模式(仅 sched_switch)" if
                  str(m.get("metadata", {}).get("minimal_mode", "")) == "1" or
                  set(av) <= {"sched_switch", "task_newtask"} else "全量", "threshold": "-"}],
                "相关维度结论缺失，无法覆盖该类问题",
                "采集脚本精简模式或内核不支持部分事件",
                ["如需完整分析请用全量模式重新采集: sudo bash cpu_trace_collect.sh --duration 30 (不加 -m)"])
        else:
            m["warnings"].extend(["诊断提示: " + s for s in limited])

    # ============ 汇总 ============
    sev_rank = {"CRITICAL": 3, "WARNING": 2, "INFO": 1, "OK": 0}
    conf_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    findings.sort(key=lambda f: (-sev_rank.get(f["severity"], 0), -conf_rank.get(f["confidence"], 0)))
    # 未知事件提示
    unknown = sorted(av - set(_KNOWN_EVENTS))
    if unknown:
        m.setdefault("warnings", []).append("存在未收录事件: %s (已按通用事件处理)" % ", ".join(unknown))

    crit = [f for f in findings if f["severity"] == "CRITICAL"]
    warn = [f for f in findings if f["severity"] == "WARNING"]
    oktype = [f for f in findings if f["severity"] == "OK"]
    # 数据不可信 (events_ok=False) 时, 若除数据质量提示 (INSUFFICIENT_EVIDENCE)
    # 与肯定性结论 (OK) 外没有任何真实发现, 则整机状态标 UNKNOWN,
    # 避免基于不完整数据给出误导性的 HEALTHY/DEGRADED 结论
    _real = [f for f in findings if f["type"] != "INSUFFICIENT_EVIDENCE" and f["severity"] != "OK"]
    if not m.get("events_ok", True) and not _real:
        host = "UNKNOWN"
    elif crit:
        host = "CRITICAL"
    elif warn:
        host = "WARNING"
    elif oktype:
        host = "HEALTHY"
    elif findings:
        host = "DEGRADED"
    else:
        host = "HEALTHY"
    primary = findings[0] if findings and findings[0]["severity"] in ("CRITICAL", "WARNING") else \
              (findings[0] if findings else None)
    return {
        "host_status": host,
        "primary": primary,
        "findings": findings,
        "stats": {
            "avg_util": avg_util, "max_util": max_cpu, "min_util": min_cpu,
            "n_cpus": len(cpus), "duration": dur,
        },
    }

_KNOWN_EVENTS = set([
    "sched_switch", "sched_wakeup", "sched_waking", "sched_wakeup_new",
    "sched_migrate_task", "task_newtask", "irq_handler_entry", "irq_handler_exit",
    "softirq_entry", "softirq_exit", "softirq_raise", "cpu_idle", "cpu_frequency"])
