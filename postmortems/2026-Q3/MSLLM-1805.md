# MSLLM-1805: mindspore 启动 No module named tasks.checkpoint.models（代码漂移）

> 源是结构化 GitCode issue 线程，按 to-postmortem 优化②——只写指针，不重写。

**源文档**：https://gitcode.com/Ascend/MindSpeed-LLM/issues/1805
**框架**：mindspeed-llm（Ascend/MindSpeed-LLM，训练侧，Ascend NPU）
**category**：interrupt
**investigation_quality**：high（用户定位 commit + 源码验证）

## 结构化 case

`knowledge/training/mindspeed-llm/interrupt/MSLLM-1805.yaml`（Tier 2，2026-08-31 转正）

## 一句话根因

上游 commit f107818 删除 ckpt-v1，MindSpore 侧 4 处悬挂引用未同步（代码漂移）
