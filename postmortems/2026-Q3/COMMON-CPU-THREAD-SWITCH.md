# COMMON-CPU-THREAD-SWITCH: 系统侧大量与训练无关的后台线程与算子下发线程竞争 CPU → 下发线程频繁非自愿上下文切换

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/cpu_thread_frequent_switching.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-CPU-THREAD-SWITCH.yaml`（已转正 Tier 2）

## 一句话根因

系统侧大量与训练无关的后台线程与算子下发线程竞争 CPU → 下发线程频繁非自愿上下文切换

- **判据**：单卡 Dequeue 最长 7.9s，同期 Device 无算子执行、synchronize 多等 92ms（Host 阻塞，非 Device 计算）。
