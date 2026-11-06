# CPU Host 性能分析 Skill（cpu-host-performance）

面向训练/推理场景的 **Host 侧 CPU 根因自动化分析**：解析 Linux ftrace/trace-cmd 采集数据，自动计算调度延迟、IRQ/SoftIRQ、CPU 利用率/频率等指标，输出**全中文**诊断报告（Markdown + 离线 HTML）。客户只负责采集，Skill 负责分析；报告先给结论、结论必有证据。

## 功能特性

- **多格式健壮解析**：tar.gz / zip / 目录 / 裸 ftrace 文本 / trace-cmd report 文本 / Chrome Tracing / Perfetto JSON，自动探测无需人工转换
- **指标全覆盖**：CPU 利用率与均衡、调度延迟（avg/p50/p95/p99/max）、硬中断、软中断（含 NET_RX 等 vec 归类）、CPU 频率与 Idle/C-state、任务运行时长、迁移/抢占、wakeup 频率
- **组合式诊断**：拒绝"单指标定罪"，10 类具体诊断 + 证据不足兜底，每条结论带置信度（HIGH/MEDIUM/LOW）
- **全中文报告**：每个指标附"它是什么"的中文释义；报告 14 节固定结构，先结论后证据再建议
- **零依赖离线可用**：Python 3.7+ 仅标准库；HTML 报告为单文件 inline SVG，无 CDN/外部 JS
- **采集脚本独立**：单文件 bash 脚本，仅依赖 bash + ftrace + 核心 utils，不联网、不装包、结束自动恢复 tracing 配置

## 快速开始

环境要求：Python 3.7+（仅标准库），无第三方依赖。

```bash
# 在本 Skill 根目录执行
python3 -m analyzer analyze <输入路径> --output-dir <输出目录>
# 简洁模式（不打印过程日志）
python3 -m analyzer analyze <输入路径> -o <输出目录> -q
# 亦可直接运行入口脚本（任意目录均可）
python3 analyzer/analyze_cpu_trace.py <输入路径> -o <输出目录>
```

输出到指定目录：

- `report.md` — 中文 Markdown 报告
- `hostbound_report.html` — 固定名称的单文件离线 HTML（inline SVG 图表，双击浏览器即可打开），内容与 MD 版一致

分析器运行结束后会在终端打印 **Host 状态**（CRITICAL / WARNING / DEGRADED / HEALTHY / UNKNOWN）与问题清单。

## 支持的输入格式

| 输入类型 | 说明 |
|----------|------|
| `cpu_trace_*.tar.gz` | 本 Skill 采集脚本产物（trace.txt + 系统快照），信息最全 |
| 任意 `.tar.gz` / `.zip` | 内含 ftrace 文本即可，自动在包内定位 |
| 目录 | 递归扫描目录内的 trace 文件与快照 |
| 裸 ftrace 文本 | `cat /sys/kernel/debug/tracing/trace` 的原样输出 |
| trace-cmd report 文本 | `trace-cmd report` 的输出重定向文本 |
| Chrome Tracing / Perfetto JSON | 事件数组格式（含 `ph`/`ts`/`name` 字段） |

精简模式（仅 sched_switch）与全量模式 trace 均可分析；缺失维度会在报告"分析限制"中明确说明，不会强行编造结论。

## 采集脚本使用（发给客户）

```bash
sudo bash cpu_trace_collect.sh --duration 30          # 默认 30s 全量模式
sudo bash cpu_trace_collect.sh --duration 10 -m       # 精简模式，仅 sched_switch
sudo bash cpu_trace_collect.sh -t 60 -c 0-47          # 指定时长与 CPU 列表
```

产物 `cpu_trace_YYYYMMDD_HHMMSS.tar.gz` 直接回传即可。脚本不修改业务进程，采集结束自动恢复 tracing 原配置（onoff/tracing_on/当前_tracer）。

导出提速：脚本并行读取各 CPU 独立缓冲区（`per_cpu/cpu*/trace`）后拼接为 trace.txt，多核机器上比读取全局 trace 明显更快（核心越多提速越接近线性）；分析器加载后会按时间戳全局稳定排序，分析结果与传统 `cat trace` 方式完全一致。

## 报告结构（14 节固定）

1. Executive Summary（结论摘要：Host 状态、核心问题、影响、方案）
2. 问题证据总表
3. 问题详情（每问题：现象 → 证据 → 阈值与解释 → 根因假设 → 建议）
4. CPU 总体状态
5. CPU Core Balance（各核心负载）
6. Scheduler 调度分析
7. IRQ / SoftIRQ 分析
8. CPU Frequency / Idle 分析
9. Task / Thread 分析
10. Affinity / NUMA 分析
11. 时间窗口分析
12. 根因判断
13. 优化建议（按优先级，含具体命令）
14. 数据说明与指标解释（数据概况、分析限制、指标/事件中文释义）

骨架模板见 `templates/report_template.md`（供数据缺失时人工撰写或结构定制）；真实样例见 `examples/sample_report.md` 与 `examples/sample_report.html`。

HTML 报告左侧带有固定导航栏（宽屏可见）：列出全部 14 节，点击平滑跳转，滚动时自动高亮当前章节；窄屏（≤1024px）与打印时自动隐藏，不影响排版与导出。

## 诊断类型清单

