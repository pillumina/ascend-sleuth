# MSLLM-1780: FSDP2 断点续训后首步日志 lm loss 被错误除以 global_step：trainer.py _last_logged_step 恢复错误，纯日志统计 bug，升级修复版本

> 源是结构化 GitCode issue 线程，按 to-postmortem 优化②——只写指针，不重写。

**源文档**：https://gitcode.com/Ascend/MindSpeed-LLM/issues/1780
**框架**：mindspeed-llm（Ascend/MindSpeed-LLM，训练侧，Ascend NPU）
**category**：precision
**investigation_quality**：见 case 正式文件

## 结构化 case

`knowledge/training/mindspeed-llm/precision/MSLLM-1780.yaml`（Tier 2，2026-08-31 转正）

## 一句话根因

FSDP2 断点续训后首步日志 lm loss 被错误除以 global_step：trainer.py _last_logged_step 恢复错误，纯日志统计 bug，升级修复版本
