# TEXT 模式数据结构参考

## 概述

TEXT 模式是 msprof-analyze 集群分析的输出格式之一，当输入数据为 `ascend_pt`/`ascend_ms` 目录（非 DB 格式）时生成。文件位于 `cluster_analysis_output/` 目录下。

## 文件列表

| 文件名 | 说明 | 是否必有 |
|--------|------|---------|
| `cluster_step_trace_time.csv` | Step 级时间统计 | 是 |
| `communication_group.json` | 通信组映射信息 | 是 |
| `cluster_communication.json` | 通信时间分析结果 | 否（TEXT 模式生成） |
| `cluster_communication_matrix.json` | 通信矩阵分析结果 | 否（TEXT 模式生成） |

## cluster_step_trace_time.csv

### 字段定义

| 列名 | 类型 | 说明 |
|------|------|------|
| Step | TEXT | Step 编号 |
| Type | TEXT | 类型（rank/stage） |
| Index | TEXT | Rank 索引（当 Type=rank）或 Stage 元组（当 Type=stage） |
| Computing | REAL | 计算时间（μs） |
| Communication(Not Overlapped) | REAL | 未重叠通信时间（μs） |
| Overlapped | REAL | 重叠时间（μs） |
| Communication | REAL | 总通信时间（μs） |
| Free | REAL | 空闲时间（μs） |
| Stage | REAL | Stage 总时间（μs） |
| Bubble | REAL | Bubble 时间（μs） |
| Communication(Not Overlapped and Exclude Receive) | REAL | 排除接收的未重叠通信（μs） |
| Preparing | REAL | 准备时间（μs） |

### 数据行类型

- **rank 行**：Type=`rank`，Index 为单个 Rank ID，记录该 Rank 在该 Step 的时间分解
- **stage 行**：Type=`stage`，Index 为 Rank 元组（如 `(0,1,2,3)`），记录该 Stage 组的聚合时间（取各 Rank 的最大值）

### 示例数据

```csv
Step,Type,Index,Computing,Communication(Not Overlapped),Overlapped,Communication,Free,Stage,Bubble,Communication(Not Overlapped and Exclude Receive),Preparing
1,rank,4,239637.638,109905.202,14826.532,124731.734,297887.055,647429.75,0.0,109905.202,10671.0
1,rank,7,240226.045,401927.422,238997.843,640925.265,3334.33,648737.25,0.0,401927.422,26926.5
```

### 解析方式

```python
import pandas as pd
df = pd.read_csv('cluster_step_trace_time.csv')
# 仅取 rank 行
rank_df = df[df['Type'] == 'rank']
# 按 Step 分组求均值
summary = rank_df.groupby('Step').agg({
    'Computing': 'mean',
    'Communication': 'mean',
    'Free': 'mean',
    'Stage': 'mean'
})
```

## communication_group.json

### 结构定义

```json
{
  "collective": [
    [0, 1, 2, 3, 4, 5, 6, 7]
  ],
  "p2p": [
    [0, 1],
    [2, 3]
  ],
  "comm_group_parallel_info": [
    {
      "type": "collective",
      "rank_set": [0, 1, 2, 3, 4, 5, 6, 7],
      "group_name": "hccl_world_group",
      "group_id": "xxx",
      "pg_name": "xxx"
    }
  ]
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| collective | List[List[int]] | 集合通信组列表，每个子列表为参与 Rank ID |
| p2p | List[List[int]] | P2P 通信组列表 |
| comm_group_parallel_info | List[Dict] | 通信组与并行策略映射详情 |

### 特殊情况

当集群没有通信数据时，所有字段为空数组：
```json
{"collective": [], "p2p": [], "comm_group_parallel_info": []}
```

## cluster_communication.json（如有）

### 结构定义

```json
{
  "(0,1,2,3)": {
    "1": {
      "hcom_allreduce_xxx@group_name": {
        "rank_id": 0,
        "communication_time_info": {
          "wait_time_ms": 100.5,
          "transit_time_ms": 200.3,
          "synchronization_time_ms": 50.2,
          "start_timestamp": 1234567890
        },
        "communication_bandwidth_info": {
          "HCCS": {
            "transit_time_ms": 200.3,
            "transit_size_mb": 1024.0,
            "bandwidth_gb_s": 5.12
          }
        }
      }
    }
  }
}
```

### 层级结构

1. **第一层**：通信组 Rank 元组（如 `"(0,1,2,3)"`）
2. **第二层**：Step ID（如 `"1"`）
3. **第三层**：通信算子名（格式 `op_name@group_name`）
4. **第四层**：Rank ID + 时间信息 + 带宽信息

## cluster_communication_matrix.json（如有）

### 整体结构（4 层嵌套 JSON）

```
{
  "<通信组Rank列表>": {           // 第1层: 通信组（Rank列表作为key，如 "(0, 1, 2, 3, 5, 6, ..., 31)"）
    "<Step名称>": {               // 第2层: Step名称 (如 "step5")
      "<算子名称>@<组ID>": {      // 第3层: 通信算子名称 + 进程组ID (如 "allreduce-top1@5862276093215481612")
        "<src-dst>": {            // 第4层: 源Rank-目标Rank (如 "0-1", "0-24")
          "字段": 值
        }
      }
    }
  }
}
```

### 各层级说明

| 层级 | Key 示例 | Value 说明 |
|------|---------|-----------|
| 第1层 | `(0, 1, 2, 3, 5, 6, ..., 31)` | 通信组的 Rank 列表（元组形式字符串） |
| 第2层 | `step5` | 采集的 Step 名称 |
| 第3层 | `allreduce-top1@5862276093215481612` | 通信算子名称 + 进程组ID |
| 第4层 | `0-0`, `0-1`, `0-24` | 源Rank-目标Rank 的通信对 |

### 通信对数据字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `Transport Type` | string | 传输类型：LOCAL / HCCS / RDMA |
| `Transit Time(ms)` | float | 传输耗时（毫秒） |
| `Transit Size(MB)` | float | 传输数据量（MB） |
| `Op Name` | string | HCCL 算子名称 |
| `Bandwidth(GB/s)` | float | 带宽（GB/s） |

### 示例数据

```json
{
  "(0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31)": {
    "step5": {
      "allreduce-top1@5862276093215481612": {
        "0-0": {"Transport Type": "LOCAL", "Transit Time(ms)": 0.0685, "Transit Size(MB)": 45.39, "Op Name": "allreduce", "Bandwidth(GB/s)": 662.61},
        "0-1": {"Transport Type": "HCCS", "Transit Time(ms)": 0.289, "Transit Size(MB)": 5.67, "Op Name": "allreduce", "Bandwidth(GB/s)": 19.60},
        "0-24": {"Transport Type": "RDMA", "Transit Time(ms)": 0.545, "Transit Size(MB)": 10.29, "Op Name": "allreduce", "Bandwidth(GB/s)": 18.88}
      }
    }
  }
}
```

### 解析脚本示例

```python
import json

