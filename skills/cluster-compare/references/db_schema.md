# cluster.db 数据库结构参考

## 概述

`cluster.db` 是 Ascend 集群性能分析工具生成的集群级别性能数据库。存在两种表结构版本：**旧格式**（msprof-analyze 早期版本）和**新格式**（msprof-analyze 26.1.0+），字段名略有差异。

## 旧格式表结构（cluster.db）

### 1. cluster_base_info

集群基础信息，键值对存储。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| key | VARCHAR(50) | 键名（如 ranks/steps/algorithm/dp_size/pp_size/tp_size 等） |
| value | TEXT | 值（JSON 字符串或纯文本） |

**已知键名**：`file_path`、`ranks`、`steps`、`collect_start_time`、`collect_duration`、`stages`、`pp_stages`、`algorithm`、`dp_size`、`pp_size`、`tp_size`、`cp_size`、`ep_size`、`moe_tp_size`、`level`、`parse_status`

### 2. step_statistic_info

Step 级别时间统计，每个 rank 每个 step 一行。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER | 自增主键 |
| rank_id | VARCHAR(50) | Rank ID |
| step_id | VARCHAR(50) | Step ID |
| stage_id | VARCHAR(50) | Stage ID |
| compute_time | DOUBLE | 计算时间（μs） |
| pure_communication_time | DOUBLE | 未重叠通信时间（μs） |
| overlap_communication_time | DOUBLE | 重叠时间（μs） |
| communication_time | DOUBLE | 总通信时间（μs） |
| free_time | DOUBLE | 空闲时间（μs） |
| stage_time | DOUBLE | Stage 总时间（μs） |
| bubble_time | DOUBLE | Bubble 时间（μs） |
| pure_communication_exclude_receive_time | DOUBLE | 排除接收的未重叠通信时间（μs） |
| preparing | DOUBLE | 准备时间（μs） |
| dp_index | INTEGER | 数据并行索引 |
| pp_index | INTEGER | 流水线并行索引 |
| tp_index | INTEGER | 张量并行索引 |

### 3. communication_time_info

通信时间统计。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER | 自增主键 |
| iteration_id | VARCHAR(50) | 迭代 ID |
| stage_id | VARCHAR(200) | Stage ID |
| rank_id | VARCHAR(50) | Rank ID |
| op_name | VARCHAR(100) | 通信算子名 |
| op_suffix | VARCHAR(100) | 算子后缀 |
| start_time | INTEGER | 开始时间戳 |
| elapse_time | DOUBLE | 总耗时（μs） |
| synchronization_time_ratio | DOUBLE | 同步时间比例 |
| synchronization_time | DOUBLE | 同步时间（μs） |
| transit_time | DOUBLE | 传输时间（μs） |
| wait_time_ratio | DOUBLE | 等待时间比例 |
| wait_time | DOUBLE | 等待时间（μs） |
| idle_time | DOUBLE | 空闲时间（μs） |

### 4. communication_bandwidth_info

通信带宽详情。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER | 自增主键 |
| iteration_id | VARCHAR(50) | 迭代 ID |
| stage_id | VARCHAR(200) | Stage ID |
| rank_id | VARCHAR(50) | Rank ID |
| op_name | VARCHAR(100) | 通信算子名 |
| op_suffix | VARCHAR(100) | 算子后缀 |
| transport_type | VARCHAR(20) | 传输类型（HCCS/RDMA/SDMA/SIO） |
| bandwidth_size | DOUBLE | 带宽大小 |
| bandwidth_utilization | DOUBLE | 带宽利用率 |
| large_package_ratio | DOUBLE | 大包比例 |
| size_distribution | JSON | 大小分布（JSON） |
| transit_size | DOUBLE | 传输大小（MB） |
| transit_time | DOUBLE | 传输时间（μs） |

### 5. communication_matrix

通信矩阵，rank 间通信详情。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER | 自增主键 |
| group_id | VARCHAR(100) | 通信组 ID |
| iteration_id | VARCHAR(50) | 迭代 ID |
| op_name | VARCHAR(100) | 通信算子名 |
| op_sort | VARCHAR(100) | 算子排序 |
| group_name | VARCHAR(100) | 通信组名 |
| src_rank | VARCHAR(50) | 源 Rank |
| dst_rank | VARCHAR(50) | 目标 Rank |
| transport_type | VARCHAR(50) | 传输类型 |
| transit_size | DOUBLE | 传输大小（MB） |
| transit_time | DOUBLE | 传输时间（μs） |
| bandwidth | DOUBLE | 带宽（GB/s） |

### 6. group_id

通信组映射信息。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| id | INTEGER | 自增主键 |
| rank_set | VARCHAR(100) | Rank 集合 |
| type | VARCHAR(50) | 类型（collective/p2p） |
| group_id_hash | VARCHAR(100) | 通信组 ID 哈希 |
| group_id | VARCHAR(100) | 通信组 ID |
| pg_name | VARCHAR(50) | 进程组名 |

