# VLLM-ASC-11312: GLM5.1 v0.20.2 图模式 + DCP=2 启动失败 —— sfa_cp build_cp_metadata 读 None 的 num_computed_tokens_cpu

> 源是结构化 GitHub issue 线程（+ 维护者 draft fix PR），按 to-postmortem 只写指针，不重写。
> 本草案由 sed-g3 批量流水线产出（第 5/7 条），pre-triage: variant_of VLLM-ASC-9507。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/11312
**fix 跟踪**：thread 提出 draft PR #11388（[BugFix][Attention] Fix GLM52 DCP）——closed 未合入（draft, merged_at=null）；**无已合入修复 PR**；用户以 GLM5.2 + v0.23.0 混部开启 DCP 验证通过收尾
**时间**：created 2026-07-02，closed 2026-07-17（state_reason=completed）
**框架版本**：vllm-ascend / vLLM 0.20.2（title "v20.2 版本"，启动脚本 VLLM_VERSION=0.20.2）
**平台**：issue 无 npu-smi 输出；启动脚本线索（CANN 8.2.RC1 + CAM op_api、/a3_inference 工作区）指向 A3/910C 系——未确认，case 不填 platforms
**category**：interrupt（启动失败）
**investigation_quality**：medium（维护者 draft PR 陈述根因 + 用户验证 workaround/新版本；fix PR 未合入、GLM5.1 原配置未回验）
**verification**：upstream-maintainer-confirmed（维护者 pisceskkk 提供 draft PR #11388 含根因与修法，PR 未合入）

## 现象摘要

能正常启动的脚本增加 DCP=2（`--decode-context-parallel-size 2` + `--cp-kv-cache-interleave-size 128`）后服务拉起失败：`RuntimeError: NPUModelRunner init failed, error is AttributeError: 'NoneType' object has no attribute 'to'`。关闭图模式可正常拉起。报错在 cudagraph 捕获 warmup（`capture_model → _dummy_run → _build_attn_group_metadata → builder.build`），栈到 `vllm_ascend/attention/context_parallel/sfa_cp.py:178 build_cp_metadata`：`num_computed_tokens = common_attn_metadata.num_computed_tokens_cpu.to(seq_lens.device)`。

## 一句话根因

DCP（decode context parallel）+ 异步投机解码（MTP，`--speculative-config ... deepseek_mtp`）路径把 `common_attn_metadata.num_computed_tokens_cpu` 清成 None（维护者根因陈述），`sfa_cp.py:178` 图捕获阶段仍直接对它调 `.to(seq_lens.device)` → `AttributeError: 'NoneType' object has no attribute 'to'` → NPUModelRunner init 失败、服务拉不起。

## fix

- 已合入修复 PR：**无**。#11388 为 draft 且 closed 未合入；其修法 = SFA CP 元数据源在 `num_computed_tokens_cpu` 被清空时改用 `num_computed_tokens_of_pcp_dcp`（+ 稀疏 C8 indexer 量化 scale 透传 + SFA decode metadata 占位）。
- 版本区间：受影响 v0.20.2；**修复版本未在 thread 明确**（无 merged PR 可锚定）。用户验证路径：GLM5.2 + v0.23.0 混部开启 DCP 正常（注意验证的是 GLM5.2，非原 GLM5.1 配置，不能确证 GLM5.1 同配置已修）。
- workaround：**关闭图模式**可正常拉起（用户已验证）。

## 弯路与级联

- 弯路：症状外形像 9507（图模式 + CP + AttributeError），但本环境 `compilation-config` 已是 `FULL_DECODE_ONLY` 仍崩 → 不是 9507 那条 "FULL 图不支持 PCP" 的功能限制，而是另一触发面（DCP × async spec decode × 图捕获）的元数据源选择缺陷。
- 级联：NPUModelRunner init failed → WorkerProc exception → 引擎/服务退出均为根因后的噪声，根因只在 `sfa_cp.py:178` 断言行。
