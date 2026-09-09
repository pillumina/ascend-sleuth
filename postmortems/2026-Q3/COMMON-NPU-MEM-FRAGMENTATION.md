# COMMON-NPU-MEM-FRAGMENTATION: 短序列场景显存碎片持续累积（GE 侧 + 框架侧），非典型代码泄漏

> 源是结构化文档（msprof 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprof/blob/tag_MindStudio_26.2.0.B060_001/docs/zh/best_practices/memory_fragmentation.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Host/Device 侧性能，与框架无关）
**category**：performance
**investigation_quality**：high（上游官方案例，含定位链与根因结论）
**namespace 建议**：common/performance/

## 结构化 case

`knowledge/common/performance/COMMON-NPU-MEM-FRAGMENTATION.yaml`（已转正 Tier 2）

## 一句话根因

短序列场景显存碎片持续累积（GE 侧 + 框架侧），非典型代码泄漏

- **关键判据**：allocated 基本不涨而 reserved 持续上涨 → 优先按碎片排查（而不是泄漏）。\n- **验证**：开 GE_USE_STATIC_MEMORY=3 + PYTORCH_NPU_ALLOC_CONF=expandable_segments:True 后 reserved 涨幅从约 600MB 降至约 75MB。
