# COMMON-FSDP-OFFLOAD-SYNC-NAN: MOVA 训练 NaN（FSDP offload 流同步/搬运时序）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_mova_model_nan_analysis.md
**时间**：2026-09-09（沉淀）
**框架**：cross（accelerate + FSDP + offload）
**category**：precision
**investigation_quality**：high（L0 dump → mix dump → 调用栈 → monitor → 手动打印 → 加同步验证）
**namespace 建议**：common/

## 结构化 case

`knowledge/common/precision/COMMON-FSDP-OFFLOAD-SYNC-NAN.yaml`（已转正 Tier 2）

## 一句话根因

offload 场景下 FSDP post_backward / foreach_reduce 前后、以及 `.to()` 前后的数据搬运时序异常（缺流同步），导致权重更新阶段 NaN 并在 DDP 域传播。

## 弯路与级联

- **判据**：「加同步后问题消失」——区分同步/时序问题与算子数值问题。
- **工具组合**：L0 dump 定到 step → mix dump 定位算子 → monitor 看模块聚合 shape 异常 → 手动打印确认 FSDP post_backward 位置。
