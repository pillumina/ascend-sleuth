# VLLM-ASC-10322: DSV4-Flash decode FULL_DECODE_ONLY cudagraph 启动崩溃——pre-KV ACL graph 显存预估撞 DSA 压缩路径（aclnnScatterNdUpdateV2 507015，PR #10369 修复）

> 源是结构化 GitHub issue 线程（结构化外部文档），按 to-postmortem 优化②——只写指针，不重写。
> 本草案由 issue-ingest r2-sed-g4（2026-09）产出，进 inbox 待 groom 分诊；不改正式 knowledge/ 目录。

**源文档**：https://github.com/vllm-project/vllm-ascend/issues/10322
**fix 跟踪**：PR #10369 "[BugFix][Worker] Skip DSV4 pre-KV graph memory profiling"（base main，merged 2026-06-12，merge 49a1fed17e，Fixes #10322）；issue closed 2026-06-12（随 merge）
**时间**：2026-06-11 ~ 2026-06-12
**框架/平台**：vllm 0.21.0 + vllm-ascend main（0a79510a0）、CANN 9.0.0、driver 25.2.1；Ascend910（ascend910_9392）×16 单机；DeepSeek-V4-Flash w8a8-mtp decode（DP16/EP、FULL_DECODE_ONLY + MooncakeHybridConnector）
**category**：interrupt
**investigation_quality**：high（16 DP worker 一致崩溃 + plog aicore fault kernel 定位 + #9865 变更点归因 + merged PR + 1P1D 精度验证）
**verification**：upstream-fix-merged（PR #10369）
**novelty**：new_pattern——库内无 pre-KV ACL graph 显存预估（#9865）case；同 507015 但机制不同的 11893（PCP 空段 batchTokens 下溢）作判别

## 现象摘要

DeepSeek-V4-Flash（w8a8-mtp）decode 服务 `cudagraph_mode: FULL_DECODE_ONLY` 启动，16 个 DP worker 全部在启动期 `profile_cudagraph_memory()` → `_warmup_and_capture()` → `_dummy_run()` 崩溃；同配置 `--enforce-eager` 正常。

```
RuntimeError: ... current working operator name is aclnnScatterNdUpdateV2   # torch.npu.graph 内 synchronize

# plog（硬件级）
errorStr: The DDR address of the MTE instruction is out of range.   # errCode 0x800000, SMMU fault
fault kernel_name=Compressor_5d0f..._12449                        # Compressor SuperKernel 含 ScatterNdUpdateV2
[ERROR] ASCENDCL: aclrtLaunchKernelWithHostArgs failed, runtime result = 507015
```

## 一句话根因

#9865 引入的 **pre-KV ACL graph memory profiling**（KV cache 分配前临时 capture 估显存），在 DeepSeek-V4 DSA **压缩 attention** 下于 KV 分配前执行，撞上 fused 进 Compressor SuperKernel 的 `ScatterNdUpdateV2`（`vllm_ascend/_cann_ops_custom/custom_transformer`）→ aicore exception 507015（MTE DDR 越界 + SMMU fault）。正常 KV-cache 分配后的 capture/replay 路径本身可用（enforce-eager 正常印证）。PR #10369 仅对 `model_type=deepseek_v4` + 压缩 attention 跳过 pre-KV profiling。

## fix

- **升级/合入 PR #10369**（merged 2026-06-12）：跳过 DSV4 压缩场景的 pre-KV profiling，保留 KV 分配后正常 ACL graph capture/replay（cudagraph_mode 不变）。
- 升级前规避（Nagisa125 建议）：`--enforce-eager`，或 `export VLLM_MEMORY_PROFILER_ESTIMATE_CUDAGRAPHS=0`。
- #10369 附 1P1D（A3 双节点、300k ctx、GPQA 0.8838 符合预期）精度验证。

## 弯路与级联

- 别与 VLLM-ASC-11893（PCP 空段导致 batchTokens uint32 下溢 → MTE 507015）混淆——同错误码不同机制；本条特征 = 启动期 pre-KV profiling 阶段 + ScatterNdUpdateV2 fault kernel。

## 建议 triage 路由症状

`507015`/`aicore exception` 属错误码型签名，inference_interrupt 现有 `ErrCode=\d+` 正则不覆盖裸 `507015`；建议补 `507015|aicore exception`（可选，needs-review；与 12983/11893 等 507xxx 族一并考虑）。
