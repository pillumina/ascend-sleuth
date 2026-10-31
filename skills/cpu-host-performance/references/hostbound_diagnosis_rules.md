# HostBound Diagnosis Rules

所有 finding 必须包含 `Metric`、`Value`、`Threshold/Baseline`、`Evidence source`、`Time window`、`Confidence`。单一指标只产生“待验证假设”，不产生根因结论。

| 结论 | 最低证据组合 | 排除/降级条件 | 后续动作 |
|---|---|---|---|
| CPU 饱和/调度争用 | 高 CPU 利用率 + runnable 或 wakeup/sched latency 异常 | 仅单核高而大量核心空闲时改判不均衡 | 降并发、隔离关键线程、复采验证 |
| IRQ/SQ-CQ 干扰 | IRQ 处理占比/频率热点 + 关键线程调度延迟或同核关系；SQ/CQ 再需 NPU/IRQ 名称证据 | 仅 `/proc/interrupts` 快照，没有时间相关性 | 先建议 affinity 方案，确认后执行，前后对比 |
| CPU affinity 问题 | taskset/cpuset 限制 + ftrace 显示关键线程在受限热核或频繁迁移 + 存在可用空闲核 | 没有 PID/TID 对应关系 | 仅输出风险与补采计划 |
| NUMA 风险 | NPU CPU affinity 与线程/内存节点不一致 + 延迟/迁移/吞吐差异 | 只有拓扑，不含线程/内存/性能证据 | `NUMA_RISK`，不可称根因 |
| GIL contention | GIL Trace 长 hold/wait + 同窗口 Python 业务线程延迟或 Device 空泡 | 只有 take/drop 总数 | 调整线程模型/释放 GIL；复采 |
| Function/PMU 异常 | 函数长尾 + 同窗口 PMU Cache Miss/Page Fault/IPC 异常 + ftrace 或 Device 空泡 | 仅 PMU 计数或仅函数耗时 | 标注更粗粒度函数并复采 |
| HostBound | Device 空泡或 Host/Device overlap 失配 + 对应 Host 侧调度/GIL/PMU/Runtime 证据 | 无 CANN/Device 时间线 | 仅称“Host 侧风险/疑似”，不可确认 HostBound |

优化操作的门槛：禁止自动写 `/proc/irq/*/smp_affinity`、停止 `irqbalance`、执行 host_analyzer、修改 cpuset/taskset。报告只能给出计划，用户明确确认且保存现状后才可执行。
