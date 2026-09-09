# COMMON-OP-COMPILE-LATENCY: 未装/不全 ops 包时 aclopCompile 作为保底行为在运行时触发算子编译，额外增加 Host 下发耗时

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/operator_compilation_latency.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-OP-COMPILE-LATENCY.yaml`（已转正 Tier 2）

## 一句话根因

未装/不全 ops 包时 aclopCompile 作为保底行为在运行时触发算子编译，额外增加 Host 下发耗时

- **判据**：api_statistic.csv 中 aclopCompile 频繁 + free 占比偏高（示例 22%）。
