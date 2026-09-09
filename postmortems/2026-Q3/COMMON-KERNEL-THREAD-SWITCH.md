# COMMON-KERNEL-THREAD-SWITCH: 业务创建大量轻量短时线程 + 默认调度配置未做亲和性绑定 → 线程频繁跨核调度，上下文切换开销激增

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/kernel_thread_switching.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-KERNEL-THREAD-SWITCH.yaml`（已转正 Tier 2）

## 一句话根因

业务创建大量轻量短时线程 + 默认调度配置未做亲和性绑定 → 线程频繁跨核调度，上下文切换开销激增

- **判据**：全局上下文切换暴涨 + 内核态 CPU 占比高 + 就绪队列堆积。
