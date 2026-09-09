# VLLM-ASC-ROPE-CFG-MISMATCH: tora+vllm-ascend 推理评分 NPU 54.4 vs GPU 80.6（hf config 取值不匹配）

> 源是结构化文档（msprobe 官方 best_practices），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://gitcode.com/Ascend/msprobe/blob/tag_MindStudio_26.2.0.B050_003/docs/zh/best_practices/ascend_tora_inference_diff_localization.md
**时间**：2026-09-09（沉淀）
**框架**：vllm-ascend（文档记录 0.9.1，enforce_eager=True）
**category**：precision
**investigation_quality**：high（同平台跨版本对照 + 排除两个干扰项后逐层比对）
**namespace 建议**：inference/vllm-ascend/

## 结构化 case

`knowledge/inference/vllm-ascend/precision/VLLM-ASC-ROPE-CFG-MISMATCH.yaml`（已转正 Tier 2）

## 一句话根因

tora 模型 hf config.json 的 max_position_embedding（16384）与 rope_theta（1000000）与训练时取值不匹配，位置编码计算偏差致推理评分下降。

## 弯路与级联

- **关键手法**：先把「NPU vs GPU」转成「同一台 GPU 上跨 vllm 版本」，评分差异被缩小到版本/配置面。
- **两个干扰项（不是根因）**：①旧版对 input_token pad 成 8 的倍数；②旧版 embedding 未覆盖区间填随机值（含极值/nan）而新版填 0。对齐这两点后评测结果不变 —— 它们只影响 dump 可比性，不是精度根因。
