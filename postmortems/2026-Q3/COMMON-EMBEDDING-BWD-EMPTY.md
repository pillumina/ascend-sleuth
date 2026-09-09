# COMMON-EMBEDDING-BWD-EMPTY: FSDP 全参微调 Loss NaN（embedding 反向空输入返回未初始化数据）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_multimodal_training_nan_analysis.md
**时间**：2026-09-09（沉淀）
**框架**：cross（根因在 aclnn 算子空输入边界）
**category**：precision
**investigation_quality**：high（首个 NaN 定位到 wte 层 → dump 输入 shape → 算子空输入行为 → 改算子重出包验证）
**namespace 建议**：common/（框架无关；注：common/ 目前为空，见 triage-tree 头注）

## 结构化 case

`knowledge/common/precision/COMMON-EMBEDDING-BWD-EMPTY.yaml`（已转正 Tier 2）

## 一句话根因

开启 dsp 后部分卡无 token 输入，embedding 反向输入为空（[0, 4096]）时 aclnnEmbeddingDenseBackward 直接返回默认内存中的未初始化数据，被当作梯度参与计算 → loss NaN。

## 弯路与级联

- **触发条件**：依赖 dsp 切分后该卡是否分到 token，随机数据有几率复现（非必现）。
- **首个 NaN 位置**：wte（embedding）层梯度 —— 首个 NaN 落在 embedding 反向时，优先查输入形态而非算子精度。
