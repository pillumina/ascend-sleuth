# collectors（客户现场采集器）

Analyzer 读已经拿到的日志和数据；Collector 负责把缺的那一份数据从客户现场拿回来。两类工具共用一条链：

```
collector（现场采集） → 返回文件 → analyzer（离线提取事实） → agent 判断
```

采集器只交付脚本、依赖和执行说明，**不在诊断会话里执行，也不访问客户环境或公网**。由工程师把文件发给客户，客户在目标机执行并回传结果。

## 目录

```text
scripts/collectors/
├── cli.py                  list / show / bundle 三个入口
├── registry.py             采集器清单（用途、环境、权限、影响、返回文件）
├── instructions/           人工采集说明（iBMC、日志）
├── ascend-dump/            环境采集脚本
└── cpu-host/               CPU 和网卡采集脚本与依赖
```

`cpu-trace` 使用 Analyzer 侧已保留的 `cpu_trace_collect.sh`，不复制第二份。其余脚本在各自的采集器目录下。

## 清单

| 名称 | 类型 | 采什么 | 返回 | 后续分析 |
|---|---|---|---|---|
| `env-snapshot` | 脚本 | 系统、驱动/固件、CANN、NPU、环境变量、进程启动环境、rank table、HCCL 链路 | `snapshot-<host>.json` | `ascend-dump-analyzer` |
| `cpu-trace` | 脚本（root） | Host ftrace、系统快照、NUMA/NPU 拓扑、进程/线程快照 | `cpu_trace_*.tar.gz` | `cpu-host-performance` |
| `network-evidence` | 脚本 | 网卡到 PCI/NUMA、MSI IRQ、affinity、队列、RPS/XPS、ethtool | `network-window.json` | 与 `cpu-host-performance` 报告一起读 |
| `cpu-power-audit` | 脚本 | CPUFreq 策略、governor、策略/硬件上限、实际频率采样 | `cpu-power-audit.json` | agent 直接读 |
| `ibmc-dump` | 人工 | iBMC 一键收集（带外） | 含 `dump_info/` 的压缩包 | `ibmc_analyzer` |
| `ascend-logs` | 人工 | plog、dmesg、npu-smi、框架/rank 日志 | 日志包与文本 | `issue-analyzer` |

`network-evidence` 与 `cpu-power-audit` 目前没有自动消费的适配器，输出由诊断 agent 直接读；这是有意的：先把证据拿回来，不为它们各写一个分析器。

Profiling 数据采集没有新增脚本：性能类数据缺口继续按 [`msprof-collect-parse`](../../references/tools/msprof-collect-parse.yaml) 等先验词条给命令；本目录只补环境、Host、BMC 与日志侧证据。

## 使用

```bash
# 这台机器上有哪些采集器
python3 scripts/collectors/cli.py list
python3 scripts/collectors/cli.py list --json

# 看一个采集器的完整交付说明（脚本路径、用途、环境、命令、权限、影响、返回文件）
python3 scripts/collectors/cli.py show env-snapshot
python3 scripts/collectors/cli.py show env-snapshot --json

# 打包成可直接发给客户的目录：脚本 + 依赖 + README.md + collector.json
python3 scripts/collectors/cli.py bundle env-snapshot --out-dir /tmp/env-snapshot-bundle
```

`bundle` 只复制文件，不执行、不联网；输出目录必须是新目录或空目录。`collector.json` 记录文件 SHA-256 与上游提交，便于核对客户回传的是同一份脚本。

## 推荐给工程师时带什么

按 `show` 的字段给，不要只丢一个路径：

| 字段 | 内容 |
|---|---|
| 脚本路径 | `show` 输出的「脚本文件」或「交付文件」；需要发包时给 `bundle` 目录 |
| 采集目的 | 为什么这条证据能推进当前诊断 |
| 适用环境 | 宿主机/容器、OS、Python 版本、是否为 root |
| 执行命令 | `show` 的「建议命令」或「执行步骤」，含占位符替换说明 |
| 权限与运行影响 | 是否 root、是否短时开启 ftrace、是否读取带外、预计耗时 |
| 客户返回 | `outputs` 列出的文件，必要时附时间窗和节点名 |
| 后续分析 | `consumer`，并把 analyzer 的调用命令一起给出 |

Agent 只推荐，不执行采集。`cpu-trace` 需要 root 且会短时开启 ftrace，必须写明现场授权与窗口；`network-evidence` 与 `cpu-power-audit` 是只读采集。

## 与诊断流程的接入

`skills/diagnose/SKILL.md` 步骤 5 与 `skills/diagnose/references/steps/3-cases.md` 的数据缺口段指向 `skills/diagnose/references/collector-dispatch.md`；该文件按缺口选采集器，并说明推荐格式。诊断 agent 不把采集器放进自动调用图，也不因为推荐了采集器就把它当成已执行。

采集结果回来后，按 `consumer` 调对应 Analyzer；Analyzer 的读法与失败退化见 `skills/diagnose/references/analyzer-dispatch.md`。

## 来源与许可

上游来源、固定提交、文件对应关系与改动见 [PROVENANCE.yaml](PROVENANCE.yaml)。上游未声明开源许可；迁入与再分发依据迁入方确认的作者口头授权，尚无书面许可记录。保留原作者署名。
