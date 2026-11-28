# 默认完整采集与证据契约

此契约用于解释 Manifest、读取原始数据和判断是否复采。入口是 `sudo bash scripts/cpu_trace_collect.sh`，默认3秒全量事件、HostBound、NPU自动发现及全机进程/线程前后快照。安全快照仍受内核能力、工具和权限限制；完整采集指尝试并记录所有常规能力，不能承诺每台机器都有每项数据。

## 数据链

1. `cpu_trace_collect.sh` 每次原子创建带时间及随机后缀的独立采集目录，再保留只读快照、创建私有 trace instance；tar.gz与目录同名。
2. Bash/awk 函数逐命令和接口记录状态，标准化 sysfs、proc、cgroup 和身份。默认原生 Dump 由同一 sh 内置的原版 Python 采集器生成。
3. `hostbound/npu_smi_info{_start,}.txt`、`npu_smi_map.txt`、`npu_smi_topology.txt` 保存设备状态、映射和拓扑原文。机型另取 `cat /sys/class/dmi/id/product_name` 和 `npu-smi info -t product -i 0 -c 0` 两项原文，分别保存在 `hostbound/dmi_product_name.txt`、`hostbound/npu_smi_product.txt`。核对产品字段识别 A2/A3/A5，未知和冲突保留在报告中。解析错误与没有活动任务应分别记录。
4. `hostbound/numa_topology.json` 与 `hostbound/sysfs/node/nodeN/{cpulist,distance,meminfo}` 保存 NUMA 降级证据；lscpu、lscpu 扩展/可解析输出、numactl、numastat 保留原文。
5. `process_start/end.json` 保留所有可读进程与线程；所有进程保留 NUMA 页汇总，指定目标另保存 NUMA 原始文件与 numastat -p。`frequency_start/end.json`、`frequency_samples.jsonl` 和 `idle_start/end.json` 是各自的 sysfs 来源。
6. 资源原始快照位于 `hostbound/resource_start/end.json` 及 `resource_samples.jsonl`，包含boottime时间和 `/proc/stat/loadavg/meminfo/vmstat/diskstats/pressure/{cpu,memory,io}` 等原文及缺失状态。`hostbound/resources/df_blocks.txt`、`df_inodes.txt`、`lsblk.txt` 保留容量/inode/块设备原文。进程 cgroup 快照另含memory/pids限制；资源分析不依赖ftrace完整性。
7. 根目录及 hostbound 的 Manifest 随整个 `cpu_trace/` 打包。`parser.py` 保留声明的原始文件和真实包内路径清单，不把 JSONL/vendor 原始输出误当 trace。
8. `collection_integrity.py` 对账声明、包内存在性及实际解析；`report_data.json` 保留原文、字段、来源与诊断；HTML 展示摘要和可展开完整数据。
9. `hostbound/environment/` 保存 ftrace 启动前的只读环境证据。分析器将它整理到 `metrics.environment`，在报告第6节展示。环境证据单独核验，原有 HostBound 和 ftrace 完整性各自计算。

Manifest schema_version=1，`entries` 每条包含：`category`、`requested`、`command`（argv数组或null）、`command_exists`、`returncode`、`raw_path`（相对 cpu_trace）、`raw_exists`、`empty`、`parse_success`、`parsed_count`、`started_at`、`ended_at`、`failure_reason`、`status`。允许附加 size_bytes、PID/starttime、item_errors 等。opaque 原文没有语义解析时 parse_success/count 为null；不能将非空文件本身视为已正确解析。

采集脚本向 stderr 逐项打印可检测的缺项和原因，并在结束时汇总。离线分析把缺失、解析失败、丢失统计和快照子项问题整理到 `metrics.collection_integrity.gaps`，在报告第1节显示。按选项跳过和无活动进程可在采集记录中核对。

## 环境快照

