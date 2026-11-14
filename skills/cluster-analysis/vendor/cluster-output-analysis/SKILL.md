---
name: "cluster-output-analysis"
description: "Ascend cluster analysis output report generator. Invoke when the input contains only a cluster_analysis_output directory (DB or TEXT format, no card dirs): extract data, generate a standalone single-cluster or two-cluster compare HTML/MD report."
---

# Ascend 集群性能分析与比对

面向华为昇腾 NPU 集群 profiling 数据的性能分析工具。支持从 `cluster_analysis_output` 目录（DB 或 TEXT 格式）提取数据，生成全景数据总结 MD 文件，并根据用户需求生成**单集群整体分析**或**双集群比对分析** HTML 报告。

> 定位说明：当上级技能（cluster-analysis）检测到输入**仅含 `cluster_analysis_output`（无任何卡目录）**时，只调用本子技能产出独立报告，不生成完整 HTML 总报告。

## 触发场景

当用户出现以下意图时触发：
- "分析集群数据"、"集群性能报告"、"cluster analysis"
- "比对两个集群"、"对比正常和异常集群"、"cluster compare"
- 用户提供 `cluster_analysis_output` 目录路径或 `cluster.db` 文件路径
- 用户提到 `ClusterStepTraceTime`、`ClusterCommunicationTime` 等表名

## 核心工作流（必须严格遵循）

### 阶段 1: 数据识别与全景提取

**目标**：解析集群数据（DB 或 TEXT），提取全量信息，生成 MD 总结文件保存到原始数据文件夹。

#### 步骤 1.1: 识别数据格式

检查用户提供的路径：
- **DB 模式**：路径下存在 `cluster.db`（旧格式）或 `cluster_analysis_output/cluster_communication_analyzer.db`（新格式）
- **TEXT 模式**：路径下存在 `cluster_analysis_output/cluster_step_trace_time.csv` + `communication_group.json`
- **混合模式**：同时存在 DB 和 TEXT 文件（优先使用 DB）

#### 步骤 1.2: 提取全景数据

**DB 模式 SQL 查询**（参考 `references/db_schema.md` 获取完整表结构）：

```sql
-- 1. 集群基础信息
SELECT key, value FROM cluster_base_info;
-- 或新格式: SELECT * FROM CommunicationGroupMapping;

-- 2. Step 时间全景（核心表）
SELECT step_id, AVG(compute_time), AVG(pure_communication_time),
       AVG(overlap_communication_time), AVG(communication_time),
       AVG(free_time), AVG(stage_time), AVG(bubble_time), AVG(preparing)
FROM step_statistic_info GROUP BY step_id;
-- 新格式表名: ClusterStepTraceTime, 字段名略有不同

-- 3. 各 Rank 时间明细
SELECT rank_id, step_id, compute_time, communication_time, free_time, stage_time
FROM step_statistic_info ORDER BY step_id, rank_id;

-- 4. 通信时间汇总（如有数据）
SELECT hccl_op_name, AVG(elapsed_time), AVG(transit_time), AVG(wait_time),
       AVG(synchronization_time), AVG(idle_time)
FROM ClusterCommunicationTime GROUP BY hccl_op_name;

-- 5. 通信带宽汇总（如有数据）
SELECT band_type, AVG(bandwidth), AVG(transit_size), AVG(transit_time)
FROM ClusterCommunicationBandwidth GROUP BY band_type;

-- 6. 通信矩阵（如有数据）
SELECT src_rank, dst_rank, transport_type, AVG(bandwidth), AVG(transit_size)
FROM ClusterCommunicationMatrix GROUP BY src_rank, dst_rank, transport_type;

-- 7. Rank/Host 总数
SELECT COUNT(DISTINCT rankId) FROM RankDeviceMap;
SELECT COUNT(DISTINCT hostUid) FROM HostInfo;
```

