# 进阶分析 Recipe 目录（五大类，23 个正式 + 1 个扩展）

| 类别 | recipe | 介绍 | 输出 |
|------|--------|------|------|
| 拆解对比类 | cluster_time_summary | 集群训练迭代耗时拆解，定位性能瓶颈 | 各 rank 各 step 耗时拆解 CSV |
| 拆解对比类 | cluster_time_compare_summary | 集群维度性能数据对比，支持标杆数据对比（--bp） | step 耗时对比 CSV |
| 拆解对比类 | module_statistic | 自动解析 PyTorch 模型层级结构，精准定位瓶颈 | module 层级耗时 CSV |
| 拆解对比类 | calibrate_npu_gpu | NPU/GPU 性能数据对比校准与瓶颈分析 | 校准对比 CSV |
| 计算类 | compute_op_sum | device 侧计算类算子汇总 | 算子统计 CSV |
| 计算类 | freq_analysis | 使用 AICORE_FREQ 实测频率；不以跨核累计 cycles/平均核时间推算 | 频率统计与逐卡样本 CSV |
| 计算类 | ep_load_balance | MoE 负载信息汇总分析 | 专家负载 CSV |
| 计算类 | computational_op_masking | 算子耗时掩盖计算，分析线性度 | 掩盖分析 CSV |
| 计算类 | operator_mfu | 基于 FLOPs 与 kernel 耗时计算 kernel/module 级 MFU | MFU CSV |
| 通信类 | communication_group_map | 通信域与并行策略呈现 | 通信域映射 CSV |
| 通信类 | communication_time_sum | 通信时间汇总分析 | 通信耗时 CSV |
| 通信类 | communication_matrix_sum | 通信矩阵汇总分析 | 通信矩阵 CSV |
| 通信类 | communication_bandwidth_sum | 通信带宽汇总分析（扩展：随全量执行，未注册 CATEGORIES） | 带宽 CSV |
| 通信类 | hccl_sum | 通信类算子信息汇总（--top_num 设置 TopN） | TopN 通信算子 CSV |
| 通信类 | pp_chart | pp 流水图数据分析与可视化 | 流水线数据 CSV |
| 通信类 | slow_rank | 各 rank 快慢卡影响次数，识别慢卡原因 | 慢卡统计 CSV |
| 通信类 | slow_link | 集群异常耗时算子汇总，识别慢卡 | 异常算子 CSV |
| 通信类 | communication_bottleneck | 长耗时通信算子快慢卡识别，推测 Host&Device 侧成因 | 瓶颈归因 CSV |
| Host下发类 | cann_api_sum | CANN 层 API 汇总 | API 统计 CSV |
| Host下发类 | mstx_sum | MSTX 自定义打点汇总 | 打点统计 CSV |
| Host下发类 | free_analysis | Device 侧大块空闲时间自动分析，识别空闲原因 | 空闲分析 CSV |
| 其他 | export_summary（数据导出类） | 导出各卡 API 统计与 Kernel 详情 | CSV 文件 |
| 其他 | mstx2commop（数据处理类） | MSTX 通信打点转通信算子表格式 | 转换 CSV |
| 其他 | p2p_pairing（数据处理类） | P2P 算子生成全局关联索引 opConnectionId | 关联索引 CSV |

执行纪律：

1. 全量执行；某 recipe 数据缺失时输出"数据缺失/不支持"说明并继续，不算失败。
2. 输出统一落在 `<root>/cluster_analysis_output/recipes/<recipe_name>/`。
3. 汇总 `recipes_summary.md/json` 必须覆盖全部 24 项（23 正式 + 1 扩展）与五大类归类，供最终报告"进阶分析"分区集中展示。
4. 单位纪律（db μs / text-CSV μs / text-JSON ms；CSV 列名带单位；报告层统一 ms）统一以 SKILL.md「执行规则」为准，本文件不再重复。

通信等待的精确实例去重与下发归因、计算关键热点、Free 具体区间由 P6a Insight 定位器补充；聚合 recipe 不等同于已经找到根因，输出口径见 references/insight_localization.md。
