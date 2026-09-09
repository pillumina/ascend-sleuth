# COMMON-NONZERO-ACCESS-HEAVY: 索引类算子（如 NonZero）属访存密集型，对昇腾达芬奇架构不友好，访存开销主导

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/code_high_latency_function.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-NONZERO-ACCESS-HEAVY.yaml`（已转正 Tier 2）

## 一句话根因

索引类算子（如 NonZero）属访存密集型，对昇腾达芬奇架构不友好，访存开销主导

- **判据**：op_statistic.csv 中该算子占比很大、执行时间长。