**TEXT 模式文件解析**（参考 `references/text_schema.md`）：
- 读取 `cluster_step_trace_time.csv`：解析 Step/Type/Index/Computing/Communication/Free/Stage 等列
- 读取 `communication_group.json`：解析 collective/p2p 通信组信息，提取 rank 列表作为基础信息
- 读取 `cluster_communication.json`（如有）：解析通信算子耗时统计，提取 Top10 算子的 elapsed/transit/wait/sync 时间
- 读取 `cluster_communication_matrix.json`（如有）：解析 4 层嵌套 JSON 通信矩阵，提取 src_rank/dst_rank/transport_type/bandwidth/transit_size，按传输类型（LOCAL/HCCS/RDMA）聚合带宽
- **路径检测**：支持两种路径 — `data_dir/cluster_step_trace_time.csv`（直接是输出目录）或 `data_dir/cluster_analysis_output/cluster_step_trace_time.csv`（嵌套结构）
- **单位注意**：TEXT 模式 JSON 中时间单位为 ms（毫秒），DB 模式为 μs（微秒），脚本需自动适配

#### 步骤 1.3: 生成 MD 总结文件

将提取的全部数据组织为结构化 Markdown，保存到**原始数据文件夹**下（如 `{data_dir}/cluster_data_summary.md`）。

MD 文件必须包含以下章节：
1. **集群概览**：Rank 数量、Step 数量、采集时间、并行策略（TP/PP/DP）、算法类型
2. **Step 时间统计**：各 Step 的平均计算/通信/空闲/Stage 时间（μs 和 ms 双单位）
3. **Rank 级明细**：每个 Rank 在各 Step 的时间分解表
4. **负载分布分析**：计算 vs 通信 vs 空闲的占比饼图数据
5. **通信分析**（如有数据）：通信算子耗时 Top10、带宽汇总、通信矩阵
6. **异常 Rank 识别**：偏离均值超过 10% 的 Rank（慢卡/快卡）
7. **数据完整性说明**：哪些表有数据、哪些表为空

**单位换算规则**：原始数据单位为微秒（μs），报告展示时需除以 1000 转换为毫秒（ms）。

### 阶段 2: 生成 HTML 报告

根据用户需求选择报告类型：

#### 报告类型 A: 单集群整体分析报告

**触发**：用户说"分析这个集群"、"生成集群报告"、只提供一个数据路径。

**使用模板**：`templates/cluster_analysis_report.html`

**报告包含**：
1. **KPI 卡片区**：Rank 总数、Step 数、平均 Stage 时间、计算占比、通信占比、空闲占比
2. **Step 耗时趋势图**：各 Step 的 Stage 总耗时趋势线图（ECharts line）
3. **时间分解柱状图**：各 Step 的 Computing/Communication/Free 并排柱状图（ECharts bar）
4. **负载分布饼图**：计算/通信/空闲/重叠占比饼图（ECharts pie）
5. **Rank 耗时热力图**：Rank × Step 的 Stage 时间热力表（HTML table + 颜色梯度）
6. **慢卡识别表**：按 Stage 时间降序排列的 Rank 明细表，高亮偏离均值 >10% 的 Rank
7. **通信算子分析**（如有数据）：Top10 通信算子耗时柱状图、带宽类型对比
8. **优化建议**：基于数据分析的自动化建议（通信主导/计算主导/空闲过高/负载不均）

#### 报告类型 B: 双集群比对分析报告

**触发**：用户提供两个数据路径，或说"比对"、"对比"、"正常 vs 异常"。

**使用模板**：`templates/cluster_compare_report.html`

**比对工作流**：

1. **分别提取两个集群的全景数据**（按阶段 1 步骤对每个集群执行）
2. **计算差异**：
   - 整体差值：ΔStage = Stage_B − Stage_A
   - 一级归因：计算劣化贡献度 = (ΔCompute / ΔStage) × 100%
   - 通信劣化贡献度 = (ΔComm / ΔStage) × 100%
   - 空闲劣化贡献度 = (ΔFree / ΔStage) × 100%
   - 二级算子归因：通信时间差值 Top5 算子
   - 带宽劣化：各 band_type 带宽下降百分比
3. **渲染比对报告**

**报告包含**：
1. **核心 KPI 卡片**：Stage 耗时增幅、通信劣化贡献度、带宽暴跌百分比、集群规模对比
2. **Step 核心耗时对比**：并排柱状图（集群A vs 集群B），按 Step 分组
3. **负载类型转换**：双饼图对比（A 的计算/通信/空闲占比 vs B 的占比）
4. **劣化归因瀑布图**：计算/通信/空闲对总劣化的贡献度分解
5. **通信算子差异 Top10**：表格 + 柱状图，展示耗时差最大的算子
6. **带宽对比柱状图**：各 band_type 的 A vs B 带宽对比
7. **Rank 级差异热力图**：每个 Rank 的 Stage 时间差值
8. **劣化根因总结 & 行动建议**：P0/P1/P2 优先级问题列表

