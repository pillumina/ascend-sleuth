# COMMON-FA-RACE-DETERMINISM: 80 卡训练确定性无法固定（CANN FA 算子内部数据竞争）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_80_card_large_model_training_determinism_troubleshooting.md
**时间**：2026-09-09（沉淀）
**框架**：cross（根因在 CANN 算子内部）
**category**：precision
**investigation_quality**：high（链路追踪 → 单算子复现 → 根因分析 + 修复包验证）
**namespace 建议**：common/

## 结构化 case

`knowledge/common/precision/COMMON-FA-RACE-DETERMINISM.yaml`（已转正 Tier 2）

## 一句话根因

CANN 8.1.0 RC1 的 Flash Attention 算子内部在数据搬迁操作前后缺少同步机制（数据竞争），多卡/高并发下读写时序不确定 → 结果不可复现；8.0.0 RC4 无此问题。

## 弯路与级联

- **关键观察**：全量 dump 会让问题不复现（采集行为影响执行时序）→ 应降采集粒度（如 L1）或缩小模型规模。
- **判定手法**：`ASCEND_LAUNCH_BLOCKING=1` 强制算子串行下发 → 消失即算子间并发竞争；算子内部大量加 flag 等待 → 消失即算子内竞争；单算子脚本 + mssanitizer 定位内存竞争。
