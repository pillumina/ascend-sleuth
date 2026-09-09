# COMMON-SYSCALL-THP: Checkpoint 的 30GB D2H 拷贝长期占用 Host 内存触发内核内存回收/重整，THP 后台合并进一步抢

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/syscall_high_latency.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-SYSCALL-THP.yaml`（已转正 Tier 2）

## 一句话根因

Checkpoint 的 30GB D2H 拷贝长期占用 Host 内存触发内核内存回收/重整，THP 后台合并进一步抢占 CPU

- **判据**：前 500 步正常、保存 Checkpoint 后降 20%+ 再缓慢恢复，malloc/free 耗时增长。
