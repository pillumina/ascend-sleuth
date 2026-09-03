# VLLM-ASC-7823: vllm serve 启动即崩 —— MiniMax usage accounting patch 源码改写在上游 vLLM v0.18.0 漂移后定位不到目标块

> 源是结构化 GitHub issue 线程 + 修复 PR，按 to-postmortem 优化②——只写指针，不重写。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/7823
**fix 跟踪**：PR https://github.com/vllm-project/vllm-ascend/pull/7835（reimplement MiniMax usage accounting patch，base releases/v0.18.0，merged 2026-03-31）
**时间**：issue 创建 2026-03-30，fix 2026-03-31，issue completed 关闭 2026-07-29
**框架版本**：vLLM v0.18.0（commit bcf2be9）+ vllm-ascend releases/v0.18.0（0.1.dev1+g90bb1b4b9 = commit 6fbd0049）；CANN 8.5.0
**平台**：Ascend 910C（A3-910C，ARM64）
**category**：interrupt（启动崩溃）
**investigation_quality**：medium
**verification**：upstream-fix-merged（fix PR #7835）
**pre-triage**：variant_of VLLM-ASC-9167

## 现象摘要

- `vllm serve` 启动即崩（CLI arg 解析阶段、EngineCore 之前），Traceback 终止于 `RuntimeError: Failed to locate expected block while patching OpenAIServingChat usage accounting`。
- 崩溃栈：`vllm_ascend/platform.py:138 pre_register_and_update` → `utils.py:381 adapt_patch` → `patch/platform/patch_minimax_usage_accounting.py:366 _patch_chat_completion_stream_generator` → `:71 _replace_block`。
- 与模型无关：comment 0 报告 qwen3.5 单机启动同样报错（不仅 MiniMax 系模型）。
- 日志尾 `ERR99999 UNKNOWN application exception` 是同一次 import 期异常的级联退出，非独立错误。

## 一句话根因

`patch_minimax_usage_accounting.py` 用**源码改写**方式给上游 `OpenAIServingChat` 打 MiniMax usage accounting 补丁——`_replace_block()`（:71）按精确源码块文本匹配重写上游方法；上游 vLLM v0.18.0（commit bcf2be9）源码相对补丁假设漂移后期望块定位不到，平台插件激活期（import 期）直接抛 RuntimeError，服务无法启动。

## fix

PR #7835 将补丁从"源码改写"重写为 **runtime wrapper 实现**（wrap 原 stream/full generator、运行时按输出 token id 统计 usage；MiniMax `</think>` 缺失时输出计为 reasoning token），对上游源码漂移免疫。2026-03-31 合入 releases/v0.18.0；zhaomingyu13（2026-07-29）确认最新 release/rc 已解决。**受影响版本**：含旧源码改写式 patch 的 vllm-ascend 构建（崩溃环境 releases/v0.18.0 线、2026-03-31 前）；**修复版本**：含 PR #7835 的构建（releases/v0.18.0 2026-03-31 后及各后续 release/rc）。无配置 workaround——崩溃发生在平台插件 import 期，无法绕过，只能升级。

## 弯路与级联

issue 本身无弯路：崩溃单点、根因由 fix PR #7835 自述（"previous implementation rewrote OpenAIServingChat by matching exact source blocks. That was brittle against vllm source drift"）。级联仅日志尾 ERR99999（非独立错误）。关联上游 vLLM issue #37988（usage accounting 语义来源，非本 crash 根因）。
