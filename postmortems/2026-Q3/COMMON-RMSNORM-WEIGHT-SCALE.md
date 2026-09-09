# COMMON-RMSNORM-WEIGHT-SCALE: 加载权重后重复训练 Loss/grad_norm 差异偏大（RMSNorm 权重数值异常放大）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_gemma_retrain_loss_diff_analysis.md
**时间**：2026-09-09（沉淀）
**框架**：cross（结论明确「非昇腾软件栈问题」）
**category**：precision
**investigation_quality**：high（可视化溢出检测定位到 RMSNorm 反向 high level + 前向 dump 统计值对比 + 层间放大趋势）
**namespace 建议**：common/（框架无关；注：common/ 目前为空，见 triage-tree 头注）

## 结构化 case

`knowledge/common/precision/COMMON-RMSNORM-WEIGHT-SCALE.yaml`（已转正 Tier 2）

## 一句话根因

加载的 RMSNorm 权重数值异常放大（每经一层约放大百倍，深层尤甚），放大了确定性计算误差，导致两遍训练 Loss/grad_norm 差异偏大 —— 根因不在昇腾软件栈。

## 弯路与级联

- **入口特征**：「两侧加载的权重完全一致，但两遍 Loss 差异偏大」—— 直接排除权重加载错位（对比 MSLLM-1532）。
- **对照观察**：随机初始化时 RMSNorm 权重为全 1、数值大多 <1（起缩小作用）；本 case 加载的权重远大于 1。
- **旁证**：减层处理后能对齐；master 分支与旧分支训练也有差异。