| Manifest 类别 | 证据 | 范围 |
|---|---|---|
| `environment_host` | `host/*.txt` | `os-release`、`uname`、THP、NUMA balancing、swappiness、overcommit_memory、内核时钟源 |
| `environment_ascend` | `ascend/*.txt` | 按实际安装位置采集驱动、Toolkit、Runtime、Compiler、HCCL、OPP、ATB、MindIE 的版本文件 |
| `environment_process` | `pid_<TGID>.json` | 显式 `--pid` 指定的目标。记录 PID、starttime、可执行文件、启动变量、已映射的共享库和进程资源限额 |
| `environment_dump` | `msprechecker_dumped.json` | 默认调用内置原版采集器。包内位于 `hostbound/environment/`，独立文件位于输出目录，命名为 `<采集目录名>_msprechecker_dumped.json` |

宿主机文件路径记录在 Manifest 的 `source` 中，命令来源记录在 `command` 中。版本取自文件内容，目录名仅用于定位。各产品对应的软件包、安装方式与华为文档见[安装路径参考](ascend_install_paths.md)。

1. **选 CANN 安装目录。** 优先使用采集进程中第一个存在的绝对目录 `ASCEND_HOME_PATH`、`ASCEND_TOOLKIT_HOME`。否则依次检查活动 Conda 环境的 `Ascend` 前缀、当前用户与系统 CANN 安装记录中的 `Install_Path`、`/usr/local/Ascend`、当前用户的 `$HOME/Ascend`。安装记录仅解析对应键。
2. **识别布局。** 在选中的前缀下先查 `cann` 与 `ascend-toolkit/latest`。若均无有效入口，仅在该前缀下识别 `cann-<版本>`、`ascend-toolkit/<版本>`、`nnrt/latest` 和 `nnae/latest`。有多个不同的候选目录时记为 `ambiguous_cann_installation`，`source` 指向有歧义的前缀。可通过上述环境变量明确选定目录。如果新旧两个活动入口实际指向不同安装，默认探测仍按组件兼容查找这两个入口；现场需要单套版本时应显式指定目录。
3. **定位组件。** 对每项先查 `<组件>/version.info`，再查 `share/info/<组件>/version.info`。Toolkit 的旧版文件与本机架构的 `<arch>-linux/ascend_toolkit_install.info` 优先于 `asc-devkit/version.info`、`share/info/asc-devkit/version.info`。OPP 可由 `ASCEND_OPP_PATH/version.info` 单独定位。驱动从 `/etc/ascend_install.info` 的 `Driver_Install_Path_Param` 定位，ATB、MindIE 还识别 `ATB_HOME_PATH` 的 ABI 目录和 `MINDIE_LLM_HOME_PATH` 的 LLM 子目录，读取上层版本记录。
4. **解释结果。** 命中常规文件后按实际读取结果记录状态。仅遇到目录或断链时记录首个异常路径和 `version_source_not_regular`，均不存在时记录首选路径和 `interface_missing`。报告逐组件合并 Bash 快照与原生 Dump，并显示提供该值的来源。只有子包证据时项目显示为“asc-devkit 子包”。独立原生 JSON 仍反映原生采集器自己的探测范围。

默认命令只能观察采集进程可见的环境和文件系统。sudo 清除了安装用户的环境、pip 安装位于独立虚拟环境、或同机部署多套 CANN 时，可显式提供 CANN 的版本目录。容器内组件与业务进程实际加载的库需结合对应容器或 `--pid` 证据判断。

进程快照仅用于读取。先核对 TGID 和 starttime，读完再次核对 starttime。进程退出或身份变化时丢弃该次快照。启动变量取自 `/proc/<PID>/environ`，仅保留 Rank、可见设备、OpenMP/BLAS 线程设置、HCCL 超时等白名单键和允许的值格式。启动环境读取上限为 1 MiB，映射表读取上限为 4 MiB，库路径结果上限为 64 KiB。达到限制时记录字段失败原因。完整环境、进程代码执行、包枚举和主动网络探测在此快照范围之外。

