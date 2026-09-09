# COMMON-PY-GC-LATENCY: Python 循环引用累积触发自动 GC（Stop-The-World），阻塞整个进程

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/python_gc_high_latency.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-PY-GC-LATENCY.yaml`（已转正 Tier 2）

## 一句话根因

Python 循环引用累积触发自动 GC（Stop-The-World），阻塞整个进程

- **判据**：step 耗时周期性抖动（示例 2770→2900ms）且跨节点高度一致。
