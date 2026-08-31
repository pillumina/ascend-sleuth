# MSLLM-1655: gemma-2-9b 预训练启动报 Cannot infer model type：CKPT_LOAD_DIR 传 HF 权重触发权重在线加载（train_from_hf）未全面支持，先转 HF→Megatron 权重

> 源是结构化 GitCode issue 线程，按 to-postmortem 优化②——只写指针，不重写。

**源文档**：https://gitcode.com/Ascend/MindSpeed-LLM/issues/1655
**框架**：mindspeed-llm（Ascend/MindSpeed-LLM，训练侧，Ascend NPU）
**category**：interrupt
**investigation_quality**：见 case 正式文件

## 结构化 case

`knowledge/training/mindspeed-llm/interrupt/MSLLM-1655.yaml`（Tier 2，2026-08-31 转正）

## 一句话根因

gemma-2-9b 预训练启动报 Cannot infer model type：CKPT_LOAD_DIR 传 HF 权重触发权重在线加载（train_from_hf）未全面支持，先转 HF→Megatron 权重