未提供 PID 或 HostBound 最终关闭时，进程环境记为 `NOT_REQUESTED`，仍保留宿主机和组件版本快照。`--minimal` 只缩减 trace 事件。较旧采集包没有环境证据时使用 `UNKNOWN` 并在 HTML 显示 N/A。环境证据缺失或格式问题按 Manifest 状态处理。

原生 Dump 的包内副本与独立 JSON 逐字节一致，使用原版采集器的 `_meta.tool`、`_meta.schema_version`、`_meta.collection` 及证据字段。CPU 分析器按内容识别独立文件，按 `hostbound/environment/msprechecker_dumped.json` 读取包内文件。第6节展示原生采集状态及用于 CPU 诊断的环境字段，原生全量证据保留在原始 JSON 中。默认 Bash 快照及其来源保留在包中。原生文件缺失、解析失败或未生成时，继续使用 Bash 快照。

原生采集在 ftrace 前以 `--filter --no-probes` 执行。缺少 Python 时，`environment_dump` 记录 `COMMAND_NOT_FOUND`。脚本不可读或执行失败时记录 `EXECUTION_FAILED`。已有 Bash 或 trace 证据仍可分析。独立 JSON 采用与 CPU 包相同的唯一前缀，便于在两个 Skill 间对应同一批取证。

原版采集器更新后，在完整仓库中的 CPU Skill 根目录运行 `python3 scripts/update_ascend_dump_bundle.py` 同步内置版本。同步脚本用于维护发行文件。现场分发新版 `cpu_trace_collect.sh` 即可。

## 状态及行动

| 状态 | 含义 | 后续处理 |
|---|---|---|
| COLLECTED | 命令/接口取得有效原文；parse_success 单独说明语义验证 | 使用已有证据 |
| NO_ACTIVE_PROCESS | 有效空进程表/明确无活动任务 | 说明该窗口无任务，无需机械复采 |
| COMMAND_NOT_FOUND | 可选工具缺失 | 先核对工具/驱动，使用已有proc/sysfs降级 |
| PERMISSION_DENIED | 读取/执行权限不足 | 说明具体接口和权限/namespace条件 |
| UNSUPPORTED | 内核、驱动、硬件或选项不支持 | 使用其他可信来源，重复相同采集不能解决 |
| PARSE_FAILED | 原始数据存在但语义/格式无效 | 修复解析器后离线重跑 |
| NOT_REQUESTED | 本次明确关闭该类采集 | 必要时使用默认完整入口 |
| NOT_INCLUDED | Manifest 声明已生成的文件不在收到的包中 | 找回原始文件并修复打包 |
| EXECUTION_FAILED | 工具存在但执行失败/超时/身份变化 | 保留返回码/错误原文，解决具体失败原因 |
| UNKNOWN | 旧包没有请求/能力记录 | 不伪造成功或未请求，先审查原始目录 |

`metrics.collection_integrity.entries[].collector_status` 是原始声明，`status` 是收到证据后的对账结果。ftrace 单独列出事件存在性、解析统计与丢失状态；未知丢失不能当0。HostBound 单独列出各状态数量和缺失类别。`actions` 解释具体缺失、原因、可解决性及条件；只有明确未请求常规数据、实际事件丢失等可由复采补足的场景才生成复采命令。常规复采默认 `--buffer-size 16384` KiB/CPU。采集元数据分别记录请求与实际读回的缓冲区大小。

## 拓扑、身份与诊断约束

