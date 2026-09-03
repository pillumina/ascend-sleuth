# VLLM-ASC-8201: vllm-ascend 0.18.0RC1 patch_minimax_usage_accounting 全局覆写 vLLM OpenAI protocol 类 → 非 MiniMax 场景（vllm-omni 等）pydantic 校验失败

> 源是结构化 GitHub issue 线程（7 条评论），按 to-postmortem 优化②——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/8201
**fix 跟踪**：issue 内无 vllm-ascend fix PR（workaround=注释 platform patch import；vllm-omni 侧 workaround PR 见 issue #2777）；main 侧后续治理：PR #11050（scope MiniMax usage accounting patch，2026-06-29）→ PR #11384（替换/移除 MiniMax parser backports，2026-07-17，main 上该文件已不存在）。家族根 fix（wrapper 化）为 PR #7835（7823 的 fix，merged 2026-03-31 releases/v0.18.0）——**注意**：已核实 releases/v0.18.0 上 #7835 后的 patch_minimax_usage_accounting.py 仍保留 protocol 类全局覆写（L40-62），故 0.18.0 正式版同样受影响，需到 main ≥ #11050/#11384 的版本才真正去除
**时间**：2026-04-13 ~ 2026-04-14（completed，报者关闭）
**框架**：vllm-ascend v0.18.0RC1（quay.io/ascend/vllm-ascend:v0.18.0rc1）+ vllm-omni v0.18.0（qwen-image-edit）；同源问题 MiniMax-M2.5 教程部署亦现（评论#6）
**平台**：未在 thread 内明确
**category**：interrupt（启动/请求期 pydantic 校验失败）
**investigation_quality**：medium（报者定位到具体 patch 覆写代码 + 回退实测恢复 + 维护者确认全局影响；未在 thread 内追到根治 commit）
**verification**：upstream-maintainer-confirmed（维护者 gcanlin 确认 vllm-ascend patch 全局覆写缺陷并主张移除；报者回退 patch 实测恢复；main 侧根治=#11050 scope / #11384 移除）
**pre-triage**：variant_of VLLM-ASC-7823（同族=同一 patch_minimax_usage_accounting.py 在 v0.18.0RC1 及同代的全局副作用；7823=import 期 _replace_block 找不到目标块崩溃，本条=pydantic/协议类覆写导致非 MiniMax 场景校验失败；家族修复沿 #7835 → main #11050/#11384 线）

## 现象摘要

- vllm-omni:v0.18.0（基于 quay vllm-ascend v0.18.0rc1）跑 qwen-image-edit image-to-image 推理抛 Pydantic 校验错误。
- 定位到 vllm_ascend/patch/platform/patch_minimax_usage_accounting.py：patch 里定义 `UsageInfo(engine_protocol.UsageInfo)` 子类并整体覆写 `engine_protocol.UsageInfo / chat_protocol.UsageInfo / chat_serving.UsageInfo / CompletionTokenUsageInfo`（模块级赋值），与 vLLM 原生 pydantic 模型校验冲突。
- MiniMax-M2.5 官方教程部署（0.18 线）同样出现（评论#6）。
- workaround：注释 `patch/platform/__init__.py:32-33` 两个 patch import（patch_minimax_usage_accounting 与 patch_glm_tool_call_parser 有依赖，须一起注释）→ 推理恢复正常、Pydantic 报错消失（报者实测 + vllm-omni PR 已提交）。
- 报者 04-13 查 main 分支未见该文件（当时判断是特定版本临时 patch）——实际 main 于 2026-07-17（#11384）才最终移除该 backport。

## 一句话根因

vllm-ascend v0.18.0RC1 的 `patch_minimax_usage_accounting.py`（为 MiniMax 推理场景加 usage accounting 的 platform patch）通过**模块级类覆写**把自建 `UsageInfo`/`CompletionTokenUsageInfo` 塞进 `vllm.entrypoints.openai.*` 的 engine/chat protocol 与 serving 模块，属于全局副作用：非 MiniMax 场景（如 vllm-omni qwen-image-edit、M2.5 教程部署）与 vLLM 原生 pydantic 校验冲突抛错。维护者 gcanlin 确认应尽快移除；main 侧经 #11050（scope）→ #11384（替换移除）根治。

## fix

- 短期 workaround：注释 `vllm_ascend/patch/platform/__init__.py:32-33` 的 patch import（两行有依赖须同注释）后重启；vllm-omni 侧随 issue #2777 的 workaround PR 兼容。
- 根治：升级到全局覆写被 scope/移除的版本（main ≥ PR #11050 scope / #11384 替换移除；0.18.0 正式版经核实仍含覆写，不能作为本条修复版本）。

## 弯路与级联

- 弯路：报者最初以为 main 已无该文件（04-13 时点 main 仍存在，07-17 才移除）——升级前先核实目标版本的该文件与覆写行。
- 级联：无（校验失败单点）；勿与 7823（import 期定位不到目标块崩溃）混为同一报错面——本条根因是"覆写仍在但作用于非 MiniMax 场景"。
