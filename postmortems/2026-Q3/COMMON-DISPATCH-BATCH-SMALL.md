# COMMON-DISPATCH-BATCH-SMALL: 未充分利用硬件（如 batch 过小），算子下发与执行之间出现大量空档

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/dispatch_small_batch_performance.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-DISPATCH-BATCH-SMALL.yaml`（已转正 Tier 2）

## 一句话根因

未充分利用硬件（如 batch 过小），算子下发与执行之间出现大量空档

- **注意**：本案例根因表述偏泛（'资源没用满'），investigation_quality=medium、初始 score 0.55。
