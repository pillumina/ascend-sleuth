# VLLM-ASC-9024: MTP + prefix caching 同时开启首请求即崩——mamba_utils 路径 IndexError

> 源是结构化 GitHub issue 线程（5 条评论），按 to-postmortem 优化——只写指针，不重写。

**源文档**（完整调查）：https://github.com/vllm-project/vllm-ascend/issues/9024
**同族**：#9003（0.19.1rc1 MTP+prefix cache 推理报错，同 PR 解决）
**fix 跟踪**：PR #9456（https://github.com/vllm-project/vllm-ascend/pull/9456，[BugFix] Fix Deepseek-V4 async scheduling with MTP，merged 2026-05-22 main；`vllm_ascend/worker/model_runner_v1.py` 多流计数同步 + DSV4 专用 positions CPU buffer）
**时间**：2026-05-09（报）～ 2026-05-27（closed completed）
**框架**：vllm-ascend v0.19.1rc1；Qwen3.5-27B-w8a8-mtp（qwen3_5_mtp），GLM-5 W4A8 同栈复现
**平台**：发帖未声明（评论者 aeytkn 在 910B1 复现同栈）
**category**：interrupt
**investigation_quality**：medium（第三方机制分析为推断；崩溃栈到行；fix 由维护者指定合入；PR 语义与报错路径映射未逐级闭环）
**批量导入**：sed-g3（2026-09）
**pre-triage**：new_pattern（全库无 mamba_utils/preprocess_mamba 崩溃 case；10500/13964/13710/8926 模块或组合全异）

## 结构化 case

`postmortems/inbox/VLLM-ASC-9024.case.yaml`（Tier 2 候选，待 groom 审）

## 现象摘要

Qwen3.5-27B-w8a8-mtp：`qwen3_5_mtp` + `--enable-prefix-caching`（+ async scheduling + FULL_DECODE_ONLY）同开，v0.19.1rc1 服务能拉起、一发 curl 即崩；去掉 MTP 或 prefix-caching 任一即正常。崩溃：`model_runner_v1.py:1597 execute_model → mamba_utils.preprocess_mamba → collect_mamba_copy_meta → get_temporal_copy_spec` `src_block_id = block_ids[cur_block_idx + num_accepted_tokens - 1]` → `IndexError: list index out of range`。GLM-5 W4A8 同版本同栈复现；workaround：关 FULL_DECODE_ONLY 可跑但很慢。

## 一句话根因

vllm-ascend ModelRunnerV1 把内存状态处理盲目路由进 vllm 的 mamba preprocess/postprocess（不经架构判别）；prefix caching + MTP 产生的带填充 token 偏移被当成 mamba state block id 索引 → `get_temporal_copy_spec` block_ids 越界 IndexError。维护者将本族（#9003/#9024）归因并修复于 PR #9456（async MTP 下 `valid_sampled_tokens_count` 多流脏读写 + DSV4 positions_cpu）——issue 内 mamba 误路由/KV 失步分析为第三方推断，机制链未完全闭环，以维护者指定 fix 为准。

## fix

升级到含 PR #9456 的构建。workaround：去 MTP 或 prefix-caching 之一；或关 FULL_DECODE_ONLY（性能代价大）。

## verification

**upstream-fix-merged**（fix PR #9456，merged 2026-05-22；维护者声明 solved，closed completed）