### 阶段 3: 输出与交付

1. MD 总结文件保存到原始数据文件夹（每个集群一份）
2. HTML 报告保存到用户指定输出路径或原始数据文件夹下
3. 向用户展示报告摘要（关键发现 + 数据链接）

## 数据格式兼容

本 skill 必须同时兼容两种数据格式：

| 维度 | DB 模式（旧格式） | DB 模式（新格式） | TEXT 模式 |
|------|------------------|------------------|-----------|
| **DB 文件名** | `cluster.db`（根目录） | `cluster_analysis.db`（cluster_analysis_output/ 下） | 无 DB 文件 |
| **Step 时间表** | `step_statistic_info` | `ClusterStepTraceTime` | `cluster_step_trace_time.csv` |
| **通信时间表** | `communication_time_info` | `ClusterCommunicationTime` | `cluster_communication.json` |
| **通信带宽表** | `communication_bandwidth_info` | `ClusterCommunicationBandwidth` | `cluster_communication_matrix.json`（按传输类型聚合） |
| **通信矩阵表** | `communication_matrix` | `ClusterCommunicationMatrix` | `cluster_communication_matrix.json`（4 层嵌套 JSON） |
| **基础信息表** | `cluster_base_info` | `CommunicationGroupMapping` | `communication_group.json` |
| **字段名差异** | `compute_time` | `computing` | `Computing` |
| **字段名差异** | `communication_time` | `communication` | `Communication` |
| **字段名差异** | `free_time` | `free` | `Free` |
| **字段名差异** | `stage_time` | `stage` | `Stage` |
| **字段名差异** | `rank_id` | `index`（SQL 保留字，需双引号包裹） | `Index` |
| **时间单位** | μs | μs | μs（CSV）/ ms（JSON 通信数据） |
| **路径检测** | `data_dir/cluster.db` | `data_dir/cluster_analysis_output/cluster_analysis.db` | `data_dir/cluster_step_trace_time.csv` 或 `data_dir/cluster_analysis_output/cluster_step_trace_time.csv` |

**字段映射策略**：提取数据时先检查表存在性和列名，自动适配对应字段名。

## 脚本工具

### 数据提取脚本

`scripts/cluster_data_extractor.py`：自动识别数据格式，执行 SQL/CSV 提取，输出 JSON 格式的结构化数据。

```bash
python scripts/cluster_data_extractor.py --data-dir <path> --output <output.json>
```

### 报告生成脚本

`scripts/generate_cluster_report.py`：基于提取的数据生成 HTML 报告。

```bash
# 单集群分析
python scripts/generate_cluster_report.py --mode single --data <data.json> --output report.html

# 双集群比对
python scripts/generate_cluster_report.py --mode compare --data-a <a.json> --data-b <b.json> --output compare.html
```

当脚本不可用时，按照上述工作流手动执行 SQL 查询、计算差异、参考 HTML 模板构造报告。

## HTML 报告设计要求

两份 HTML 模板必须满足：
1. **自包含**：单个 HTML 文件，内联 CSS/JS，无外部依赖（ECharts 通过 CDN 引入）
2. **数据驱动**：模板中使用 `{{占位符}}` 标记数据插入点，脚本替换后生成最终报告
3. **交互式图表**：使用 ECharts 渲染所有图表（柱状图/饼图/线图/热力图）
4. **响应式**：适配不同屏幕宽度
5. **专业视觉**：深色标题栏、卡片式布局、颜色梯度表格、状态标签（正常/警告/严重）
6. **中文界面**：所有标题、标签、描述使用中文

## 注意事项

- 原始数据单位为微秒（μs），展示时转换为毫秒（ms），保留 2 位小数
- 通信表可能为空（如单卡场景或未采集通信数据），报告中需标注"无通信数据"
- 并行策略信息从 `cluster_base_info` 的 `algorithm`/`dp_size`/`pp_size`/`tp_size` 字段或 `profiler_metadata.json` 获取
- 慢卡识别阈值：Stage 时间偏离所有 Rank 均值超过 10% 即标记为异常
- 比对报告中，集群 A 为基准（正常），集群 B 为对比（异常），所有差值 = B − A
