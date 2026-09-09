# COMMON-GT-LABELS-EMPTY-NAN: mmdetection 换数据集后 NaN（gt_labels 空 → embedding 反向 NaN）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_mmdetection_training_nan_localization.md
**时间**：2026-09-09（沉淀）
**框架**：cross（根因在数据侧 + 早期 CANN）
**category**：precision
**investigation_quality**：high（确定性控制 → 通信排查 → 数据流分析）
**namespace 建议**：common/
**novelty**：variant_of COMMON-EMBEDDING-BWD-EMPTY（同机制：embedding 输入为空 → 反向 NaN；差异在触发源与处置）

## 结构化 case

已并入 `knowledge/common/precision/COMMON-EMBEDDING-BWD-EMPTY.yaml`（作为触发源 B）——本文件保留为 Tier 3 来源记录

## 一句话根因

数据集分类标注越界 → gt_labels 为空 → embedding 输入为空 → 早期 CANN（<8.0.0）embedding 反向 NaN。

## 弯路与级联

- **无标杆场景**：本 case 没有标杆环境可对照，靠确定性控制 + 通信排查 + 数据流分析收敛。
- **双修**：CANN 升级（8.0.0+ 已修复）与数据集标注修复需同时做——只做一项仍可能复现。
- **家族关系**：与 COMMON-EMBEDDING-BWD-EMPTY 同机制不同触发源（dsp 切分 vs gt_labels 空），groom 可考虑归并或互链。
