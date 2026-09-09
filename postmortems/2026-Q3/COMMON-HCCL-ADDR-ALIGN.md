# COMMON-HCCL-ADDR-ALIGN: 自定义算子用 torch.empty() 分配输出未指定 memory_format，起始地址不满足 HCCL 128 

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/communication_address_misalignment.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-HCCL-ADDR-ALIGN.yaml`（已转正 Tier 2）

## 一句话根因

自定义算子用 torch.empty() 分配输出未指定 memory_format，起始地址不满足 HCCL 128 字节对齐 → HCCL 自动对齐拷贝（约 200ms）

- **判据**：单 step 通信耗时占比 >40%、AllReduce 耗时波动 2~3 倍，而计算侧稳定——不是算子慢，是通信被额外拷贝拖慢。