- CPU→NUMA 使用本次 sysfs/lscpu/numactl；节点可稀疏编号，不能用 CPU 数量或卡号补造。距离矩阵保留列对应节点；MemFree 和 MemAvailable 分开。
- NPU 硬件亲和只由显式 CPU Affinity 字段确认。仅确认 A3 且缺亲和时允许按排序的逻辑 NPU ID 在排序的可用 NUMA 节点间均衡轮转，并单列为分配策略。HCCS/PCIe 和 Logic/Physical ID 均不能证明本地性。
- 调度字段是 TID；TGID 来自 proc 或可证明的 clone 关系。使用 boot_id、starttime、进程/线程前后快照及生命周期隔离 PID 复用。未确认宿主机命名空间时不生成可执行方案。
- 当前 CPU、allowed CPUs、有效 cpuset、Mems_allowed 与实际 numa_maps 页分布有不同语义。各 TID 的 cgroup 可能不同，需要逐线程核对。
- 计划使用在线 CPU 与相关 TID 有效 cpuset 的交集，保留既有窄掩码。共享池缺少负载证据时只做可核验的本地性建议。只有完整物理核组、互斥分区及负载证据均可核验时才讨论隔离。现场逐项复核对象与权限后使用配套客户配置。
- CPU 绑定不迁移现有内存页。启动命令 `numactl --physcpubind=... --membind=... COMMAND` 仅在有独立内存策略证据时讨论，不作为运行 PID 的迁移命令。
- 允许跨节点、单次 PSR 或页分布偏离只是潜在风险。已分配页不等于远端访问流量；风险升级需要关联迁移、实际内存访问、等待及性能退化证据。建议不直接修改全局调度参数。
- AI HIGH 置信度来自稳定 NPU PID 归属；父子/cgroup/命令等关联分别标注 MEDIUM/LOW。高CPU或名称匹配不能单独认定 AI/竞争。竞争候选需要 AI 可运行等待与其他任务同 CPU 执行窗口交集，因果标记保持 UNPROVEN。
- Frequency 按 related_cpus/policy 去重，显式kHz→MHz，记录 trace/sysfs 来源和时钟对齐。Idle 的 C-state 编号仅表示状态；进入到退出的时长用于 Residency。`-1`、32/64位无符号最大值表示退出；未知区间为null/N/A。

## 验证边界

`python3 -m unittest discover -s tests -v` 包括假 proc/sysfs/tracefs、归档与报告端到端用例。`tests/offline_report_browser.js` 在已有 Playwright/浏览器环境验证离线交互；依赖不可用会明确跳过。Python 3.7 语法兼容检查不等于实际在该解释器/目标内核运行。发布报告时分别说明模拟验证、本机浏览器验证与 openEuler/Kunpeng/Ascend 现场验证。

单文件采集使用 `/proc/uptime` 的 boottime 时间戳；频率样本和进程快照声明 `clock=boottime`，优先选择 ftrace `boot` 时钟。内核不支持 boot 时钟时保留数据但不叠加不同域时间线。旧版 Python 采集包的 monotonic/mono 组合继续兼容。

展示契约：HTML每类明细最多100条，完整指标和原始证据保留于report_data.json。截断只发生在渲染层；2.3不生成逐PID全部线程亲和证据表。第4节用一张图展示最可能影响任务的资源占用与压力。资源速率依赖同钟不同时间点与非回退计数，缺失显示N/A；MemAvailable不能用MemFree替代，磁盘分区与整盘不累加，短窗口及磁盘busy%本身不证明资源瓶颈。

HTML、报告 JSON 和客户模板/配置直接生成。2.3 展示当前摘要。第三节按 `metrics.binding_plan` 展示 AI 对象清单、`design` 配置与待核验原因，JSON 文件保留完整配置。

## 定制绑核的补充网络证据

涉及NIC/IRQ隔离时读取[定制绑核上游说明](https://github.com/hu669293657/skills/blob/bf82e886ddda0a9955c2d5422f50b0b4caeb80b6/cpu-host-performance/references/custom_binding.md)（上游完整 Skill 的定制生成链，本仓不交付对应生成器）。`python3 scripts/collect_network_evidence.py --interval 5 --output network-window.json` 为完整skill目录下的只读补充采集，不改变原单文件采集器和旧包Manifest契约。保留NIC前后拓扑、PCI/NUMA/队列/MSI IRQ、requested/effective affinity、RPS/XPS、两次中断/softirq/softnet/netdev计数及读取时间、ethtool和irqbalance状态。缺失项写入该JSON的errors/status；该补充JSON需单独随原包交付，不声称已经自动进入原tar.gz或HTML。多窗口与归因/物理核校准要求见参考页。
