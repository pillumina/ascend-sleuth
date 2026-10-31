---
name: "cpu-host-performance"
description: "Linux 训练/推理 HostBound 定位（怀疑 Host/CPU 侧拖慢 NPU/GPU）。当用户需要现场采集或离线分析 ftrace、Ascend Host 快照、可选 GIL/函数 PMU/msprof 数据来定位 Host 侧瓶颈时使用，覆盖 acl_thread、release_thread、SQ/CQ、IRQ、NUMA、CPU affinity/抢占、Python GIL、函数长尾、Host/Device overlap。不用于 Prof 数据的性能分析与比对（用 cluster-analysis / prof-compare / cluster-compare）；不用于只分析 NPU 算子本身；不用于报错/中断等故障日志排查（用 issue-analyzer）。"
---

# HostBound 性能诊断

面向 Ascend 训练/推理的 Host 侧定位与优化闭环。保留原有 ftrace 采集和离线分析能力；官方 `msProf`、`function_monitor`、`gil_tracer`、`host_analyzer` 始终作为独立外部工具管理，绝不修改或复制其源码。

## 固定交付

最终交付物固定为 `<output-dir>/hostbound_report.html`，单文件、离线可打开、中文。可同时保留 `report.md` 作为审阅辅助，但不可用它替代 HTML 报告。

## 统一入口与采集原则

默认发给客户的入口是：

```bash
sudo bash scripts/cpu_trace_collect.sh --duration 30 --output /tmp --pid <业务PID>
```

`scripts/cpu_trace_collect.sh` 是唯一采集脚本。默认全量 ftrace，不改变采集事件和恢复行为；追加 `--pid <PID[,PID...]>` 时在采集包内增加只读快照：CPU/NUMA 拓扑、IRQ/SoftIRQ、NPU 拓扑、目标进程及线程 affinity（写入 `cpu_trace/hostbound/`）。默认使用全量模式；仅在存储或风险限制明确时才使用 `--minimal`。采集包内的 `hostbound/collection_manifest.json` 必须记录未运行的外部工具，避免把缺失数据误当作正常。

采集前根据现象生成只读工具计划：

```bash
python3 tools/tool_router.py --signals python,gil,irq,numa,device-gap
```

工具选择不是自动执行授权。GIL、PMU、业务插桩、CANN Profiling 和绑核都必须逐项满足前置条件并获得用户授权。

## 工具选择

| 条件 | 补充工具 | 采集边界 |
|---|---|---|
| 一切 HostBound 初诊 | ftrace + HostBound 快照 | 必选；全量采集调度、迁移、IRQ/SoftIRQ、idle、频率 |
| Python 多线程、锁等待、下发线程看似空闲 | 官方 gil_tracer | root、sysTrace、指定 PID、短窗口；无侵入 |
| 已知业务段慢、Cache Miss/Page Fault/IPC 嫌疑 | 官方 function_monitor | 需用户允许 PyTorch 业务插桩；PMU 需 libkperf 与权限 |
| Device 空泡、Host Runtime 与 Device task 重叠关系 | 已有/按官方采集的 msprof collection-dir | 只导入/导出，不修改 CANN/msProf 源码 |
| IRQ/affinity/NUMA 争用已有证据，需要优化验证 | 官方 host_analyzer | 只生成建议和预检；不得自动绑核、写 IRQ affinity 或停止 irqbalance |

外部工具详细契约见 [官方工具适配说明](references/official_tool_integration.md)。

## 诊断方法

1. 先解析 ftrace 和快照，建立 CPU、调度、抢占、IRQ/SoftIRQ、迁移、频率、NUMA、affinity 的时间窗证据。
2. 读取 [Ascend Host Thread Knowledge](references/ascend_host_thread_knowledge.md)，将 `acl_thread`、`release_thread`、SQ/CQ、IRQ 作为候选对象；名称匹配不能单独形成结论。
3. 有补充数据时，按相同业务稳定窗口关联 GIL、函数耗时/PMU 和 msprof Host/Device 时间线。时钟域不能证明一致时，明确标注为近似关联。
4. 只按 [HostBound Diagnosis Rules](references/hostbound_diagnosis_rules.md) 输出 finding。每个 finding 必须含 Metric、Value、Threshold 或 Baseline、Evidence source、Time window、Confidence。
5. 无至少两类独立证据时，输出 `INSUFFICIENT_EVIDENCE` 或“待验证假设”，不得声称根因。CPU 高、IRQ 多、GIL 事件多、Cache Miss 高均不能单独判定 HostBound。
6. HostBound 的确认还必须有 Device 空泡/Host-Device overlap 失配，以及至少一项对应 Host 侧证据；没有 CANN/Device 时间线时只能表述为“Host 侧风险/疑似”。

## 优化与安全边界

- 先保留原始采集包、affinity、IRQ 和 NUMA 快照，再提出优化方案。
- `host_analyzer` 是优化执行器，不是诊断器。禁止自动执行 `taskset`、`migratepages`、写 `/proc/irq/*/smp_affinity` 或停止 `irqbalance`。
- 优化必须由用户确认，并以前后相同负载、同一窗口的复采结果验证；无收益或副作用须给出回滚方案。
- 离线报告仅使用现有包；不要求客户为已有数据重复采集。信息不足时一次性给出“最小补采集组合”，优先同窗口 ftrace + 进程/拓扑快照，随后才按疑点请求 GIL、PMU 或 msprof。

## 离线分析

```bash
# 在本 Skill 根目录 (cpu-host-performance/) 下执行
python3 -m analyzer analyze <采集包或trace> --output-dir <输出目录>
# 或在任意目录直接运行入口脚本
python3 <Skill路径>/analyzer/analyze_cpu_trace.py <采集包或trace> --output-dir <输出目录>
```

查看生成的 `hostbound_report.html`。分析器不应因缺少 GIL、PMU、msprof 而失败；必须在报告的数据覆盖与限制章节明确这些数据是否存在。
