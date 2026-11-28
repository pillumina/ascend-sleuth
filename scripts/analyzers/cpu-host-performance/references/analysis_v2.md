# v2 数据契约、分析方法与兼容性

本页为本次升级的实现依据。目标平台为openEuler22.03SP4 / Kunpeng920 / ARM64 / Ascend910B4；本地只使用合成证据和模拟文件系统，未连接目标服务器。

## 原始证据

所有新sidecar位于采集包 `cpu_trace/hostbound/`，旧包继续兼容。

| 文件 | 内容 |
|---|---|
| capabilities.tsv（或导入JSON） | event、exists、writable、requested、enabled、失败原因；支持不等于有事件 |
| frequency_start/end.json | schema_version、单调时钟采样时间、每policy的related_cpus、当前/最大/上下限、Governor、接口错误 |
| frequency_samples.jsonl | 每次轮询的单调时间与policy样本；同一policy不按CPU重复读取 |
| process_start/end.json | 快照起止、CLK_TCK、进程/TGID/PPID/starttime/cmdline/cgroup及全线程TID、状态、CPU ticks/秒、PSR、allowed/mems_allowed |
| npu_smi_info_start.txt / npu_smi_info.txt | 前后NPU→PID/显存关联；版本相关文本解析未知时不猜 |
| trace_stats/cpuN.txt / trace_overrun.txt | 每CPU buffer stats和overrun/commit-overrun/dropped汇总；不再读取不存在的stats/overrun路径 |
| export_errors.txt / helper_error.txt | 导出与增强采集失败；失败不等于没有事件 |
| collection_cpus.txt / trace_clock.txt | 实际请求CPU范围与时钟模式 |
| device_windows.json（仅导入，可选） | clock=mono且与metadata一致的NPU窗口；本工具不自动采集Device |

保留对旧 `pid_*_status/threads/thread_affinity/starttime/cpuset_effective.txt` 文件的读取兼容。新采集使用完整 process_start/end.json、逐 TID cgroup/cpuset 和目标 *_start/end 原文，详见 [采集契约](collection_contract.md)。采集中的 taskset 只查询，不设置 CPU；报告建议命令不自动执行。

## 统一输出

`report_data.json` 包含schema_version=2、units、metrics、diagnosis。新增字段均为加法扩展；旧tasks、sched、freq和npu_affinity兼容视图保留。freq兼容视图明确unit=MHz，原始采集值在frequency策略域静态信息中保留。

| 字段 | 单位/语义 |
|---|---|
| per_cpu[c].observed_sec | 连续可解释调度/idle区间的秒数；不是在线CPU数乘窗口 |
| per_cpu util/idle/irq/softirq | 百分比，缺失null，真实零才为0 |
| sched.cs_rate | 全机已观测sched_switch / 窗口秒；单核rate另列 |
| sched.lat_* / thread_metrics.wait_p*_ms | 毫秒；仅成功wakeup→首次switch入的已配对样本 |
| thread_metrics.runtime_sec | 连续匹配sched_switch任务区间，秒；包含任务上下文内IRQ，不能视为纯用户态运行 |
| thread_metrics.cpu_utilization | 单线程Runtime / 采集窗口 ×100% |
| thread_metrics.runtime_share | 单线程Runtime / 全任务已观测Runtime ×100% |
| runqueue_wait_sec | 已完成成功wakeup和R/R+切出等待之和，下界；不是线程全部生存期精确等待 |
| migrations | 有显式迁移流时用该来源，否则观测运行CPU变化下界；两者不相加 |
| frequency.domains | policy级去重，MHz；时间加权统计/原始静态值/样本数/时间序列/读取失败 |
| contention.candidates | 等待与同核执行重叠的候选；causality=UNPROVEN |
| contention.cgroups | 当前/祖先配额及前后累计计数增量，counter reset或缺失为null |
| diagnosis findings | metric/value/threshold/source/time_window/confidence + causality/evidence_class |

## 频率

标准CPUFreq接口单位kHz；policy/related_cpus包含共享策略域CPU。优先ftrace有效样本，没有时使用sysfs动态采样，再降级静态数据。cpu_frequency使用payload.cpu_id，不是事件发出CPU。

平均频率是已知区间的时间加权值，第一样本前不外推；最后trace样本仅延续到采集结束；sysfs仅覆盖采样时间范围。当前值来自结束快照，可能略晚于trace。硬件最大参考为cpuinfo_max_freq，窗口观测最高频率另列。低频占比仅在该参考存在时按<=50%计算，50%是工具经验线；不使用窗口最高样本作硬件基准。

主状态按可用数据源分类；event_status独立保存未请求、开启失败、不支持、无转换和未知。丢失/解析错误/坏频率数据会降可靠性，不能以“无事件”推断物理频率不变。scaling_cur_freq通常为请求/驱动报告值，cpuinfo_cur_freq只有实现时才有硬件反馈，报告不会伪造读取失败的接口。

PMU研究结论：cycles是计数，不自行提供参考时钟；ref-cycles是否有映射及参考频率依赖PMU驱动。ARM64的执行层级过滤和虚拟化会改变统计范围，perf权限也会限制采集。本次未执行perf、不进行cycles/ref-cycles估算，统一NOT_VALIDATED。真实平台验证至少需确认PMU事件映射、同任务/同CPU统计范围、参考频率、enabled/running比例及计数器权限，最后与可信硬件反馈交叉验证；不将未验证比值输出为MHz。

## 进程、线程与生命周期

