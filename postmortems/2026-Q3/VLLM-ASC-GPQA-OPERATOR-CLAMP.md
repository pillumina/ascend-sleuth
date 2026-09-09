# VLLM-ASC-GPQA-OPERATOR-CLAMP: DeepSeek-V4 Pro GPQA 评分偏低（三根因叠加）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_deepseek_v4_gpqa_accuracy_optimization.md
**时间**：2026-09-09（沉淀）
**框架**：vllm-ascend（Atlas 800I A3）
**category**：precision
**investigation_quality**：high（badcase 分析 → 代码走读 → badcase 复现，逐项拆分验证）
**namespace 建议**：inference/vllm-ascend/
**⚠️ 多根因**：本 case 含 3 个独立根因（同一现象），fix 需全做；groom 审时可考虑拆条

## 结构化 case

`knowledge/inference/vllm-ascend/precision/VLLM-ASC-GPQA-OPERATOR-CLAMP.yaml`（已转正 Tier 2）

## 一句话根因

三处叠加：①rope 转 float32；②Dequantswigluquant / GMMswigluquant 的 clamp 缺陷（评分偏低主因）；③moe_gating_top_k_hash 内部与后续重复 renorm。

## 弯路与级联

- **收敛依据**：同模型其他环境正常 + 同环境其他模型正常 → 收敛到本模型在本环境的算子/实现差异。
- **经验**：同模型不同环境评分差异明显时，优先从算子层查 NaN、clamp 边界与数据类型适配，逐项拆分验证。
