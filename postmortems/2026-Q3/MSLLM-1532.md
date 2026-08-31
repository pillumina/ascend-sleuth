# MSLLM-1532: convert_mg2hf 按 plain 而非 grouped GQA layout 拆分 linear_qkv，QKV 权重错位致乱码（PR #4545 回归）

> 源是结构化 GitCode issue 线程，按 to-postmortem 优化②——只写指针，不重写。

**源文档**：https://gitcode.com/Ascend/MindSpeed-LLM/issues/1532
**框架**：mindspeed-llm（Ascend/MindSpeed-LLM，训练侧，Ascend NPU）
**category**：precision
**investigation_quality**：见 case 正式文件（high=维护者定论/源码级，medium=版本组合级，low=假设方向级）

## 结构化 case

`knowledge/training/mindspeed-llm/precision/MSLLM-1532.yaml`（Tier 2，2026-08-31 转正）

## 一句话根因

convert_mg2hf 按 plain 而非 grouped GQA layout 拆分 linear_qkv，QKV 权重错位致乱码（PR #4545 回归）
