# COMMON-TP-SEED-UNSYNCED: TP8 推理第 3 张图必花（TP 组内随机种子未同步）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_qwen_image_edit_tp8_distorted_image_localization.md
**时间**：2026-09-09（沉淀）
**框架**：cross（Megatron 多卡推理，框架未登记 → common/）
**category**：precision
**investigation_quality**：high（TP1 vs TP8 分级可视化切分合并比对 → 逐卡节点信息 → 代码回溯到随机数生成）
**namespace 建议**：common/

## 结构化 case

`knowledge/common/precision/COMMON-TP-SEED-UNSYNCED.yaml`（已转正 Tier 2）

## 一句话根因

TP8 下未控制同一 TP 组内各卡输入一致，仅依赖初始随机种子；0 卡作为通信主卡 random 调用次数与其他卡不同 → 组内随机数不同 → 输出不同 → 拼接后花图。

## 弯路与级联

- **判据**：首个 module 是**未做 TP 切分**的层，多卡统计值本应完全相同——不同即说明问题在输入源（随机性）而非该层算子。
- **手法**：`msprobe graph_visualize -tp tp8_data -gp tp1_data` 做跨切分比对 + tensorboard 看节点详情。
