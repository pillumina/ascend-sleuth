#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户现场采集器清单。

一个采集器只描述「采什么、在哪跑、要什么权限、有什么影响、返回什么」；
清单不执行采集，也不访问网络。新增采集器改这里与各采集器目录、`instructions/`。
"""
from __future__ import annotations

UPSTREAM_COMMIT = "bf82e88"
UPSTREAM_COMMIT_FULL = "bf82e886ddda0a9955c2d5422f50b0b4caeb80b6"
UPSTREAM_URL = "https://github.com/hu669293657/skills"

COLLECTORS = [
    {
        "name": "env-snapshot",
        "title": "环境快照（系统 / 驱动 / CANN / NPU / 进程 / 网络）",
        "kind": "script",
        "purpose": (
            "采集一台昇腾服务器的系统、驱动与固件、CANN 组件、NPU 设备与拓扑、"
            "环境变量、指定进程启动环境、rank table、hccn_tool 链路/VNIC/TLS/光模块读数"
            "与权重哈希，输出一份 JSON 快照。"
        ),
        "entry": "msprechecker_dump.py",
        "files": [
            {
                "source": "scripts/collectors/ascend-dump/msprechecker_dump.py",
                "target": "msprechecker_dump.py",
            }
        ],
        "command": "python3 {script} --filter --no-probes -o snapshot-$(hostname).json",
        "environments": [
            "Linux（x86_64 / aarch64）",
            "Python 3.8+，只用标准库",
            "宿主机或容器内均可；NPU 相关项依赖目标机的 npu-smi 与 /usr/local/Ascend 可读",
        ],
        "privilege": (
            "普通用户即可启动；读取 /proc、/sys、/usr/local/Ascend 和指定进程环境时，"
            "受运行用户与容器命名空间权限限制，读不到的项目会在 JSON 里标为不可用。"
        ),
        "impact": (
            "只读：不改系统配置、不安装依赖、不上传数据。默认建议带 --no-probes，"
            "跳过 ICMP / TCP / NPU ping 等主动探测；不带该参数时脚本会做网络连通性探测。"
        ),
        "duration": "通常 5–60 秒；加 --weight-dir 计算权重 SHA-256 时随权重体积增长。",
        "outputs": ["snapshot-<host>.json"],
        "sensitive": (
            "脚本会遮盖密码、令牌等敏感字段并省略进程参数，但 raw 文本仍需在分享前人工复核；"
            "环境变量与 rank table 可能含 IP、路径和部署信息。"
        ),
        "consumer": "ascend-dump-analyzer",
        "notes": [
            "单份快照看版本与配套；变更前后各采一份可做配置漂移比对。",
            "采业务进程时追加 --target worker-0=<PID>（可重复），跨快照沿用同一角色名。",
            "需要 rank table 或链路信息时追加 --rank-table-path <路径> --scene <mindie|vllm>；"
            "仍建议保留 --no-probes，只读采集为主。",
            "快照已包含 hccn_tool 的 Link/VNIC/TLS/光模块读数；HCCL 连通性探测需要 "
            "--rank-table-path 并去掉 --no-probes（会做 ping，属主动探测）。",
        ],
    },
    {
        "name": "cpu-trace",
        "title": "Host / CPU ftrace 与系统快照",
        "kind": "script",
        "purpose": (
            "采集 Host 侧 ftrace（调度、中断、软中断、频率等）、系统快照、NUMA/NPU 拓扑、"
            "进程与线程快照，可选附带内嵌的环境 dump；用于判断 Host/CPU 是否拖慢 NPU。"
        ),
        "entry": "cpu_trace_collect.sh",
        "files": [
            {
                "source": "scripts/analyzers/cpu-host-performance/scripts/cpu_trace_collect.sh",
                "target": "cpu_trace_collect.sh",
            }
        ],
        "command": "sudo bash {script} --minimal --no-hostbound --no-ascend-dump --duration 5 "
        "--buffer-size 1024 --cpu-list '<业务CPU列表>'",
        "environments": [
            "Linux 宿主机，Bash 4+、awk、ftrace 可用",
            "需要 root 或等价能力创建私有 trace instance 并读取 tracefs",
            "容器内通常不可用；应在宿主机执行",
            "Python 3 可选：内嵌环境 dump 需要 Python 3，缺失时跳过该子项并在采集记录中标注",
        ],
        "privilege": "需要 root；创建独立 ftrace instance，退出时清理。",
        "impact": (
            "推荐命令跟踪指定 CPU 上的调度切换，仍有内核跟踪、导出和压缩开销。"
            "缓冲区按主机所有可能 CPU 计算，每 CPU 请求 1 MiB，192 个可能 CPU 约需 192 MiB。"
            "请先核对可用内存与输出盘空间，在获批的采集窗口执行。"
        ),
        "duration": "推荐命令采样 5 秒，系统快照与压缩另计。",
        "outputs": ["cpu_trace_<时间戳>_<随机后缀>.tar.gz"],
        "sensitive": "包含主机名、进程/线程命令行、NPU 与网络拓扑、环境变量白名单值；分享前复核。",
        "consumer": "cpu-host-performance",
        "notes": [
            "把 <业务CPU列表> 换成现场核实的逻辑 CPU 编号或范围，例如 0-7,16。"
            "命令保留频率轮询和系统快照，省略中断事件、进程发现和内嵌环境快照。",
            "脚本会报告实际缓冲区大小，设置失败时仍可能继续采样。输出默认写当前目录，"
            "可用 --output 指定现场批准的输出目录。",
            "确需中断事件时另行评估全量跟踪。确需目标进程 NUMA 或亲和性数据时另行评估"
            " --hostbound -p PID；该模式还会发现宿主机进程，并收集命令行。",
            "采集包直接交给 cpu-host-performance 分析，不需要客户安装 Python 包。",
        ],
    },
    {
        "name": "network-evidence",
        "title": "网卡 / IRQ / 软中断补充证据",
        "kind": "script",
        "purpose": (
            "在同一个时间窗内读取两次 /proc 与 /sys 计数器，采集网卡到 PCI/NUMA 的归属、"
            "MSI 中断、requested/effective affinity、队列与 RPS/XPS、ethtool 与 irqbalance 状态。"
        ),
        "entry": "scripts/collect_network_evidence.py",
        "files": [
            {
                "source": "scripts/collectors/cpu-host/scripts/collect_network_evidence.py",
                "target": "scripts/collect_network_evidence.py",
            },
            {
                "source": "scripts/collectors/cpu-host/hostbind/__init__.py",
                "target": "hostbind/__init__.py",
            },
            {
                "source": "scripts/collectors/cpu-host/hostbind/network.py",
                "target": "hostbind/network.py",
            },
        ],
        "command": "sudo python3 {script} --interval 10 --output network-window.json",
        "environments": [
            "Linux 宿主机",
            "Python 3.8+，只用标准库",
            "读取 /proc/interrupts、/proc/softirqs、/sys/class/net 与 ethtool；部分项需要 root",
        ],
        "privilege": "读取中断与 PCI 信息通常需要 root；ethtool 查询一般只读。",
        "impact": (
            "只读计数器：不改 IRQ affinity、RPS/XPS、irqbalance 或网络配置。"
            "两次快照之间按 --interval 等待，不产生业务流量。"
        ),
        "duration": "约 --interval 秒加少量读取时间（默认 10 秒）。",
        "outputs": ["network-window.json"],
        "sensitive": "包含网卡名、PCI 地址、IP 相关配置与中断分布；分享前复核。",
        "consumer": None,
        "notes": [
            "这是 CPU ftrace 采集的补充证据，不替代 cpu-trace；最好与 trace 同一时间窗采集。",
            "输出目前没有自动消费的适配器：可交给 cpu-host-performance 的报告一起读，"
            "或由诊断 agent 直接读 JSON 的计数增量与 affinity。",
            "输出路径必须是新文件；重复采集请换文件名。",
        ],
    },
    {
        "name": "cpu-power-audit",
        "title": "CPU 高性能策略与实际频率（只读）",
        "kind": "script",
        "purpose": (
            "读取 CPUFreq 策略域、governor、EPP、策略/硬件频率上限，并在多个采样点读取"
            "实际频率，回答「高性能模式开了吗、业务核有没有到上限」。"
        ),
        "entry": "cpu_power_audit.py",
        "files": [
            {
                "source": "scripts/collectors/cpu-host/scripts/cpu_power_audit.py",
                "target": "cpu_power_audit.py",
            }
        ],
        "command": "python3 {script} --samples 10 --interval 1 > cpu-power-audit.json",
        "environments": [
            "Linux 宿主机",
            "Python 3.7+，只用标准库",
            "需要 /sys/devices/system/cpu 可读；虚机或容器可能只看到虚拟拓扑",
        ],
        "privilege": "普通用户通常可读；个别机型需要 root 才能读 cpuinfo_cur_freq。",
        "impact": "只读：不写 sysfs、不改 governor、不启动压测、不联网。",
        "duration": "约 samples × interval 秒（默认 10 秒）。",
        "outputs": ["cpu-power-audit.json"],
        "sensitive": "包含 CPU 型号、策略域与频率读数，通常不含业务数据。",
        "consumer": None,
        "notes": [
            "应在业务稳定期、代表性负载下采集；空闲时的频率不能代表业务核是否满载。",
            "输出是事实读数：OS 策略、策略上限与硬件上限分别记录，不替诊断下「已满频」结论。",
            "固件侧（BIOS/BMC）需要另取 iBMC dump_info 的 BIOS 配置核对。",
        ],
    },
    {
        "name": "ibmc-dump",
        "title": "iBMC 一键收集（带外日志）",
        "kind": "manual",
        "purpose": "从 iBMC Web 或命令行导出一键收集包，供 ibmc_analyzer 分析服务器硬件与带外事件。",
        "files": [
            {
                "source": "scripts/collectors/instructions/ibmc-dump.md",
                "target": "ibmc-dump.md",
            }
        ],
        "command": None,
        "environments": [
            "能访问目标服务器 iBMC 管理网",
            "浏览器或 iBMC 命令行；不需要在业务 OS 上装软件",
        ],
        "privilege": "需要 iBMC 管理员或具备一键收集/日志导出权限的账号。",
        "impact": "带外操作，不经过业务 OS；一键收集会读取 BMC 日志与硬件状态，通常不影响业务。",
        "duration": "导出通常数分钟，取决于 BMC 日志量。",
        "outputs": ["含 dump_info/ 的压缩包"],
        "sensitive": "含序列号、IP、账号登录记录、硬件与传感器读数；按客户要求脱敏后再流转。",
        "consumer": "ibmc_analyzer",
        "steps": [
            "登录 iBMC Web。",
            "进入「维护诊断」→「一键收集」，选择完整日志导出。",
            "下载压缩包并解压，确认其中包含 dump_info/ 目录。",
            "把 dump_info/ 目录或压缩包交给 ibmc_analyzer。",
        ],
        "notes": [
            "不同 iBMC 版本的菜单名可能不同，以现场界面为准。",
            "多台机器分别导出，一起交给 ibmc_analyzer 做集群对比。",
        ],
    },
    {
        "name": "ascend-logs",
        "title": "plog / slog / device / 框架 / dmesg 日志",
        "kind": "manual",
        "purpose": "按问题时间窗收集 CANN、Device、Host 内核与训练/推理框架日志，供 issue-analyzer 做日志取证。",
        "files": [
            {
                "source": "scripts/collectors/instructions/ascend-logs.md",
                "target": "ascend-logs.md",
            }
        ],
        "command": None,
        "environments": [
            "Linux 宿主机或容器",
            "需要业务用户或 root 读取 ~/ascend/log、/var/log 与 dmesg",
        ],
        "privilege": "普通用户可读业务侧 plog；dmesg、/var/log/messages 与部分 device 日志需要 root。",
        "impact": "只读：列目录、读日志、打包；不改日志级别、不重启服务。",
        "duration": "取决于日志体积；建议按时间窗裁剪后再打包。",
        "outputs": [
            "plog_<host>_window.tar.gz",
            "dmesg_<host>_<时间>.log",
            "journal_<host>.log（如有）",
            "npu_smi_info_<host>.txt 和可用的板卡、故障查询输出",
            "框架和 rank 日志、问题时间窗及受影响 rank",
        ],
        "sensitive": "日志可能含 IP、路径、模型名、账号与业务数据；分享前按客户要求脱敏。",
        "consumer": "issue-analyzer",
        "steps": [
            "先确定问题发生的时间窗与受影响 rank。",
            "按随包的 ascend-logs.md 收集 plog、dmesg、npu-smi 与框架日志。",
            "核对覆盖问题窗口的活动日志和轮转文件，保留前后上下文。",
            "工程师收到后先解包，再把日志目录或日志文件交给 issue-analyzer。",
        ],
        "notes": [
            "npu-smi 状态在问题复现时采最准；事后补采仍有参考价值。",
            "日志已被滚动覆盖时如实说明，不要用其他时间窗的日志顶替。",
        ],
    },
]

BY_NAME = {item["name"]: item for item in COLLECTORS}


def find(name: str) -> dict | None:
    return BY_NAME.get(name)


def names() -> list[str]:
    return [item["name"] for item in COLLECTORS]
