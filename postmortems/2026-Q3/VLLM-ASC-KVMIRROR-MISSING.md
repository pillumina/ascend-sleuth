# VLLM-ASC-KVMIRROR-MISSING: VL 模型迁移 vLLM 后第 7 token 起乱码（KVMirrorManager 未移植）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_vl_migration_vllm_precision.md
**时间**：2026-09-09（沉淀）
**框架**：vllm-ascend（H20+transformers → 昇腾+vLLM 迁移）
**category**：precision
**investigation_quality**：high（先做同平台跨版本对照缩小范围，再逐层 tensor 比对到 28 层分界 + 配置核对）
**namespace 建议**：inference/vllm-ascend/

## 结构化 case

`knowledge/inference/vllm-ascend/precision/VLLM-ASC-KVMIRROR-MISSING.yaml`（已转正 Tier 2）

## 一句话根因

模型移植时 Attention 的 KVMirrorManagerHook / KVMirrorManager 未随模型移植，kv_mirror_layers 对应层 K/V 取到异常小的值，28 层以后与 GPU 无法对齐 → 第 7 个 token 起输出不一致并乱码。

## 弯路与级联

- **先排除**：transformers 版本差异（NPU 侧 vLLM 要求高版本无法降级）、旋转位置编码误差（余弦接近 1）、sliding_window（未使用）、模型配置（一致）、decode_layer 统计量比对（各层余弦接近 1，**统计信息层看不出差异**）。
- **关键分界**：28 层及以后异常、27 层及以前正常 —— 单点分界而非全程漂移，是识别「某模块未移植」的判据。
