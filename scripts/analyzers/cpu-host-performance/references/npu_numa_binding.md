# NPU、NUMA 与宿主机绑核规则

按实测需求定制、网卡预留、训练/推理区别与其他客户服务预算见[上游定制容量预算说明](https://github.com/hu669293657/skills/blob/bf82e886ddda0a9955c2d5422f50b0b4caeb80b6/cpu-host-performance/references/custom_binding.md)（上游完整 Skill 的定制生成链，本仓不交付对应生成器）。下述既有Analyzer建议可能使用全部available核；定制方案先扣除客户/系统/网络预算并检查容量守恒，不能直接把旧建议称为完整隔离方案。

离线报告和定制生成器都复制同一份客户模板，只在 `bind_design.json` 中描述本次目标。需要现场 CPU 审计、业务 A/B 和 journal 恢复时，在完整 Skill 中使用独立的 `scripts/ascend_bind.py`。[客户模板与配置（上游）](https://github.com/hu669293657/skills/blob/bf82e886ddda0a9955c2d5422f50b0b4caeb80b6/cpu-host-performance/references/customer_script.md) · [现场审计](binding_workflow.md)

实现：`analyzer/npu_parser.py`、`npu_affinity.py`、`topology.py`；展示：`npu_report.py`。采集/Manifest 缺失处理统一见 [采集契约](collection_contract.md)。

## 证据语义

保留 `npu-smi info`、`info -m`、`info -t topo` 原文。进程表支持不同列、组合/拆分 NPU/Chip、续行、空任务和显存单位；无法解析的非空数据标为 PARSE_FAILED。硬件亲和以明确标注的 CPU Affinity 列为据。HCCS/PCIe、卡号、Logic/Physical ID 不提供 CPU/NUMA 位置。

CPU→NUMA 来自本机 sysfs cpulist、标准化 NUMA JSON、numactl、lscpu。稀疏节点、冲突与缺失保持显式。NPU→PID→TGID→TID 需要原始身份与父子/线程证据；容器数字 PID 未经映射不能直接关联宿主机进程。显存占用最高者只是角色提示，不得漏掉其他 PID。

| 字段/状态 | 含义 |
|---|---|
| allowed CPU | 每个线程当前调度许可，非历史运行分布 |
| PSR | 快照最近运行核，非全窗口分布 |
| ftrace CPU/NUMA | 已观测运行核/节点，丢失时仅下界 |
| 有效 cpuset | cgroup 可运行 CPU 硬边界，逐 TID 核对 |
| Mems_allowed | 允许分配内存的节点，非实际页位置 |
| numa_maps/numastat | 已分配内存位置，不能单独证明远端访存流量 |
| LOCAL | 全线程许可落在已知 NPU CPU 范围且无范围外运行观测 |
| UNCONFINED/REMOTE_ALLOWED | 许可范围可越出或偏离 NPU 公布范围 |
| REMOTE_OBSERVED | 观测 CPU 超出亲和范围；需另判是否跨 NUMA |
| UNKNOWN | 缺映射、身份、线程或拓扑证据 |

NPU 亲和 CPU 可能只是某节点的一部分，超出该范围仍可能处于同一 NUMA。此时只能说偏离公布 CPU 范围，不能自动声称远端 NUMA。

## 机型与 A3 分配策略

用 `cat /sys/class/dmi/id/product_name` 和 `npu-smi info -t product -i 0 -c 0` 保留整机与设备产品原文。有效来源中出现可识别且一致的产品代际时可确认 A2、A3 或 A5。来源相互冲突或均无法识别时保留未知。

显式亲和优先。仅当确认为 A3 且某设备没有显式 CPU Affinity 时，按数值排序占卡任务的逻辑 NPU ID。将已有显式分配计入节点占用，在每个同卡目标都能使用至少一个在线逻辑 CPU 的节点中，优先选已分配设备较少者；并列时选节点编号较小者。同卡多个进程作为一组。报告按可用逻辑 CPU 分配，定制容量预算进一步要求可用的完整物理核组。例：若两个可用节点为 2 和 7，四张卡均可使用两节点且均无显式亲和，依次分到 2、7、2、7。节点编号可以不连续。计划中的 `placement_source` 用 `A3_BALANCED_POLICY` 标示策略结果，用 `EXPLICIT_AFFINITY` 标示设备公布的亲和。策略结果只用作绑定建议，不能由此判定设备物理本地性、远端运行或性能根因。其余机型缺亲和时保留未知。

## 计划生成

1. 使用本次真实 PID/TID、boot_id、starttime 核对前后身份。PID复用、namespace未确认、同 PID 多卡但线程职责未知时阻止执行方案。
2. 候选 CPU 取设备公布的范围，或 A3 策略选定节点的核；再与本机节点 CPU、在线 CPU 和各目标 TID 的有效 cpuset 求交。各线程可能有不同的 cgroup，需单独核对。
3. 当前各线程掩码已合规且无冲突时保留，避免覆盖业务关键线程细分。CPU绑定不等于独占，仍核对其他业务和IRQ的运行/等待重叠。
4. 共享候选池必须有完整 Worker 运行/等待需求及可靠性证据，才按观测需求分配完整 `(socket,node,core)` SMT 组。证据不足不均分；部分重叠/物理核心冲突而无法安全分配时报告阻塞。
5. 预留系统 CPU、改配额或搬移 IRQ 需要具体负载/干扰证据，不使用固定预留数。运行/等待只是需求代理，方案须同负载实测，不能承诺收益。
6. 保留当前/建议 CPU 和 NUMA、映射来源（硬件字段或 A3 策略）、运行/等待/IRQ/cgroup 依据、风险和复测条件。身份、节点或 CPU 范围不足时记录具体阻塞。

## 执行与内存

报告第三节提供 `cpu_binder_simple.py` 与 `bind_design.json`。配置记录本次可核验的对象和 CPU 范围。无可核验目标时交付空 `custom_bind` 列表、说明阻塞原因。

CPU 条目使用 `pid` 和 `cpu_list`。批量设置进程现有线程时还需核实每个现有线程的许可范围、保留的窄掩码和线程集合。模板的 `bind_sub_process=true` 只作用于同一线程组，子进程须以自身身份独立评估。

模板按数字 ID 直接设置。执行前在原宿主机确认身份、线程集合、cpuset、IRQ、CPU 和权限，保存各对象实时原值并获得授权后，在两文件所在目录运行 `python3 cpu_binder_simple.py -c bind_design.json`。模板没有自动预检或回滚。

默认 `mem_bind=false`。开启后，模板只尝试向目标 CPU 所在的单一 NUMA 节点迁移已分配页。IRQ 条目可能停止运行中的 irqbalance 并写中断亲和。[模板字段、依赖与操作影响（上游）](https://github.com/hu669293657/skills/blob/bf82e886ddda0a9955c2d5422f50b0b4caeb80b6/cpu-host-performance/references/customer_script.md)

## 风险等级与缺口

拓扑/许可偏离仅是潜在配置风险，不直接列 P1。提高性能风险需关联跨节点运行迁移、实际内存位置/远端访问、明显等待及性能下降证据；没有远端流量测量不能声称已证实远端访存。默认不建议修改全局调度参数。

缺证据先看 Manifest：无活动任务说明窗口事实；工具缺失/权限不足说明条件；原文解析失败先修解析器；已生成未入包先修打包。只有重新采集确实能解决的问题才给完整命令，不机械输出附加 `--hostbound` 的复采模板。

## 调度证据不完整时的本地化建议

互斥核心组仍要求完整runtime/等待证据。若同组显式原始NPU亲和池相同，全部池内CPU归属唯一NUMA，online范围已知，宿主机进程/全TID身份和cpuset均核验，允许把各进程约束到相同的完整在线亲和池（SHARED_LOCALITY）。这只约束本地性，组内共享，不按卡数均分、不提供隔离或吞吐收益承诺。部分重叠池、未知CPU归属、不同cpuset候选、多NUMA或缺失身份继续阻断。已合规窄掩码保留。报告没有NUMA建议时显示“待核验”，不打印空列表。

## HTML第三部分与脚本交付

2.3 展示当前 NPU/NUMA 的观测和来源。第 3 节的配置对应 `metrics.binding_plan.design`。旧包能核对宿主机身份、完整线程掩码和显式 NPU 映射时仍可规划。缺逐线程 cpuset 时以各自的当前 allowed 作为安全边界。
