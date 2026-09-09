# COMMON-IRQ-IMBALANCE: A+K 默认中断调度未优化，核心业务中断过度集中在个别 CPU 核，长期抢占业务线程时间片

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/irq_interruption.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-IRQ-IMBALANCE.yaml`（已转正 Tier 2）

## 一句话根因

A+K 默认中断调度未优化，核心业务中断过度集中在个别 CPU 核，长期抢占业务线程时间片

- **判据**：排除常规问题后，部分 CPU 核中断次数异常偏高。
