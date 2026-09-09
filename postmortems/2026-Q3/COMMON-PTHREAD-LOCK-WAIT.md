# COMMON-PTHREAD-LOCK-WAIT: 锁粒度过大——整个数据预处理在临界区内，平均持锁 8ms，worker 无法入队形成串行化

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/pthread_lock_wait.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-PTHREAD-LOCK-WAIT.yaml`（已转正 Tier 2）

## 一句话根因

锁粒度过大——整个数据预处理在临界区内，平均持锁 8ms，worker 无法入队形成串行化

- **判据**：NPU 利用率降低、Device 空闲等 Host 下发。