| 诊断类型 | 触发条件（组合判断） | 典型处置方向 |
|----------|----------------------|--------------|
| `CPU_SATURATION` | CPU 整体高利用率 + runnable 堆积 | 降载 / 扩容 / 优化热点线程 |
| `SCHEDULER_CONTENTION` | 高负载 + 调度延迟抬升 | 调整优先级 / 减少并发 / 绑核 |
| `CPU_IMBALANCE` | 总利用率中等但个别核打满、其余空闲 | 排查 IRQ affinity / 任务绑核 |
| `IRQ_HOTSPOT` | 硬中断耗时集中单核 | 调整 IRQ 亲和性（irqbalance） |
| `SOFTIRQ_HOTSPOT` | 软中断（如 NET_RX）集中少数核 | RPS/XPS 分流、网卡多队列 |
| `SCHEDULER_LATENCY` | 调度延迟 p95/p99 超阈值 | 降低 runnable 队列长度 |
| `CPU_FREQUENCY_LOW` | 高负载核长期低频（低频样本占比≥阈值） | governor 改 performance、查温控 |
| `TASK_MIGRATION_HIGH` | 任务迁移频率过高 | 绑核 / CPU affinity 优化 |
| `TASK_AFFINITY_PROBLEM` | 任务集中在少数饱和核上运行且存在空闲核（绑核受限风险） | 检查 taskset/cgroup cpuset，迁移到空闲核 |
| `NUMA_RISK` | 多 NUMA 节点拓扑 + 任务跨节点运行或迁移频繁（风险提示，非根因） | numactl 节点内绑定，补采内存侧证据 |
| `HOST_NOT_BOTTLENECK` | CPU 空闲但业务差 | 明确 CPU 不是主瓶颈，勿强行归因 |
| `CPU_IDLE_EXCESSIVE` | 多数核心空闲但存在热点核 | 负载均衡 / 队列分布检查 |
| `INSUFFICIENT_EVIDENCE` | 采集数据维度有限 | 兜底声明，置信度不得标 HIGH |

## 置信度体系

- **HIGH**：多指标交叉印证（如利用率 + runnable + 延迟同时超阈）
- **MEDIUM**：单指标明确超阈或旁证支持
- **LOW**：仅弱关联证据；证据不足时统一输出 `INSUFFICIENT_EVIDENCE`，绝不冒充 HIGH

## 目录结构

```text
cpu-host-performance/
├── SKILL.md                      # Agent 使用规范（何时用/如何用/分析逻辑要求）
├── README.md                     # 本文件
├── scripts/cpu_trace_collect.sh  # 独立采集脚本（可单独发给客户）
├── analyzer/                     # 分析包（含 CLI 入口，python3 -m analyzer analyze <path>）
│   ├── __init__.py / __main__.py # 包标识 + python -m analyzer 入口
│   ├── analyze_cpu_trace.py      # CLI 入口与分析主流程编排
│   ├── parser.py                 # 多格式健壮解析（tar/zip/目录/文本/JSON）
│   ├── metrics.py                # 指标计算 + 中文释义表 METRIC_EXPLANATIONS
│   ├── diagnosis.py              # 诊断规则与置信度
│   ├── report.py                 # Markdown 报告生成
│   └── report_html.py            # 离线 HTML 报告（inline SVG）
├── templates/                    # 报告骨架模板（人工撰写/定制用）
└── examples/                     # 真实端到端示例报告（MD + HTML）
```

## 设计要点

- **解析健壮性**：行格式兼容 `<idle>-0`、`bash-1234 [005]` 等变体；`cpu_idle` 的 state=4294967295 识别为 idle 退出；中断配对以 `(CPU, 中断号)` 复合键支持同核多中断交错；exit 缺编号时按最早 pending 兜底配对
- **单位自动识别**：频率原始值按量级启发式换算（≥1e7 视为 Hz、≥1e3 视为 kHz），报告统一显示 MHz
- **buffer 溢出感知**：`overrun > 0` 时在报告中标注 trace 可能不完整，结论置信度下调
- **未知事件兜底**：未收录事件按 TASK/IRQ/未知事件给兜底释义并标注"未收录事件"

## 常见问题

**Q: 需要root权限吗？**
A: 采集需要（ftrace 挂载在 debugfs/tracefs 下）；分析在任意机器离线完成，无需 root。

**Q: 采集多久合适？**
A: 问题复现周期内取 10–60s。太短覆盖不到问题窗口，太长 ring buffer 可能溢出（报告会提示）。

**Q: 精简模式（-m）能用吗？**
A: 能，但仅有调度/利用率维度，IRQ/频率/idle 分析会标注不可用，整体结论降级。

**Q: HTML 报告能离线打开吗？**
A: 能。单文件、inline SVG、零外部依赖，直接拷给客户或贴邮件均可。

**Q: 能判断 NUMA 吗？**
A: trace 内有足够跨核迁移/节点信息才判断，否则明确写"证据不足"。

## 限制说明

- 仅分析 Host CPU 侧，不覆盖 NPU/HCCL 内部性能（但可佐证"Host 慢导致 NPU 等待"）
- 频率单位换算为启发式，极端平台数值可能需人工核对（相对比较不受影响）
- 单次 trace 时间窗有限，长周期/低频抖动问题建议多时段采集多次分析