## 新格式表结构（cluster_communication_analyzer.db）

### ClusterStepTraceTime

| 字段名 | 类型 | 说明 |
|--------|------|------|
| step | TEXT | Step 名称 |
| type | TEXT | 类型（rank/stage） |
| index | TEXT | Rank 索引 |
| computing | REAL | 计算时间（μs） |
| communication_not_overlapped | REAL | 未重叠通信时间（μs） |
| overlapped | REAL | 重叠时间（μs） |
| communication | REAL | 总通信时间（μs） |
| free | REAL | 空闲时间（μs） |
| stage | REAL | Stage 总时间（μs） |
| bubble | REAL | Bubble 时间 |
| communication_not_overlapped_and_exclude_receive | REAL | 排除接收的未重叠通信 |
| preparing | REAL | 准备时间 |

### ClusterCommunicationTime

| 字段名 | 类型 | 说明 |
|--------|------|------|
| step | TEXT | Step 名称 |
| rank_id | INTEGER | Rank ID |
| hccl_op_name | TEXT | HCCL 操作名 |
| group_name | TEXT | 通信组名 |
| start_timestamp | REAL | 开始时间戳 |
| elapsed_time | REAL | 总耗时（μs） |
| transit_time | REAL | 传输时间（μs） |
| wait_time | REAL | 等待时间（μs） |
| synchronization_time | REAL | 同步时间（μs） |
| idle_time | REAL | 空闲时间（μs） |
| synchronization_time_ratio | REAL | 同步时间比例 |
| wait_time_ratio | REAL | 等待时间比例 |

### ClusterCommunicationBandwidth

| 字段名 | 类型 | 说明 |
|--------|------|------|
| step | TEXT | Step 名称 |
| rank_id | INTEGER | Rank ID |
| hccl_op_name | TEXT | HCCL 操作名 |
| group_name | TEXT | 通信组名 |
| band_type | TEXT | 带宽类型（HCCS/RDMA/SDMA/SIO） |
| transit_size | REAL | 传输大小（MB） |
| transit_time | REAL | 传输时间（μs） |
| bandwidth | REAL | 带宽（GB/s） |
| large_packet_ratio | REAL | 大包比例 |
| package_size | REAL | 包大小 |
| count | INTEGER | 计数 |
| total_duration | REAL | 总持续时间 |

### ClusterCommunicationMatrix

| 字段名 | 类型 | 说明 |
|--------|------|------|
| step | TEXT | Step 名称 |
| hccl_op_name | TEXT | HCCL 操作名 |
| group_name | TEXT | 通信组名 |
| src_rank | REAL | 源 Rank |
| dst_rank | REAL | 目标 Rank |
| transport_type | TEXT | 传输类型 |
| op_name | TEXT | 操作名 |
| transit_size | REAL | 传输大小（MB） |
| transit_time | REAL | 传输时间（μs） |
| bandwidth | TEXT | 带宽（GB/s） |

### CommunicationGroupMapping

| 字段名 | 类型 | 说明 |
|--------|------|------|
| type | TEXT | 类型（collective/p2p） |
| rank_set | TEXT | Rank 集合 |
| group_name | TEXT | 通信组名 |
| group_id | TEXT | 通信组 ID |
| pg_name | TEXT | 进程组名 |

## 字段映射表（旧格式 → 新格式）

| 旧格式字段 | 新格式字段 | 说明 |
|-----------|-----------|------|
| `step_statistic_info` | `ClusterStepTraceTime` | 表名映射 |
| `compute_time` | `computing` | 计算时间 |
| `pure_communication_time` | `communication_not_overlapped` | 未重叠通信 |
| `overlap_communication_time` | `overlapped` | 重叠时间 |
| `communication_time` | `communication` | 总通信 |
| `free_time` | `free` | 空闲 |
| `stage_time` | `stage` | Stage 总时间 |
| `rank_id` | `index`（当 type='rank'） | Rank 标识 |
| `step_id` | `step` | Step 标识 |

## 带宽类型说明

| 类型 | 说明 | 典型带宽 |
|-----|------|---------|
| HCCS | 华为芯片间高速互联（节点内） | 30-120 GB/s |
| RDMA | 远程直接内存访问（跨节点） | 10-25 GB/s |
| SDMA | 系统 DMA（节点内） | 50-100 GB/s |
| SIO | 串行 IO | 50-100 GB/s |

## HCCL 操作类型

| 操作类型 | 说明 |
|---------|------|
| allReduce | 全规约操作 |
| allGather | 全收集操作 |
| reduceScatter | 规约散射操作 |
| broadcast | 广播操作 |
| batchSendRecv | 批量发送接收 |
| alltoall | 全对全通信 |

## 自动适配策略

提取数据时按以下顺序检测表和字段：
1. 检查表是否存在：`SELECT name FROM sqlite_master WHERE type='table'`
2. 检查列名：`PRAGMA table_info(table_name)`
3. 根据检测结果选择对应的字段名
4. 若关键字段缺失则跳过该表并记录警告