全机/proc摘要和全部线程前后只读快照可发现不直接占NPU的API Server、EngineCore、DataLoader与辅助任务。NPU进程和用户根TGID是种子；上溯祖先保留关系，只向种子/识别到的框架launcher子树扩展，不扫入sshd所有兄弟进程。共享非根cgroup仅为关联证据；`0::/`等根membership不构成工作负载关系。

线程身份由TID与/proc/stat starttime构成；PID复用但生命周期边界缺失时保持歧义，不跨代配对或标记NPU归属。fork本身不能区分新进程和clone线程，TGID未知则null；task_newtask的clone_flags按内核文本十六进制解析，CLONE_THREAD时继承父TGID。fork/newtask双事件合并为一次出生；退出切断等待，缺少最终switch时截断Runtime并标记不完整。

comm可能截断且会重名；角色分类结合关系、NPU、命令行和comm，附证据/置信度，不用于认定根因。PSR、Affinity和cgroup为快照事实，不冒充历史配置；Mems_allowed为许可节点，不证明内存页实际分布。

## 调度、竞争与中断

- 不用sched_waking作为延迟起点，不把重复成功wakeup当独立延迟样本；退出/边界/不连续/歧义样本不补齐。真实长等待不再被任意30秒老化丢弃。
- R/R+计为Runnable Switch-out，不等于其他任务因果性抢占。可运行等待期间的迁移会把目标CPU时间窗分段。
- 候选必须在目标等待片段对应CPU上实际运行。已知Affinity与CPU冲突时不形成强候选；Affinity交集本身只是配置相关性。
- 候选总重叠时间和全部窗口保存至 JSON；HTML 默认仅展示 Top N/少量例证，详细数据可展开。全线程数据、完整等待和运行区间仍保留。
- Affinity成对比较按已观测等待排序最多512个活跃关联线程，输出比较范围/截断标记，避免巨量线程的无界二次方比较；全线程Affinity仍保留。
- cgroup v2读取cpu.max/cpu.stat，v1读取cfs quota/period与throttled_time（ns转μs）。检查祖先，不把quota问题等价于整机饱和。快照窗口包围trace，增量不能直接归到某个线程或某次请求。
- Device导入仅在明确mono同域且窗口相交时标记相关。即使相交，也不证明因果；需相同负载、控制变量优化前后复测吞吐/请求尾延迟。
- IRQ/SoftIRQ配对使用CPU+irq/vec，不再用无编号exit去猜另一条pending。嵌套同类区间先取并集，再与有效CPU观测区间求交；分母为这些CPU总观测秒。handler不覆盖全部入口/IPI成本，SoftIRQ墙钟区间可能含嵌套IRQ，二者不可简单相加。

## 兼容性与现场验证边界

已验证：标准库离线分析、8/64/256核、8NUMA、旧归档/NPU亲和性回归、sysfs/proc/cgroup模拟、全量/精简fake tracefs、HTML交互与无外部脚本。Python3.7语法检查通过；实际执行解释器为3.14，3.7运行时不在本机。

需要真实平台验证：目标内核trace instance/boot 时钟支持、事件权限与实际产生率、Ascend npu-smi输出版本、CPUFreq驱动语义、PID namespace/cgroup挂载布局、256核采集buffer丢失率与CPU/IO开销、Device时钟对齐和优化收益。没有声称已完成Kunpeng/Ascend实机验证。

不支持项按现场capabilities报告，不能从内核版本猜测：cpu_frequency、sched_process_*、task_newtask、sched_stat_wait都可能受CONFIG/驱动/权限限制。sched_stat_wait默认只探测；无NPU工具不阻断/proc与用户PID发现。无私有trace instance时不退回破坏全局trace，helper快照仍可离线报告。

开销：默认每policy每秒读取最多7个小文件，进程发现只在采集前后两次遍历/proc，全量trace增加3个低频生命周期事件，既有高频调度/IRQ事件仍可能使buffer溢出；默认约1GiB/256核buffer。导出并发<=16。离线分析保存事件与区间，超大trace需关注内存；本次不以合成处理速度承诺实机开销。

## 一手依据

以下内容已核对，但目标发行版可能有补丁，现场仍应以其trace format和驱动为准。

- [CPUFreq接口、policy和频率含义](https://docs.kernel.org/admin-guide/pm/cpufreq.html)
- [Linux v5.10 task_newtask格式与clone_flags=%lx](https://raw.githubusercontent.com/torvalds/linux/v5.10/include/trace/events/task.h)
- [调度tracepoint字段](https://raw.githubusercontent.com/torvalds/linux/master/include/trace/events/sched.h)
- [ftrace实例、时钟与buffer统计](https://docs.kernel.org/trace/ftrace.html)
- [cgroup v2 CPU控制器与配额](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [Linux v5.10 ARMv8 PMU事件映射](https://raw.githubusercontent.com/torvalds/linux/v5.10/arch/arm64/kernel/perf_event.c)
- [perf权限](https://docs.kernel.org/admin-guide/perf-security.html)
- [ARM64 perf执行层级过滤](https://www.kernel.org/doc/html/latest/arch/arm64/perf.html)

## 资源与展示增补

默认采集3秒，每次使用独立时间目录。新增resources指标来自原始proc前后/周期快照、df、lsblk和cgroup memory/pids。第4节用一张图展示主要资源占用与压力；窗口与trace分开声明，旧包缺失不填0。HTML每张明细表最多100条，完整CPU曲线和report_data.json保留全部指标。

报告直接渲染成离线 HTML，保留 `report_data.json`。第 2.3 节展示当前亲和摘要，第 3 节提供固定 `cpu_binder_simple.py` 和本次 `bind_design.json`，并列出 AI 对象及待核验原因。
