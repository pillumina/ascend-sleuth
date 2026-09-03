# VLLM-ASC-14363: DeepSeek V4 routed expert 漏传 swiglu_limit → 敏感前缀 logit 漂移

> 源是结构化 GitHub issue 线程 + 修复 PR，按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 self-evolve 试点（EV-2026-002，S2 缺口驱动）产出——S2 replay 发现
> 该问题无 knowledge 覆盖（覆盖缺口信号）。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/14363
**修复 PR**：https://github.com/vllm-project/vllm-ascend/pull/14364（merged）
**框架**：vllm-ascend（推理侧，Ascend NPU）
**category**：precision
**investigation_quality**：high（维护者定论 + 源码级 diff 验证）

## 现象（用户首帖）

DeepSeek V4 部署后出现异常中文/特殊 token（关联 #13615）。BF16 与量化 checkpoint 均受影响，main 与 v0.25.1rc 都存在。由 FusedMoE refactor（#11081）引入——refactor 前 adapter 直接从 hf_config 读 swiglu_limit，refactor 后需显式传参但 routed FusedMoE 漏传。

## 一句话根因

`vllm_ascend` 的 `DeepseekV4MoE` adapter 构造 routed `FusedMoE` 时漏传 `swiglu_limit`（shared expert 传了、routed 没传）→ routed expert 以默认 None 运行、缺少模型要求的 SwiGLU clamp → 敏感前缀处 next-token logit/ranking 漂移。

## fix

PR #14364：给 routed `FusedMoE` 传 `self.swiglu_limit`（与 shared expert 及 DeepSeek V4 model contract 一致）。修复版本 v0.25.1。

## 建议 quickly_check 信号

`swiglu_limit` / DeepSeek V4 routed expert / 异常中文 token + 敏感前缀 logit 漂移
