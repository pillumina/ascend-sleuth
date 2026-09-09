# VERL-LOGPROB-CONFIG-MISMATCH: RL 训推 log_prob 首 step 差异过大（YarnRotaryEmbedding 配置不一致）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_kimi2_5_train_infer_consistency_optimization.md
**时间**：2026-09-09（沉淀）
**框架**：verl（RL；推理侧 vLLM，训练侧 Megatron）
**category**：precision
**investigation_quality**：high（缩规模复现 → 训推同输入分别 dump → 逐层比对 → 追到位置编码入参）
**namespace 建议**：training/verl/

## 结构化 case

`knowledge/training/verl/precision/VERL-LOGPROB-CONFIG-MISMATCH.yaml`（已转正 Tier 2）

## 一句话根因

训练侧 YarnRotaryEmbedding 的 original_max_position_embeddings=1024 与外层实际配置 4096 不一致 → 位置编码偏差 → MLA 输出不一致 → 训推 log_prob 首 step 差异指数级偏大。

## 弯路与级联

- **定位手法**：先减层——dense 层各减到 1 层确保对齐，再加 moe 层比较；训推两侧加 dump 后直接逐层比对 `train_dump.json` / `infer_dump.json`。
- **首个不一致模块**：MLA 输出（再向上追溯 cos/sin → freqs → YarnRotaryEmbedding 入参）。
