# Ascend Host Thread Knowledge

本知识库仅用于解释 trace/快照，不把名称匹配当作根因证据。

| 对象 | 角色与可观察证据 | 常见风险 | 不能据此断言 |
|---|---|---|---|
| `acl_thread` | CANN ACL 相关 Host 下发线程；以 `ps -T`、ftrace comm/TID、msprof Runtime API 交叉识别 | runnable 延迟、与 IRQ 同核、CPU affinity 受限、长时间被抢占 | 名称出现不代表一定是瓶颈；必须证明其慢窗口与 Device 空泡重合 |
| `release_thread` | CANN 资源回收相关线程 | 被抢占导致资源回收滞后、与业务线程竞争 | 不可将任意延迟直接归因于内存泄漏或资源释放 |
| SQ | Submission Queue，Host 向 NPU 下发任务的队列；常结合 ACL/Runtime 时间线观察 | 下发间隙、SQ 相关 IRQ 与业务下发线程同核 | 没有 Device 时间线时，不可仅凭 IRQ 次数判定 SQ 阻塞 |
| CQ | Completion Queue，Device 完成后的状态/通知路径；常与 CQ 更新 IRQ 关联 | CQ IRQ 热点、完成处理延后 | 不能把 CQ IRQ 高直接等同于 NPU 故障 |
| `sq_send_trigger_irq` / `cq_update_irq` | Ascend 相关中断名；从 `/proc/interrupts` 与 ftrace IRQ 名称读取 | IRQ 集中到业务关键核、IRQ/SoftIRQ 时段与调度延迟重叠 | IRQ 数量本身不是故障；需要占比、核分布、受影响线程三类证据 |
| `dev[i]_sq_task` | 驱动 SQ 相关任务，host_analyzer 默认会尝试识别 | 亲和性错误、与业务线程争核 | 容器中可能看不到，缺失不代表没有驱动问题 |

NUMA/affinity 证据优先级：`npu-smi info -t topo` + `numactl -H` + `/proc/<pid>/status`/`taskset -pc` + ftrace CPU 迁移。没有内存页归属或性能差异对比，只能报告 `NUMA_RISK`，不能认定跨 NUMA 是根因。

Host/Device overlap 的有效证据要求：同一稳定窗口内，msprof Device task 的空泡/等待、Host Runtime/ACL 线程延迟、以及 ftrace 调度或 IRQ 事件至少同时具备两项；各工具时钟域不明时只能做相对关联。
