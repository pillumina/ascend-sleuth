# Collector Dispatch（证据缺口 → 客户现场采集器）

**何时读**：诊断缺一项现场证据，而已有的日志、分析器结果和采集包都补不齐时。先判断这项证据是否真的缺；已有材料能回答的问题不重复采集。

采集器清单在 `scripts/collectors/`。Agent 只负责推荐，不执行采集、不访问客户环境、不上传数据。

## 先看有没有对口的采集器

```bash
python3 scripts/collectors/cli.py list --json
python3 scripts/collectors/cli.py show <名字> --json
```

`show` 是交付说明的权威来源：脚本路径、用途、适用环境、执行命令、权限、运行影响、客户返回文件与后续分析器都在里面。`installed=false` 表示仓库内文件缺失，这时不要推荐。

## 按缺口选

| 缺的证据 | 采集器 | 不要用的情形 |
|---|---|---|
| 系统/驱动/固件/CANN/框架版本、NPU 设备与拓扑、进程启动环境、rank table、HCCL 链路状态 | `env-snapshot` | 已经有可用的环境快照；只需要单个日志文件 |
| Host/CPU 调度切换与频率。中断事件和业务进程证据需要按缺口选采集模式 | `cpu-trace` | 只需要版本信息；不能在宿主机执行或拿不到 root |
| 网卡到 PCI/NUMA 的归属、MSI IRQ、affinity、队列、RPS/XPS、ethtool | `network-evidence` | 问题不在网络/IRQ 路径；已经有同一窗口的网卡证据 |
| CPU governor、策略/硬件频率上限、业务核实际频率 | `cpu-power-audit` | 只需要 OS 版本；没有代表性负载或不在业务窗口 |
| iBMC 带外硬件状态、当前告警、SEL、传感器、PSU/风扇 | `ibmc-dump` | 问题明确在 OS/应用层；没有 iBMC 访问权限 |
| plog / device / dmesg / 框架 / rank 日志 | `ascend-logs` | 已有覆盖问题时间窗的完整日志包 |

Profiling 数据没有新增采集脚本：采集方式仍走已有的 `msprof-collect-parse` 等词条（性能类数据缺口闸门）。`env-snapshot` 与 `cpu-trace` 只补环境与 Host 侧证据，不替代 profiler 采集。

数据形态判不出来就问一句，不要猜。混在一个缺口里的，只推荐当前最需要的那一个。

## 推荐时给什么

按 `show` 的字段给，缺一项都可能让客户执行失败或误判影响：

| 要给的 | 内容 |
|---|---|
| 脚本路径 | `show` 的「脚本文件」或「交付文件」；要发包时先 `bundle <名字> --out-dir <新目录>`，把目录里的脚本与 README 一起给 |
| 采集目的 | 这条证据要回答当前哪个判断，为什么现有材料不够 |
| 适用环境 | 宿主机/容器、OS、Python 版本、是否需要 NPU 工具 |
| 执行命令 | `show` 的「建议命令」或「执行步骤」，说明哪些占位符要替换（PID、时间窗、路径） |
| 权限与运行影响 | 是否 root、是否短时开启 ftrace、是否读取带外、预计耗时、对业务的影响 |
| 客户返回 | `outputs` 列出的文件；必要时指定时间窗、节点名、受影响 rank |

`bundle` 只复制文件，不执行、不联网。需要多个采集器时分别打包，不要混在一个目录里。

## 边界

- **只推荐，不执行**：诊断 agent 不在客户机器上运行采集脚本，也不代客户上传或回传。
- **先授权**：`cpu-trace` 需要 root 且会短时开启 ftrace，必须写明现场授权与采集窗口；`network-evidence` 读取中断信息通常也需要 root。只读采集同样要说明读取范围。
- **不联网、不上传**：`env-snapshot` 保留 `--no-probes`；任何采集器都不访问公网、不自动回传。
- **不重复采集**：已有证据够用时不再推荐；同一窗口的证据不要重复采。
- **没有对应采集器时如实说**：写清缺什么、为什么现有材料不够，不临时手写采集脚本，也不要用其他时间窗的数据顶替。
- **敏感信息**：脚本的脱敏不是分享许可；返回前按客户要求复核 IP、路径、模型名、账号与业务数据。

## 数据回来之后

按 `show` 的 `consumer` 调对应 Analyzer，读法见 `analyzer-dispatch.md`：

| 采集器 | 后续分析 |
|---|---|
| `env-snapshot` | 单份用 `ascend-dump-analyzer` 核对采集环境版本配套。业务进程已加载库与采集缺项见兼容性 JSON。变更前后两份可比对配置漂移。 |
| `cpu-trace` | `cpu-host-performance` |
| `network-evidence` | 没有自动适配器；与 `cpu-host-performance` 报告一起读，或直接读 JSON 的计数增量与 affinity |
| `cpu-power-audit` | 没有自动适配器；直接读 JSON 的 governor、上下限与频率采样 |
| `ibmc-dump` | `ibmc_analyzer` |
| `ascend-logs` | 先解包，把日志目录或日志文件交给 `issue-analyzer` |

采集成功不等于诊断成立：Analyzer 只提取事实，根因、fix 与 severity 仍由诊断 agent 判。

## trace 记什么

复用 `reference_lookup`，不新增 action 词表：

```yaml
- {action: reference_lookup, step: <当前步>, purpose: collect, outcome: hit,
   ref_id: sleuth-collectors, output: "推荐 <采集器名>：<一句话目的>",
   reason: "<缺哪项证据、为什么现有材料不够>"}
```

推荐了但工程师决定先不采，`outcome` 仍记 `hit`（推荐发生了），在 `reason` 写明「已推荐、未执行」。
没有对应采集器时 `outcome` 记 `miss`，`reason` 写清缺什么、现有材料为什么不够。
