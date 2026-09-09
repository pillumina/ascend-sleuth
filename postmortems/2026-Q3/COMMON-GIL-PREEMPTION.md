# COMMON-GIL-PREEMPTION: Python GIL 单时刻单线程 + 工作线程长期持锁不释放 → 其他线程抢锁失败、调度失衡

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/gil_lock_preemption.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-GIL-PREEMPTION.yaml`（已转正 Tier 2）

## 一句话根因

Python GIL 单时刻单线程 + 工作线程长期持锁不释放 → 其他线程抢锁失败、调度失衡

- **判据**：无算子/数据/硬件问题，但多核利用率偏低且业务大量多线程。
