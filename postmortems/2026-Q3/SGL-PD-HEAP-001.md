# SGL-PD-HEAP-001: PD 分离偶发失败（CombineMemories 合并 K+V 超过 heap_size）

> 源是结构化调查报告（30KB），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/pillumina/issue-investigation/blob/main/sglang/ascend_npu/2026-07-28_sglang_pd_sdma_npu4_ipc_open_failure.md
**gitcode issue**（fix 跟踪）：https://gitcode.com/Ascend/memfabric_hybrid/issues/347
**时间**：2026-07-23 ~ 2026-07-29
**框架**：SGLang v0.5.10 + memfabric_hybrid v1.0.5
**平台**：Atlas 800I A3 (910C)
**category**：interrupt
**investigation_quality**：high（5 天详查，源码级根因 + 三个修复方案 + 驱动层 pLog 确认）

## 结构化 case

已手工播种到 `knowledge/inference/sglang/SGL-PD-HEAP-001.yaml`（Tier 2）。

## 一句话根因

CombineMemories 将物理相邻的 K+V 半区合并为 19.13 GiB → 驱动 `halShmemCreateHandle` 校验 size(19.13G) > heap_size(17.0G) 拒绝 → decode 偶发崩溃。非必现：page_num ±1（torch.npu.mem_get_info 整数除法精度）→ K end 是否等于 V base → 是否合并。