def parse_comm_matrix(json_path):
    """解析通信矩阵 JSON"""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    results = []
    for rank_group, step_data in data.items():
        for step_name, op_data in step_data.items():
            for op_name, pair_data in op_data.items():
                clean_op = op_name.split("@")[0]
                if clean_op.lower().startswith("total"):
                    continue
                for pair_key, metrics in pair_data.items():
                    try:
                        src, dst = pair_key.split("-")
                        src_rank = int(src)
                        dst_rank = int(dst)
                    except (ValueError, AttributeError):
                        continue
                    results.append({
                        'src_rank': src_rank, 'dst_rank': dst_rank,
                        'transport_type': metrics.get('Transport Type', 'UNKNOWN'),
                        'transit_time_ms': float(metrics.get('Transit Time(ms)', 0) or 0),
                        'transit_size_mb': float(metrics.get('Transit Size(MB)', 0) or 0),
                        'bandwidth_gbs': float(metrics.get('Bandwidth(GB/s)', 0) or 0),
                        'op_name': clean_op, 'step': step_name,
                    })
    return results
```

### 可提取的分析指标

1. **按传输类型统计**：LOCAL / HCCS / RDMA 的平均带宽和耗时
2. **Rank 间通信矩阵**：任意两个 Rank 之间的带宽和延迟
3. **跨节点通信 vs 节点内通信**：区分 HCCS（节点内）和 RDMA（跨节点）
4. **通信算子性能排名**：哪个 allreduce/allgather 操作最慢

### 传输类型说明

| 类型 | 说明 | 典型带宽 |
|-----|------|---------|
| LOCAL | 本地传输（同 Rank 内） | 500-700 GB/s |
| HCCS | 华为芯片间高速互联（节点内） | 30-120 GB/s |
| RDMA | 远程直接内存访问（跨节点） | 10-25 GB/s |

## TEXT 与 DB 字段映射

| TEXT (CSV 列名) | DB 旧格式 | DB 新格式 | 说明 |
|----------------|----------|----------|------|
| `Computing` | `compute_time` | `computing` | 计算时间 |
| `Communication(Not Overlapped)` | `pure_communication_time` | `communication_not_overlapped` | 未重叠通信 |
| `Overlapped` | `overlap_communication_time` | `overlapped` | 重叠时间 |
| `Communication` | `communication_time` | `communication` | 总通信 |
| `Free` | `free_time` | `free` | 空闲 |
| `Stage` | `stage_time` | `stage` | Stage 总时间 |
| `Bubble` | `bubble_time` | `bubble` | Bubble |
| `Preparing` | `preparing` | `preparing` | 准备时间 |
| `Step` | `step_id` | `step` | Step 编号 |
| `Index` (当 Type=rank) | `rank_id` | `index` | Rank ID |

## 数据完整性检测

解析 TEXT 数据时应检测：
1. `cluster_step_trace_time.csv` 是否存在且有数据
2. `communication_group.json` 的 `collective`/`p2p` 是否非空
3. `cluster_communication.json` 是否存在（判断是否有通信分析数据）
4. `cluster_communication_matrix.json` 是否存在
5. CSV 中是否有 `stage` 类型行（判断是否有 Stage 聚合数据）
