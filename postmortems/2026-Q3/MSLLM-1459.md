# MSLLM-1459: bitsandbytes 为 CUDA 依赖、NPU 环境不支持，清理环境/用昇腾原生镜像修复

> 源是结构化 GitCode issue 线程，按 to-postmortem 优化②——只写指针，不重写。

**源文档**：https://gitcode.com/Ascend/MindSpeed-LLM/issues/1459
**框架**：mindspeed-llm（Ascend/MindSpeed-LLM，训练侧，Ascend NPU）
**category**：interrupt
**investigation_quality**：见 case 正式文件（high=维护者定论/源码级，medium=版本组合级，low=假设方向级）

## 结构化 case

`knowledge/training/mindspeed-llm/interrupt/MSLLM-1459.yaml`（Tier 2，2026-08-31 转正）

## 一句话根因

bitsandbytes 为 CUDA 依赖、NPU 环境不支持，清理环境/用昇腾原生镜像修复
