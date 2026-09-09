# COMMON-CPU-CACHE-MISS: A+K 平台未做 CPU 资源隔离，业务进程与系统进程抢占 CPU 核 → 上下文切换致 Cache Miss 劣化 →

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/cpu_cache_miss_conflict.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-CPU-CACHE-MISS.yaml`（已转正 Tier 2）

## 一句话根因

A+K 平台未做 CPU 资源隔离，业务进程与系统进程抢占 CPU 核 → 上下文切换致 Cache Miss 劣化 → 下发延迟 → 集群短板

- **判据**：A+K vs A+X 指标全面劣化，但无算子/通信报错 → 指向 Host 侧。
